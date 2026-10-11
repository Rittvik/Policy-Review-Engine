# HorizonCare Silver PPO 2500 — Codes, JSON Schema & Adjudication Reference Manual

This manual provides the complete catalog of all **Procedure Codes**, **Diagnosis Codes (ICD-10)**, **JSON Schema Attributes**, **Permitted Values**, **Adjudication Decisions**, and **Copy-Paste Templates** evaluated by the HorizonCare Claims Review Engine.

---

## 1. Complete Procedure Code Catalog

The review engine evaluates explicit service profiles mapped to HorizonCare coverage provisions (`policies/horizoncare_silver_ppo_2500.pdf`).

| Procedure Code | Service Name & Category | Prior Auth Requirement | Key Clinical Prerequisites | Resulting Action When Criteria Met | Resulting Action When Criteria Failed / Missing |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **`MRI-LUMBAR`** | Lumbar Spine MRI (Diagnostic Imaging) | **Required** (Sec 3.1 & 5.1) | Supported diagnosis (`M54.5`), medical necessity, conservative therapy attempted (6+ wks) OR contraindicated | `approve_pre_authorization` (or `approve_claim_payment` for payment) | `deny_claim` if therapy not attempted and not contraindicated; `route_to_coding_review` if mismatched code |
| **`MRI-CERVICAL`** | Cervical Spine MRI (Diagnostic Imaging) | **Required** (Sec 3.1 & 5.1) | Supported cervical diagnosis (`M54.2`), medical necessity, conservative therapy attempted OR contraindicated | `approve_pre_authorization` | `deny_claim` if therapy not attempted |
| **`MRI-KNEE`** | Knee MRI (Diagnostic Imaging) | **Required** (Sec 3.1 & 5.1) | Joint diagnosis, medical necessity, conservative therapy attempted OR contraindicated | `approve_pre_authorization` | `deny_claim` if therapy not attempted |
| **`MRI-BRAIN`** | Brain MRI (Diagnostic Imaging) | **Required** (Sec 3.1 & 5.1) | Neurological indications, medical necessity | `approve_claim_payment` (with PA) | `route_to_senior_reviewer` if PA missing |
| **`MRI`** or **`MRI-*`** | Any anatomical MRI region | **Required** (Sec 3.1 & 5.1) | Region-appropriate diagnosis, medical necessity, conservative treatment attempted OR contraindicated | `approve_pre_authorization` / `approve_claim_payment` | `deny_claim` or `route_to_senior_reviewer` |
| **`CT`** / **`CT-*`** (Routine) | Computed Tomography (Routine non-emergency) | **Required** (Sec 3.1 & 5.2) | Supported diagnosis (`R10.9`, etc.), medical necessity, approved Prior Authorization | `approve_claim_payment` (e.g. $900.00) | `route_to_senior_reviewer` (missing PA) |
| **`CT`** / **`CT-*`** (Emergency) | Emergency CT Scan | **Waived** (Sec 3.1 exception) | Emergency classification (`emergency_service = established`), acute necessity | `approve_claim_payment` | `route_to_senior_reviewer` if emergency status unverified |
| **`ULTRASOUND`** | Diagnostic Ultrasound (Abdominal/Pelvic/Doppler) | **Not Required** (Sec 1 & 5.2) | Documented diagnostic symptoms, medical necessity | `approve_claim_payment` (e.g. $320.00) or `approve_pre_authorization` | `deny_claim` if member inactive or exclusions apply |
| **`OFFICE-VISIT`** | Primary Care Evaluation & Management | **Not Required** (Sec 1) | Covered evaluation visit, valid diagnosis, claimed amount <= $5,000 | `approve_claim_payment` (e.g. $60.00) | `route_to_senior_reviewer` if amount > $5,000 |
| **`SPECIALIST-CONSULTATION`** | Outpatient Specialist Consultation | **Not Required** (Sec 1) | Diagnostic workup, clinical note, claimed amount <= $5,000 | `approve_claim_payment` (e.g. $140.00) | `deny_claim` if duplicate submission |
| **`OUTPATIENT-PROCEDURE`** | Ambulatory Outpatient Surgery/Procedure | **Not Required** (Sec 1) | Clinical note establishing necessity, claimed amount <= $5,000 | `approve_claim_payment` (e.g. $260.00) | `route_to_senior_reviewer` if amount > $5,000 |
| **`EMERGENCY-SERVICE`** | Emergency Department Care | **Waived** (Sec 1 & 3.1) | Emergency condition documentation | `approve_claim_payment` (e.g. $480.00) | `deny_claim` if member inactive |
| **`INPATIENT-ADMISSION`** (Elective) | Elective Inpatient Hospital Admission | **Required** (Sec 3.1) | Elective classification (`elective_admission = established`), approved Prior Authorization | `approve_claim_payment` | `route_to_senior_reviewer` (elective admission lacking PA) |
| **`INPATIENT-ADMISSION`** (Urgent/Emergent) | Non-Elective Inpatient Hospital Admission | **Waived** (Sec 3.1) | Non-elective classification (`elective_admission = not_established`), acute admission note | `approve_claim_payment` | `route_to_senior_reviewer` if status unknown |
| **`DME`** (Cost <= $500) | Durable Medical Equipment (Low Cost) | **Waived** (Sec 3.1 threshold) | Source equipment cost assessment <= $500.00 (e.g. $350 or $500 exactly) | `approve_claim_payment` | `deny_claim` if member inactive |
| **`DME`** (Cost > $500) | Durable Medical Equipment (High Cost) | **Required** (Sec 3.1) | Source equipment cost assessment > $500.00 (e.g. $850.00) with approved Prior Authorization | `approve_claim_payment` | `route_to_senior_reviewer` (DME > $500 lacking PA) |
| **`PRESCRIPTION-DRUG`** | Standard Formulary Medication | **Not Required** (unless marked on formulary) | Verified covered on plan formulary document (`formulary_coverage = established`) | `approve_claim_payment` | `route_to_senior_reviewer` (non-formulary medication) |
| **`SPECIALTY-DRUG`** (PA Required) | High-Cost Specialty Medication | **Required** (Sec 3.1) | Verified on formulary, specialty classification, approved Prior Authorization | `approve_claim_payment` (e.g. $2,400.00) | `route_to_senior_reviewer` (specialty drug lacking PA) |
| **`SPECIALTY-DRUG`** (PA Waived) | Specialty Medication with PA Waiver | **Waived** (Formulary exception) | Verified on formulary, formulary specifies `formulary_pa_required = not_established` | `approve_claim_payment` | `route_to_senior_reviewer` if unlisted |

