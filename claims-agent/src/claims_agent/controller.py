"""Lumbar MRI service reviews and persisted appeals with validated action stubs."""

from dataclasses import fields, replace
from pathlib import Path

from pydantic import ValidationError

from .actions import dispatch_action, route_to_senior_reviewer
from .appeals import (
    AppealSubmission, evaluate_appeal_documentation, evaluate_appeal_timeliness,
    evaluate_appeal_evidence, evaluate_appeal_duplicates, resolve_appeal_origin,
)
from .decisions import ActionContext, Decision, InputIssue, InputValidationFailure, TraceEntry
from .exclusions import evaluate_mri_exclusions
from .policy import PolicyError, PolicyIndex, ingest_policy, resolve_policy
from .retrieval import LexicalRetriever
from .rules import (
    RuleResult, evaluate_coding_consistency, evaluate_duplicate_claim,
    evaluate_high_value_claim, evaluate_inactive_plan, evaluate_mri_clinical_conditions,
    evaluate_pre_authorization_documentation,
)
from .schemas import Claim
from .services import profile_for
from .service_rules import evaluate_service_clinical
from .payments import evaluate_payment_documentation, evaluate_payment_authorization, evaluate_payment_determination
from .reviews import ReviewStore, ReviewStoreError


APPROVAL_SEQUENCE = (
    ("policy_resolution", "satisfied"), ("inactive_plan", "not_applicable"),
    ("duplicate_claim", "not_applicable"), ("coding_consistency", "not_applicable"),
    ("pre_authorization_documentation", "not_applicable"), ("high_value_claim", "not_applicable"),
    ("mri_clinical_conditions", "satisfied"), ("mri_exclusions", "not_applicable"),
)
PAYMENT_APPROVAL_SEQUENCE = tuple(
    ("payment_documentation" if rule == "pre_authorization_documentation" else rule, outcome)
    for rule, outcome in APPROVAL_SEQUENCE
) + (("payment_authorization", "satisfied"), ("payment_amount", "satisfied"))
APPEAL_GATES = (
    ("appeal_link", "satisfied"), ("appeal_documentation", "satisfied"),
    ("appeal_timeliness", "satisfied"), ("appeal_evidence", "satisfied"),
)


def _input_failure(exc: ValidationError) -> InputValidationFailure:
    return InputValidationFailure(issues=tuple(InputIssue(
        location=tuple(error["loc"]), message=error["msg"], code=error["type"],
    ) for error in exc.errors(include_input=False, include_url=False)))


def _trace(result: RuleResult) -> TraceEntry:
    return TraceEntry(**{field.name: getattr(result, field.name) for field in fields(result)})


def _duplicate_check(claim: Claim, index: PolicyIndex, store: ReviewStore | None = None, *, assessment_source_review_id: str | None = None) -> RuleResult:
    mapping = [f"claim_id={claim.claim_id};review_id={claim.review_id}"]
    history = None
    correction_review = None
    all_priors = []

    if store is not None:
        try:
            records = store.history(insurer=claim.insurer, plan_name=claim.plan_name, member_id=claim.member_id)
            stored_records = [r for r in records if r.claim.review_id not in {claim.review_id, assessment_source_review_id}]

            # Always check every saved claim. A caller's subset must not hide a duplicate.
            seen_claims = set()
            for r in stored_records:
                if r.claim.claim_id not in seen_claims:
                    seen_claims.add(r.claim.claim_id)
                    all_priors.append(r.claim.duplicate_snapshot().model_copy(update={
                        "claim_id": r.claim.claim_id, "review_id": r.claim.review_id,
                    }))
        except Exception:
            return RuleResult("unresolved", None, "Saved claim history could not be verified.",
                              claim_evidence=tuple(mapping), rule_id="duplicate_claim")

    if not all_priors and claim.prior_claims is not None:
        all_priors = list(claim.prior_claims)

    if all_priors:
        if any(prior.review_id is None for prior in all_priors):
            return RuleResult("unresolved", None, "Prior submissions need explicit review IDs for duplicate comparison.",
                              claim_evidence=tuple(mapping), rule_id="duplicate_claim")
        if claim.corrects_claim_id is not None:
            originals = [p for p in all_priors if p.claim_id == claim.corrects_claim_id or p.review_id == claim.corrects_claim_id]
            if len(originals) != 1:
                return RuleResult("unresolved", None, "Correction reference does not identify one prior review unambiguously.",
                                  claim_evidence=tuple(mapping), rule_id="duplicate_claim")
            correction_review = originals[0].review_id
        history = tuple(p.model_copy(update={"claim_id": p.review_id}) for p in all_priors)
        mapping.extend(f"prior_claim_id={p.claim_id};prior_review_id={p.review_id}" for p in all_priors)
    elif claim.prior_claims is not None or store is not None:
        history = ()

    result = evaluate_duplicate_claim(
        claim.duplicate_snapshot(), history, index, insurer=claim.insurer, plan_name=claim.plan_name,
        correction_declared=claim.correction_declared,
        corrects_claim_id=correction_review if claim.corrects_claim_id is not None else None,
    )
    dup_extra = []
    if result.outcome == "matched":
        for fact in result.claim_evidence:
            if fact.startswith("duplicate_of="):
                dup_target = fact.split("=", 1)[1]
                for p in all_priors:
                    if p.review_id == dup_target or p.claim_id == dup_target:
                        dup_extra.append(f"duplicate_of_claim_id={p.claim_id}")
                        if p.review_id:
                            dup_extra.append(f"duplicate_of_review_id={p.review_id}")
                        break
    return replace(result, claim_evidence=tuple(mapping) + tuple(
        fact.replace("claim_id=", "duplicate_submission_id=", 1) if fact.startswith("claim_id=") else fact
        for fact in result.claim_evidence
    ) + tuple(dup_extra))


