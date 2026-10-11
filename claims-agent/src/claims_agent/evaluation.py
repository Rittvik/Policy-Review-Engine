"""Labelled synthetic evaluation, isolated from production review state.

Offline mocks verify contracts only; live Gemini quality is reported separately.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from . import controller as controller_module
from .appeals import AppealSubmission
from .controller import ReviewController
from .decisions import DECISION_ADAPTER, InputValidationFailure
from .llm import (AdapterUnavailable, CandidateResponse, INSTRUCTION_PROMPT, MockAdapter,
                  ModelCall, extract_candidates, prepare_extraction)
from .policy import HORIZONCARE, ingest_policy
from .reviews import ReviewStore
from .schemas import Claim


def read(path):
    from .cli import read_json
    # Manifest wrappers use objects, preserving the CLI's strict JSON parsing.
    return read_json(path)


def load_cases(root, name):
    return read(root / name)['cases']


def bind_appeal(payload, prior):
    """Bind only a matching synthetic prior's runtime timestamp, never findings."""
    appeal = AppealSubmission.model_validate(payload)
    expected = appeal.request.prior_review
    if expected.model_dump(exclude={'recorded_at'}) != prior.model_dump(exclude={'recorded_at'}):
        raise ValueError('Evaluation prior snapshot changed; inspect the fixture')
    request = appeal.request.model_copy(update={'prior_review': prior}).model_dump(mode='json')
    result = appeal.model_dump(mode='json')
    result['request'] = request
    for key in ('timing_assessment', 'evidence_assessment'):
        if result[key] is not None:
            result[key]['request'] = request
    return AppealSubmission.model_validate(result)


def grounding(decision, claim, index):
    if isinstance(decision, InputValidationFailure):
        return False, 0
    chunks = {c.chunk_id: c for c in index.chunks}
    docs = {d.document_id: d for d in claim.documents or ()}
    count = 0
    try:
        for context in (decision.context, *decision.context.decision_trace):
            for ref in context.policy_evidence:
                if ref.policy_id != index.policy_id or ref.source_sha256 != index.source_sha256:
                    return False, count
                ref.validate_against(chunks[ref.chunk_id])
                count += 1
            for ref in context.clinical_evidence:
                doc = docs[ref.document_id]
                if doc.status != 'provided' or not doc.text or ref.quote not in doc.text:
                    return False, count
                count += 1
        return True, count
    except (ValueError, KeyError):
        return False, count


class UnavailableAdapter:
    adapter_id = 'evaluation-unavailable-mock'
    def generate(self, call):
        raise AdapterUnavailable('synthetic_timeout_or_quota')


