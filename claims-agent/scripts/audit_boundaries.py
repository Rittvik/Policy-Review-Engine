"""Additional isolated API lifecycle checks; append to an existing audit report."""
from audit_system import *
from unittest.mock import patch
from claims_agent.llm import ExtractionResult, ModelPayload
from claims_agent.assessment_review import prepare_packet, review_template
from claims_agent.reviews import ReviewStore


def main():
    out=Path(sys.argv[1]); report=json.loads((out/'results.json').read_text())
    def add(id, expected, actual, **extra):
        report['cases'] = [r for r in report['cases'] if r['id'] != id]
        report['cases'].append(dict(id=id, category='Review lifecycle',kind='independent API boundary',expected=expected,actual=actual,result='PASS' if expected==actual else 'FAIL',correctness=100 if expected==actual else 0,**extra))
    with TemporaryDirectory(prefix='claims-boundary-') as temp:
        temp=Path(temp)
        def client_for(name):
            client=TestClient(create_app(ROOT,store_path=temp/(name+'.sqlite3')))
            client.headers['x-review-token'] = extract_token(client.get('/').text)
            return client
        for route in ('/api/review','/api/appeal'):
            with client_for(route.split('/')[-1]) as client:
                data=read('examples/appeal_submission.json')
                payload=dict(claim=data,mode='disabled',save=True) if route=='/api/review' else data
                resp=client.post(route,json=payload);body=resp.json()
                add('unverified-prior'+route.replace('/','-'),False,body.get('decision',{}).get('action')=='approve_pre_authorization',response=body,http_status=resp.status_code)
        for mutation in ('missing_evidence','missing_binding','missing_source'):
            with client_for(mutation) as client:
                claim=read('examples/services/office-visit.json')
                assessment=claim['clinical_assessment']
                if mutation=='missing_binding':assessment.pop('request',None)
                elif mutation=='missing_source':assessment['diagnosis_support'].pop('source',None)
                else:
                    for v in assessment.values():
                        if isinstance(v,dict) and 'evidence' in v:v['evidence']=[]
                resp=client.post('/api/review',json=dict(claim=claim,mode='disabled'))
                add(mutation,False,resp.json().get('decision',{}).get('action')=='approve_claim_payment',response=resp.json(),http_status=resp.status_code)
        # Actual Gemini transport is mocked here, clearly labelled. It exercises complete web bridge.
        with client_for('human-bridge') as client:
            def fixture_generate(self,call):
                payload=ModelPayload.model_validate_json(call.payload_json)
                recorded=read('examples/clinical_review/extraction.json')['advisory']['candidates']
                recorded['request_id']=payload.request_id
                return json.dumps(recorded)
            source=read('examples/clinical_review/source_claim.json')
            with patch('claims_agent.gemini.GeminiAdapter.generate',fixture_generate):
                resp=client.post('/api/review',json=dict(claim=source,mode='gemini',save=True))
            body=resp.json()
            if body.get('extraction',{}).get('evidence_reliability'):
                body['extraction']['evidence_reliability']['origin']='mocked_transport'
            add('mock-web-extraction', 'validated_candidates',body.get('extraction',{}).get('status'),trust=body.get('extraction',{}).get('evidence_reliability'),execution='mocked transport, not live Gemini')
            if body.get('packet'):
                assessment=read('examples/clinical_review/reviewer_response.json')
                assessment['packet_sha256']=body['packet']['packet_sha256']
                for variant in ('unconfirmed','tampered','confirmed','replay'):
                    packet=deepcopy(body['packet']); response=deepcopy(assessment)
                    if variant=='unconfirmed':response['confirmed_sources']=False
                    if variant=='tampered':packet['source_claim']['notes']='altered after extraction'
                    res=client.post('/api/confirm',json=dict(packet=packet,assessment=response))
                    expected=200 if variant=='confirmed' else (409 if variant=='replay' else 422)
                    if variant=='replay':
                        add('confirmation-replay',422,res.status_code,response=res.json())
                    elif variant=='confirmed':
                        add('confirmation-confirmed',dict(status=200, action='approve_pre_authorization'),dict(status=res.status_code, action=res.json().get('decision',{}).get('action')),response=res.json())
                    else:add('confirmation-'+variant,expected,res.status_code,response=res.json())
            no_token=client.headers.pop('x-review-token')
            add('csrf-required',403,client.post('/api/review',json=dict(claim=source,mode='disabled')).status_code)
            client.headers['x-review-token']=no_token
            add('malformed-json',422,client.post('/api/review',content='{broken',headers={'content-type':'application/json'}).status_code)
    render(report,out)
    print('Boundary audit appended:',len(report['cases']))

if __name__=='__main__':main()
