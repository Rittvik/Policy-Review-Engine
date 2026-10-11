"""Validate a supplied payment calculation; never infer a benefit formula."""

from .services import profile_for
from .rules import RuleResult, _normalize_provision
from .schemas import PaymentDetermination, PaymentRequest, Claim, PolicyEvidence
from .evidence import retrieve_mri_evidence
from .exclusions import SUPPORTED_SCREENING
from .policy import PolicyIndex


SUPPORTED_AUTHORIZATION = (
    "The following services require Prior Authorization: MRI (all anatomical regions) "
    "CT scans (except emergency) Elective inpatient admissions "
    "Durable medical equipment (DME) exceeding $500 "
    'Specialty drugs listed as “PA Required” on the Formulary '
    "Claims for these services performed without approval may be denied unless retroactive authorization is granted."
)


def _policy_evidence(index: PolicyIndex, scope: dict[str, str], key: str, expected: str) -> tuple[PolicyEvidence, ...]:
    bundle = retrieve_mri_evidence(index, **scope)
    chunks = sorted(next(r.chunks for r in bundle.requirements if r.requirement.key == key),
                    key=lambda c: (c.source_page, c.chunk_id))
    text = " ".join(c.text for c in chunks).replace("\uf0b7", " ").replace("•", " ")
    if len({c.section for c in chunks}) != 1 or _normalize_provision(text) != _normalize_provision(expected):
        return ()
    return tuple(PolicyEvidence.from_chunk(c, c.text) for c in chunks)


def evaluate_payment_documentation(claim: Claim, index: PolicyIndex, *, insurer: str, plan_name: str) -> RuleResult:
    """Check known missing necessity evidence, without importing the PA checklist."""
    claim = Claim.model_validate(claim.model_dump())
    claim.payment_request()  # Reject accidental use for another workflow.
    profile = profile_for(claim.procedure_code)
    if profile and not profile.imaging:
        from .service_rules import provision, SUPPORTED_BENEFITS
        evidence = provision(index, SUPPORTED_BENEFITS, dict(insurer=insurer, plan_name=plan_name))
    else:
        evidence = _policy_evidence(index, dict(insurer=insurer, plan_name=plan_name), "screening_exception", SUPPORTED_SCREENING)
    if profile is None:
        return RuleResult("unresolved", None, "Service payment documentation profile is unknown.",
                          rule_id="payment_documentation", unresolved_information=("supported_service",))
    missing, unresolved = [], []
    if not evidence:
        unresolved.append("policy.payment_documentation")
    if claim.documents is None:
        unresolved.append("document_inventory")
    elif not claim.documents or all(d.status == "missing" for d in claim.documents):
        missing.append("medical_necessity_documentation")
    assessment = claim.clinical_assessment
    if assessment and assessment.request == claim.clinical_request() and assessment.medical_necessity:
        documents = {d.document_id: d for d in claim.documents or ()}
        for ref in assessment.medical_necessity.evidence:
            doc = documents.get(ref.document_id)
            if claim.documents is not None and (doc is None or doc.status == "missing"):
                missing.append(ref.document_id)
    if not claim.diagnosis_codes:
        missing.append("diagnosis_codes")
    return RuleResult(
        outcome="matched" if missing and evidence else "unresolved" if unresolved else "not_applicable",
        proposed_action="request_missing_documentation" if missing and evidence else None,
        reason="Essential payment documentation is missing." if missing else "Payment document presence checked; clinical evidence is assessed separately.",
        rule_id="payment_documentation", policy_evidence=evidence,
        missing_information=tuple(dict.fromkeys(missing)), unresolved_information=tuple(unresolved),
        rule_source="Task requirement: request missing essential information, including diagnosis codes.",
    )