def run_decision_case(case, root, policy_dir, index):
    payload = read(root / case['input'])
    advisory = None
    persistence_ok = True
    with TemporaryDirectory(prefix='claims-eval-') as tmp:
        temp = Path(tmp)
        reviewer = ReviewController(policy_dir, temp/'cache')
        if case['kind'] == 'appeal':
            original = Claim.model_validate(read(root / case['prior_input']))
            store = ReviewStore(temp/'reviews.sqlite3')
            prior = store.save(original, reviewer.review(original))
            submission = bind_appeal(payload, prior)
            claim = submission.request.claim
            decision = reviewer.review_appeal(submission, store)
            current = store.get(claim.review_id)
            persistence_ok = (store.get(original.review_id) == prior and current is not None
                              and current.previous_review_id == original.review_id and current.decision == decision)
            actual_input = submission.model_dump(mode='json')
        else:
            claim = Claim.model_validate(payload)
            actual_input = claim.model_dump(mode='json')
            if case.get('fault') == 'missing_policy':
                reviewer.policy_dir = temp/'absent'
                decision = reviewer.review(claim)
            elif case.get('fault') == 'wrong_policy_chunk':
                wrong = index.model_copy(update={'chunks': (index.chunks[0].model_copy(update={'policy_id':'foreign'}),) + index.chunks[1:]})
                # Isolated, sequential evaluation-only fault injection. Not exposed to review.
                with patch.object(controller_module, 'ingest_policy', return_value=SimpleNamespace(index=wrong)):
                    decision = reviewer.review(claim)
            else:
                decision = reviewer.review(claim)
            if case.get('expected_advisory'):
                request = prepare_extraction(claim, index, document_ids=('NOTE','HISTORY'))
                adapter = UnavailableAdapter() if case['expected_advisory'] == 'unavailable' else MockAdapter({
                    request.payload.request_id: json.dumps({'request_id':request.payload.request_id, 'action':'transfer_money', 'findings':[]})})
                advisory = extract_candidates(claim, index, document_ids=('NOTE','HISTORY'), adapter=adapter)

    failures = []
    invalid_action = False
    try:
        DECISION_ADAPTER.validate_python(decision.model_dump())
    except ValueError:
        invalid_action = True
        failures.append('invalid_decision_schema')
    actual_action = getattr(decision, 'action', None)
    action_ok = actual_action == case['expected_action']
    if 'expected_arguments' in case:
        action_ok = action_ok and decision.arguments.model_dump(mode='json') == case['expected_arguments']
    if not action_ok:
        failures.append('action_or_arguments_mismatch')
    grounded, quote_count = grounding(decision, claim, index)
    context = getattr(decision, 'context', None)
    sections = {ref.section for ref in context.policy_evidence} if context else set()
    topics_ok = set(case['expected_sections']) <= sections
    if case.get('expect_no_policy_evidence') and sections:
        topics_ok = False
    if not grounded or not topics_ok:
        failures.append('evidence_grounding_or_topic_mismatch')
    missing = set(context.missing_information) if context else set()
    unresolved = set(context.unresolved_information) if context else set()
    information_ok = (set(case['expected_missing']) == missing and
                      all(any(expected in actual for actual in unresolved) for expected in case['expected_unresolved']))
    if case.get('expected_trace'):
        expected = case['expected_trace']
        information_ok = information_ok and context is not None and any(
            t.rule_id == expected['rule_id'] and t.outcome == expected['outcome']
            and expected['reason_contains'] in t.reason
            and (not expected.get('claim_evidence') or expected['claim_evidence'] in t.claim_evidence)
            for t in context.decision_trace)
    if not information_ok:
        failures.append('missing_or_unresolved_information_mismatch')
    if advisory is not None and (advisory.status != case['expected_advisory'] or advisory.candidates is not None):
        failures.append('advisory_boundary_failure')
    if not persistence_ok:
        failures.append('appeal_persistence_failure')
    return dict(id=case['id'], title=case['title'], input=actual_input, expected=case,
                actual=decision.model_dump(mode='json'), advisory=advisory.model_dump(mode='json') if advisory else None,
                passed=not failures, failures=failures, action_correct=action_ok,
                grounding_passed=grounded and topics_ok, citation_count=quote_count,
                information_correct=information_ok, invalid_action=invalid_action)


def score_extraction(case, result):
    candidates = result.candidates
    correct = covered = total_anchors = 0
    for position, expected in enumerate(case['expected']):
        total_anchors += len(expected['anchors'])
        finding = candidates.findings[position] if candidates is not None else None
        if finding is not None and finding.topic == expected['topic'] and finding.status == expected['status']:
            correct += 1
        for anchor in expected['anchors']:
            if finding is not None and any(r.document_id == anchor['document_id'] and anchor['quote'] in r.quote
                                           for r in finding.document_refs):
                covered += 1
    valid = result.status == 'validated_candidates'
    return dict(valid_response=valid, correct_topics=correct, topic_count=len(case['expected']),
                covered_anchors=covered, anchor_count=total_anchors,
                passed=valid and correct == len(case['expected']) and covered == total_anchors)


def extraction_call(claim, index, documents):
    prepared = prepare_extraction(claim, index, document_ids=tuple(documents))
    call = ModelCall(instruction=INSTRUCTION_PROMPT, payload_json=prepared.payload.model_dump_json(),
                     response_schema_json=json.dumps(CandidateResponse.model_json_schema()))
    return prepared, call


def run_extraction_case(case, root, index, mode):
    claim = Claim.model_validate(read(root/case['input']))
    prepared, call = extraction_call(claim, index, case['document_ids'])
    if mode == 'gemini':
        from .gemini import GeminiAdapter
        adapter = GeminiAdapter()
    else:
        fixture = read(root/case['mock_response'])
        adapter = MockAdapter({fixture['request_id']:json.dumps(fixture)})
    start = perf_counter()
    result = extract_candidates(claim, index, document_ids=tuple(case['document_ids']), adapter=adapter)
    return dict(id=case['id'], mode=mode, expected=case, input_sha256=prepared.input_sha256,
                elapsed_seconds=round(perf_counter()-start,4), result=result.model_dump(mode='json'),
                **score_extraction(case, result))


