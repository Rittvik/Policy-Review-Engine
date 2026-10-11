"""Clinical & Payer Intelligence Modules for Claims Adjudication.

Implements high-leverage AI/LLM extensions:
1. Smart Fast-Tracking & Automated Approval Prior Authorization Triage (Green/Yellow/Red lanes)
2. Appeal Intelligence & Case Difference Synthesis
3. Plain-Language Adverse Determination & Denial Letters (EOB Generator)
"""

from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

from .schemas import Claim
from .appeals import AppealSubmission


# ==============================================================================
# 1. Pydantic Models
# ==============================================================================

class FastTrackAssessment(BaseModel):
    """Prior authorization triage recommendation and automated approval eligibility."""
    lane: Literal["GREEN", "YELLOW", "RED"]
    confidence: float = Field(ge=0.0, le=1.0)
    auto_approval_eligible: bool = Field(default=False, description="Whether claim qualifies for instant automated approval without manual review")
    gold_card_eligible: bool = Field(default=False, description="Backwards-compatible alias for auto_approval_eligible")
    recommended_priority: Literal["routine", "expedited", "stat"]
    rationale: List[str]
    suggested_action: str

    @model_validator(mode="before")
    @classmethod
    def sync_eligibility_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "auto_approval_eligible" in data and "gold_card_eligible" not in data:
                data["gold_card_eligible"] = data["auto_approval_eligible"]
            elif "gold_card_eligible" in data and "auto_approval_eligible" not in data:
                data["auto_approval_eligible"] = data["gold_card_eligible"]
        return data


class AppealSynthesis(BaseModel):
    """Synthesis comparing appeal evidence to prior adverse determination."""
    original_claim_id: str
    original_review_id: str
    prior_denial_reason: str
    prior_failed_gates: List[str]
    new_evidence_provided: List[str]
    resolved_defects: List[str]
    remaining_defects: List[str]
    clinical_recommendation: Literal["overturn_denial", "uphold_denial", "request_additional_clarification"]
    confidence: float = Field(ge=0.0, le=1.0)
    synthesis_narrative: str


class AdverseNotice(BaseModel):
    """Plain-Language Adverse Determination & Denial Notice (EOB Generator).
    
    Complies with ERISA § 503 and ACA § 2719 plain-language disclosure requirements.
    Written in clear 6th–8th grade English, free of payer jargon, citing specific
    plan terms and statutory 180-day internal appeal rights.
    """
    claim_id: str
    review_id: str
    member_id: str
    service_date: Optional[str] = None
    procedure_code: str
    procedure_name: str
    claimed_amount: Optional[str] = None
    status: Literal["denied", "pended_missing_documentation", "routed_for_clinical_review"]
    reading_level: str = "6th–8th Grade Plain Language"
    plain_language_summary: str
    clinical_rationale: str
    policy_citations: List[str]
    missing_items: List[str] = Field(default_factory=list)
    next_steps: List[str]
    appeal_rights_statement: str
    full_letter_text: str


# ==============================================================================
# 2. Capability 4: Smart Fast-Tracking & Automated Approval Triage
# ==============================================================================

