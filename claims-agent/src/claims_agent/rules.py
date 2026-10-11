"""Pure, evidence-grounded rule checks. No action execution or full controller."""

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Literal

from .services import profile_for
from .evidence import retrieve_evidence, retrieve_mri_evidence
from .policy import PolicyIndex
from .requirements import CODING_REQUIREMENT, DOCUMENTATION_REQUIREMENT, DUPLICATE_REQUIREMENTS, ELIGIBILITY_REQUIREMENT
from .schemas import (
    CodingAssessment, CodingRequest, DuplicateClaimSnapshot, PolicyEvidence,
    PreAuthorizationDocumentationRequest, TreatmentHistoryApplicability,
    ClaimDocumentEvidence, MRIClinicalAssessment,
    ClinicalReviewRequest, CLINICAL_REQUEST_ADAPTER,
)


# Explicit supported provision for the supplied v3.2 policy, not a general
# natural-language parser. Changed/qualified provisions require rule review.
SUPPORTED_ELIGIBILITY_PROVISION = (
    "Benefits are payable only if the member is enrolled and the Plan is active on the date of service. "
    "If the member’s Plan is inactive at the time services are rendered, the claim will be denied. "
    "Denial reason: “Plan inactive at time of service.”"
)


def _normalize_provision(text: str) -> str:
    return " ".join(text.split()).casefold().translate(str.maketrans({"’": "'", "“": '"', "”": '"'}))


@dataclass(frozen=True)
class RuleResult:
    outcome: Literal["matched", "not_applicable", "unresolved", "satisfied"]
    proposed_action: Literal["deny_claim", "route_to_coding_review", "request_missing_documentation", "route_to_senior_reviewer"] | None
    reason: str
    policy_evidence: tuple[PolicyEvidence, ...] = ()
    claim_evidence: tuple[str, ...] = ()
    rule_id: Literal["inactive_plan", "duplicate_claim", "coding_consistency", "pre_authorization_documentation", "high_value_claim", "mri_clinical_conditions", "mri_exclusions", "service_clinical_conditions", "service_exclusions", "payment_amount", "payment_documentation", "payment_authorization", "appeal_evidence", "appeal_documentation", "appeal_timeliness", "appeal_link"] = "inactive_plan"
    missing_information: tuple[str, ...] = ()
    unresolved_information: tuple[str, ...] = ()
    rule_source: str | None = None
    clinical_evidence: tuple[ClaimDocumentEvidence, ...] = ()
    validated_payment_amount: Decimal | None = None


def evaluate_high_value_claim(claimed_amount: Decimal | None) -> RuleResult:
    """Task workflow threshold, independent of coverage or policy interpretation.

    Accept only finite nonnegative Decimal values, or None for missing input.
    The input schema should parse JSON amounts before this rule is called.
    The controller must apply earlier approved checks before high-value routing.
    """
    source = "AI_Engineer_Take_Home_Task.pdf, page 2, Core workflow rules"
    if claimed_amount is None:
        return RuleResult(
            outcome="unresolved", proposed_action=None,
            reason="Claimed amount is missing; high-value routing cannot be evaluated.",
            rule_id="high_value_claim", unresolved_information=("claimed_amount",),
            rule_source=source,
        )
    if not isinstance(claimed_amount, Decimal):
        raise TypeError("claimed_amount must be a Decimal or None")
    if not claimed_amount.is_finite() or claimed_amount < 0:
        raise ValueError("claimed_amount must be finite and nonnegative")
    above_threshold = claimed_amount > Decimal("5000")
    return RuleResult(
        outcome="matched" if above_threshold else "not_applicable",
        proposed_action="route_to_senior_reviewer" if above_threshold else None,
        reason=("Claimed amount exceeds $5,000; senior review is required." if above_threshold
                else "Claimed amount does not exceed $5,000; other review checks remain."),
        claim_evidence=(f"claimed_amount={claimed_amount}", "high_value_threshold=5000", "comparison=strictly_greater_than"),
        rule_id="high_value_claim", rule_source=source,
    )


