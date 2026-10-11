"""Build explicitly synthetic multi-service scenarios; no model or actual patient data."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
from claims_agent.schemas import Claim

ROOT = Path(__file__).resolve().parents[1]


def service_claim(code, *, workflow='payment', emergency=None, elective=None, specialty=None,
                  formulary=None, formulary_pa=None, equipment_cost=None, authorization=True):
    base = json.loads((ROOT/'examples'/('covered_payment.json' if workflow == 'payment' else 'covered_mri.json')).read_text())
    base['procedure_code'] = code
    base['claim_id'] = 'SYNTHETIC-'+code
    base['review_id'] = 'REVIEW-'+code
    text = ('Synthetic clinician assessment: diagnosis supported; service medically necessary and clinically appropriate, '
            'consistent with accepted standards, not for convenience and most cost-effective among comparable alternatives. '
            'Symptomatic diagnostic request; not cosmetic, experimental or medically unnecessary.')
    for name, value in [('emergency_service',emergency),('elective_admission',elective),('specialty_drug',specialty)]:
        if value is not None: text += f' {name} is {str(value).lower()}.'
    for doc in base['documents']:
        if doc['document_id']=='NOTE': doc['text']=text
    if formulary is not None or formulary_pa is not None:
        base['documents'].append(dict(document_id='FORMULARY',document_type='formulary',status='provided',
            text=f'Synthetic HorizonCare Silver PPO 2500 formulary v1, current for this service: {code}; covered={formulary}; PA Required={formulary_pa}.'))
    if equipment_cost is not None:
        base['documents'].append(dict(document_id='COST',document_type='equipment_quote',status='provided',
            text=f'Synthetic equipment service cost: ${equipment_cost}.'))
    if equipment_cost is not None and workflow == 'payment':
        base['claimed_amount'] = equipment_cost
        # Fixture supplies its own amount; the application has no 80% formula.
        base['payment_determination']['payable_amount'] = str((Decimal(equipment_cost) * Decimal('0.8')).quantize(Decimal('0.01')))
        for doc in base['documents']:
            if doc['document_id'] == 'CALC':
                doc['text'] = 'Synthetic independently supplied payable amount: $'+base['payment_determination']['payable_amount']+'.'
                base['payment_determination']['evidence'] = [dict(document_id='CALC',quote=doc['text'])]
    originals={field:deepcopy(base.get(field)) for field in ('coding_assessment','clinical_assessment',
        'treatment_history_applicability','exclusion_assessment','payment_determination','authorization_assessment')}
    for field in originals: base[field]=None
    claim=Claim.model_validate(base)
    def finding(value, doc='NOTE'):
        return dict(status='established' if value else 'not_established',source='synthetic-service-reviewer',
                    reason='Explicit synthetic source assessment; not a real clinical determination.',
                    evidence=[dict(document_id=doc,quote=next(d.text for d in claim.documents if d.document_id==doc))])
    base['coding_assessment']=originals['coding_assessment']|{'request':claim.coding_request().model_dump(mode='json')}
    ca={'request':claim.clinical_request().model_dump(mode='json'), 'diagnosis_support':finding(True), 'medical_necessity':finding(True)}
    if code.startswith('MRI'):
        ca['conservative_treatment_attempted']=finding(True,'HISTORY')
    for name,value in [('emergency_service',emergency),('elective_admission',elective),('specialty_drug',specialty),
                       ('formulary_coverage',formulary),('formulary_pa_required',formulary_pa)]:
        if value is not None: ca[name]=finding(value,'FORMULARY' if name.startswith('formulary') else 'NOTE')
    base['clinical_assessment']=ca
    ea=originals['exclusion_assessment']
    ea['request']=claim.clinical_request().model_dump(mode='json')
    for name,value in ea.items():
        if name!='request' and isinstance(value,dict) and 'evidence' in value:
            value['evidence']=[dict(document_id='NOTE',quote=text)]
    base['exclusion_assessment']=ea
    if workflow=='pre_authorization':
        base['treatment_history_applicability']=originals['treatment_history_applicability']|{
            'request':claim.documentation_request().model_dump(mode='json'),
            'status':'required' if code.startswith('MRI') else 'not_required'}
    else:
        for field in ('payment_determination','authorization_assessment'):
            if originals[field]:base[field]=originals[field]|{'request':claim.payment_request().model_dump(mode='json')}
        if not authorization:
            base['authorization_assessment']=None
            base['prior_authorization_approved']=None
    if equipment_cost is not None:
        base['equipment_cost_assessment']={'request':claim.clinical_request().model_dump(mode='json'),
            'amount':equipment_cost,'source':'synthetic-equipment-quote-reviewer','reason':'Reviewed equipment cost, distinct from total billed and payable amounts.',
            'evidence':[dict(document_id='COST',quote=next(d.text for d in claim.documents if d.document_id=='COST'))]}
    return Claim.model_validate(base)


SCENARIOS = [
 ('mri-brain','MRI-BRAIN',{},'approve_claim_payment'),
 ('mri-knee-preauth','MRI-KNEE',{'workflow':'pre_authorization'},'approve_pre_authorization'),
 ('ct-routine','CT',{'emergency':False},'approve_claim_payment'),
 ('ct-emergency','CT',{'emergency':True,'authorization':False},'approve_claim_payment'),
 ('ct-emergency-unknown','CT',{},'route_to_senior_reviewer'),
 ('ct-no-authorization','CT',{'emergency':False,'authorization':False},'route_to_senior_reviewer'),
 ('ultrasound','ULTRASOUND',{'authorization':False},'approve_claim_payment'),
 ('office-visit','OFFICE-VISIT',{'authorization':False},'approve_claim_payment'),
 ('specialist','SPECIALIST-CONSULTATION',{'authorization':False},'approve_claim_payment'),
 ('outpatient','OUTPATIENT-PROCEDURE',{'authorization':False},'approve_claim_payment'),
 ('emergency-service','EMERGENCY-SERVICE',{'authorization':False},'approve_claim_payment'),
 ('inpatient-elective','INPATIENT-ADMISSION',{'elective':True},'approve_claim_payment'),
 ('inpatient-nonelective','INPATIENT-ADMISSION',{'elective':False,'authorization':False},'approve_claim_payment'),
 ('inpatient-unknown','INPATIENT-ADMISSION',{},'route_to_senior_reviewer'),
 ('dme-exactly-500','DME',{'equipment_cost':'500','authorization':False},'approve_claim_payment'),
 ('dme-over-500-no-auth','DME',{'equipment_cost':'500.01','authorization':False},'route_to_senior_reviewer'),
 ('dme-over-500-approved','DME',{'equipment_cost':'700'},'approve_claim_payment'),
 ('dme-cost-unknown','DME',{},'route_to_senior_reviewer'),
 ('drug-formulary','PRESCRIPTION-DRUG',{'specialty':False,'formulary':True,'authorization':False},'approve_claim_payment'),
 ('specialty-pa-required','SPECIALTY-DRUG',{'specialty':True,'formulary':True,'formulary_pa':True},'approve_claim_payment'),
 ('specialty-no-pa','SPECIALTY-DRUG',{'specialty':True,'formulary':True,'formulary_pa':False,'authorization':False},'approve_claim_payment'),
 ('drug-formulary-missing','PRESCRIPTION-DRUG',{'specialty':False,'authorization':False},'route_to_senior_reviewer'),
 ('specialty-pa-unknown','SPECIALTY-DRUG',{'specialty':True,'formulary':True},'route_to_senior_reviewer'),
]


def main():
    manifest=[]
    for name,code,kwargs,expected in SCENARIOS:
        claim=service_claim(code,**kwargs)
        # Unique IDs per scenario with deliberately regenerated synthetic bindings.
        raw=claim.model_dump_json().replace('REVIEW-'+code, 'SERVICE-'+name)
        claim=Claim.model_validate_json(raw)
        (ROOT/'examples/services'/f'{name}.json').write_text(claim.model_dump_json(indent=2)+'\n')
        label={'file':name+'.json','expected_action':expected}
        if expected=='approve_claim_payment':
            label['expected_payment']={'dme-exactly-500':400.0,'dme-over-500-approved':560.0}.get(name,900.0)
        unknowns={'ct-emergency-unknown':['emergency_service'],'ct-no-authorization':['current_authorization_assessment'],
                  'inpatient-unknown':['elective_admission'],'dme-cost-unknown':['current_equipment_cost_assessment'],
                  'dme-over-500-no-auth':['current_authorization_assessment'],'drug-formulary-missing':['formulary_coverage'],
                  'specialty-pa-unknown':['formulary_pa_required']}
        label['expected_unresolved']=unknowns.get(name,[])
        manifest.append(label)
    (ROOT/'examples/services/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':main()