---

## 2. Complete Diagnosis Code Catalog (ICD-10)

| Diagnosis Code | Clinical Condition Description | Compatible Procedure Codes | Incompatible Procedure Codes | Result When Paired with Incompatible Procedure |
| :--- | :--- | :--- | :--- | :--- |
| **`M54.5`** | Low back pain (Lumbar spine) | `MRI-LUMBAR`, `CT`, `OFFICE-VISIT`, `SPECIALIST-CONSULTATION`, `OUTPATIENT-PROCEDURE`, `DME`, `PRESCRIPTION-DRUG` | Ophthalmic / Optical procedures, Dermatological excision | `route_to_coding_review` (Section 7.2 coding mismatch) |
| **`M54.2`** | Cervicalgia (Cervical neck pain) | `MRI-CERVICAL`, `CT-CHEST`, `CT-HEAD`, `OFFICE-VISIT`, `SPECIALIST-CONSULTATION` | Lumbar spine procedures (`MRI-LUMBAR` without back symptoms) | `route_to_coding_review` |
| **`M25.561`** / **`M25.56`** | Pain in right / unspecified knee joint | `MRI-KNEE`, `ULTRASOUND`, `OFFICE-VISIT`, `OUTPATIENT-PROCEDURE`, `DME` (Knee brace) | Spinal procedures (`MRI-LUMBAR`) | `route_to_coding_review` |
| **`R10.9`** | Unspecified abdominal pain | `ULTRASOUND`, `CT` (Abdomen/Pelvis), `EMERGENCY-SERVICE`, `OUTPATIENT-PROCEDURE`, `OFFICE-VISIT` | Eye exams, isolated spinal procedures | `route_to_coding_review` |
| **`H52.1`** | Myopia (Nearsightedness - Eye disorder) | Eye evaluation, Refraction | `MRI-LUMBAR`, `MRI-CERVICAL`, `CT-ABDOMEN`, `DME-WHEELCHAIR` | **`route_to_coding_review`** strictly triggered |