def evaluate_inactive_plan(
    member_status: Literal["active", "inactive"] | None,
    policy_index: PolicyIndex,
    *,
    insurer: str,
    plan_name: str,
) -> RuleResult:
    """Evaluate trusted structured status at the relevant service date.

    The caller supplies service-date status, not merely current membership.
    Invalid status raises ValueError; wrong/unknown policy raises PolicyError.
    Notes cannot override status because this rule never consumes free text.
    A non-match is not an approval. An unresolved result must not be skipped
    by a future controller to reach an approval.
    """
    if member_status not in ("active", "inactive", None):
        raise ValueError("member_status must be active, inactive, or None")
    bundle = retrieve_evidence(
        policy_index, insurer=insurer, plan_name=plan_name,
        requirements=(ELIGIBILITY_REQUIREMENT,),
    )
    facts = (f"member_status={member_status if member_status is not None else 'unknown'}",)
    if member_status is None:
        return RuleResult("unresolved", None, "Member status at the service date is unknown.", claim_evidence=facts)
    candidates = bundle.requirements[0].chunks
    # Require one supported section, retaining all its cross-page fragments.
    # Extra/changed candidate provisions are not interpreted via keyword overlap.
    sections = {c.section for c in candidates}
    ordered = tuple(sorted(candidates, key=lambda c: (c.source_page, c.chunk_id)))
    provision = " ".join(c.text for c in ordered)
    if len(sections) != 1 or _normalize_provision(provision) != _normalize_provision(SUPPORTED_ELIGIBILITY_PROVISION):
        return RuleResult(
            "unresolved", None,
            "Supported inactive-plan provision is missing, changed, or ambiguous; policy review is required.",
            claim_evidence=facts,
        )
    evidence = tuple(PolicyEvidence.from_chunk(c, c.text) for c in ordered)
    for quote, chunk in zip(evidence, ordered):
        quote.validate_against(chunk)
    if member_status == "active":
        return RuleResult("not_applicable", None, "Inactive-plan denial does not apply; other checks remain.", evidence, facts)
    return RuleResult("matched", "deny_claim", "Plan inactive at time of service.", evidence, facts)


DUPLICATE_FIELDS = ("member_id", "provider_npi", "service_date", "procedure_code", "billed_amount")
SUPPORTED_DUPLICATE_PROVISION = (
    "A claim is considered duplicate if all of the following match: "
    "Member ID Provider NPI Date of service CPT / procedure code Billed amount "
    "Duplicate claims will be denied with reason: “Duplicate claim submission.”"
)
SUPPORTED_CORRECTION_PROVISION = (
    "Duplicate claims for the same service date and provider, unless corrected and resubmitted"
)


def _duplicate_policy_evidence(bundle):
    criteria, correction = bundle.requirements
    ordered = sorted(criteria.chunks, key=lambda c: (c.source_page, c.chunk_id))
    text = " ".join(c.text for c in ordered).replace("\uf0b7", " ").replace("•", " ")
    if (len({c.section for c in ordered}) != 1
            or _normalize_provision(text) != _normalize_provision(SUPPORTED_DUPLICATE_PROVISION)):
        return ()
    if len({c.section for c in correction.chunks}) != 1:
        return ()
    exception_quotes = []
    for chunk in correction.chunks:
        for line in chunk.text.splitlines():
            if "duplicate" not in line.casefold():
                continue
            normalized = re.sub(r"^\s*(?:\d+\.|[•\uf0b7])\s*", "", line)
            if _normalize_provision(normalized) != _normalize_provision(SUPPORTED_CORRECTION_PROVISION):
                return ()
            exception_quotes.append(PolicyEvidence.from_chunk(chunk, line))
    if not exception_quotes:
        return ()
    return tuple(PolicyEvidence.from_chunk(c, c.text) for c in ordered) + tuple(exception_quotes)


