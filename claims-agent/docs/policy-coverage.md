# Supplied-policy coverage and service profiles

The implementation covers the service families and decision provisions in the
supplied HorizonCare Silver PPO 2500 policy. It remains a prototype of a claims
review process, with six local action stubs. Its coverage is no longer restricted
to lumbar MRI. This document supersedes earlier milestone scope descriptions.

## Service coverage

| Service identifier | Clinical/benefit requirements | Prior authorization requirement |
| --- | --- | --- |
| `MRI`, `MRI-*` (any anatomical region) | Supported diagnosis, medical necessity, conservative treatment attempted **or** contraindicated; imaging exclusions | Required for every region |
| `CT`, `CT-*` | Supported diagnosis, medical necessity, imaging exclusions, explicit emergency classification | Required unless emergency status is established |
| `ULTRASOUND` | Supported diagnosis, medical necessity, imaging exclusions | Not listed as requiring PA in this policy |
| `OFFICE-VISIT` | Supported diagnosis, medical necessity, general exclusions | Not listed as requiring PA |
| `SPECIALIST-CONSULTATION` | Same general requirements | Not listed as requiring PA |
| `OUTPATIENT-PROCEDURE` | Same general requirements | Not listed as requiring PA |
| `EMERGENCY-SERVICE` | Same general requirements | Not listed as requiring PA |
| `INPATIENT-ADMISSION`, `ELECTIVE-INPATIENT` | General requirements and explicit elective classification | Required for elective admissions |
| `DME` | General requirements and a source-supported equipment cost assessment | Required only when equipment cost is **greater than $500** |
| `PRESCRIPTION-DRUG`, `SPECIALTY-DRUG` | General requirements, source-supported formulary coverage and specialty classification | Required for specialty drugs marked “PA Required” on the supplied formulary |

These are explicit local service identifiers, not a CPT/NDC mapping database.
The caller/upstream coding assessment must identify the correct service. Names
and narrative text do not automatically select a profile or establish a medical
fact. Generic outpatient/emergency identifiers must not be used to conceal a more
specific service such as CT/MRI or a specialty drug. Unknown service IDs route to
review. Lumbar diagnosis examples in section 5.1 are not a universal diagnosis
allowlist for other MRI regions. A trusted diagnosis-support assessment is required.

CT emergency, elective admission and specialty status are source-bound clinical
findings. `established` means affirmative; `not_established` can support a negative
classification only after the reviewer explicitly assesses the source. Missing
information stays `unknown`. The application cannot certify clinical interpretation.
Contradictions between explicit `ELECTIVE-INPATIENT` / `SPECIALTY-DRUG` IDs and their
classification remain unresolved. An emergency-CT exception does not waive other
coverage, exclusion or payment requirements.

DME uses `equipment_cost_assessment` with a numeric amount, exact document quote,
source/reason and current clinical-request snapshot. It is distinct from billed
and payable amounts. The comparison with $500 is deterministic; neither Gemini
nor a reviewer-supplied boolean determines the threshold result. Cost missing,
stale or unsupported by its source prevents approval. The field can be explicitly
carried forward in a confirmed review. The numeric assessment is supplied upstream;
Gemini does not calculate it.

Drug decisions require a supplied document with type `formulary`. The policy PDF
specifies formulary-based coverage but does not contain a formulary. A clinician
note alone cannot establish formulary coverage or its PA designation. Missing,
conflicting, unverified or not-established coverage routes for review; it is not
invented from the policy's general benefits statement. Example formularies are
**synthetic fixtures**, never presented as the real insurer's drug list. Currentness,
authenticity and correct drug/plan applicability remain the trusted assessor's
responsibility in this local prototype.

## Every policy section