---

## 3. JSON Schema Attributes & Permitted Values

### Top-Level Claim Attributes
| JSON Field | Permitted Values | Default / Typical | Effect on Adjudication |
| :--- | :--- | :---: | :--- |
| **`claim_type`** | `"pre_authorization"`, `"payment"`, `"appeal"` | `"pre_authorization"` | Determines the adjudication pipeline: pre-service review, post-service payment, or appeal overturn. |
| **`member_status`** | `"active"`, `"inactive"` | `"active"` | `"inactive"` triggers immediate **`deny_claim`** under Section 2 eligibility rules. |
| **`provider_npi`** | 10-digit string (e.g. `"1234567890"`) or `null` | `"1234567890"` | `null` triggers **`route_to_senior_reviewer`** (unresolved provider verification). |
| **`claimed_amount`** | Numeric string (e.g. `"1200"`, `"5000"`, `"5001"`) | `"1200"` | Amounts **> $5,000.00** strictly trigger **`route_to_senior_reviewer`** (high-value audit). Exactly $5,000.00 is permitted. |
| **`prior_authorization_approved`** | `true`, `false`, `null` | `null` | Explicit flag for service pre-approval. |
| **`correction_declared`** | `true`, `false` | `false` | When `true` on duplicate claim, bypasses automatic denial and triggers **`route_to_senior_reviewer`**. |
| **`corrects_claim_id`** | String (prior claim ID) or `null` | `null` | Identifies original claim being corrected. |
| **`prior_claims`** | Array of prior snapshots `[]` | `[]` | Exact match on 5 fields (Member, Provider, Date, Procedure, Amount) triggers **`deny_claim`** (Duplicate). |

---

### Assessments & Clinical Findings

#### A. Coding Consistency (`coding_assessment`)
| Sub-Attribute | Permitted Values | Adjudication Outcome |
| :--- | :--- | :--- |
| **`status`** | `"consistent"` | Passes coding check under Section 7.2. |
| | `"inconsistent"` | Strictly triggers **`route_to_coding_review`** (e.g. pairing eye diagnosis `H52.1` with `MRI-LUMBAR`). |
| | `"unknown"` | Triggers **`route_to_senior_reviewer`**. |

---

#### B. Treatment History Applicability (`treatment_history_applicability`)
| Sub-Attribute | Permitted Values | Adjudication Outcome |
| :--- | :--- | :--- |
| **`status`** | `"required"` | Mandated for all MRI services under Section 5.1; activates conservative therapy requirement. |
| | `"not_required"` | Automatically set/allowed for non-MRI services (office visits, ultrasound, etc.); waives PT requirement. |
| | `"unknown"` | Unresolved; routes to senior reviewer. |

---

#### C. Clinical Assessment Findings (`clinical_assessment`)
Each clinical finding supports the following status values:
`"established"`, `"not_established"`, `"unknown"`, `"conflicting"`

| Finding Name | Value | Adjudication Outcome |
| :--- | :--- | :--- |
| **`diagnosis_support`** | `"established"` | Medical records confirm the submitted ICD-10 diagnosis. |
| | `"not_established"` | Diagnosis unsupported; triggers senior reviewer. |
| **`medical_necessity`** | `"established"` | Service meets clinical necessity standard under Section 4. |
| | `"not_established"` | Fails medical necessity; denied or routed. |
| **`conservative_treatment_attempted`** | `"established"` | Documented 6+ weeks conservative therapy (PT, medication) for MRI; satisfies Section 5.1. |
| | `"not_established"` | Conservative therapy was not attempted; requires contraindication check. |
| **`conservative_treatment_contraindicated`** | `"established"` | Documented red-flag contraindication (progressive neuro deficit, cauda equina); **approves MRI even without PT attempt!** |
| | `null` / `"not_established"` | No contraindication present. |
| **`emergency_service`** | `"established"` | Documented acute emergency; **waives Prior Authorization for CT scans under Section 3.1!** |
| | `"not_established"` | Non-emergency service; routine PA rules apply. |
| **`elective_admission`** | `"established"` | Elective hospital admission; **mandates Prior Authorization under Section 3.1**. |
| | `"not_established"` | Urgent/emergent admission; exempt from elective PA requirement. |
| **`formulary_coverage`** | `"established"` | Prescription drug verified on plan formulary document. |
| | `"not_established"` | Non-formulary drug; triggers senior review. |
| **`specialty_drug`** | `"established"` | Medication classified as high-cost specialty drug. |
| **`formulary_pa_required`** | `"established"` | Formulary document mandates Prior Authorization for this drug. |
| | `"not_established"` | Formulary explicitly waives PA; allows approval without PA. |

