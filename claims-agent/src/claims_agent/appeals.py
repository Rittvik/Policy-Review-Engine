"""Appeal input models and pure gates used by the reassessment controller."""

from datetime import date
from dataclasses import replace
from typing import Literal

from pydantic import model_validator

from .decisions import FrozenModel
from .evidence import retrieve_evidence
from .policy import PolicyIndex
from .requirements import APPEAL_REQUIREMENT
from .reviews import ReviewRecord, ReviewStore, ReviewStoreError
from .rules import RuleResult, _normalize_provision, evaluate_duplicate_claim
from .schemas import Claim, ClaimDocumentEvidence, ClinicalFinding, Nonblank, PolicyEvidence


SUPPORTED_APPEAL_PROVISION = (
    "Members and providers have the right to appeal a denial within 180 days. "
    "Appeals must include: A written appeal request The denial letter or claim reference number "
    "Any new clinical documentation relevant to the denial reason "
    "Appeals without new or relevant documentation may be upheld."
)


class AppealEvidenceRequest(FrozenModel):
    """Exact current submission and original decision reviewed by the assessor.

    The caller loads prior_review from trusted ReviewStore storage. A supplied
    snapshot alone does not authenticate its origin.
    """

    claim: Claim
    prior_review: ReviewRecord
    claim_reference: Nonblank | None = None


class AppealEvidenceAssessment(FrozenModel):
    request: AppealEvidenceRequest | None = None
    # Reuses provenance/status/quotation validation from existing trusted findings.
    new_relevant_evidence: ClinicalFinding


class DocumentedAppealDate(FrozenModel):
    """Trusted event-date finding; quote validation does not interpret date meaning."""

    status: Literal["established", "unknown", "conflicting"]
    value: date | None = None
    source: Nonblank
    reason: Nonblank
    evidence: tuple[ClaimDocumentEvidence, ...] = ()

    @model_validator(mode="after")
    def supported_date(self):
        if self.status == "established" and (self.value is None or not self.evidence):
            raise ValueError("An established event date requires a date and document references")
        if self.status != "established" and self.value is not None:
            raise ValueError("Unknown/conflicting event dates cannot supply a usable date")
        return self


class AppealTimingAssessment(FrozenModel):
    request: AppealEvidenceRequest | None = None
    denial_notice: DocumentedAppealDate | None = None
    appeal_received: DocumentedAppealDate | None = None


class AppealSubmission(FrozenModel):
    """Envelope for an appeal; current service assessments live on request.claim."""

    request: AppealEvidenceRequest
    timing_assessment: AppealTimingAssessment | None = None
    evidence_assessment: AppealEvidenceAssessment | None = None

    @model_validator(mode="before")
    @classmethod
    def expand_appeal_requests(cls, data):
        if isinstance(data, dict):
            req = data.get("request")
            if req is not None:
                for k in ("timing_assessment", "evidence_assessment"):
                    val = data.get(k)
                    if isinstance(val, dict) and "request" not in val:
                        val = dict(val)
                        val["request"] = req
                        data[k] = val
        return data


def resolve_appeal_origin(
    request: AppealEvidenceRequest, store: ReviewStore, policy_index: PolicyIndex,
) -> tuple[RuleResult, Literal["pre_authorization", "payment"] | None]:
    """Verify the stored denial chain before any appeal or service adjudication."""
    request = AppealEvidenceRequest.model_validate(request.model_dump())
    quotes, facts, unresolved = _appeal_context(request, policy_index, "appeal_link")

    def result(workflow=None):
        return RuleResult(
            outcome="unresolved" if unresolved else "satisfied",
            proposed_action="route_to_senior_reviewer" if unresolved else None,
            reason="Stored appeal link requires review." if unresolved else "Stored denial and original service workflow verified.",
            rule_id="appeal_link", policy_evidence=tuple(quotes), claim_evidence=tuple(facts),
            unresolved_information=tuple(unresolved),
        ), workflow

    if unresolved:
        return result()
    try:
        if store.get(request.claim.review_id) is not None:
            unresolved.append("review_id_already_stored")
            return result()
        prior = store.get(request.prior_review.claim.review_id)
        if prior is None or prior != request.prior_review:
            unresolved.append("stored_prior_denial")
            return result()
        visited = set()
        while prior.previous_review_id is not None:
            if prior.claim.review_id in visited:
                unresolved.append("appeal_lineage_cycle")
                return result()
            visited.add(prior.claim.review_id)
            parent = store.get(prior.previous_review_id)
            if (parent is None or prior.claim.claim_type != "appeal" or parent.decision.action != "deny_claim"
                    or any(getattr(parent.claim, f) != getattr(request.claim, f)
                           for f in ("claim_id", "member_id", "insurer", "plan_name"))
                    or parent.decision.context.policy_id != policy_index.policy_id
                    or parent.decision.context.source_sha256 != policy_index.source_sha256):
                unresolved.append("appeal_lineage_link")
                return result()
            prior = parent
        if prior.claim.claim_type not in {"pre_authorization", "payment"}:
            unresolved.append("appeal_lineage_root")
            return result()
        facts.extend((f"original_review_id={prior.claim.review_id}", f"reassessment_workflow={prior.claim.claim_type}"))
        return result(prior.claim.claim_type)
    except ReviewStoreError:
        unresolved.append("review_storage")
        return result()


