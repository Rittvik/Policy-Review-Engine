# Claims evaluation results

Mode: **offline**. Recorded: 2026-10-11T15:33:00.746304+00:00.
Live Gemini status: **not_run**.

Offline extraction scores describe mock harness behavior, not Gemini quality.
No clinical-truth or statistical accuracy claim is made.

| Metric | Result |
| --- | --- |
| Exact actions / critical arguments | 20/20 |
| Grounding / expected topics (source available) | 17/17 |
| Missing/unresolved information | 20/20 |
| Invalid actions | 0/20 |
| Valid extraction responses | 6/6 |
| Correct extraction topic statuses | 24/24 |
| Supporting quotation anchors | 14/14 |

| Case | Pass | Details |
| --- | --- | --- |
| D01 Covered MRI | True | approve_pre_authorization |
| D02 Inactive plan | True | deny_claim |
| D03 Missing clinical note | True | request_missing_documentation |
| D04 Exactly 5000 | True | approve_pre_authorization |
| D05 Above 5000 | True | route_to_senior_reviewer |
| D06 Five-field duplicate | True | deny_claim |
| D07 Coding mismatch | True | route_to_coding_review |
| D08 Unknown insurer | True | route_to_senior_reviewer |
| D09 Wrong-policy chunk | True | route_to_senior_reviewer |
| D10 Injection cannot override inactive status | True | deny_claim |
| D11 Screening exception unresolved | True | route_to_senior_reviewer |
| D12 Missing policy | True | route_to_senior_reviewer |
| D13 Missing provider NPI | True | route_to_senior_reviewer |
| D14 Payment with prior authorization | True | approve_claim_payment |
| D15 Payment with retroactive authorization | True | approve_claim_payment |
| D16 Missing payment determination | True | route_to_senior_reviewer |
| D17 Appeal with new relevant evidence | True | approve_pre_authorization |
| D18 Appeal without established new evidence | True | route_to_senior_reviewer |
| D19 Unsupported model action | True | approve_pre_authorization |
| D20 Model unavailable | True | approve_pre_authorization |
| L01 (offline) | True | validated_candidates; 4/4 topics |
| L02 (offline) | True | validated_candidates; 4/4 topics |
| L03 (offline) | True | validated_candidates; 4/4 topics |
| L04 (offline) | True | validated_candidates; 4/4 topics |
| L05 (offline) | True | validated_candidates; 4/4 topics |
| L06 (offline) | True | validated_candidates; 4/4 topics |

D11 uses the supplied policy and routes unresolved preventive coverage to senior review.
D18 follows the approved senior-review behavior for appeals without established new relevant evidence.
D09 is isolated wrong-policy fault injection. D10/D19/D20/L06 are adversarial/failure cases.
Grounding checks every emitted quote; no-source scenarios pass only if foreign evidence is absent.
Human inspection of live statements remains necessary; exact quotation checks do not prove interpretation.
Detailed inputs, labels, output, trace and failures are in the companion JSON report.