---

#### D. Exclusions Assessment (`exclusion_assessment`)
Each exclusion finding supports the following status values:
`"ruled_out"`, `"established"`, `"unknown"`, `"conflicting"`

| Exclusion Name | Value | Adjudication Outcome |
| :--- | :--- | :--- |
| **`screening_without_symptoms`** | `"ruled_out"` | Patient is symptomatic; passes Section 5.2 imaging exclusion check. |
| | `"established"` | Asymptomatic routine screening; excluded unless preventive exception applies. |
| **`cosmetic_or_reconstructive`** | `"ruled_out"` | Medically necessary functional care, not cosmetic. |
| | `"established"` | Cosmetic procedure; triggers **`deny_claim`** unless trauma exception applies. |
| **`required_by_trauma_or_congenital_anomaly`** | `"established"` | Accidental trauma or birth defect; **waives cosmetic exclusion under Section 6**. |
| | `null` / `"not_established"` | Cosmetic exception does not apply. |
| **`experimental_or_investigational`** | `"ruled_out"` | Standard established medical care. |
| | `"established"` | Experimental protocol; strictly triggers **`deny_claim`** under Section 6. |
| **`medically_unnecessary`** | `"ruled_out"` | Clinically indicated service. |
| | `"established"` | Medically unnecessary; strictly triggers **`deny_claim`** under Section 6. |

---

#### E. Payment Determinations (`payment_determination`)
Used exclusively for `claim_type: "payment"`.

| Sub-Attribute | Permitted Values | Adjudication Outcome |
| :--- | :--- | :--- |
| **`status`** | `"determined"` | Trusted calculation completed; requires `payable_amount`. |
| | `null` / `"unknown"` | Missing calculation; triggers **`route_to_senior_reviewer`**. |
| **`payable_amount`** | Numeric string (e.g. `"900"`, `"320"`) | The exact dollar amount payable after deductibles and co-insurance. |

---

#### F. Payment Authorization Assessment (`authorization_assessment`)
Used for verifying prior approvals during post-service payment adjudication.

| Sub-Attribute | Permitted Values | Adjudication Outcome |
| :--- | :--- | :--- |
| **`prior.status`** | `"approved"` | Service had approved prior authorization before service date; satisfies Section 3.1. |
| | `"not_obtained"` | No pre-service authorization on file. |
| **`retroactive.status`** | `"approved"` | Service granted retroactive authorization; satisfies Section 3.1 post-service. |
| | `null` / `"not_obtained"` | No retroactive authorization granted. |

---

#### G. Document Object Attributes (`documents[]`)
| Attribute | Permitted Values | Description |
| :--- | :--- | :--- |
| **`document_type`** | `"clinical_note"` | Physician notes, clinical consults, physical exam findings. |
| | `"prior_treatment_history"` | Physical therapy records, conservative care history. |
| | `"payment_calculation"` | Trusted benefits / pricing determination record. |
| | `"authorization"` | Prior or retroactive authorization approval letter. |
| | `"formulary"` | Health plan drug formulary coverage document. |
| | `"written_appeal"` | Written appeal letter for formal appeal submissions. |
| | `"denial_letter"` | Initial adverse determination / denial letter. |
| | `"appeal_receipt"` | Proof of receipt date stamped by the insurer. |
| **`status`** | `"provided"` | Document text is present and verifiable. |
| | `"missing"` | Document was omitted; triggers **`request_missing_documentation`**. |

---

#### H. Appeal Envelope Attributes (`timing_assessment` & `evidence_assessment`)
Used for `claim_type: "appeal"`.