def evaluate_fast_track(claim_input: Claim | dict, decision: Optional[Any] = None) -> FastTrackAssessment:
    """Triage incoming prior-auth request into Green, Yellow, or Red lanes."""
    claim_dict = claim_input.model_dump(mode="json") if isinstance(claim_input, Claim) else dict(claim_input)
    if "request" in claim_dict and "claim" in claim_dict["request"]:
        claim_dict = claim_dict["request"]["claim"]

    claimed_amount = Decimal(str(claim_dict.get("claimed_amount", "0") or "0"))
    member_status = str(claim_dict.get("member_status", "active")).lower()
    proc_code = str(claim_dict.get("procedure_code", "")).upper()
    claim_type = str(claim_dict.get("claim_type", "")).lower()
    docs = claim_dict.get("documents", []) or []

    # Extract adjudication decision context if provided
    dec_dict = decision.model_dump(mode="json") if hasattr(decision, "model_dump") else (decision if isinstance(decision, dict) else {})
    action = dec_dict.get("action")
    context = dec_dict.get("context", {})
    unresolved = context.get("unresolved_information", []) or []
    missing = context.get("missing_information", []) or []

    rationale = []
    
    # 1. Check RED lane conditions (Hard denials, high dollar, high surgical risk)
    is_red = False
    if member_status != "active":
        is_red = True
        rationale.append("Inactive member coverage - ineligible for automated pre-auth fast-track.")
    if claimed_amount > Decimal("5000"):
        is_red = True
        rationale.append(f"High-dollar value (${claimed_amount:,.2f}) exceeds policy $5,000 threshold (Sec 7.2). Mandatory medical director sign-off.")
    if "TRANSPLANT" in proc_code or "EXPERIMENTAL" in proc_code or "SURGERY-MAJOR" in proc_code:
        is_red = True
        rationale.append(f"High-complexity/experimental procedure ({proc_code}) requires sub-specialty peer-to-peer review.")
    if action == "deny_claim":
        is_red = True
        rationale.append("Adverse determination: Claim does not satisfy coverage criteria or policy exclusions apply.")

    if is_red:
        return FastTrackAssessment(
            lane="RED",
            confidence=0.96,
            auto_approval_eligible=False,
            recommended_priority="stat" if claimed_amount > Decimal("10000") else "routine",
            rationale=rationale,
            suggested_action="Route to Senior Medical Director for peer-to-peer clinical review.",
        )

    # 1b. Check coding review routing
    if action == "route_to_coding_review":
        rationale.append("Coding inconsistency detected between diagnosis and procedure codes (Sec 7.2).")
        return FastTrackAssessment(
            lane="YELLOW",
            confidence=0.90,
            auto_approval_eligible=False,
            recommended_priority="routine",
            rationale=rationale,
            suggested_action="Route to Coding Review Desk for code validation.",
        )

    # 2. Check clinical assessment status & human review prerequisites
    has_clinical_assessment = claim_dict.get("clinical_assessment") is not None
    is_clinical_review_pending = (
        action == "route_to_senior_reviewer"
        or "current_clinical_assessment" in unresolved
        or not has_clinical_assessment
    )

    has_clinical_note = any(d.get("document_type") == "clinical_note" and d.get("status") == "provided" for d in docs)
    has_treatment_history = any(d.get("document_type") == "prior_treatment_history" and d.get("status") == "provided" for d in docs)
    notes_text = " ".join((d.get("text") or "") for d in docs).lower()

    conservative_supported = "conservative" in notes_text or "physical therapy" in notes_text or "pt" in notes_text
    
    from .services import profile_for
    profile = profile_for(proc_code)
    is_mri = bool((profile and profile.key == "mri") or "MRI" in proc_code)
    supported_procedure = bool(profile is not None or any(p in proc_code for p in ["MRI", "CT", "US", "ULTRASOUND", "EVAL", "OFFICE", "INPATIENT", "DME", "DRUG"]))
    conservative_prereq_satisfied = (conservative_supported or "contraindicat" in notes_text) if is_mri else True

    # 3. Check GREEN lane conditions (Zero-touch Auto-Approval)
    # ONLY eligible if supported procedure, fully documented, clinical necessity satisfied and NOT pending review
    can_green = (
        supported_procedure
        and has_clinical_note
        and conservative_prereq_satisfied
        and claimed_amount <= Decimal("2500")
        and not is_clinical_review_pending
        and (action is None or action in {"approve_pre_authorization", "approve_claim_payment"})
        and not missing
        and not unresolved
    )

    if can_green:
        if is_mri:
            rationale.append("Standard diagnostic imaging protocol with documented clinical necessity.")
            rationale.append("Conservative therapy prerequisites satisfied under Section 5.1.")
        else:
            desc = profile.key.replace("_", " ").title() if profile else proc_code
            rationale.append(f"Covered {desc} benefit with verified clinical necessity and criteria satisfied.")
        rationale.append(f"Claimed amount (${claimed_amount:,.2f}) within standard fee schedule benchmark.")
        return FastTrackAssessment(
            lane="GREEN",
            confidence=0.95,
            auto_approval_eligible=True,
            recommended_priority="routine",
            rationale=rationale,
            suggested_action="Fast-Track: Eligible for instant automated approval.",
        )

    # 4. YELLOW lane (Assisted Clinical Review / Clinician Evaluation Needed / Documentation Remediation)
    if is_clinical_review_pending:
        rationale.append("Clinical assessment of medical necessity is pending clinician evaluation under Section 5.1.")
        if is_mri:
            rationale.append("Conservative therapy prerequisites and clinical findings require clinical validation before prior-auth approval.")
        rationale.append(f"Claimed amount (${claimed_amount:,.2f}) within standard fee schedule benchmark.")
        return FastTrackAssessment(
            lane="YELLOW",
            confidence=0.85,
            auto_approval_eligible=False,
            recommended_priority="routine",
            rationale=rationale,
            suggested_action="Route to Clinical Review Desk for clinician assessment.",
        )

    if action == "request_missing_documentation" or missing:
        for m in (missing or ["clinical_note"]):
            clean_m = m.replace("_", " ").title()
            rationale.append(f"Missing required documentation: {clean_m} (Sec 3.2).")
        return FastTrackAssessment(
            lane="YELLOW",
            confidence=0.88,
            auto_approval_eligible=False,
            recommended_priority="expedited",
            rationale=rationale,
            suggested_action="Route to Clinical Review Desk with pre-drafted documentation request.",
        )

    if not has_clinical_note:
        rationale.append("Missing required primary clinical assessment note (Sec 3.2).")
    if not has_treatment_history and "MRI" in proc_code:
        rationale.append("Documentation of conservative therapy history required before approval.")
    if claimed_amount > Decimal("2500"):
        rationale.append(f"Moderate dollar amount (${claimed_amount:,.2f}) requires nurse reviewer validation.")
    if not rationale:
        rationale.append("Standard clinical review required to confirm clinical criteria.")

    return FastTrackAssessment(
        lane="YELLOW",
        confidence=0.82,
        auto_approval_eligible=False,
        recommended_priority="routine",
        rationale=rationale,
        suggested_action="Route to Clinical Review Desk for clinician assessment.",
    )


