"""Generates the updated synthetic test set for all 18 sample claims with full schema synchronization."""
import json
from pathlib import Path
from decimal import Decimal
from copy import deepcopy

from claims_agent.schemas import Claim
from claims_agent.controller import ReviewController
from claims_agent.reviews import ReviewStore
from claims_agent.decisions import DECISION_ADAPTER
from claims_agent.policy import HORIZONCARE, ingest_policy

ROOT = Path(__file__).resolve().parents[1]

def sync_claim_requests(data):
    base_claim = Claim.model_validate(data)
    if "coding_assessment" in data and data["coding_assessment"]:
        data["coding_assessment"]["request"] = base_claim.coding_request().model_dump(mode="json")
    
    if data["claim_type"] == "pre_authorization":
        doc_req = base_claim.documentation_request().model_dump(mode="json")
        for k in ("treatment_history_applicability", "clinical_assessment", "exclusion_assessment"):
            if k in data and data[k]:
                data[k]["request"] = doc_req
    elif data["claim_type"] == "payment":
        pay_req = base_claim.payment_request().model_dump(mode="json")
        clin_req = base_claim.clinical_request().model_dump(mode="json")
        for k in ("payment_determination", "authorization_assessment"):
            if k in data and data[k]:
                data[k]["request"] = pay_req
        for k in ("clinical_assessment", "exclusion_assessment", "equipment_cost_assessment"):
            if k in data and data[k]:
                data[k]["request"] = clin_req
    return data