| Assessment | Sub-Attribute | Permitted Values | Adjudication Outcome |
| :--- | :--- | :--- | :--- |
| **`timing_assessment`** | `denial_notice.status` | `"established"` | Requires `value: "YYYY-MM-DD"`. Date of original denial. |
| | `appeal_received.status` | `"established"` | Requires `value: "YYYY-MM-DD"`. Date appeal was received. |
| | *Date Difference* | **<= 180 days** | Timely appeal under Section 8 statutory deadline. |
| | *Date Difference* | **> 180 days** | Untimely appeal; strictly triggers **`route_to_senior_reviewer`**. |
| **`evidence_assessment`** | `new_relevant_evidence.status` | `"established"` | New clinical records addressing denial reason; allows overturn. |
| | | `"not_established"` | No new evidence; appeal upheld / routed to senior reviewer. |

---

## 4. Strict Assessment Validation & Request Binding Rules

To maintain absolute audit integrity and prevent security bypasses:
1. **No Silent Auto-Repair:** The system enforces strict Pydantic schema validation. Incomplete assessments (e.g. missing evidence citations, missing request bindings, or omitted sources) are rejected with HTTP 422 rather than silently defaulted or repaired.
2. **Request-Binding Enforcement:** Assessments contain frozen snapshots of the exact reviewed request (`request.review_id`, `request.claim_id`). Mismatched or mutated review IDs trigger senior review routing, preventing stale assessments from being improperly rebound to new reviews without clinician re-attestation.
3. **Verified Lineage for Appeals:** Appeal entry points (`/api/appeal`, CLI `appeal`) require pre-existing, verified historical records in `ReviewStore`. Unverified lineage is rejected.

---

## 5. Complete Decision Determination Matrix

| Scenario / Trigger Condition | Policy Gate Triggered | Resulting Decision Action (`action`) | Context Reason (`reason`) |
| :--- | :--- | :--- | :--- |
| **Member coverage inactive** on date of service | Section 2 (Eligibility) | `deny_claim` | *"Plan inactive at time of service."* |
| **Exact 5-field duplicate** matches prior claim (same member, provider, date, procedure, amount) | Section 7.1 (Duplicate Detection) | `deny_claim` | *"Duplicate claim submission."* |
| Duplicate match, but `correction_declared: true` | Section 7.1 / Section 6.5 (Correction) | `route_to_senior_reviewer` | *"Resubmission with declared correction requires examiner review."* |
| **Clinically incompatible diagnosis & procedure** (e.g. `H52.1` with `MRI-LUMBAR`) | Section 7.2 (Coding Consistency) | `route_to_coding_review` | *"Clinically inconsistent coding requires coding specialist review."* |
| **Missing required clinical notes** or prior treatment history | Section 3.2 (Documentation) | `request_missing_documentation` | *"Pended for missing documentation: clinical_note, prior_treatment_history."* |
| **Claimed amount strictly exceeds $5,000.00** (e.g. $5,001.00) | Governance (High-Value Gate) | `route_to_senior_reviewer` | *"Claimed amount exceeds $5,000 threshold; routed to senior reviewer."* |
| **Experimental or investigational service** (`experimental_or_investigational: "established"`) | Section 6 (General Exclusions) | `deny_claim` | *"Experimental or investigational service excluded under policy Section 6."* |
| **Cosmetic service without trauma/congenital origin** (`cosmetic_or_reconstructive: "established"`) | Section 6 (General Exclusions) | `deny_claim` | *"Cosmetic service excluded under policy Section 6."* |
| Cosmetic service caused by accidental trauma (`required_by_trauma_or_congenital_anomaly: "established"`) | Section 6 (Trauma Exception) | Proceed with adjudication | Exception applies; cosmetic exclusion waived. |
| **Medically unnecessary service** (`medically_unnecessary: "established"`) | Section 4 & 6 (Necessity) | `deny_claim` | *"Service not medically necessary under Section 4 standard."* |
| **Routine CT Scan without Prior Auth** | Section 3.1 & 5.2 | `route_to_senior_reviewer` | *"Required checks remain unresolved: prior_authorization."* |
| **Emergency CT Scan without Prior Auth** (`emergency_service: "established"`) | Section 3.1 (Emergency Exemption) | `approve_claim_payment` | *"All required workflow checks passed with supporting evidence."* |
| **DME cost > $500 without Prior Auth** | Section 3.1 (DME Mandate) | `route_to_senior_reviewer` | *"DME exceeding $500 requires prior authorization."* |
| **DME cost <= $500 without Prior Auth** (e.g. $500.00 or $350.00) | Section 3.1 (DME Exemption) | `approve_claim_payment` | *"All required workflow checks passed with supporting evidence."* |
| **Specialty Drug without Prior Auth** | Section 3.1 (Formulary Specialty) | `route_to_senior_reviewer` | *"Specialty medication requiring prior authorization."* |
| **Appeal submitted within 180 days with new clinical evidence** | Section 8 (Appeals) | `approve_pre_authorization` (Overturned) | *"All required workflow checks passed with supporting evidence."* |
| **Appeal submitted after 180 days** (e.g. Day 185) | Section 8 (Statutory Timeliness) | `route_to_senior_reviewer` | *"Untimely appeal outside 180-day window."* |
| **Appeal submitted without new relevant evidence** | Section 8 (Evidence Prerequisite) | `route_to_senior_reviewer` | *"Appeals without new or relevant documentation may be upheld."* |
| **All policy and clinical checks satisfied (Pre-Auth)** | Section 5.1 / Service Rules | `approve_pre_authorization` | *"All required workflow checks passed with supporting evidence."* |
| **All policy and clinical checks satisfied (Payment)** | Section 1 & Benefit Rules | `approve_claim_payment` | *"All required workflow checks passed with supporting evidence."* |