class ReviewController:
    def __init__(self, policy_dir: Path, cache_dir: Path):
        self.policy_dir = policy_dir
        self.cache_dir = cache_dir

    def review(self, payload: Claim | dict, store: ReviewStore | None = None) -> Decision | InputValidationFailure:
        return self._review(payload, store=store)

    def review_confirmed_assessment(self, claim: Claim, source: Claim, store: ReviewStore):
        """Called only after packet and reviewer validation; retain other saved claims."""
        if (source.clinical_assessment is not None or source.review_id == claim.review_id
                or (source.claim_id, source.member_id, source.insurer, source.plan_name)
                != (claim.claim_id, claim.member_id, claim.insurer, claim.plan_name)):
            raise ValueError("Invalid assessment revision lineage")
        stored = store.get(source.review_id)
        if stored is not None and stored.claim != source:
            raise ValueError("Assessment source does not match saved history")
        return self._review(claim, store=store, assessment_source_review_id=source.review_id)

    def review_appeal(self, payload: AppealSubmission | dict, store: ReviewStore) -> Decision | InputValidationFailure:
        """Run appeal gates, reassess the original workflow, and persist valid lineage.

        Invalid input or unverifiable links are not stored. Once the link passes,
        terminal decisions are saved atomically before being returned. A save
        failure returns an explicitly unsaved senior-review result, never approval.
        """
        try:
            appeal = AppealSubmission.model_validate(payload.model_dump() if isinstance(payload, AppealSubmission) else payload)
        except ValidationError as exc:
            return _input_failure(exc)
        return self._review(appeal.request.claim, appeal=appeal, store=store)

    def _review(self, payload: Claim | dict, *, appeal: AppealSubmission | None = None,
                store: ReviewStore | None = None, assessment_source_review_id: str | None = None) -> Decision | InputValidationFailure:
        try:
            # Reparse snapshots as well, including a caller's model_copy updates.
            claim = Claim.model_validate(payload.model_dump() if isinstance(payload, Claim) else payload)
        except ValidationError as exc:
            return _input_failure(exc)
        trace = []
        index = None
        workflow = claim.claim_type
        link_verified = False

        def approval_sequence(action):
            sequence = PAYMENT_APPROVAL_SEQUENCE if action == "approve_claim_payment" else APPROVAL_SEQUENCE
            profile = profile_for(claim.procedure_code)
            if profile is None or profile.key != 'mri':
                sequence = tuple(({'mri_clinical_conditions':'service_clinical_conditions',
                                  'mri_exclusions':'service_exclusions'}.get(rule, rule), outcome)
                                 for rule, outcome in sequence)
            return sequence[:1] + APPEAL_GATES + sequence[1:] if appeal is not None else sequence

        def finish(action: str, reason: str) -> Decision:
            nonlocal trace
            if action in {"approve_pre_authorization", "approve_claim_payment"} and (
                (action == "approve_pre_authorization" and workflow != "pre_authorization")
                or (action == "approve_claim_payment" and workflow != "payment")
                or tuple((t.rule_id, t.outcome) for t in trace) != approval_sequence(action)
            ):
                trace.append(TraceEntry(rule_id="approval_guard", outcome="unresolved",
                    reason="Approval was proposed before all required checks passed."))
                action, reason = "route_to_senior_reviewer", trace[-1].reason
            # Verify every emitted quote, including trace citations, at the final boundary.
            try:
                policy_chunks = {c.chunk_id: c for c in index.chunks} if index else {}
                documents = {d.document_id: d for d in claim.documents or ()}
                for entry in trace:
                    for evidence in entry.policy_evidence:
                        if index is None or evidence.policy_id != index.policy_id or evidence.source_sha256 != index.source_sha256:
                            raise ValueError("Evidence belongs to another policy or revision")
                        chunk = policy_chunks.get(evidence.chunk_id)
                        if chunk is None:
                            raise ValueError("Evidence chunk is absent from selected policy")
                        evidence.validate_against(chunk)
                    for evidence in entry.clinical_evidence:
                        document = documents.get(evidence.document_id)
                        if document is None or document.status != "provided" or document.text is None or evidence.quote not in document.text:
                            raise ValueError("Claim evidence does not match a supplied document")
            except ValueError as exc:
                # Preserve rule outcomes but do not return unverified source quotations.
                trace = [entry.model_copy(update={"policy_evidence": (), "clinical_evidence": ()}) for entry in trace]
                trace.append(TraceEntry(rule_id="evidence_validation", outcome="unresolved", reason=str(exc)))
                action, reason = "route_to_senior_reviewer", "Final evidence validation failed; manual review is required."
            unresolved, missing = [], []
            for entry in trace:
                unresolved.extend(entry.unresolved_information)
                if entry.outcome == "unresolved" and not entry.unresolved_information:
                    unresolved.append(entry.rule_id)
                missing.extend(entry.missing_information)
            context = ActionContext(
                claim_id=claim.claim_id, review_id=claim.review_id, reason=reason,
                policy_id=index.policy_id if index else None,
                source_sha256=index.source_sha256 if index else None,
                policy_evidence=tuple(dict.fromkeys(e for t in trace for e in t.policy_evidence)),
                clinical_evidence=tuple(dict.fromkeys(e for t in trace for e in t.clinical_evidence)),
                claim_evidence=tuple(dict.fromkeys(e for t in trace for e in t.claim_evidence)),
                missing_information=tuple(dict.fromkeys(missing)),
                unresolved_information=tuple(dict.fromkeys(unresolved)), decision_trace=tuple(trace),
            )
            arguments = {"documents": list(context.missing_information)} if action == "request_missing_documentation" else {}
            if action == "approve_claim_payment":
                arguments = {"payment_in_dollars": float(trace[-1].validated_payment_amount)}
            try:
                decision = dispatch_action(action, context, arguments)
            except ValidationError:
                failure = TraceEntry(rule_id="action_validation", outcome="unresolved",
                                     reason="Proposed action or its arguments failed allow-list/schema validation.")
                context = ActionContext(**(context.model_dump() | {
                    "reason": failure.reason,
                    "unresolved_information": context.unresolved_information + ("action_validation",),
                    "decision_trace": context.decision_trace + (failure,),
                }))
                decision = route_to_senior_reviewer(context)
            if appeal is None:
                return decision
            if not link_verified:
                failure = TraceEntry(rule_id="review_persistence", outcome="unresolved",
                    reason="Appeal was not saved because the policy or stored denial link could not be verified.")
                context = ActionContext(**(decision.context.model_dump() | {
                    "unresolved_information": decision.context.unresolved_information + ("review_not_saved",),
                    "decision_trace": decision.context.decision_trace + (failure,),
                }))
                return route_to_senior_reviewer(context)
            persisted = TraceEntry(rule_id="review_persistence", outcome="satisfied",
                reason="Appeal input and decision saved as a new immutable linked review.")
            context = ActionContext(**(decision.context.model_dump() | {
                "decision_trace": decision.context.decision_trace + (persisted,),
            }))
            decision = dispatch_action(decision.action, context, decision.arguments.model_dump())
            try:
                store.save(claim, decision, previous_review_id=appeal.request.prior_review.claim.review_id,
                           supplemental_input_json=appeal.model_dump_json())
            except (ReviewStoreError, ValidationError) as exc:
                failure = TraceEntry(rule_id="review_persistence", outcome="unresolved",
                    reason="Appeal result was not saved; storage validation or insertion failed.",
                    claim_evidence=(f"storage_error_type={type(exc).__name__}",))
                context = ActionContext(**(context.model_dump() | {
                    "reason": failure.reason,
                    "unresolved_information": context.unresolved_information + ("review_not_saved",),
                    "decision_trace": context.decision_trace[:-1] + (failure,),
                }))
                return route_to_senior_reviewer(context)
            return decision

        try:
            spec = resolve_policy(claim.insurer, claim.plan_name)
            loaded = ingest_policy(spec, self.policy_dir, self.cache_dir).index
            # Reject a mismatched index before any rule can consume it.
            LexicalRetriever(loaded, insurer=claim.insurer, plan_name=claim.plan_name)
            index = loaded
            trace.append(TraceEntry(rule_id="policy_resolution", outcome="satisfied",
                                    reason="Insurer and plan matched to the selected policy revision.",
                                    claim_evidence=(f"insurer={claim.insurer}", f"plan_name={claim.plan_name}")))
        except (PolicyError, OSError) as exc:
            trace.append(TraceEntry(rule_id="policy_resolution", outcome="unresolved", reason=str(exc)))
            return finish("route_to_senior_reviewer", "A valid matching policy could not be loaded.")
        if appeal is not None:
            try:
                link, original_workflow = resolve_appeal_origin(appeal.request, store, index)
                trace.append(_trace(link))
                if link.outcome != "satisfied" or original_workflow is None:
                    return finish("route_to_senior_reviewer", link.reason)
                workflow = original_workflow
                link_verified = True
                gates = (
                    lambda: evaluate_appeal_documentation(appeal.request, index),
                    lambda: evaluate_appeal_timeliness(appeal.request, appeal.timing_assessment, index),
                    lambda: evaluate_appeal_evidence(appeal.request, appeal.evidence_assessment, index),
                )
                for gate in gates:
                    result = gate()
                    trace.append(_trace(result))
                    if result.outcome != "satisfied" or result.unresolved_information or result.missing_information:
                        return finish(result.proposed_action or "route_to_senior_reviewer", result.reason)
            except (PolicyError, OSError, ReviewStoreError) as exc:
                trace.append(TraceEntry(rule_id="appeal_evaluation", outcome="unresolved", reason=str(exc)))
                return finish("route_to_senior_reviewer", "Appeal checks could not be completed safely.")
        elif claim.claim_type == "appeal":
            trace.append(TraceEntry(rule_id="workflow_support", outcome="unresolved",
                                    reason="Appeals require review_appeal with the appeal submission and review store."))
            return finish("route_to_senior_reviewer", trace[-1].reason)
        # Only the service-workflow discriminator changes. Never rebind supplied assessments.
        service_claim = Claim.model_validate(claim.model_dump() | {"claim_type": workflow})
        request = service_claim.clinical_request()
        scope = dict(insurer=claim.insurer, plan_name=claim.plan_name)
        checks = (
            lambda: evaluate_inactive_plan(claim.member_status, index, **scope),
            lambda: (evaluate_appeal_duplicates(appeal.request, store, index) if appeal is not None
                     else _duplicate_check(claim, index, store=store, assessment_source_review_id=assessment_source_review_id)),
            lambda: evaluate_coding_consistency(claim.coding_request(), claim.coding_assessment, index, **scope),
            lambda: (evaluate_payment_documentation(service_claim, index, **scope) if workflow == "payment"
                     else evaluate_pre_authorization_documentation(request, claim.treatment_history_applicability, index, **scope)),
            lambda: evaluate_high_value_claim(claim.claimed_amount),
        )
        try:
            for check in checks:
                result = check()
                trace.append(_trace(result))
                if result.outcome == "matched" and result.proposed_action is not None:
                    return finish(result.proposed_action, result.reason)
            profile = profile_for(claim.procedure_code)
            clinical = (evaluate_mri_clinical_conditions(request, claim.clinical_assessment, index, **scope)
                        if profile and profile.key == 'mri' else evaluate_service_clinical(service_claim, index, **scope))
            exclusions = evaluate_mri_exclusions(request, claim.exclusion_assessment, index, **scope)
            if profile is None or profile.key != 'mri':
                exclusions = replace(exclusions, rule_id='service_exclusions')
            trace.extend((_trace(clinical), _trace(exclusions)))
            ca, ea = claim.clinical_assessment, claim.exclusion_assessment
            if (ca and ea and ca.request == request and ea.request == request and ca.medical_necessity
                    and ea.medically_unnecessary and ca.medical_necessity.status == "established"
                    and ea.medically_unnecessary.status == "established"):
                trace.append(TraceEntry(rule_id="clinical_contradiction", outcome="unresolved",
                                        reason="Clinical assessments disagree on medical necessity."))
                return finish("route_to_senior_reviewer", trace[-1].reason)
            if exclusions.outcome == "matched" and exclusions.proposed_action:
                return finish(exclusions.proposed_action, exclusions.reason)
            if workflow == "payment":
                trace.append(_trace(evaluate_payment_authorization(service_claim, index, **scope)))
                trace.append(_trace(evaluate_payment_determination(service_claim.payment_request(), claim.payment_determination)))
            action = "approve_claim_payment" if workflow == "payment" else "approve_pre_authorization"
            sequence = approval_sequence(action)
            passed = tuple((t.rule_id, t.outcome) for t in trace) == sequence
            if passed and not any(t.unresolved_information or t.missing_information for t in trace):
                return finish(action, "All required workflow checks passed with supporting evidence.")
            return finish("route_to_senior_reviewer", "Required checks remain unresolved; senior review is required.")
        except (PolicyError, OSError) as exc:
            trace.append(TraceEntry(rule_id="policy_evaluation", outcome="unresolved", reason=str(exc)))
            return finish("route_to_senior_reviewer", "Policy evaluation could not be completed safely.")