def _correction_changes(current: DuplicateClaimSnapshot, original: DuplicateClaimSnapshot) -> tuple[str, ...]:
    changes = []
    for field in (*DUPLICATE_FIELDS, "diagnosis_codes", "procedure_description"):
        before, after = getattr(original, field), getattr(current, field)
        if before is None or after is None:
            continue  # Unavailable data is not proof that a submission changed.
        if field == "diagnosis_codes":
            before, after = frozenset(before), frozenset(after)
        if before != after:
            changes.append(field)
    if original.documents is not None and current.documents is not None:
        # Ignore generated identifiers, ordering, repeated identical documents,
        # and review provenance. Only compare document type/status/content.
        def signatures(documents):
            return {(d.document_type, d.status, d.text) for d in documents}
        # If provided content is unavailable, content changes cannot be verified.
        incomplete = any(d.status == "unknown" or (d.status == "provided" and d.text is None)
                         for d in (*original.documents, *current.documents))
        if not incomplete and signatures(original.documents) != signatures(current.documents):
            changes.append("documents")
    return tuple(changes)


def evaluate_duplicate_claim(
    current: DuplicateClaimSnapshot,
    prior_claims: tuple[DuplicateClaimSnapshot, ...] | None,
    policy_index: PolicyIndex,
    *,
    insurer: str,
    plan_name: str,
    correction_declared: bool = False,
    corrects_claim_id: str | None = None,
) -> RuleResult:
    """Compare trusted, policy-scoped history and inspect a linked correction.

    A verified change only exempts the linked original, never another duplicate.
    This check establishes neither correction legitimacy nor medical sufficiency.
    Missing history is unresolved; empty history explicitly reports no priors.
    """
    if not isinstance(correction_declared, bool):
        raise ValueError("correction_declared must be a boolean")
    if corrects_claim_id is not None and (not isinstance(corrects_claim_id, str) or not corrects_claim_id.strip()):
        raise ValueError("corrects_claim_id must be a nonblank string")
    bundle = retrieve_evidence(policy_index, insurer=insurer, plan_name=plan_name,
                               requirements=DUPLICATE_REQUIREMENTS)
    evidence = _duplicate_policy_evidence(bundle)
    facts = [f"claim_id={current.claim_id}"]

    def result(outcome, reason, action=None):
        return RuleResult(outcome, action, reason, evidence, tuple(facts), "duplicate_claim")

    if not evidence:
        return result("unresolved", "Duplicate criteria or corrected-submission exception are missing, changed, or ambiguous.")
    if prior_claims is None:
        return result("unresolved", "Prior-claim history is unavailable.")
    missing = [f for f in DUPLICATE_FIELDS if getattr(current, f) is None]
    if missing:
        facts.append("missing_fields=" + ",".join(missing))
        return result("unresolved", "Current claim lacks duplicate-comparison fields.")
    ids = [c.claim_id for c in prior_claims]
    if len(ids) != len(set(ids)) or current.claim_id in ids:
        return result("unresolved", "History must identify distinct prior submissions unambiguously.")
    corrected_id = None
    if correction_declared or corrects_claim_id is not None:
        if not correction_declared or corrects_claim_id is None:
            return result("unresolved", "Correction declaration and original-claim reference are both required.")
        original = next((c for c in prior_claims if c.claim_id == corrects_claim_id), None)
        if original is None:
            return result("unresolved", "Referenced original claim is absent from supplied history.")
        if any(getattr(original, f) is None for f in DUPLICATE_FIELDS):
            return result("unresolved", "Referenced original claim lacks comparison fields.")
        changes = _correction_changes(current, original)
        if not changes:
            return result("unresolved", "No identifiable correction could be verified against the original submission.")
        corrected_id = original.claim_id
        facts.extend((f"corrects_claim_id={corrected_id}", "changed_fields=" + ",".join(changes)))
    incomplete = False
    for prior in prior_claims:
        if prior.claim_id == corrected_id:
            continue
        # A known differing key rules out this particular prior even if another
        # key is missing. Otherwise incomplete matching data remains unresolved.
        if any(getattr(prior, f) is not None and getattr(prior, f) != getattr(current, f)
               for f in DUPLICATE_FIELDS):
            continue
        if any(getattr(prior, f) is None for f in DUPLICATE_FIELDS):
            incomplete = True
            continue
        facts.append(f"duplicate_of={prior.claim_id}")
        facts.extend(f"{f}={getattr(current, f)}" for f in DUPLICATE_FIELDS)
        return result("matched", "Duplicate claim submission.", "deny_claim")
    if incomplete:
        return result("unresolved", "Incomplete prior-claim data prevents ruling out a duplicate.")
    reason = ("Linked correction has identifiable changes; continue other review checks."
              if corrected_id else "No duplicate found in the supplied history; continue other review checks.")
    facts.append(f"prior_claims_checked={len(prior_claims)}")
    return result("not_applicable", reason)