---

## 6. "If You Change Attribute X ➔ What Happens" Matrix

| If You Edit This Field... | From | To | The Resulting Action Changes To... |
| :--- | :--- | :--- | :--- |
| `member_status` | `"active"` | `"inactive"` | **`deny_claim`** (*"Plan inactive at time of service."*) |
| `coding_assessment.status` | `"consistent"` | `"inconsistent"` | **`route_to_coding_review`** (*Coding discrepancy*) |
| `diagnosis_codes` | `["M54.5"]` | `["H52.1"]` (with MRI) | **`route_to_coding_review`** (*Eye condition paired with lumbar MRI*) |
| `claimed_amount` | `"1200"` | `"5001"` | **`route_to_senior_reviewer`** (*Exceeds $5k audit threshold*) |
| `conservative_treatment_attempted.status` | `"established"` | `"not_established"` | **`deny_claim`** (*Conservative therapy required for MRI*) |
| `conservative_treatment_contraindicated.status` | `null` | `"established"` | **`approve_pre_authorization`** (*Alternative contraindication branch*) |
| `experimental_or_investigational.status` | `"ruled_out"` | `"established"` | **`deny_claim`** (*Excluded under Section 6*) |
| `emergency_service.status` (on CT) | `"not_established"` | `"established"` | **`approve_claim_payment`** (*PA requirement waived for emergency*) |
| `payment_determination` | `{"status": "determined"}` | `null` | **`route_to_senior_reviewer`** (*Missing payment determination*) |
| `documents` (clinical_note) | `"status": "provided"` | `"status": "missing"` | **`request_missing_documentation`** (*Section 3.2 documentation pend*) |
| `prior_claims` | `[]` | *5 matching fields* | **`deny_claim`** (*"Duplicate claim submission."*) |
| `correction_declared` | `false` | `true` (on duplicate) | **`route_to_senior_reviewer`** (*Bypasses duplicate denial for review*) |

---

## 7. Ready-to-Use Copy-Paste Templates

### Template 1: Pre-Authorization Claim (Lumbar MRI)
```json
{
  "claim_id": "CLM-PREAUTH-1",
  "review_id": "REV-PREAUTH-1",
  "insurer": "HorizonCare",
  "plan_name": "Silver PPO 2500",
  "member_id": "MEMBER-100",
  "claim_type": "pre_authorization",
  "member_status": "active",
  "service_date": "2025-03-10",
  "service_location": "Synthetic clinic",
  "provider_npi": "1234567890",
  "procedure_code": "MRI-LUMBAR",
  "diagnosis_codes": [
    "M54.5"
  ],
  "claimed_amount": "1200",
  "documents": [
    {
      "document_id": "NOTE",
      "document_type": "clinical_note",
      "status": "provided",
      "text": "Clinician assessment: diagnosis supported; MRI medically necessary. Symptomatic diagnostic request, not cosmetic or experimental."
    },
    {
      "document_id": "HISTORY",
      "document_type": "prior_treatment_history",
      "status": "provided",
      "text": "Prior treatment history: conservative treatment attempted with 6 weeks physical therapy."
    }
  ],
  "coding_assessment": {
    "status": "consistent"
  },
  "treatment_history_applicability": {
    "status": "required"
  },
  "clinical_assessment": {
    "diagnosis_support": {
      "status": "established"
    },
    "medical_necessity": {
      "status": "established"
    },
    "conservative_treatment_attempted": {
      "status": "established"
    }
  },
  "exclusion_assessment": {
    "screening_without_symptoms": {
      "status": "ruled_out"
    },
    "cosmetic_or_reconstructive": {
      "status": "ruled_out"
    },
    "experimental_or_investigational": {
      "status": "ruled_out"
    },
    "medically_unnecessary": {
      "status": "ruled_out"
    }
  }
}
```

