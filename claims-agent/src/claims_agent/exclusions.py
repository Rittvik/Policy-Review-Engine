"""Conditional exclusions shared by MRI service workflows; no action execution."""

from .services import profile_for
from .evidence import retrieve_mri_evidence
from .policy import PolicyIndex
from .retrieval import tokenize
from .rules import RuleResult, _normalize_provision
from .schemas import MRIExclusionAssessment, PolicyEvidence, ClinicalReviewRequest, CLINICAL_REQUEST_ADAPTER


SUPPORTED_SCREENING = (
    "Diagnostic imaging is not covered when: "
    "Requested for screening without symptoms, unless explicitly included as preventive care; "
    "Related to excluded procedures; Lacking documentation supporting Medical Necessity."
)
SUPPORTED_EXCLUSIONS = (
    "The Plan does not cover: "
    "1. Cosmetic or reconstructive procedures not required by trauma or congenital anomaly "
    "2. Services deemed not Medically Necessary "
    "3. Experimental or investigational treatments "
    "4. Services for which required Prior Authorization was not obtained "
    "5. Duplicate claims for the same service date and provider, unless corrected and resubmitted"
)


def evaluate_mri_exclusions(
    request: ClinicalReviewRequest,
    assessment: MRIExclusionAssessment | None,
    policy_index: PolicyIndex,
    *,
    insurer: str,
    plan_name: str,
) -> RuleResult:
    """Deny only with established exclusions and relevant exceptions ruled out.

    Trusted assessments establish meaning; this function validates their scope,
    provenance, and conditional logic. Unknown/conflicting applicable findings
    leave the overall check unresolved. Lack of existing authorization is not
    an exclusion for a request seeking its first authorization.
    """
    request = CLINICAL_REQUEST_ADAPTER.validate_python(request)
    if assessment is not None:
        assessment = MRIExclusionAssessment.model_validate(assessment)
    bundle = retrieve_mri_evidence(policy_index, insurer=insurer, plan_name=plan_name)
    facts = [f"claim_id={request.claim_id}", f"review_id={request.review_id}"]
    unresolved, reasons, policy_evidence, clinical_evidence = [], [], [], []

    def result(outcome, reason, action=None):
        return RuleResult(
            outcome=outcome, proposed_action=action, reason=reason,
            policy_evidence=tuple(dict.fromkeys(policy_evidence)), claim_evidence=tuple(facts),
            rule_id="mri_exclusions", unresolved_information=tuple(dict.fromkeys(unresolved)),
            clinical_evidence=tuple(dict.fromkeys(clinical_evidence)),
        )

    profile = profile_for(request.procedure_code)
    if profile is None:
        unresolved.append("supported_service")
    generic_sections = set()
    provisions = (("screening_exception", SUPPORTED_SCREENING), ("exclusions", SUPPORTED_EXCLUSIONS)) if profile and profile.imaging else (("exclusions", SUPPORTED_EXCLUSIONS),)
    for key, expected in provisions:
        candidates = next(r.chunks for r in bundle.requirements if r.requirement.key == key)
        ordered = sorted(candidates, key=lambda c: (c.source_page, c.chunk_id))
        text = " ".join(c.text for c in ordered).replace("\uf0b7", " ").replace("•", " ")
        if len({c.section for c in ordered}) != 1 or _normalize_provision(text) != _normalize_provision(expected):
            unresolved.append(f"policy.{key}")
        else:
            for chunk in ordered:
                quote = PolicyEvidence.from_chunk(chunk, chunk.text)
                quote.validate_against(chunk)
                policy_evidence.append(quote)
                generic_sections.add(chunk.section)
    if assessment is None or assessment.request != request:
        unresolved.append("current_exclusion_assessment")
        return result("unresolved", "An exclusion assessment for the current submission is required.")
    documents = {d.document_id: d for d in request.documents or ()}

    def clinical_status(name):
        finding = getattr(assessment, name)
        if finding is None:
            unresolved.append(name)
            return "unknown"
        facts.extend((f"{name}={finding.status}", f"{name}.source={finding.source}", f"{name}.reason={finding.reason}"))
        invalid = False
        for reference in finding.evidence:
            document = documents.get(reference.document_id)
            if document is None or document.status != "provided" or document.text is None or reference.quote not in document.text:
                unresolved.append(f"{name}.evidence")
                invalid = True
            else:
                clinical_evidence.append(reference)
        if finding.status in {"unknown", "conflicting"}:
            unresolved.append(name)
        return "unknown" if invalid else finding.status

    def preventive_status():
        finding = assessment.preventive_coverage
        if finding is None:
            unresolved.append("preventive_coverage")
            return "unknown"
        facts.extend((f"preventive_coverage={finding.status}", f"preventive_coverage.source={finding.source}",
                      f"preventive_coverage.reason={finding.reason}"))
        if finding.status in {"unknown", "conflicting"}:
            unresolved.append("preventive_coverage")
            return finding.status
        chunks = {c.chunk_id: c for c in policy_index.chunks}
        valid = True
        for reference in finding.evidence:
            chunk = chunks.get(reference.chunk_id)
            try:
                if chunk is None:
                    raise ValueError("Unknown policy chunk")
                reference.validate_against(chunk)
                terms = set(tokenize(reference.quote))
                # Reject the generic exception itself and unrelated excerpts.
                # The trusted assessor, not keyword overlap, determines coverage.
                if chunk.section in generic_sections or not {"preventive", profile.key} <= terms:
                    raise ValueError("Explicit service-specific preventive provision needed")
            except ValueError:
                valid = False
                unresolved.append("preventive_coverage.evidence")
            else:
                policy_evidence.append(reference)
        return finding.status if valid else "unknown"

    if profile and profile.imaging and clinical_status("screening_without_symptoms") == "established":
        if preventive_status() == "ruled_out":
            reasons.append("Screening without symptoms is not included as preventive care.")
    if clinical_status("cosmetic_or_reconstructive") == "established":
        if clinical_status("required_by_trauma_or_congenital_anomaly") == "ruled_out":
            reasons.append("Cosmetic or reconstructive service is not required by trauma or congenital anomaly.")
    if clinical_status("experimental_or_investigational") == "established":
        reasons.append("Service is established as experimental or investigational.")
    if clinical_status("medically_unnecessary") == "established":
        reasons.append("Service is established as not medically necessary.")
    if unresolved:
        return result("unresolved", "Applicable exclusions or exceptions require further evidence or review.")
    if reasons:
        return result("matched", " ".join(reasons), "deny_claim")
    return result("not_applicable", "Assessed exclusions do not apply or their exceptions are supported; other review checks remain.")