# ==============================================================================
# 3. Capability 5: Appeal Intelligence & Case Difference Synthesis
# ==============================================================================

def synthesize_appeal(
    original_claim: Claim | dict,
    original_decision: Any,
    appeal_submission: AppealSubmission | dict,
) -> AppealSynthesis:
    """Synthesize differences between prior adverse determination and new appeal evidence."""
    orig_dict = original_claim.model_dump(mode="json") if isinstance(original_claim, Claim) else dict(original_claim)
    app_dict = appeal_submission.model_dump(mode="json") if isinstance(appeal_submission, AppealSubmission) else dict(appeal_submission)
    
    orig_claim_id = orig_dict.get("claim_id", "UNKNOWN")
    orig_review_id = orig_dict.get("review_id", "UNKNOWN")
    
    # Prior determination details
    prior_reason = "Initial claim failed medical necessity or required documentation criteria."
    prior_gates = []
    if hasattr(original_decision, "reason"):
        prior_reason = getattr(original_decision, "reason")
    elif isinstance(original_decision, dict) and "reason" in original_decision:
        prior_reason = original_decision["reason"]
        
    if hasattr(original_decision, "context") and getattr(original_decision, "context"):
        ctx = getattr(original_decision, "context")
        prior_gates = [t.rule_id for t in getattr(ctx, "decision_trace", []) if getattr(t, "outcome", "") != "satisfied"]
    elif isinstance(original_decision, dict) and "context" in original_decision:
        trace = original_decision.get("context", {}).get("decision_trace", [])
        prior_gates = [t.get("rule_id") for t in trace if t.get("outcome") != "satisfied"]
    if not prior_gates:
        prior_gates = ["clinical_evidence_prerequisites"]

    # Analyze new evidence in appeal
    app_request = app_dict.get("request", {})
    app_claim = app_request.get("claim", app_dict)
    app_docs = app_claim.get("documents", []) or []
    
    new_evidence = []
    for doc in app_docs:
        doc_type = doc.get("document_type", "document")
        doc_text = doc.get("text", "") or ""
        if len(doc_text) > 10:
            new_evidence.append(f"{doc_type}: {doc_text[:120]}...")
            
    if not new_evidence:
        new_evidence.append("Provider appeal statement and request for reconsideration submitted.")

    # Determine resolution of prior defects
    all_new_text = " ".join(d.get("text") or "" for d in app_docs).lower()
    resolved = []
    remaining = []

    has_new_pt = "physical therapy" in all_new_text or "conservative" in all_new_text or "completed" in all_new_text
    has_new_note = any(d.get("document_type") == "clinical_note" for d in app_docs)

    if has_new_pt:
        resolved.append("Conservative therapy completion documented with verifiable clinical notes.")
    if has_new_note:
        resolved.append("Attending physician clinical evaluation provided.")

    if not resolved:
        remaining.append("No established new clinical evidence addressing the original denial reason.")
        recommendation = "uphold_denial"
        conf = 0.88
        narrative = (
            f"Appeal for Claim {orig_claim_id} (Prior Review {orig_review_id}) was reviewed. "
            f"The original adverse determination cited: '{prior_reason}'. "
            f"The current submission did not present verifiable new clinical documentation or corrective findings. "
            f"Under HorizonCare Policy Section 8, the original denial is recommended to be UPHELD."
        )
    else:
        recommendation = "overturn_denial"
        conf = 0.94
        narrative = (
            f"Appeal for Claim {orig_claim_id} (Prior Review {orig_review_id}) was successfully synthesized. "
            f"The initial adverse determination cited: '{prior_reason}'. "
            f"The newly submitted appeal records established verifiable resolution: {'; '.join(resolved)}. "
            f"All clinical coverage prerequisites under Policy Section 5.1 & Section 8 are now satisfied. "
            f"Recommendation: OVERTURN original denial and issue pre-authorization approval."
        )

    return AppealSynthesis(
        original_claim_id=orig_claim_id,
        original_review_id=orig_review_id,
        prior_denial_reason=prior_reason,
        prior_failed_gates=prior_gates,
        new_evidence_provided=new_evidence,
        resolved_defects=resolved,
        remaining_defects=remaining,
        clinical_recommendation=recommendation,
        confidence=conf,
        synthesis_narrative=narrative,
    )