SUPPORTED_CODING_PROVISION = (
    "Claims may be routed for coding review if diagnosis and procedure codes are clinically inconsistent "
    "based on standard coding guidelines."
)


def evaluate_coding_consistency(
    request: CodingRequest,
    assessment: CodingAssessment | None,
    policy_index: PolicyIndex,
    *,
    insurer: str,
    plan_name: str,
) -> RuleResult:
    """Consume a trusted assessment; never infer clinical compatibility locally.

    The assessment must belong to the exact current claim/review/code request.
    Source/reason are audit data, not instructions. This rule invokes no provider.
    Task-required routing is stricter than the policy's permissive 'may' wording.
    """
    request = CodingRequest.model_validate(request)
    if assessment is not None:
        assessment = CodingAssessment.model_validate(assessment)
    bundle = retrieve_evidence(policy_index, insurer=insurer, plan_name=plan_name,
                               requirements=(CODING_REQUIREMENT,))
    facts = [f"claim_id={request.claim_id}", f"review_id={request.review_id}",
             f"procedure_code={request.procedure_code}", f"diagnosis_codes={request.diagnosis_codes}"]

    def result(outcome, reason, action=None, evidence=()):
        return RuleResult(outcome, action, reason, evidence, tuple(facts), "coding_consistency")

    if request.procedure_code is None or not request.diagnosis_codes:
        return result("unresolved", "Procedure or diagnosis codes are missing; coding consistency is unknown.")
    if assessment is None:
        return result("unresolved", "No trusted coding assessment was supplied.")
    if assessment.request != request:
        return result("unresolved", "Coding assessment does not match the current claim, review, and codes.")
    facts.extend((f"coding_status={assessment.status}", f"coding_source={assessment.source}",
                  f"coding_source_version={assessment.source_version}", f"coding_reason={assessment.reason}"))
    if assessment.status == "unknown":
        return result("unresolved", "Coding assessment could not establish consistency.")
    ordered = tuple(sorted(bundle.requirements[0].chunks, key=lambda c: (c.source_page, c.chunk_id)))
    text = " ".join(c.text for c in ordered)
    if (len({c.section for c in ordered}) != 1
            or _normalize_provision(text) != _normalize_provision(SUPPORTED_CODING_PROVISION)):
        return result("unresolved", "Supported coding-review provision is missing, changed, or ambiguous.")
    evidence = tuple(PolicyEvidence.from_chunk(c, c.text) for c in ordered)
    for quote, chunk in zip(evidence, ordered):
        quote.validate_against(chunk)
    if assessment.status == "inconsistent":
        return result("matched", "Trusted assessment reports inconsistent diagnosis/procedure codes; coding review is required.",
                      "route_to_coding_review", evidence)
    return result("not_applicable", "Trusted assessment reports consistent codes; other review checks remain.",
                  evidence=evidence)


SUPPORTED_DOCUMENTATION_PROVISION = (
    "Prior Authorization requests must include: "
    "1. Ordering provider’s clinical note "
    "2. Relevant diagnosis code(s) "
    "3. Prior treatment history (if applicable) "
    "4. Expected service date and location "
    "If documentation is missing, the request will be pended until complete information is received."
)