def evaluate_appeal_duplicates(
    request: AppealEvidenceRequest, store: ReviewStore, policy_index: PolicyIndex,
) -> RuleResult:
    """Exclude only stored, verified appeal lineage; check every other submission.

    Supplied history remains a trusted input; a local database is not assumed to
    contain an insurer's complete claim history. The current history must be known.
    Known snapshots recorded with earlier lineage reviews are also retained, so
    the external duplicate behind an original denial cannot silently disappear.
    No records are written and no appeal is finally adjudicated by this gate.
    """
    request = AppealEvidenceRequest.model_validate(request.model_dump())
    claim = request.claim
    quotes, facts, unresolved = _appeal_context(request, policy_index, "appeal_duplicates")
    assumption = "User-approved appeal workflow: exclude only the SQLite-verified original submission and linked appeal reviews from duplicate comparison; retain other submissions."

    def blocked(reason, field):
        return RuleResult("unresolved", "route_to_senior_reviewer", reason,
            policy_evidence=tuple(quotes), claim_evidence=tuple(facts), rule_id="duplicate_claim",
            unresolved_information=tuple(dict.fromkeys([*unresolved, field])), rule_source=assumption)

    if unresolved:
        return blocked("Appeal context must be verified before excluding any history.", "appeal_lineage")
    try:
        records = store.history(insurer=claim.insurer, plan_name=claim.plan_name, member_id=claim.member_id)
        if store.get(claim.review_id) is not None:
            return blocked("This review ID is already stored; a new attempt requires a new ID.", "review_id_already_stored")
    except ReviewStoreError:
        return blocked("Stored history could not be loaded safely.", "review_storage")
    by_id = {r.claim.review_id: r for r in records}
    selected = by_id.get(request.prior_review.claim.review_id)
    if selected is None or selected != request.prior_review:
        return blocked("The supplied prior denial does not match its stored snapshot.", "stored_prior_denial")

    def verified_edge(child, parent):
        return (child.claim.claim_type == "appeal" and parent.decision.action == "deny_claim"
                and child.claim.claim_id == parent.claim.claim_id == claim.claim_id
                and child.decision.context.policy_id == parent.decision.context.policy_id == policy_index.policy_id
                and child.decision.context.source_sha256 == parent.decision.context.source_sha256 == policy_index.source_sha256)

    # Find the original submission. Links from ordinary re-reviews are not appeals.
    ancestor_ids = set()
    root = selected
    while root.previous_review_id is not None:
        if root.claim.review_id in ancestor_ids:
            return blocked("Stored appeal lineage contains a cycle.", "appeal_lineage_cycle")
        ancestor_ids.add(root.claim.review_id)
        parent = by_id.get(root.previous_review_id)
        if parent is None or not verified_edge(root, parent):
            return blocked("A prior-review link is not a verified appeal of a denial.", "appeal_lineage_link")
        root = parent
    if root.claim.claim_type not in {"pre_authorization", "payment"}:
        return blocked("The appeal lineage does not identify an original service submission.", "appeal_lineage_root")
    excluded = {root.claim.review_id}
    # Include only connected, verified appeal attempts, never all rows sharing a claim ID.
    while True:
        linked = {r.claim.review_id for r in records if r.previous_review_id in excluded
                  and verified_edge(r, by_id[r.previous_review_id])}
        if linked <= excluded:
            break
        excluded.update(linked)
    for review_id in sorted(excluded):
        record = by_id[review_id]
        facts.append(f"lineage_excluded_review_id={review_id};claim_id={record.claim.claim_id};parent_review_id={record.previous_review_id}")
    if claim.prior_claims is None:
        return blocked("Supplied prior-claim history is unknown; the local store cannot prove completeness.", "prior_claim_history")

    snapshots = {}

    def merge(snapshot):
        if snapshot.review_id is None or snapshot.review_id == claim.review_id:
            return False
        existing = snapshots.get(snapshot.review_id)
        if existing is not None and existing != snapshot:
            return False
        snapshots[snapshot.review_id] = snapshot
        return True

    for record in records:
        snapshot = record.claim.duplicate_snapshot().model_copy(update={"claim_id": record.claim.claim_id})
        if not merge(snapshot):
            return blocked("Stored history has ambiguous submission identities.", "duplicate_history_identity")
    historical = [p for r in records if r.claim.review_id in excluded for p in r.claim.prior_claims or ()]
    for snapshot in (*claim.prior_claims, *historical):
        if not merge(snapshot):
            return blocked("Supplied and stored duplicate history disagree or lack review IDs.", "duplicate_history_conflict")
    remaining = tuple(p for review_id, p in snapshots.items() if review_id not in excluded)
    correction_review = None
    if claim.corrects_claim_id is not None:
        originals = [p for p in remaining if p.claim_id == claim.corrects_claim_id]
        if len(originals) != 1:
            return blocked("A correction must identify one retained submission unambiguously.", "correction_reference")
        correction_review = originals[0].review_id
    facts.extend(f"compared_claim_id={p.claim_id};review_id={p.review_id}" for p in remaining)
    result = evaluate_duplicate_claim(
        claim.duplicate_snapshot(), tuple(p.model_copy(update={"claim_id": p.review_id}) for p in remaining),
        policy_index, insurer=claim.insurer, plan_name=claim.plan_name,
        correction_declared=claim.correction_declared, corrects_claim_id=correction_review,
    )
    return replace(result, policy_evidence=tuple(dict.fromkeys([*quotes, *result.policy_evidence])),
                   claim_evidence=tuple(facts) + result.claim_evidence, rule_source=assumption)


