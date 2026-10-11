"""Scores cannot replace clinical review or alter decision behavior."""
import json
from pathlib import Path
import pytest
from claims_agent.llm import extract_candidates, prepare_extraction, MockAdapter
from claims_agent.policy import HORIZONCARE, ingest_policy
from claims_agent.schemas import Claim
from claims_agent.trust import evidence_reliability

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def source(tmp_path):
    claim = Claim.model_validate_json((ROOT/'evaluation/extraction/L01.json').read_text())
    index = ingest_policy(HORIZONCARE, ROOT/'policies', tmp_path).index
    prepared = prepare_extraction(claim, index, document_ids=('NOTE1',))
    findings = [dict(topic=t,status='documented',statement='A statement requiring human review.',document_refs=[dict(document_id='NOTE1',quote=prepared.payload.documents[0].text)],policy_refs=[dict(chunk_id=prepared.payload.policy_chunks[0].chunk_id,quote=prepared.payload.policy_chunks[0].text)]) for t in prepared.payload.requested_topics]
    return claim,index,prepared,dict(request_id=prepared.payload.request_id, findings=findings)


def run(source, response):
    claim,index,prepared,_=source
    return extract_candidates(claim,index,document_ids=('NOTE1',),adapter=MockAdapter({prepared.payload.request_id:json.dumps(response)}))


def test_full_provenance_does_not_claim_semantic_correctness(source):
    result=run(source,source[3])
    assert result.evidence_reliability['score']==100
    assert 'not whether quotations entail' in result.evidence_reliability['limitation']
    assert result.evidence_reliability['origin']=='fixture'


@pytest.mark.parametrize('mutation',['quote','binding','topic','policy'])
def test_invalid_outputs_score_zero(source,mutation):
    response=source[3]
    if mutation=='quote':response['findings'][0]['document_refs'][0]['quote']='Invented unsupported quotation'
    if mutation=='binding':response['request_id']='another-review'
    if mutation=='topic':response['findings'].pop()
    if mutation=='policy':response['findings'][0]['policy_refs'][0]['quote']='Invented policy clause'
    result=run(source,response)
    assert result.status=='invalid_response'
    assert result.evidence_reliability['score']==0


def test_no_output_has_no_score(source):
    result=extract_candidates(source[0],source[1],document_ids=('NOTE1',))
    assert result.status=='unavailable'
    assert result.evidence_reliability['score'] is None


def test_not_found_is_not_verified_absence(source):
    response=source[3]
    for finding in response['findings']:
        finding.update(status='not_found',statement=None,document_refs=[],policy_refs=[])
    result=run(source,response)
    assert result.evidence_reliability['score']==40
    assert all(f['absence_verified'] is False for f in result.evidence_reliability['findings'])


def test_recompute_rejects_transferred_result(source):
    result=run(source,source[3]).model_copy(update={'input_sha256':'0'*64})
    assert evidence_reliability(result,source[2])['score']==0


def test_legacy_packets_keep_digest():
    from claims_agent.assessment_review import parse_packet,packet_digest
    packet=parse_packet(json.loads((ROOT/'examples/clinical_review/packet.json').read_text()))
    assert packet_digest(packet)==packet.packet_sha256
