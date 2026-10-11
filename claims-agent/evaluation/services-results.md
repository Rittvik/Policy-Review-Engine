# Policy-wide service evaluation

Passed: 23/23.
Synthetic trusted assessments; this is not a clinical or model-accuracy benchmark.

| Case | Expected | Actual | Pass |
| --- | --- | --- | --- |
| mri-brain.json | approve_claim_payment | approve_claim_payment | True |
| mri-knee-preauth.json | approve_pre_authorization | approve_pre_authorization | True |
| ct-routine.json | approve_claim_payment | approve_claim_payment | True |
| ct-emergency.json | approve_claim_payment | approve_claim_payment | True |
| ct-emergency-unknown.json | route_to_senior_reviewer | route_to_senior_reviewer | True |
| ct-no-authorization.json | route_to_senior_reviewer | route_to_senior_reviewer | True |
| ultrasound.json | approve_claim_payment | approve_claim_payment | True |
| office-visit.json | approve_claim_payment | approve_claim_payment | True |
| specialist.json | approve_claim_payment | approve_claim_payment | True |
| outpatient.json | approve_claim_payment | approve_claim_payment | True |
| emergency-service.json | approve_claim_payment | approve_claim_payment | True |
| inpatient-elective.json | approve_claim_payment | approve_claim_payment | True |
| inpatient-nonelective.json | approve_claim_payment | approve_claim_payment | True |
| inpatient-unknown.json | route_to_senior_reviewer | route_to_senior_reviewer | True |
| dme-exactly-500.json | approve_claim_payment | approve_claim_payment | True |
| dme-over-500-no-auth.json | route_to_senior_reviewer | route_to_senior_reviewer | True |
| dme-over-500-approved.json | approve_claim_payment | approve_claim_payment | True |
| dme-cost-unknown.json | route_to_senior_reviewer | route_to_senior_reviewer | True |
| drug-formulary.json | approve_claim_payment | approve_claim_payment | True |
| specialty-pa-required.json | approve_claim_payment | approve_claim_payment | True |
| specialty-no-pa.json | approve_claim_payment | approve_claim_payment | True |
| drug-formulary-missing.json | route_to_senior_reviewer | route_to_senior_reviewer | True |
| specialty-pa-unknown.json | route_to_senior_reviewer | route_to_senior_reviewer | True |