def _appeal_context(request: AppealEvidenceRequest, policy_index: PolicyIndex, rule_id: str):
    """Shared policy and lineage validation for each independently callable gate."""
    claim, prior = request.claim, request.prior_review
    bundle = retrieve_evidence(policy_index, insurer=claim.insurer, plan_name=claim.plan_name,
                               requirements=(APPEAL_REQUIREMENT,))
    chunks = sorted(bundle.requirements[0].chunks, key=lambda c: (c.source_page, c.chunk_id))
    text = " ".join(c.text for c in chunks).replace("\uf0b7", " ").replace("•", " ")
    policy_quotes, unresolved = [], []
    facts = [f"claim_id={claim.claim_id}", f"review_id={claim.review_id}",
             f"prior_review_id={prior.claim.review_id}", f"prior_action={prior.decision.action}",
             f"prior_reason={prior.decision.context.reason}"]
    if len({c.section for c in chunks}) != 1 or _normalize_provision(text) != _normalize_provision(SUPPORTED_APPEAL_PROVISION):
        unresolved.append(f"policy.{rule_id}")
    else:
        policy_quotes = [PolicyEvidence.from_chunk(c, c.text) for c in chunks]
    if claim.claim_type != "appeal":
        unresolved.append("appeal_workflow")
    if claim.review_id == prior.claim.review_id:
        unresolved.append("distinct_appeal_review_id")
    if any(getattr(claim, field) != getattr(prior.claim, field)
           for field in ("claim_id", "member_id", "insurer", "plan_name")):
        unresolved.append("prior_review_scope")
    if prior.decision.action != "deny_claim":
        unresolved.append("prior_denial")
    if (prior.decision.context.policy_id != policy_index.policy_id
            or prior.decision.context.source_sha256 != policy_index.source_sha256):
        unresolved.append("prior_policy_revision")
    if request.claim_reference is not None and request.claim_reference != prior.claim.claim_id:
        unresolved.append("claim_reference_mismatch")
    return policy_quotes, facts, unresolved


