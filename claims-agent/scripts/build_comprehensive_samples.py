"""Generate comprehensive JSON sample fixtures for all claim cases and edge conditions."""
import json
from pathlib import Path
from copy import deepcopy
from decimal import Decimal

from claims_agent.schemas import Claim
from claims_agent.controller import ReviewController

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
SERVICES_DIR = ROOT / "examples" / "services"

def make_sample(base_dict, **overrides):
    d = deepcopy(base_dict)
    d.update(overrides)
    return Claim.model_validate(d)

def generate_samples():
    controller = ReviewController(ROOT / "policies", ROOT / ".policy-cache")
    created = []

    # 1. Inactive Membership (Administrative Denial)
    d02 = json.loads((ROOT / "evaluation" / "cases" / "D02.json").read_text())
    d02["claim_id"] = "SAMPLE-INACTIVE"
    d02["review_id"] = "REVIEW-INACTIVE"
    c_inactive = Claim.model_validate(d02)
    dec = controller.review(c_inactive)
    assert dec.action == "deny_claim" and "inactive" in dec.context.reason.lower()
    (EXAMPLES_DIR / "inactive_membership.json").write_text(c_inactive.model_dump_json(indent=2) + "\n")
    created.append(("inactive", "examples/inactive_membership.json", "Inactive membership (Administrative denial)"))

    # 2. Duplicate Claim (Administrative Denial)
    d06 = json.loads((ROOT / "evaluation" / "cases" / "D06.json").read_text())
    d06["claim_id"] = "SAMPLE-DUPLICATE"
    d06["review_id"] = "REVIEW-DUPLICATE"
    c_dup = Claim.model_validate(d06)
    dec = controller.review(c_dup)
    assert dec.action == "deny_claim" and "duplicate" in dec.context.reason.lower()
    (EXAMPLES_DIR / "duplicate_claim.json").write_text(c_dup.model_dump_json(indent=2) + "\n")
    created.append(("duplicate", "examples/duplicate_claim.json", "Duplicate claim (Exact 5-field match)"))

    # 3. Coding Inconsistency / Mismatch (Route to Coding Review)
    d07 = json.loads((ROOT / "evaluation" / "cases" / "D07.json").read_text())
    claim_id = "SAMPLE-CODING-MISMATCH"
    review_id = "REVIEW-CODING-MISMATCH"
    d07["claim_id"] = claim_id
    d07["review_id"] = review_id
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment"):
        if d07.get(key) and "request" in d07[key]:
            d07[key]["request"]["claim_id"] = claim_id
            d07[key]["request"]["review_id"] = review_id
    c_coding = Claim.model_validate(d07)
    dec = controller.review(c_coding)
    assert dec.action == "route_to_coding_review", f"Expected route_to_coding_review, got {dec.action}"
    (EXAMPLES_DIR / "coding_mismatch.json").write_text(c_coding.model_dump_json(indent=2) + "\n")
    created.append(("coding-mismatch", "examples/coding_mismatch.json", "Coding mismatch (CPT/ICD discrepancy)"))

    # 4. Unknown Insurer / Unmapped Policy (Senior Review)
    d08 = json.loads((ROOT / "evaluation" / "cases" / "D08.json").read_text())
    claim_id = "SAMPLE-UNKNOWN-INSURER"
    review_id = "REVIEW-UNKNOWN-INSURER"
    d08["claim_id"] = claim_id
    d08["review_id"] = review_id
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment"):
        if d08.get(key) and "request" in d08[key]:
            d08[key]["request"]["claim_id"] = claim_id
            d08[key]["request"]["review_id"] = review_id
    c_unknown_ins = Claim.model_validate(d08)
    dec = controller.review(c_unknown_ins)
    assert dec.action == "route_to_senior_reviewer", f"Expected route_to_senior_reviewer, got {dec.action}"
    (EXAMPLES_DIR / "unknown_insurer.json").write_text(c_unknown_ins.model_dump_json(indent=2) + "\n")
    created.append(("unknown-insurer", "examples/unknown_insurer.json", "Unknown insurer (Unrecognized policy)"))

    # 5. Missing Provider NPI (Senior Review / Unresolved Duplicate Check)
    d13 = json.loads((ROOT / "evaluation" / "cases" / "D13.json").read_text())
    claim_id = "SAMPLE-MISSING-NPI"
    review_id = "REVIEW-MISSING-NPI"
    d13["claim_id"] = claim_id
    d13["review_id"] = review_id
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment"):
        if d13.get(key) and "request" in d13[key]:
            d13[key]["request"]["claim_id"] = claim_id
            d13[key]["request"]["review_id"] = review_id
    c_npi = Claim.model_validate(d13)
    dec = controller.review(c_npi)
    assert dec.action == "route_to_senior_reviewer" and "duplicate_claim" in dec.context.unresolved_information
    (EXAMPLES_DIR / "missing_provider_npi.json").write_text(c_npi.model_dump_json(indent=2) + "\n")
    created.append(("missing-npi", "examples/missing_provider_npi.json", "Missing provider NPI (Incomplete comparison)"))

    # 6. Payment with Retroactive Authorization
    d15 = json.loads((ROOT / "evaluation" / "cases" / "D15.json").read_text())
    claim_id = "SAMPLE-PAYMENT-RETROACTIVE"
    review_id = "REVIEW-PAYMENT-RETROACTIVE"
    d15["claim_id"] = claim_id
    d15["review_id"] = review_id
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment", "authorization_assessment", "payment_determination"):
        if d15.get(key) and "request" in d15[key]:
            d15[key]["request"]["claim_id"] = claim_id
            d15[key]["request"]["review_id"] = review_id
    c_retro = Claim.model_validate(d15)
    dec = controller.review(c_retro)
    assert dec.action == "approve_claim_payment"
    (EXAMPLES_DIR / "payment_retroactive.json").write_text(c_retro.model_dump_json(indent=2) + "\n")
    created.append(("payment-retroactive", "examples/payment_retroactive.json", "Payment with retroactive authorization"))

    # 7. Missing Payment Determination Calculation (Senior Review)
    d16 = json.loads((ROOT / "evaluation" / "cases" / "D16.json").read_text())
    claim_id = "SAMPLE-MISSING-PAYMENT-CALC"
    review_id = "REVIEW-MISSING-PAYMENT-CALC"
    d16["claim_id"] = claim_id
    d16["review_id"] = review_id
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment", "authorization_assessment"):
        if d16.get(key) and "request" in d16[key]:
            d16[key]["request"]["claim_id"] = claim_id
            d16[key]["request"]["review_id"] = review_id
    c_calc = Claim.model_validate(d16)
    dec = controller.review(c_calc)
    assert dec.action == "route_to_senior_reviewer"
    (EXAMPLES_DIR / "missing_payment_calc.json").write_text(c_calc.model_dump_json(indent=2) + "\n")
    created.append(("missing-payment-calc", "examples/missing_payment_calc.json", "Payment missing calculation assessment"))

    # 8. Cervical Spine MRI Pre-Authorization
    mri_base = json.loads((EXAMPLES_DIR / "covered_mri.json").read_text())
    claim_id = "SAMPLE-MRI-CERVICAL"
    review_id = "REVIEW-MRI-CERVICAL"
    mri_base["procedure_code"] = "MRI-CERVICAL"
    mri_base["claim_id"] = claim_id
    mri_base["review_id"] = review_id
    mri_base["diagnosis_codes"] = ["M54.2"] # Cervicalgia / Neck pain
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment"):
        if mri_base.get(key) and "request" in mri_base[key]:
            mri_base[key]["request"]["claim_id"] = claim_id
            mri_base[key]["request"]["review_id"] = review_id
            mri_base[key]["request"]["procedure_code"] = "MRI-CERVICAL"
            mri_base[key]["request"]["diagnosis_codes"] = ["M54.2"]
    c_cervical = Claim.model_validate(mri_base)
    dec = controller.review(c_cervical)
    assert dec.action == "approve_pre_authorization", f"Expected approve_pre_authorization, got {dec.action}"
    (SERVICES_DIR / "mri-cervical.json").write_text(c_cervical.model_dump_json(indent=2) + "\n")
    created.append(("mri-cervical", "examples/services/mri-cervical.json", "MRI — Cervical spine pre-authorization"))

    # 9. MRI without Conservative Therapy (Senior Review / Unresolved)
    mri_no_pt = json.loads((EXAMPLES_DIR / "covered_mri.json").read_text())
    claim_id = "SAMPLE-MRI-NO-PT"
    review_id = "REVIEW-MRI-NO-PT"
    mri_no_pt["claim_id"] = claim_id
    mri_no_pt["review_id"] = review_id
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment"):
        if mri_no_pt.get(key) and "request" in mri_no_pt[key]:
            mri_no_pt[key]["request"]["claim_id"] = claim_id
            mri_no_pt[key]["request"]["review_id"] = review_id
    mri_no_pt["clinical_assessment"]["conservative_treatment_attempted"]["status"] = "not_established"
    mri_no_pt["clinical_assessment"]["conservative_treatment_attempted"]["reason"] = "Physical therapy was not attempted."
    c_mri_no_pt = Claim.model_validate(mri_no_pt)
    dec = controller.review(c_mri_no_pt)
    assert dec.action == "route_to_senior_reviewer", f"Expected route_to_senior_reviewer, got {dec.action}"
    (SERVICES_DIR / "mri-no-pt.json").write_text(c_mri_no_pt.model_dump_json(indent=2) + "\n")
    created.append(("mri-no-pt", "examples/services/mri-no-pt.json", "MRI — Conservative therapy not attempted"))

    # 10. Ultrasound Pre-Authorization
    us_preauth = json.loads((EXAMPLES_DIR / "covered_mri.json").read_text())
    claim_id = "SAMPLE-ULTRASOUND-PREAUTH"
    review_id = "REVIEW-ULTRASOUND-PREAUTH"
    us_preauth["procedure_code"] = "ULTRASOUND"
    us_preauth["claim_id"] = claim_id
    us_preauth["review_id"] = review_id
    us_preauth["diagnosis_codes"] = ["R10.9"]
    for key in ("coding_assessment", "treatment_history_applicability", "clinical_assessment", "exclusion_assessment"):
        if us_preauth.get(key) and "request" in us_preauth[key]:
            us_preauth[key]["request"]["claim_id"] = claim_id
            us_preauth[key]["request"]["review_id"] = review_id
            us_preauth[key]["request"]["procedure_code"] = "ULTRASOUND"
            us_preauth[key]["request"]["diagnosis_codes"] = ["R10.9"]
    us_preauth["treatment_history_applicability"]["status"] = "not_required"
    us_preauth["clinical_assessment"].pop("conservative_treatment_attempted", None)
    c_us_pre = Claim.model_validate(us_preauth)
    dec = controller.review(c_us_pre)
    assert dec.action == "approve_pre_authorization", f"Expected approve_pre_authorization, got {dec.action}"
    (SERVICES_DIR / "ultrasound-preauth.json").write_text(c_us_pre.model_dump_json(indent=2) + "\n")
    created.append(("ultrasound-preauth", "examples/services/ultrasound-preauth.json", "Ultrasound — Pre-authorization"))

    # 11. Inpatient Elective Admission Without PA (Senior Review)
    inp_no_pa = json.loads((SERVICES_DIR / "inpatient-elective.json").read_text())
    inp_no_pa["claim_id"] = "SAMPLE-INPATIENT-NO-PA"
    inp_no_pa["review_id"] = "REVIEW-INPATIENT-NO-PA"
    inp_no_pa["prior_authorization_approved"] = None
    inp_no_pa["authorization_assessment"] = None
    c_inp_no_pa = Claim.model_validate(inp_no_pa)
    dec = controller.review(c_inp_no_pa)
    assert dec.action == "route_to_senior_reviewer"
    (SERVICES_DIR / "inpatient-elective-no-auth.json").write_text(c_inp_no_pa.model_dump_json(indent=2) + "\n")
    created.append(("inpatient-no-auth", "examples/services/inpatient-elective-no-auth.json", "Inpatient — Elective without prior authorization"))

    # 12. Prescription Drug Not on Formulary (Senior Review)
    drug_non_form = json.loads((SERVICES_DIR / "drug-formulary.json").read_text())
    drug_non_form["claim_id"] = "SAMPLE-DRUG-NON-FORMULARY"
    drug_non_form["review_id"] = "REVIEW-DRUG-NON-FORMULARY"
    drug_non_form["clinical_assessment"]["formulary_coverage"]["status"] = "not_established"
    drug_non_form["clinical_assessment"]["formulary_coverage"]["reason"] = "Drug is not listed on current HorizonCare Silver PPO formulary."
    c_drug_non = Claim.model_validate(drug_non_form)
    dec = controller.review(c_drug_non)
    assert dec.action == "route_to_senior_reviewer"
    (SERVICES_DIR / "drug-non-formulary.json").write_text(c_drug_non.model_dump_json(indent=2) + "\n")
    created.append(("drug-non-formulary", "examples/services/drug-non-formulary.json", "Prescription drug — Not on formulary"))

    # 13. Specialty Drug Missing Required PA (Senior Review)
    spec_no_pa = json.loads((SERVICES_DIR / "specialty-pa-required.json").read_text())
    spec_no_pa["claim_id"] = "SAMPLE-SPECIALTY-PA-MISSING"
    spec_no_pa["review_id"] = "REVIEW-SPECIALTY-PA-MISSING"
    spec_no_pa["prior_authorization_approved"] = None
    spec_no_pa["authorization_assessment"] = None
    c_spec_no_pa = Claim.model_validate(spec_no_pa)
    dec = controller.review(c_spec_no_pa)
    assert dec.action == "route_to_senior_reviewer"
    (SERVICES_DIR / "specialty-pa-missing.json").write_text(c_spec_no_pa.model_dump_json(indent=2) + "\n")
    created.append(("specialty-missing-pa", "examples/services/specialty-pa-missing.json", "Specialty drug — PA required but missing"))

    print(f"Successfully created and validated {len(created)} comprehensive claim samples:")
    for key, path, desc in created:
        print(f"  • [{key}] {desc} -> {path}")

if __name__ == "__main__":
    generate_samples()