def evaluate_pre_authorization_documentation(
    request: PreAuthorizationDocumentationRequest,
    applicability: TreatmentHistoryApplicability | None,
    policy_index: PolicyIndex,
    *,
    insurer: str,
    plan_name: str,
) -> RuleResult:
    """Check presence, never infer document sufficiency or treatment completion.

    Known missing items may be requested while other questions remain unresolved;
    both lists are retained. Unknown presence is not reported as known absence.
    The future action adapter must pass missing_information as its documents list.
    """
    request = PreAuthorizationDocumentationRequest.model_validate(request)
    if applicability is not None:
        applicability = TreatmentHistoryApplicability.model_validate(applicability)
    bundle = retrieve_evidence(policy_index, insurer=insurer, plan_name=plan_name,
                               requirements=(DOCUMENTATION_REQUIREMENT,))
    chunks = tuple(sorted(bundle.requirements[0].chunks, key=lambda c: (c.source_page, c.chunk_id)))
    facts = [f"claim_id={request.claim_id}", f"review_id={request.review_id}",
             f"diagnosis_codes={request.diagnosis_codes}",
             f"expected_service_date={request.expected_service_date}", f"service_location={request.service_location}"]
    missing = []
    unresolved = []
    evidence = ()

    def result(outcome, reason, action=None):
        return RuleResult(outcome, action, reason, evidence, tuple(facts),
                          "pre_authorization_documentation", tuple(missing), tuple(unresolved))

    if (len({c.section for c in chunks}) != 1 or
            _normalize_provision(" ".join(c.text for c in chunks)) != _normalize_provision(SUPPORTED_DOCUMENTATION_PROVISION)):
        unresolved.append("documentation_policy")
        return result("unresolved", "Supported pre-authorization documentation provision is missing, changed, or ambiguous.")
    evidence = tuple(PolicyEvidence.from_chunk(c, c.text) for c in chunks)
    for quote, chunk in zip(evidence, chunks):
        quote.validate_against(chunk)

    def check_document(kind):
        if request.documents is None:
            unresolved.append(f"{kind}.presence")
            return
        documents = [d for d in request.documents if d.document_type == kind]
        states = {d.status for d in documents}
        facts.extend(f"document={d.document_id};type={kind};status={d.status}" for d in documents)
        if not documents or states == {"missing"}:
            missing.append(kind)
        elif states == {"provided"}:
            if not any(d.text is not None for d in documents):
                unresolved.append(f"{kind}.content")
        else:
            # Unknown or conflicting presence declarations require clarification.
            unresolved.append(f"{kind}.presence")

    check_document("clinical_note")
    if not request.diagnosis_codes:
        missing.append("diagnosis_codes")
    if request.expected_service_date is None:
        missing.append("expected_service_date")
    if request.service_location is None:
        missing.append("service_location")

    if applicability is None or applicability.request != request or request.procedure_code is None:
        unresolved.append("prior_treatment_history.applicability")
    else:
        facts.extend((f"treatment_history_applicability={applicability.status}",
                      f"applicability_source={applicability.source}", f"applicability_reason={applicability.reason}"))
        if applicability.status == "required":
            check_document("prior_treatment_history")
        elif applicability.status == "unknown":
            unresolved.append("prior_treatment_history.applicability")
        # not_required affects this presence check only; never waives coverage rules.
    if missing:
        return result("matched", "Request the identified missing pre-authorization items; any unresolved checks remain pending.",
                      "request_missing_documentation")
    if unresolved:
        return result("unresolved", "Document presence, content availability, or treatment-history applicability remains unresolved.")
    return result("not_applicable", "Required items are present; clinical evidence sufficiency and coverage still require assessment.")


SUPPORTED_MRI_PROVISION = (
    "MRI is covered when all of the following conditions are met: "
    "A covered diagnosis is present; and "
    "Conservative treatment has been attempted (unless contraindicated); and "
    "Prior Authorization has been approved. "
    "Examples of covered diagnoses for lumbar spine MRI include: "
    "M54.5 Low back pain M51.26 Other intervertebral disc displacement, lumbar region"
)
SUPPORTED_NECESSITY_PROVISION = (
    "A service is considered Medically Necessary if it is: "
    "Consistent with generally accepted standards of medical practice; "
    "Clinically appropriate in type, frequency, and setting; "
    "Not primarily for convenience of the member or provider; "
    "The most cost-effective option among clinically comparable alternatives. "
    "Medical Necessity determinations may involve internal clinical guidelines."
)


