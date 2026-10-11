"""Regression tests for the independent audit's actual trust-boundary defects."""
import json
import re
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from claims_agent.web import create_app
from claims_agent.schemas import Claim
from claims_agent.decisions import InputValidationFailure
from claims_agent.controller import ReviewController
from claims_agent.reviews import ReviewStore
from claims_agent.policy import HORIZONCARE, ingest_policy
from claims_agent.assessment_review import parse_packet, apply_review

ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads((ROOT/p).read_text())
@pytest.fixture
def client(tmp_path):
 with TestClient(create_app(ROOT,tmp_path/'web.sqlite3')) as c:
  token_match = re.search(r'name="review-token" content="([^"]+)"', c.get('/').text)
  assert token_match is not None
  c.headers['x-review-token'] = token_match.group(1)
  yield c

@pytest.mark.parametrize('file',['mri-brain','ct-routine','ultrasound','office-visit','specialist','outpatient','emergency-service','inpatient-elective','dme-exactly-500','drug-formulary','specialty-pa-required'])
def test_api_never_rebinds_stale_assessments(client,file):
 claim=load('examples/services/'+file+'.json');claim['review_id']+='-new';original=deepcopy(claim)
 res=client.post('/api/review',json=dict(claim=claim,mode='disabled'))
 assert res.status_code==422 or res.json()['decision']['action'] not in {'approve_claim_payment','approve_pre_authorization'}
 assert claim==original

@pytest.mark.parametrize('mutation',['request','source','evidence','reason'])
def test_incomplete_assessments_rejected_by_schema_and_api(client,mutation):
 claim=load('examples/services/office-visit.json')
 if mutation=='request':claim['clinical_assessment'].pop('request')
 else:claim['clinical_assessment']['diagnosis_support'].pop(mutation)
 with pytest.raises(ValidationError):Claim.model_validate(claim)
 assert client.post('/api/review',json=dict(claim=claim,mode='disabled')).status_code==422

@pytest.mark.parametrize('route',['/api/review','/api/appeal'])
def test_unverified_appeal_history_is_not_imported(client,route):
 appeal=load('examples/appeal_submission.json')
 body=dict(claim=appeal,mode='disabled',save=True) if route=='/api/review' else appeal
 res=client.post(route,json=body)
 assert res.status_code==200
 assert res.json()['decision']['action']=='route_to_senior_reviewer'
 assert client.get('/api/history').json()['total']==0


def test_unknown_history_and_missing_identity_are_not_invented():
 claim=load('examples/services/office-visit.json');claim['prior_claims']=None
 assert Claim.model_validate(claim).prior_claims is None
 claim.pop('review_id')
 with pytest.raises(ValidationError):Claim.model_validate(claim)


def test_history_failure_cannot_approve(tmp_path):
 controller=ReviewController(ROOT/'policies',tmp_path/'cache');store=ReviewStore(tmp_path/'store.sqlite3')
 with patch.object(store,'history',side_effect=OSError('unavailable')):
  decision=controller.review(load('examples/services/office-visit.json'),store=store)
 assert not isinstance(decision, InputValidationFailure)
 assert decision.action=='route_to_senior_reviewer'


def test_confirmed_review_checks_other_saved_duplicates(tmp_path):
 controller=ReviewController(ROOT/'policies',tmp_path/'cache');store=ReviewStore(tmp_path/'store.sqlite3')
 packet=parse_packet(load('examples/clinical_review/packet.json'))
 other=Claim.model_validate(load('examples/covered_mri.json'))
 other=other.model_copy(update={'claim_id':'OTHER-CLAIM','review_id':'OTHER-REVIEW','member_id':packet.source_claim.member_id,'service_date':packet.source_claim.service_date,'provider_npi':packet.source_claim.provider_npi})
 # A saved submission may have an unresolved assessment but still supplies duplicate identity.
 dec=controller.review(other)
 assert not isinstance(dec, InputValidationFailure)
 store.save(other,dec)
 index=ingest_policy(HORIZONCARE,ROOT/'policies',tmp_path/'cache').index
 response=load('examples/clinical_review/reviewer_response.json')
 saved=apply_review(packet,response,index,controller,store)
 assert saved.decision.action=='deny_claim'
 assert any(t.rule_id=='duplicate_claim' and t.outcome=='matched' for t in saved.decision.context.decision_trace)