| Section | Implemented behavior |
| --- | --- |
| 1 Benefits | General medically necessary/nonexcluded service coverage; formulary dependency for drugs; no invented cost-sharing formula |
| 2 Eligibility | Inactive membership denies; unresolved eligibility cannot approve |
| 3 / 3.1 Authorization | MRI, CT emergency exception, elective admission, strict DME threshold, specialty formulary designation, prior/retroactive authorization |
| 3.2 Documentation | Clinical note, diagnosis, expected date/location, treatment history when applicable; request known missing documents |
| 4 Necessity | Source-bound trusted/reviewer assessment of the stated standard; no model-only clinical verdict |
| 5.1 MRI | Diagnosis and treatment-or-contraindication requirements for every MRI region; approved authorization for payment |
| 5.2 Imaging | Screening/preventive exception and imaging documentation exclusions; applies to MRI, CT and ultrasound only |
| 6 Exclusions | Cosmetic/reconstructive with trauma/congenital exception, unnecessary and experimental services, authorization and duplicate checks |
| 7.1 Duplicates | Exact five-field comparison, correction handling and immutable review IDs |
| 7.2 Coding | Source-bound upstream coding assessment; inconsistent codes route to coding review |
| 8 Appeals | Saved denial linkage, required documents, inclusive 0–180-day interpretation, new relevant evidence, reassessment of original service workflow |
| 9 Contact | Informational insurer contact details; no adjudication rule or external contact action |

The strict **billed amount above $5,000** rule comes from the task, independently
of the policy's **DME equipment cost above $500** authorization threshold. Payment
uses the supplied trusted payable amount and validates it against the bill; no
benefit formula is inferred from the plan name. The DME examples' payment amounts
are synthetic supplied determinations, not an implemented reimbursement percentage.

All profiles use the same precedence and six-action validation boundary.
Pre-authorization approval means the submitted request passed the coverage review;
the trace separately records whether this policy mandates prior authorization.
Payment approvals require authorization only where applicable. A missing required
approval remains a review case because the policy allows retroactive authorization
and discretionary denial. Unknown exceptions are never silently treated as false.
Screening without symptoms remains unresolved if its preventive exception cannot
be established or ruled out using relevant policy evidence. No external preventive
schedule or clinical guidelines have been invented. Appeals without established
new relevant evidence retain the previously approved senior-review outcome.

## Gemini and human review

The extractor selects topics from `services.py`. MRI keeps its four original
topics; CT adds emergency classification to diagnosis/necessity; inpatient adds
elective status; drugs add formulary coverage, specialty status and formulary PA.
Other services use diagnosis/necessity. Conservative treatment is not applied to
non-MRI services. Only selected clinical notes, treatment histories and formulary
text can enter the reduced model payload; structured identities/payment amounts
and the separate numeric DME assessment remain local. Free text is not redacted.

The extraction instruction still requests quotations and forbids decisions or
amount calculations. Service requests use `clinical-candidates-services-v2` for
input binding; legacy lumbar-MRI requests retain v1 for recorded-demo compatibility.
Candidates remain untrusted until explicit reviewer assessment. The confirmation
form requires the exact ordered topic set for the selected service; it cannot
accept an MRI form for a CT claim. All applicable verdicts start unreviewed.

Legacy Python class/function names containing `MRI` are retained where necessary
for compatibility. `ClinicalAssessment` aliases the expanded assessment schema;
non-MRI traces use `service_clinical_conditions` and `service_exclusions`. Existing
source records are not migrated or overwritten. New optional fields are omitted
when absent so legacy snapshot hashes remain stable.

## Verification and reproduction

```sh
uv run --locked python -m claims_agent.cli evaluate-services
uv run --locked python -m claims_agent.cli review --input examples/services/ct-emergency.json --format human
uv run --locked python -m claims_agent.cli review --input examples/services/dme-over-500-no-auth.json --format human
uv run --locked python -m claims_agent.cli review --input examples/services/drug-formulary-missing.json --format human
```

The additional evaluation has 23 labelled service scenarios, including payment
amount and unresolved-field assertions, alongside the original 20-case evaluation.
Tests also cover general exclusions/trauma exceptions, policy revisions, stale
cost evidence, wrong-source formularies, dynamic extraction/confirmation and
appeals across the new families. See [service results](../evaluation/services-results.md)
and [examples](../examples/services/README.md). Scope limitations are explicit
review dependencies, not claims of autonomous handling of unknown clinical facts.