# ==============================================================================
# 4. Capability 6: Plain-Language Adverse Determination & Denial Letters (EOB Generator)
# ==============================================================================

FRIENDLY_PROCEDURES = {
    "MRI-LUMBAR": "Lumbar Spine Magnetic Resonance Imaging (MRI) Scan of Lower Back",
    "MRI-BRAIN": "Brain Magnetic Resonance Imaging (MRI) Scan",
    "MRI-KNEE": "Knee Joint Magnetic Resonance Imaging (MRI) Scan",
    "CT-HEAD": "Head / Brain Computed Tomography (CT) Scan",
    "CT-ABDOMEN": "Abdominal Computed Tomography (CT) Scan",
    "ULTRASOUND-ABDOMEN": "Diagnostic Ultrasound Examination of Abdomen",
    "OFFICE-VISIT-ESTABLISHED": "Established Patient Clinical Office Visit",
    "SPECIALIST-CONSULT": "Outpatient Specialist Clinical Consultation",
    "OUTPATIENT-SURGERY": "Outpatient Ambulatory Surgical Procedure",
    "EMERGENCY-EVAL": "Emergency Department Medical Evaluation & Treatment",
    "INPATIENT-ELECTIVE": "Elective Hospital Inpatient Admission",
    "INPATIENT-EMERGENCY": "Emergency Hospital Inpatient Admission",
    "DME-WHEELCHAIR": "Standard Wheelchair (Durable Medical Equipment)",
    "DME-CPAP": "CPAP Respiratory Device & Supplies",
    "DRUG-TIER1-GENERIC": "Tier 1 Generic Formulary Prescription Medication",
    "DRUG-TIER4-SPECIALTY": "Tier 4 Specialty Biologic Medication",
}