---

### Template 2: Covered Payment Claim (Emergency CT)
```json
{
  "claim_id": "CLM-PAY-1",
  "review_id": "REV-PAY-1",
  "insurer": "HorizonCare",
  "plan_name": "Silver PPO 2500",
  "member_id": "MEMBER-100",
  "claim_type": "payment",
  "member_status": "active",
  "service_date": "2025-03-10",
  "service_location": "Emergency Department",
  "provider_npi": "1234567890",
  "procedure_code": "CT",
  "diagnosis_codes": [
    "R10.9"
  ],
  "claimed_amount": "900",
  "documents": [
    {
      "document_id": "NOTE",
      "document_type": "clinical_note",
      "status": "provided",
      "text": "Emergency evaluation: acute abdominal trauma and severe pain. CT medically necessary under acute emergency service standard."
    },
    {
      "document_id": "CALC",
      "document_type": "payment_calculation",
      "status": "provided",
      "text": "Benefit calculation: payable amount 900 dollars after emergency deductible."
    }
  ],
  "coding_assessment": {
    "status": "consistent"
  },
  "clinical_assessment": {
    "diagnosis_support": {
      "status": "established"
    },
    "medical_necessity": {
      "status": "established"
    },
    "emergency_service": {
      "status": "established"
    }
  },
  "exclusion_assessment": {
    "screening_without_symptoms": {
      "status": "ruled_out"
    },
    "cosmetic_or_reconstructive": {
      "status": "ruled_out"
    },
    "experimental_or_investigational": {
      "status": "ruled_out"
    },
    "medically_unnecessary": {
      "status": "ruled_out"
    }
  },
  "payment_determination": {
    "status": "determined",
    "payable_amount": "900"
  }
}
```

---

### Template 3: Durable Medical Equipment (DME Cost <= $500)
```json
{
  "claim_id": "CLM-DME-1",
  "review_id": "REV-DME-1",
  "insurer": "HorizonCare",
  "plan_name": "Silver PPO 2500",
  "member_id": "MEMBER-100",
  "claim_type": "payment",
  "member_status": "active",
  "service_date": "2025-03-10",
  "service_location": "DME Supplier",
  "provider_npi": "1234567890",
  "procedure_code": "DME",
  "diagnosis_codes": [
    "M54.5"
  ],
  "claimed_amount": "500",
  "documents": [
    {
      "document_id": "NOTE",
      "document_type": "clinical_note",
      "status": "provided",
      "text": "Clinician assessment: lumbar support brace medically necessary for acute stability."
    },
    {
      "document_id": "CALC",
      "document_type": "payment_calculation",
      "status": "provided",
      "text": "Equipment cost determination: retail price exactly 500 dollars. Covered payable amount 500 dollars."
    }
  ],
  "coding_assessment": {
    "status": "consistent"
  },
  "clinical_assessment": {
    "diagnosis_support": {
      "status": "established"
    },
    "medical_necessity": {
      "status": "established"
    }
  },
  "exclusion_assessment": {
    "screening_without_symptoms": {
      "status": "ruled_out"
    },
    "cosmetic_or_reconstructive": {
      "status": "ruled_out"
    },
    "experimental_or_investigational": {
      "status": "ruled_out"
    },
    "medically_unnecessary": {
      "status": "ruled_out"
    }
  },
  "payment_determination": {
    "status": "determined",
    "payable_amount": "500"
  }
}
```