def evaluate_appeal_documentation(request: AppealEvidenceRequest, policy_index: PolicyIndex) -> RuleResult:
    """Require written appeal and either denial letter or matching claim reference.

    Known absent documents are requested. Unknown inventory/content is unresolved.
    Clinical relevance is assessed separately and is not presumed from presence.
    """
    request = AppealEvidenceRequest.model_validate(request.model_dump())
    policy_quotes, facts, unresolved = _appeal_context(request, policy_index, "appeal_documentation")
    valid_context = not unresolved
    documents = request.claim.documents
    missing, references = [], []

    def presence(document_type):
        if documents is None:
            return "unknown"
        candidates = [d for d in documents if d.document_type == document_type]
        provided = next((d for d in candidates if d.status == "provided" and d.text is not None), None)
        if provided is not None:
            references.append(ClaimDocumentEvidence(document_id=provided.document_id, quote=provided.text))
            return "provided"
        if any(d.status != "missing" for d in candidates):
            return "unknown"
        return "missing"

    written = presence("written_appeal")
    facts.append(f"written_appeal={written}")
    if written == "missing":
        missing.append("written_appeal")
    elif written == "unknown":
        unresolved.append("written_appeal_content")
    if request.claim_reference is None:
        letter = presence("denial_letter")
        facts.append(f"denial_letter={letter}")
        if letter == "missing":
            missing.append("denial_letter_or_claim_reference")
        elif letter == "unknown":
            unresolved.append("denial_letter_or_claim_reference")
    else:
        facts.append(f"claim_reference={request.claim_reference}")

    if not valid_context:
        outcome, action, reason = "unresolved", "route_to_senior_reviewer", "Appeal identity or policy context requires review."
    elif missing:
        outcome, action, reason = "matched", "request_missing_documentation", "Required appeal submission items are missing."
    elif unresolved:
        outcome, action, reason = "unresolved", "route_to_senior_reviewer", "Appeal document inventory or content is unknown."
    else:
        outcome, action, reason = "satisfied", None, "Required appeal submission items are present; timing and relevance checks remain."
    return RuleResult(outcome=outcome, proposed_action=action, reason=reason, rule_id="appeal_documentation",
                      policy_evidence=tuple(policy_quotes), claim_evidence=tuple(facts), clinical_evidence=tuple(references),
                      missing_information=tuple(missing), unresolved_information=tuple(unresolved))


def evaluate_appeal_timeliness(
    request: AppealEvidenceRequest, assessment: AppealTimingAssessment | None, policy_index: PolicyIndex,
) -> RuleResult:
    """Approved MVP convention: 0..180 calendar days from notice to receipt.

    Save timestamps, today's date, and service dates are never substituted.
    Late, reversed, missing, or conflicting dates require senior review, not denial.
    Event-date interpretation is trusted upstream; exact quotations prove linkage.
    """
    request = AppealEvidenceRequest.model_validate(request.model_dump())
    if assessment is not None:
        assessment = AppealTimingAssessment.model_validate(assessment.model_dump())
    policy_quotes, facts, unresolved = _appeal_context(request, policy_index, "appeal_timeliness")
    references, dates = [], {}
    if assessment is None or assessment.request != request:
        unresolved.append("current_appeal_timing_assessment")
    else:
        documents = {d.document_id: d for d in request.claim.documents or ()}
        for name in ("denial_notice", "appeal_received"):
            finding = getattr(assessment, name)
            if finding is None:
                unresolved.append(name)
                continue
            facts.extend((f"{name}.status={finding.status}", f"{name}.source={finding.source}",
                          f"{name}.reason={finding.reason}"))
            valid = True
            for reference in finding.evidence:
                document = documents.get(reference.document_id)
                if document is None or document.status != "provided" or document.text is None or reference.quote not in document.text:
                    valid = False
                    unresolved.append(f"{name}.evidence")
                else:
                    references.append(reference)
            if finding.status != "established":
                unresolved.append(name)
            elif valid:
                dates[name] = finding.value
                facts.append(f"{name}.date={finding.value.isoformat()}")
        if len(dates) == 2:
            elapsed = (dates["appeal_received"] - dates["denial_notice"]).days
            facts.append(f"elapsed_calendar_days={elapsed}")
            if elapsed < 0:
                unresolved.append("appeal_received_before_denial_notice")
            elif elapsed > 180:
                unresolved.append("appeal_outside_180_day_window")
    return RuleResult(
        outcome="unresolved" if unresolved else "satisfied",
        proposed_action="route_to_senior_reviewer" if unresolved else None,
        reason="Appeal timing requires senior review." if unresolved else "Documented appeal receipt falls within the inclusive 180-day window.",
        rule_id="appeal_timeliness", policy_evidence=tuple(policy_quotes), claim_evidence=tuple(facts),
        clinical_evidence=tuple(dict.fromkeys(references)), unresolved_information=tuple(dict.fromkeys(unresolved)),
        rule_source="User-approved MVP convention: calendar days from denial-notice date to appeal-received date; days 0 through 180 inclusive. Outside-window cases route for review.",
    )