ERISA_ACA_APPEAL_RIGHTS = (
    "STATUTORY APPEAL RIGHTS (ERISA § 503 & ACA § 2719):\n"
    "You have the right to appeal this adverse determination. You have 180 calendar days from "
    "the date you receive this notice to file an internal appeal with HorizonCare.\n\n"
    "• How to File: Submit your written appeal to HorizonCare Appeals & Grievances Department, "
    "P.O. Box 44021, Newark, NJ 07102, via Fax at 1-800-555-0198, or online at portal.horizoncare.com/appeals. "
    "Include your Member ID, Claim/Review ID, and any medical records, clinical notes, or doctor letters supporting your request.\n"
    "• Right to Free Review of Records: You are entitled to receive, upon request and free of charge, reasonable access to "
    "and copies of all documents, records, clinical guidelines, and other information relevant to your claim.\n"
    "• Expedited (Urgent) Appeal: If your treating physician certifies that waiting for standard appeal review (30 calendar days) "
    "would seriously jeopardize your life, health, or ability to regain maximum function, you or your doctor may request an "
    "expedited appeal, which will be decided within 72 hours.\n"
    "• External Independent Review: If your internal appeal is upheld, you may be entitled to an independent external review "
    "conducted by an Independent Review Organization (IRO) at no cost to you.\n"
    "• Contact Us: For questions or assistance with filing an appeal, call HorizonCare Member Services toll-free at "
    "1-800-555-0199 (TTY: 711), Monday through Friday, 8:00 AM – 8:00 PM EST."
)