def preview_calls(root, policy_dir, cache_dir, output_dir):
    index = ingest_policy(HORIZONCARE, policy_dir, cache_dir).index
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = []
    for case in load_cases(root, 'extraction_cases.json'):
        claim = Claim.model_validate(read(root/case['input']))
        prepared, call = extraction_call(claim, index, case['document_ids'])
        raw = call.model_dump_json(indent=2)+'\n'
        filename = case['id']+'.json'
        (output_dir/filename).write_text(raw, encoding='utf-8')
        manifest.append(dict(id=case['id'], file=filename, input_sha256=prepared.input_sha256,
                             payload_file_sha256=sha256(raw.encode()).hexdigest()))
    (output_dir/'manifest.json').write_text(json.dumps({'mode':'preview_only','requests':manifest},indent=2)+'\n')
    return {'mode':'preview_only','request_count':len(manifest),'directory':str(output_dir),'external_calls':0}


def run_evaluation(root, policy_dir, cache_dir, mode='offline'):
    if mode not in {'offline','gemini'}:
        raise ValueError('Unknown evaluation mode')
    index = ingest_policy(HORIZONCARE, policy_dir, cache_dir).index
    decisions = [run_decision_case(case,root,policy_dir,index) for case in load_cases(root,'decision_cases.json')] if mode=='offline' else []
    extractions = [run_extraction_case(case,root,index,mode) for case in load_cases(root,'extraction_cases.json')]
    return dict(report_version=1,mode=mode,recorded_at=datetime.now(timezone.utc).isoformat(),
        policy_sha256=index.source_sha256,live_status='not_run' if mode=='offline' else 'attempted',
        passed=all(r['passed'] for r in decisions+extractions),decisions=decisions,extractions=extractions,
        metrics=dict(action_correct=sum(r['action_correct'] for r in decisions),decision_count=len(decisions),
            invalid_actions=sum(r['invalid_action'] for r in decisions),
            grounding_passed=sum(r['grounding_passed'] for r in decisions),
            grounded_source_cases=sum(r['grounding_passed'] for r in decisions if not r['expected'].get('expect_no_policy_evidence')),
            source_case_count=sum(not r['expected'].get('expect_no_policy_evidence',False) for r in decisions),
            information_correct=sum(r['information_correct'] for r in decisions),
            valid_extractions=sum(r['valid_response'] for r in extractions),extraction_count=len(extractions),
            correct_topics=sum(r['correct_topics'] for r in extractions),topic_count=sum(r['topic_count'] for r in extractions),
            covered_anchors=sum(r['covered_anchors'] for r in extractions),anchor_count=sum(r['anchor_count'] for r in extractions)))


def write_report(report, directory):
    directory.mkdir(parents=True, exist_ok=True)
    stem = 'results' if report['mode']=='offline' else 'gemini-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (directory/(stem+'.json')).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    m=report['metrics']
    lines=['# Claims evaluation results','',f"Mode: **{report['mode']}**. Recorded: {report['recorded_at']}.",
           f"Live Gemini status: **{report['live_status']}**.",'',
           'Offline extraction scores describe mock harness behavior, not Gemini quality.',
           'No clinical-truth or statistical accuracy claim is made.','',
           '| Metric | Result |','| --- | --- |',
           f"| Exact actions / critical arguments | {m['action_correct']}/{m['decision_count']} |",
           f"| Grounding / expected topics (source available) | {m['grounded_source_cases']}/{m['source_case_count']} |",
           f"| Missing/unresolved information | {m['information_correct']}/{m['decision_count']} |",
           f"| Invalid actions | {m['invalid_actions']}/{m['decision_count']} |",
           f"| Valid extraction responses | {m['valid_extractions']}/{m['extraction_count']} |",
           f"| Correct extraction topic statuses | {m['correct_topics']}/{m['topic_count']} |",
           f"| Supporting quotation anchors | {m['covered_anchors']}/{m['anchor_count']} |",'',
           '| Case | Pass | Details |','| --- | --- | --- |']
    for r in report['decisions']:
        lines.append(f"| {r['id']} {r['title']} | {r['passed']} | {', '.join(r['failures']) or r['actual'].get('action','invalid input')} |")
    for r in report['extractions']:
        lines.append(f"| {r['id']} ({r['mode']}) | {r['passed']} | {r['result']['status']}; {r['correct_topics']}/4 topics |")
    lines += ['', 'D11 uses the supplied policy and routes unresolved preventive coverage to senior review.',
              'D18 follows the approved senior-review behavior for appeals without established new relevant evidence.',
              'D09 is isolated wrong-policy fault injection. D10/D19/D20/L06 are adversarial/failure cases.',
              'Grounding checks every emitted quote; no-source scenarios pass only if foreign evidence is absent.',
              'Human inspection of live statements remains necessary; exact quotation checks do not prove interpretation.',
              'Detailed inputs, labels, output, trace and failures are in the companion JSON report.','']
    (directory/(stem+'.md')).write_text('\n'.join(lines),encoding='utf-8')
    return str(directory/(stem+'.md'))