def evaluate_mri_clinical_conditions(
    request: ClinicalReviewRequest,
    assessment: MRIClinicalAssessment | None,
    policy_index: PolicyIndex,
    *,
    insurer: str,
    plan_name: str,
) -> RuleResult:
    """Check lumbar-MRI predicates for the explicitly bound service workflow.

    The requested authorization is the future outcome, not a prerequisite of
    this pre-authorization check. Eligibility, coding, documents, high value,
    exclusions, and final action validation remain separate controller duties.
    Quotation validation proves source linkage, not clinical truth; findings
    must come from a trusted upstream assessment. No model or provider is called.
    """
    request = CLINICAL_REQUEST_ADAPTER.validate_python(request)
    if assessment is not None:
        assessment = MRIClinicalAssessment.model_validate(assessment)
    bundle = retrieve_mri_evidence(policy_index, insurer=insurer, plan_name=plan_name)
    facts = [f"claim_id={request.claim_id}", f"review_id={request.review_id}",
             f"procedure_code={request.procedure_code}", f"diagnosis_codes={request.diagnosis_codes}"]
    unresolved = []
    policy_quotes = []
    document_quotes = []

    def result(outcome, reason):
        return RuleResult(
            outcome=outcome, proposed_action=None, reason=reason,
            policy_evidence=tuple(policy_quotes), claim_evidence=tuple(facts),
            rule_id="mri_clinical_conditions", unresolved_information=tuple(unresolved),
            clinical_evidence=tuple(dict.fromkeys(document_quotes)),
        )

    if not profile_for(request.procedure_code) or profile_for(request.procedure_code).key != "mri":
        unresolved.append("supported_service")
    if not request.diagnosis_codes:
        unresolved.append("diagnosis_codes")
    for key, expected in (("mri_coverage", SUPPORTED_MRI_PROVISION),
                          ("medical_necessity", SUPPORTED_NECESSITY_PROVISION)):
        candidates = next(r.chunks for r in bundle.requirements if r.requirement.key == key)
        ordered = sorted(candidates, key=lambda c: (c.source_page, c.chunk_id))
        text = " ".join(c.text for c in ordered).replace("\uf0b7", " ").replace("•", " ")
        if len({c.section for c in ordered}) != 1 or _normalize_provision(text) != _normalize_provision(expected):
            unresolved.append(f"policy.{key}")
        else:
            for chunk in ordered:
                quote = PolicyEvidence.from_chunk(chunk, chunk.text)
                quote.validate_against(chunk)
                policy_quotes.append(quote)
    if assessment is None or assessment.request != request:
        unresolved.append("current_clinical_assessment")
        return result("unresolved", "A clinical assessment bound to the current submission is required.")
    documents = {d.document_id: d for d in request.documents or ()}
    statuses = {}
    for field in ("diagnosis_support", "medical_necessity", "conservative_treatment_attempted",
                  "conservative_treatment_contraindicated"):
        finding = getattr(assessment, field)
        statuses[field] = finding.status if finding else "unknown"
        if finding is None:
            facts.append(f"{field}=unknown")
            continue
        facts.extend((f"{field}={finding.status}", f"{field}.source={finding.source}",
                      f"{field}.reason={finding.reason}"))
        if finding.status == "conflicting":
            unresolved.append(f"{field}.conflicting")
        for reference in finding.evidence:
            document = documents.get(reference.document_id)
            if (document is None or document.status != "provided" or document.text is None
                    or reference.quote not in document.text):
                unresolved.append(f"{field}.evidence")
                statuses[field] = "unknown"
            else:
                document_quotes.append(reference)
    for field in ("diagnosis_support", "medical_necessity"):
        if statuses[field] != "established":
            unresolved.append(field)
    if not any(statuses[field] == "established" for field in
               ("conservative_treatment_attempted", "conservative_treatment_contraindicated")):
        unresolved.append("conservative_treatment_or_contraindication")
    if unresolved:
        return result("unresolved", "Clinical conditions are not established or supporting evidence requires review.")
    return result("satisfied", "Supported clinical conditions are established; remaining workflow and exclusion checks must precede approval.")