def evaluate_appeal_evidence(
    request: AppealEvidenceRequest,
    assessment: AppealEvidenceAssessment | None,
    policy_index: PolicyIndex,
) -> RuleResult:
    """Never automatically uphold a denial for absent new relevant evidence.

    This gate assumes appeal-document completeness is checked separately.
    A satisfied result permits further assessment, not an approval. A trusted
    assessor determines relevance to the stored denial; quotation matching only
    establishes source linkage. No semantic similarity or model is used.
    """
    request = AppealEvidenceRequest.model_validate(request.model_dump())
    if assessment is not None:
        assessment = AppealEvidenceAssessment.model_validate(assessment.model_dump())
    claim, prior = request.claim, request.prior_review
    policy_quotes, facts, unresolved = _appeal_context(request, policy_index, "appeal_evidence")
    references = []

    def result(outcome, reason):
        return RuleResult(
            outcome=outcome, proposed_action=None if outcome == "satisfied" else "route_to_senior_reviewer",
            reason=reason, rule_id="appeal_evidence", policy_evidence=tuple(policy_quotes),
            claim_evidence=tuple(facts), clinical_evidence=tuple(references),
            unresolved_information=tuple(dict.fromkeys(unresolved)),
            rule_source="User-approved Option A: absence of new relevant evidence requires senior review, not automatic denial.",
        )

    if assessment is None or assessment.request != request:
        unresolved.append("current_appeal_evidence_assessment")
        return result("unresolved", "A trusted assessment bound to this appeal and original denial is required.")
    finding = assessment.new_relevant_evidence
    facts.extend((f"new_relevant_evidence={finding.status}", f"assessment.source={finding.source}",
                  f"assessment.reason={finding.reason}"))
    documents = {d.document_id: d for d in claim.documents or ()}
    old_texts = {" ".join(d.text.split()) for d in prior.claim.documents or () if d.text is not None}
    has_new_content = False
    for reference in finding.evidence:
        document = documents.get(reference.document_id)
        if document is None or document.status != "provided" or document.text is None or reference.quote not in document.text:
            unresolved.append("appeal_evidence.references")
        else:
            references.append(reference)
            if " ".join(document.text.split()) not in old_texts:
                has_new_content = True
    if finding.status == "established":
        if prior.claim.documents is None or any(d.status != "missing" and d.text is None for d in prior.claim.documents):
            unresolved.append("prior_document_content")
        if not has_new_content:
            unresolved.append("new_document_content")
    if unresolved:
        return result("unresolved", "Appeal evidence, prior denial, or policy binding requires senior review.")
    if finding.status == "not_established":
        unresolved.append("new_relevant_evidence")
        return result("matched", "New relevant evidence is not established; the policy permits discretion, so senior review is required.")
    if finding.status != "established":
        unresolved.append("new_relevant_evidence")
        return result("unresolved", "Whether the appeal supplies new relevant evidence is unknown or conflicting.")
    return result("satisfied", "Trusted new relevant evidence is supported; appeal eligibility and full reassessment still remain.")