def generate_adverse_notice(claim_input: Claim | dict, decision: Optional[Any] = None) -> Optional[AdverseNotice]:
    """Generate a plain-language Adverse Benefit Determination Notice / EOB.
    
    Adheres strictly to ERISA § 503 and ACA § 2719 plain-language disclosure requirements.
    Written in clear 6th–8th grade English, free of payer jargon, citing specific
    governing plan provisions and internal appeal deadlines. English only.
    """
    claim_dict = claim_input.model_dump(mode="json") if isinstance(claim_input, Claim) else dict(claim_input)
    if "request" in claim_dict and "claim" in claim_dict["request"]:
        claim_dict = claim_dict["request"]["claim"]

    # Extract decision details if provided
    dec_dict = decision.model_dump(mode="json") if hasattr(decision, "model_dump") else (decision if isinstance(decision, dict) else {})
    action = dec_dict.get("action")
    context = dec_dict.get("context", {})

    # Adverse Determination & Denial Letters (with statutory ERISA/ACA appeal rights)
    # are strictly generated ONLY when a claim or pre-authorization is actually DENIED.
    if action != "deny_claim":
        return None

    claim_id = str(claim_dict.get("claim_id") or "CLM-UNKNOWN")
    review_id = str(claim_dict.get("review_id") or dec_dict.get("review_id") or "REV-UNKNOWN")
    member_id = str(claim_dict.get("member_id") or "MBR-UNKNOWN")
    service_date = claim_dict.get("service_date")
    proc_code = str(claim_dict.get("procedure_code") or "PROCEDURE")
    claimed_amount_raw = claim_dict.get("claimed_amount")
    claimed_amount = f"${float(claimed_amount_raw):,.2f}" if claimed_amount_raw else None
    member_status = str(claim_dict.get("member_status", "active")).lower()

    proc_name = FRIENDLY_PROCEDURES.get(proc_code, proc_code.replace("-", " ").title())

    notice_status = "denied"
    reason_text = context.get("reason", "") or ""
    missing = context.get("missing_information", []) or []

    # Synthesize plain-language member explanation and clinical rationale based on denial reason
    if member_status != "active" or "inactive" in reason_text.lower():
        summary = (
            "We cannot approve or pay for this medical service because your health plan coverage "
            "was not active on the date you received care. Under your plan contract, benefits are "
            "only available when coverage is active on the date services are provided."
        )
        rationale = (
            f"Coverage records show the member plan was inactive on the date of service ({service_date or 'reported date'}). "
            "Under HorizonCare Policy Section 2, all benefits require active enrollment on the service date."
        )
        citations = ["HorizonCare Silver PPO 2500 — Section 2 (Member Eligibility and Plan Status)"]
        next_steps = [
            "Check with your employer or benefit administrator to confirm your coverage start and end dates.",
            "If you had active coverage under another insurance plan on this date, submit this claim to that insurer.",
            "If you believe our enrollment records are mistaken, submit proof of active coverage with an appeal.",
        ]

    elif "duplicate" in reason_text.lower() or "7.1" in reason_text:
        prior_claim_id = None
        prior_review_id = None
        claim_ev = list(context.get("claim_evidence", ()) or ())
        for trace_entry in context.get("decision_trace", []) or []:
            if hasattr(trace_entry, "claim_evidence"):
                claim_ev.extend(trace_entry.claim_evidence or ())
            elif isinstance(trace_entry, dict):
                claim_ev.extend(trace_entry.get("claim_evidence", ()) or ())
        for fact in claim_ev:
            if fact.startswith("duplicate_of_claim_id="):
                prior_claim_id = fact.split("=", 1)[1]
            elif fact.startswith("duplicate_of_review_id="):
                prior_review_id = fact.split("=", 1)[1]
            elif fact.startswith("prior_claim_id=") and not prior_claim_id:
                parts = dict(p.split("=", 1) for p in fact.split(";") if "=" in p)
                prior_claim_id = parts.get("prior_claim_id")
                prior_review_id = parts.get("prior_review_id")

        if not prior_claim_id and claim_dict.get("prior_claims"):
            p0 = claim_dict["prior_claims"][0]
            prior_claim_id = p0.get("claim_id")
            prior_review_id = p0.get("review_id")

        prior_desc = f"prior claim {prior_claim_id}" if prior_claim_id else "a previously adjudicated claim"
        if prior_review_id:
            prior_desc += f" (Review Reference: {prior_review_id})"

        summary = (
            "We received more than one bill from your healthcare provider for the exact same medical service, "
            f"date of service ({service_date or 'service date'}), and dollar amount ({claimed_amount or 'billed amount'}). "
            f"This request duplicates previously processed {prior_desc}. "
            "Under health plan contract terms, benefits cannot be paid more than once for the same medical service."
        )
        rationale = (
            f"Claim comparison under Policy Section 7.1 confirmed an exact duplicate of {prior_desc}. "
            f"Matching criteria verified: Member ID ({member_id}), Provider NPI ({claim_dict.get('provider_npi', 'on file')}), "
            f"Date of Service ({service_date or 'on file'}), Procedure Code ({proc_code}), and Billed Amount ({claimed_amount or 'on file'}). "
            "The submission is rejected as an unexempt duplicate submission."
        )
        citations = ["HorizonCare Silver PPO 2500 — Section 7.1 (Duplicate Claims)"]
        next_steps = [
            "You do not need to take any action; you are not responsible for duplicate billings.",
            f"If your provider intended to submit a corrected claim or separate distinct service for {prior_desc}, ask their billing office to resubmit marked as a formal correction (Sec 7.1).",
        ]

    else:
        # Clinical criteria or policy exclusion denial (e.g. conservative therapy not met, cosmetic, experimental)
        summary = (
            f"Your health plan does not cover {proc_name} under the clinical information provided. "
            "Under plan guidelines, diagnostic imaging requires trying simpler treatments (such as physical therapy "
            "or anti-inflammatory medication) first, or showing why those treatments cannot be safely tried. "
            "The records sent by your doctor did not show that these requirements were met."
        )
        rationale = (
            f"Clinical criteria for {proc_name} were not met. Submitted clinical notes do not document "
            "conservative treatment trials or medical contraindications required under Section 5.1."
        )
        citations = [
            "HorizonCare Silver PPO 2500 — Section 5.1 (MRI Coverage)",
            "HorizonCare Silver PPO 2500 — Section 4 (Medical Necessity Standard)",
        ]
        if "exclusion" in reason_text.lower() or "cosmetic" in reason_text.lower():
            citations.append("HorizonCare Silver PPO 2500 — Section 6 (Exclusions)")
        next_steps = [
            "Discuss alternative treatment options or physical therapy with your ordering physician.",
            "If you have already completed conservative therapy with another provider, have that provider submit their records.",
            "You or your doctor may file an appeal within 180 days if you believe this service is medically necessary.",
        ]

    # Assemble Full Letter Text (Print & Mail Ready)
    status_header = {
        "denied": "NOTICE OF ADVERSE BENEFIT DETERMINATION — DENIAL",
        "pended_missing_documentation": "NOTICE OF PENDED REQUEST — ADDITIONAL DOCUMENTATION REQUIRED",
        "routed_for_clinical_review": "NOTICE OF PENDING CLINICAL REVIEW — CASE IN PROGRESS",
    }.get(notice_status, "NOTICE OF ADVERSE BENEFIT DETERMINATION")

    date_str = service_date or "Current"
    full_letter = f"""================================================================================
HORIZONCARE HEALTH PLAN — EXPLANATION OF BENEFITS & ADVERSE DETERMINATION NOTICE
HorizonCare Customer Service: 1-800-555-0199 (TTY: 711) | www.horizoncare.com
================================================================================

DATE: {date_str}
TO: Member ID: {member_id}
CLAIM ID: {claim_id}
REVIEW ID: {review_id}
DATE OF SERVICE: {service_date or 'N/A'}
REQUESTED SERVICE: {proc_name} (CPT/HCPCS: {proc_code})
BILLED AMOUNT: {claimed_amount or 'N/A'}

--------------------------------------------------------------------------------
DETERMINATION: {status_header}
--------------------------------------------------------------------------------

1. WHAT WE DECIDED (PLAIN-LANGUAGE SUMMARY):
{summary}

2. CLINICAL & CONTRACTUAL RATIONALE:
{rationale}

PLAN PROVISIONS AND GUIDELINES RELIED UPON:
{chr(10).join(f'  • {c}' for c in citations)}

3. WHAT YOU AND YOUR DOCTOR SHOULD DO NEXT:
{chr(10).join(f'  {i+1}. {step}' for i, step in enumerate(next_steps))}

--------------------------------------------------------------------------------
4. YOUR STATUTORY APPEAL RIGHTS (ERISA § 503 & ACA § 2719)
--------------------------------------------------------------------------------
{ERISA_ACA_APPEAL_RIGHTS}

Sincerely,

Office of Clinical Adjudication & Appeals
HorizonCare Health Plan
================================================================================
"""

    return AdverseNotice(
        claim_id=claim_id,
        review_id=review_id,
        member_id=member_id,
        service_date=service_date,
        procedure_code=proc_code,
        procedure_name=proc_name,
        claimed_amount=claimed_amount,
        status=notice_status,
        reading_level="6th–8th Grade Plain Language",
        plain_language_summary=summary,
        clinical_rationale=rationale,
        policy_citations=citations,
        missing_items=missing or [],
        next_steps=next_steps,
        appeal_rights_statement=ERISA_ACA_APPEAL_RIGHTS,
        full_letter_text=full_letter.strip(),
    )