def run():
    reviewer = ReviewController(ROOT / "policies", ROOT / ".cache")

    # 1. Covered MRI
    p = ROOT / "examples/covered_mri.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "CLM-COV-MRI"
    data["review_id"] = "REVIEW-COV-MRI"
    data["member_id"] = "MEMBER-COV-01"
    data["provider_npi"] = "1234567891"
    data["service_date"] = "2025-03-11"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 2. MRI No PT
    p = ROOT / "examples/services/mri-no-pt.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SAMPLE-MRI-NO-PT"
    data["review_id"] = "REVIEW-MRI-NOPT"
    data["member_id"] = "MEMBER-NOPT-02"
    data["provider_npi"] = "1234567892"
    data["service_date"] = "2025-03-12"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 3. Appeal Original Denial
    p = ROOT / "examples/appeal_original_denial.json"
    denial_data = json.loads(p.read_text())
    denial_data["claim_id"] = "CLM-APP-EXP"
    denial_data["review_id"] = "DENIAL-APP-03"
    denial_data["member_id"] = "MEMBER-APP-03"
    denial_data["provider_npi"] = "1234567893"
    denial_data["service_date"] = "2025-03-13"
    sync_claim_requests(denial_data)
    p.write_text(json.dumps(denial_data, indent=2) + "\n")

    # Adjudicate denial to obtain true decision for appeal fixture
    denial_claim = Claim.model_validate(denial_data)
    denial_dec = reviewer.review(denial_claim)

    # 4. Appeal Submission
    p = ROOT / "examples/appeal_submission.json"
    appeal_data = json.loads(p.read_text())
    req_claim = appeal_data["request"]["claim"]
    req_claim["claim_id"] = "CLM-APP-EXP"
    req_claim["review_id"] = "APPEAL-APP-03"
    req_claim["member_id"] = "MEMBER-APP-03"
    req_claim["provider_npi"] = "1234567893"
    req_claim["service_date"] = "2025-03-13"
    sync_claim_requests(req_claim)
    
    # Update prior_review snapshot
    appeal_data["request"]["prior_review"] = {
        "claim": denial_claim.model_dump(mode="json"),
        "decision": denial_dec.model_dump(mode="json"),
        "recorded_at": "2026-10-11T12:00:00Z",
        "previous_review_id": None,
        "supplemental_input_json": None,
    }
    # Sync assessments in appeal_data
    for k in ("timing_assessment", "evidence_assessment"):
        if k in appeal_data and appeal_data[k] and "request" in appeal_data[k]:
            appeal_data[k]["request"]["claim"] = deepcopy(req_claim)
            appeal_data[k]["request"]["prior_review"] = deepcopy(appeal_data["request"]["prior_review"])
    p.write_text(json.dumps(appeal_data, indent=2) + "\n")

    # 5. Covered Payment
    p = ROOT / "examples/covered_payment.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "CLM-PAY-APPROVED"
    data["review_id"] = "REVIEW-PAY-APPROVED"
    data["member_id"] = "MEMBER-PAY-04"
    data["provider_npi"] = "1234567894"
    data["service_date"] = "2025-03-14"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 6. Missing Documents
    p = ROOT / "examples/missing_document.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "CLM-MISSING-DOCS"
    data["review_id"] = "REVIEW-MISSING-DOCS"
    data["member_id"] = "MEMBER-MISS-05"
    data["provider_npi"] = "1234567895"
    data["service_date"] = "2025-03-15"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 7. Inactive Membership
    p = ROOT / "examples/inactive_membership.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SAMPLE-INACTIVE"
    data["review_id"] = "REVIEW-INACTIVE"
    data["member_id"] = "MEMBER-INACT-06"
    data["provider_npi"] = "1234567896"
    data["service_date"] = "2025-03-16"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 8. Duplicate Claim Submission
    p = ROOT / "examples/duplicate_claim.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SAMPLE-DUPLICATE"
    data["review_id"] = "REVIEW-DUPLICATE"
    data["member_id"] = "MEMBER-DUP-07"
    data["provider_npi"] = "1234567897"
    data["service_date"] = "2025-03-17"
    data["prior_claims"] = [
        {
            "claim_id": "CLM-DUP-ORIG",
            "review_id": "REVIEW-DUP-ORIG",
            "member_id": "MEMBER-DUP-07",
            "provider_npi": "1234567897",
            "service_date": "2025-03-17",
            "procedure_code": "MRI-LUMBAR",
            "billed_amount": "1200",
            "diagnosis_codes": ["M54.5"],
            "procedure_description": None,
            "documents": [],
        }
    ]
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 9. Coding Mismatch
    p = ROOT / "examples/coding_mismatch.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SAMPLE-CODING-MISMATCH"
    data["review_id"] = "REVIEW-CODING-MISMATCH"
    data["member_id"] = "MEMBER-CODE-08"
    data["provider_npi"] = "1234567898"
    data["service_date"] = "2025-03-18"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 10. High Value Claim
    p = ROOT / "examples/high_value.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "CLM-HIGH-VALUE"
    data["review_id"] = "REVIEW-HIGH-VALUE"
    data["member_id"] = "MEMBER-HIGH-09"
    data["provider_npi"] = "1234567899"
    data["service_date"] = "2025-03-19"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 11. CT Emergency
    p = ROOT / "examples/services/ct-emergency.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SYNTHETIC-CT"
    data["review_id"] = "REVIEW-CT-EMERG"
    data["member_id"] = "MEMBER-CT-10"
    data["provider_npi"] = "2234567890"
    data["service_date"] = "2025-03-20"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 12. DME Over 500 (No Auth)
    p = ROOT / "examples/services/dme-over-500-no-auth.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SYNTHETIC-DME-OVER"
    data["review_id"] = "REVIEW-DME-OVER"
    data["member_id"] = "MEMBER-DME-11"
    data["provider_npi"] = "3234567890"
    data["service_date"] = "2025-03-21"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 13. Inpatient Elective
    p = ROOT / "examples/services/inpatient-elective.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SYNTHETIC-INPATIENT-ELECT"
    data["review_id"] = "REVIEW-INP-ELECT"
    data["member_id"] = "MEMBER-INP-12"
    data["provider_npi"] = "4234567890"
    data["service_date"] = "2025-03-22"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 14. Inpatient Non-Elective
    p = ROOT / "examples/services/inpatient-nonelective.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SYNTHETIC-INPATIENT-NONELECT"
    data["review_id"] = "REVIEW-INP-NONELECT"
    data["member_id"] = "MEMBER-INP-13"
    data["provider_npi"] = "5234567890"
    data["service_date"] = "2025-03-23"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 15. Drug Formulary
    p = ROOT / "examples/services/drug-formulary.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SYNTHETIC-DRUG-FORM"
    data["review_id"] = "REVIEW-DRUG-FORM"
    data["member_id"] = "MEMBER-DRUG-14"
    data["provider_npi"] = "6234567890"
    data["service_date"] = "2025-03-24"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 16. DME 500
    p = ROOT / "examples/services/dme-exactly-500.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SYNTHETIC-DME-500"
    data["review_id"] = "REVIEW-DME-500"
    data["member_id"] = "MEMBER-DME-15"
    data["provider_npi"] = "7234567890"
    data["service_date"] = "2025-03-25"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    # 17. Specialty PA
    p = ROOT / "examples/services/specialty-pa-required.json"
    data = json.loads(p.read_text())
    data["claim_id"] = "SYNTHETIC-SPECIALTY-PA"
    data["review_id"] = "REVIEW-SPEC-PA"
    data["member_id"] = "MEMBER-SPEC-16"
    data["provider_npi"] = "8234567890"
    data["service_date"] = "2025-03-26"
    sync_claim_requests(data)
    p.write_text(json.dumps(data, indent=2) + "\n")

    print("[+] Successfully applied all schema-synchronized sample updates!")

if __name__ == "__main__":
    run()