def evaluate_payment_authorization(claim: Claim, index: PolicyIndex, *, insurer: str, plan_name: str) -> RuleResult:
    """Require documented prior or retroactive approval; absence remains unresolved."""
    claim = Claim.model_validate(claim.model_dump())
    claim.payment_request()
    evidence = _policy_evidence(index, dict(insurer=insurer, plan_name=plan_name), "retroactive_authorization", SUPPORTED_AUTHORIZATION)
    unresolved, references, facts = [], [], []
    if not evidence:
        unresolved.append("policy.payment_authorization")
    from .service_rules import authorization_required
    required, unknown, requirement_refs = authorization_required(claim)
    unresolved.extend(unknown)
    references.extend(requirement_refs)
    facts.append(f"prior_authorization_required={required}")
    if required is not True:
        return RuleResult('unresolved' if unresolved else 'satisfied', None,
            'Authorization applicability needs evidence.' if unresolved else
            'This service does not require prior authorization under the supplied policy; other payment gates still apply.',
            rule_id='payment_authorization', policy_evidence=evidence,
            clinical_evidence=tuple(references), claim_evidence=tuple(facts), unresolved_information=tuple(unresolved))
    assessment = claim.authorization_assessment
    if assessment is None or assessment.request != claim.payment_request():
        unresolved.append("current_authorization_assessment")
    else:
        documents = {d.document_id: d for d in claim.documents or ()}
        approved = False
        for name in ("prior", "retroactive"):
            finding = getattr(assessment, name)
            if finding is None:
                continue
            facts.extend((f"{name}_authorization={finding.status}", f"{name}.source={finding.source}",
                          f"{name}.reason={finding.reason}"))
            valid = True
            for ref in finding.evidence:
                doc = documents.get(ref.document_id)
                if doc is None or doc.status != "provided" or doc.text is None or ref.quote not in doc.text:
                    unresolved.append(f"authorization.{name}.evidence")
                    valid = False
                else:
                    references.append(ref)
            if finding.status == "conflicting":
                unresolved.append(f"authorization.{name}.conflicting")
            if name == "prior" and claim.prior_authorization_approved is not None:
                if ((finding.status == "approved" and not claim.prior_authorization_approved)
                        or (finding.status == "not_obtained" and claim.prior_authorization_approved)):
                    unresolved.append("authorization.prior.contradiction")
            approved |= valid and finding.status == "approved"
        if not approved:
            unresolved.append("approved_prior_or_retroactive_authorization")
    return RuleResult(
        outcome="unresolved" if unresolved else "satisfied", proposed_action=None,
        reason="Payment authorization requires review." if unresolved else "Documented prior or retroactive authorization is approved.",
        rule_id="payment_authorization", policy_evidence=evidence, clinical_evidence=tuple(references),
        claim_evidence=tuple(facts), unresolved_information=tuple(unresolved),
    )


def evaluate_payment_determination(
    request: PaymentRequest, determination: PaymentDetermination | None,
) -> RuleResult:
    """Validate source binding, document quotations, and the approved amount guard.

    No payment action is issued. Eligibility, coverage, coding, documentation,
    authorization, and high-value routing still require the payment controller.
    Matching quotations prove source linkage, not the correctness of arithmetic
    or benefit interpretation: this check consumes a trusted upstream calculation.
    """
    request = PaymentRequest.model_validate(request)
    if determination is not None:
        determination = PaymentDetermination.model_validate(determination)
    facts = [f"claim_id={request.claim_id}", f"review_id={request.review_id}",
             f"claimed_amount={request.claimed_amount}"]
    unresolved, references = [], []

    def result(outcome, reason, amount=None):
        return RuleResult(
            outcome=outcome, proposed_action=None, reason=reason, rule_id="payment_amount",
            claim_evidence=tuple(facts), clinical_evidence=tuple(references),
            unresolved_information=tuple(unresolved), validated_payment_amount=amount,
            rule_source="User-approved MVP guard: a supplied payable amount must not exceed the billed amount.",
        )

    if determination is None or determination.request != request:
        unresolved.append("current_payment_determination")
        return result("unresolved", "A payment determination bound to the current submission is required.")
    facts.extend((f"payment_status={determination.status}", f"payment_source={determination.source}",
                  f"payment_reason={determination.reason}"))
    if determination.status != "determined":
        unresolved.append("payment_determination")
        return result("unresolved", "The upstream payable amount is unknown or conflicting.")
    # A reviewed amount must be tied to a concrete member/service, not just an ID.
    for name in ("claimed_amount", "provider_npi", "service_date", "procedure_code"):
        if getattr(request, name) is None:
            unresolved.append(name)
    documents = {doc.document_id: doc for doc in request.documents or ()}
    for reference in determination.evidence:
        document = documents.get(reference.document_id)
        if document is None or document.status != "provided" or document.text is None or reference.quote not in document.text:
            unresolved.append("payment_determination.evidence")
        else:
            references.append(reference)
    if request.claimed_amount is not None and determination.payable_amount > request.claimed_amount:
        unresolved.append("payment_exceeds_billed_amount")
    if unresolved:
        return result("unresolved", "Payment evidence or the payable-amount guard requires senior review.")
    facts.append(f"payable_amount={determination.payable_amount}")
    return result("satisfied", "Supplied payment amount passed validation; remaining payment workflow checks still apply.",
                  determination.payable_amount)
