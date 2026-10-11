"""Regression tests for audit-20261011 live Gemini findings (validation and rate limits)."""
import json
from pathlib import Path

import pytest

from claims_agent.llm import (AdapterUnavailable, MockAdapter, ModelCall, extract_candidates,
                              layout_normalized, policy_quote_in_chunk, prepare_extraction)
from claims_agent.policy import HORIZONCARE, ingest_policy
from claims_agent.schemas import Claim

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / 'evaluation/audit-20261011-remediation/extraction-gold.json'
CHUNK = ('A service is considered Medically Necessary if it is:\n\uf0b7 Consistent with generally accepted '
         'standards of medical practice;\n\uf0b7 Clinically appropriate in type, frequency, and setting;')


def test_layout_only_differences_are_accepted():
    flattened = ('A service is considered Medically Necessary if it is: Consistent with generally '
                 'accepted standards of medical practice; Clinically appropriate in type, frequency, and setting;')
    assert policy_quote_in_chunk(flattened, CHUNK)
    assert policy_quote_in_chunk(flattened.replace(': ', ':\n• '), CHUNK)
    assert policy_quote_in_chunk('Specialty drugs listed as "PA Required"', 'Specialty drugs listed as \u201cPA Required\u201d on it')
    assert policy_quote_in_chunk(CHUNK, CHUNK)


@pytest.mark.parametrize('quote', [
    'A service is considered Medically Necessary if it is: Clinically appropriate',  # skips a line
    'A service is considered medically necessary',  # wording/case changed
    'Consistent with accepted standards of medical practice',  # word dropped
    '\uf0b7 \n ',  # layout only, no words
])
def test_word_level_differences_are_still_rejected(quote):
    assert not policy_quote_in_chunk(quote, CHUNK)


def test_layout_normalization_preserves_words():
    assert layout_normalized(CHUNK).startswith('A service is considered Medically Necessary if it is: Consistent')


def _office(tmp_path):
    case = next(c for c in json.loads(GOLD.read_text()) if c['id'] == 'office-visit.json-documented')
    claim = Claim.model_validate(case['claim'])
    index = ingest_policy(HORIZONCARE, ROOT / 'policies', tmp_path).index
    return claim, index, prepare_extraction(claim, index, document_ids=('GOLD',))


def _response(prepared, policy_quote, doc_quote='The diagnosis is supported.'):
    chunk = next(c for c in prepared.payload.policy_chunks if 'Medically Necessary if it is' in c.text)
    return json.dumps(dict(request_id=prepared.payload.request_id, findings=[
        dict(topic='diagnosis_support', status='documented', statement='Diagnosis is stated.',
             document_refs=[dict(document_id='GOLD', quote=doc_quote)], policy_refs=[]),
        dict(topic='medical_necessity', status='documented', statement='Necessity is stated.',
             document_refs=[dict(document_id='GOLD', quote='The service is medically necessary.')],
             policy_refs=[dict(chunk_id=chunk.chunk_id, quote=policy_quote)])]))


def test_reproduced_office_visit_output_now_validates(tmp_path):
    """Exact policy quote shape Gemini returned for the audit's failing office-visit case."""
    claim, index, prepared = _office(tmp_path)
    quote = ('A service is considered Medically Necessary if it is: Consistent with generally accepted standards '
             'of medical practice; Clinically appropriate in type, frequency, and setting; Not primarily for '
             'convenience of the member or provider; The most cost-effective option among clinically comparable alternatives.')
    raw = _response(prepared, quote)
    result = extract_candidates(claim, index, document_ids=('GOLD',), adapter=MockAdapter({prepared.payload.request_id: raw}))
    assert result.status == 'validated_candidates'
    assert result.evidence_reliability is not None
    assert result.evidence_reliability['score'] == 90


def test_document_quotes_remain_exact(tmp_path):
    claim, index, prepared = _office(tmp_path)
    raw = _response(prepared, 'A service is considered Medically Necessary if it is:', doc_quote='The  diagnosis is supported.')
    result = extract_candidates(claim, index, document_ids=('GOLD',), adapter=MockAdapter({prepared.payload.request_id: raw}))
    assert result.status == 'invalid_response'
    assert result.validation_error == 'document_quote_mismatch'


# ---- Gemini transport retry behaviour (no network) ----

class _FakeAPIError(Exception):
    def __init__(self, code, delay=None):
        self.code = code
        self.response = None
        self.details = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo',
                                                'retryDelay': f'{delay}s'}]}} if delay is not None else {}


def _adapter(monkeypatch, outcomes, **kwargs):
    from claims_agent import gemini
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    sleeps, calls = [], []
    adapter = gemini.GeminiAdapter(sleep=sleeps.append, **kwargs)

    def attempt(self, call, api_key, genai, types, errors, httpx):
        calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(gemini.GeminiAdapter, '_attempt', attempt)
    return adapter, sleeps, calls


CALL = ModelCall(instruction='i', payload_json='{}', response_schema_json='{}')


def test_rate_limit_is_retried_with_provider_delay(monkeypatch):
    from claims_agent.gemini import _Transient
    adapter, sleeps, calls = _adapter(monkeypatch, [_Transient('gemini_rate_limited', 7.0), '{"ok": true}'])
    assert adapter.generate(CALL) == '{"ok": true}'
    assert len(calls) == 2 and 7.0 <= sleeps[0] <= 8.0


def test_retries_are_bounded(monkeypatch):
    from claims_agent.gemini import _Transient
    adapter, sleeps, calls = _adapter(monkeypatch, [_Transient('gemini_server_error')] * 5, max_retries=2)
    with pytest.raises(AdapterUnavailable) as exc:
        adapter.generate(CALL)
    assert exc.value.args[0] == 'gemini_server_error' and len(calls) == 3 and len(sleeps) == 2


def test_long_provider_delay_fails_fast(monkeypatch):
    from claims_agent.gemini import _Transient
    adapter, sleeps, calls = _adapter(monkeypatch, [_Transient('gemini_rate_limited', 3600.0), '{}'])
    with pytest.raises(AdapterUnavailable):
        adapter.generate(CALL)
    assert len(calls) == 1 and not sleeps


def test_non_transient_failures_are_not_retried(monkeypatch):
    adapter, sleeps, calls = _adapter(monkeypatch, [AdapterUnavailable('incomplete_response'), '{}'])
    with pytest.raises(AdapterUnavailable):
        adapter.generate(CALL)
    assert len(calls) == 1 and not sleeps


def test_retry_can_be_disabled(monkeypatch):
    from claims_agent.gemini import _Transient
    monkeypatch.setenv('GEMINI_MAX_RETRIES', '0')
    adapter, sleeps, calls = _adapter(monkeypatch, [_Transient('gemini_rate_limited', 1.0), '{}'])
    with pytest.raises(AdapterUnavailable):
        adapter.generate(CALL)
    assert len(calls) == 1


def test_retry_info_parsing():
    from claims_agent.gemini import _retry_delay
    assert _retry_delay(_FakeAPIError(429, 17)) == 17.0
    assert _retry_delay(_FakeAPIError(429)) is None
