"""Frozen audit/output models and the six-action discriminated result schema."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .schemas import ClaimDocumentEvidence, Nonblank, PolicyEvidence


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class TraceEntry(FrozenModel):
    rule_id: Nonblank
    outcome: Literal["matched", "not_applicable", "unresolved", "satisfied"]
    proposed_action: str | None = None
    reason: Nonblank
    policy_evidence: tuple[PolicyEvidence, ...] = ()
    claim_evidence: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    unresolved_information: tuple[str, ...] = ()
    rule_source: str | None = None
    clinical_evidence: tuple[ClaimDocumentEvidence, ...] = ()
    validated_payment_amount: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)


class ActionContext(FrozenModel):
    claim_id: Nonblank
    review_id: Nonblank
    reason: Nonblank
    policy_id: Nonblank | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    policy_evidence: tuple[PolicyEvidence, ...] = ()
    claim_evidence: tuple[str, ...] = ()
    clinical_evidence: tuple[ClaimDocumentEvidence, ...] = ()
    missing_information: tuple[str, ...] = ()
    unresolved_information: tuple[str, ...] = ()
    decision_trace: tuple[TraceEntry, ...]


class EmptyArguments(FrozenModel):
    pass


class PaymentArguments(FrozenModel):
    payment_in_dollars: float = Field(ge=0, allow_inf_nan=False, strict=True)


class DocumentationArguments(FrozenModel):
    documents: tuple[Nonblank, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_items(self):
        if len(set(self.documents)) != len(self.documents):
            raise ValueError("Missing-document requests must not repeat items")
        return self


class ActionResult(FrozenModel):
    context: ActionContext
    mode: Literal["stub"] = "stub"


class ApprovalResult(ActionResult):
    @model_validator(mode="after")
    def no_unresolved_approval(self):
        if (self.context.unresolved_information or self.context.missing_information
                or any(t.outcome == "unresolved" for t in self.context.decision_trace)):
            raise ValueError("Cannot approve with unresolved checks or missing information")
        if not self.context.policy_id or not self.context.source_sha256 or not self.context.policy_evidence:
            raise ValueError("Approval requires policy identity and evidence")
        return self


class PreAuthorizationDecision(ApprovalResult):
    action: Literal["approve_pre_authorization"]
    arguments: EmptyArguments


class PaymentDecision(ApprovalResult):
    action: Literal["approve_claim_payment"]
    arguments: PaymentArguments

    @model_validator(mode="after")
    def amount_matches_validation(self):
        checks = [t for t in self.context.decision_trace if t.rule_id == "payment_amount"]
        if (len(checks) != 1 or checks[0].outcome != "satisfied"
                or checks[0].validated_payment_amount != Decimal(str(self.arguments.payment_in_dollars))):
            raise ValueError("Payment argument must equal the uniquely validated payable amount")
        return self


class DenialDecision(ActionResult):
    action: Literal["deny_claim"]
    arguments: EmptyArguments


class DocumentationDecision(ActionResult):
    action: Literal["request_missing_documentation"]
    arguments: DocumentationArguments

    @model_validator(mode="after")
    def requested_items_match_context(self):
        if self.arguments.documents != self.context.missing_information:
            raise ValueError("Requested items must match the audited missing information")
        return self


class SeniorReviewDecision(ActionResult):
    action: Literal["route_to_senior_reviewer"]
    arguments: EmptyArguments


class CodingReviewDecision(ActionResult):
    action: Literal["route_to_coding_review"]
    arguments: EmptyArguments


Decision = Annotated[
    PreAuthorizationDecision | PaymentDecision | DenialDecision | DocumentationDecision
    | SeniorReviewDecision | CodingReviewDecision,
    Field(discriminator="action"),
]
DECISION_ADAPTER = TypeAdapter(Decision)


class InputIssue(FrozenModel):
    location: tuple[str | int, ...]
    message: str
    code: str


class InputValidationFailure(FrozenModel):
    kind: Literal["validation_error"] = "validation_error"
    issues: tuple[InputIssue, ...]
