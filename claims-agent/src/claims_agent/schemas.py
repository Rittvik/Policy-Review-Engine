"""Policy evidence, comparison snapshots, and coding assessments; full claim model pending."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator, model_serializer


Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CodingRequest(BaseModel):
    """Exact claim/review and code set to which a coding assessment applies."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    claim_id: Nonblank
    review_id: Nonblank
    procedure_code: Nonblank | None = None
    diagnosis_codes: tuple[Nonblank, ...] = ()


class CodingAssessment(BaseModel):
    """Trusted structured result; source labels alone do not establish trust."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    request: CodingRequest
    status: Literal["consistent", "inconsistent", "unknown"]
    source: Nonblank
    reason: Nonblank
    source_version: Nonblank | None = None


class SubmissionDocument(BaseModel):
    """Document snapshot for comparisons; provenance is not itself a correction."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    document_id: Nonblank
    document_type: Nonblank
    status: Literal["provided", "missing", "unknown"]
    text: Nonblank | None = None
    submitted_in_review: Nonblank | None = None

    @model_validator(mode="after")
    def consistent_status(self):
        if self.text is not None and self.status != "provided":
            raise ValueError("Document content requires provided status")
        return self


class DuplicateClaimSnapshot(BaseModel):
    """Inputs to the duplicate rule, not the full claim/appeal schema.

    None means a value/history component is unavailable; empty tuples explicitly
    report no diagnoses/documents. Caller supplies history scoped to this policy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    claim_id: Nonblank
    review_id: Nonblank | None = None
    member_id: Nonblank | None = None
    provider_npi: Nonblank | None = None
    service_date: date | None = None
    procedure_code: Nonblank | None = None
    billed_amount: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    diagnosis_codes: tuple[Nonblank, ...] | None = None
    procedure_description: Nonblank | None = None
    documents: tuple[SubmissionDocument, ...] | None = None

    @model_validator(mode="after")
    def unique_document_ids(self):
        if self.documents is not None:
            ids = [doc.document_id for doc in self.documents]
            if len(ids) != len(set(ids)):
                raise ValueError("Document IDs must be unique within a submission")
        return self


class PreAuthorizationDocumentationRequest(BaseModel):
    """Completeness-check input, not a coverage or medical-necessity assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    claim_id: Nonblank
    review_id: Nonblank
    claim_type: Literal["pre_authorization"] = "pre_authorization"
    procedure_code: Nonblank | None = None
    diagnosis_codes: tuple[Nonblank, ...] = ()
    expected_service_date: date | None = None
    service_location: Nonblank | None = None
    # None: inventory unavailable; (): explicitly no submitted documents.
    documents: tuple[SubmissionDocument, ...] | None = None

    @model_validator(mode="after")
    def unique_document_ids(self):
        ids = [d.document_id for d in self.documents or ()]
        if len(ids) != len(set(ids)):
            raise ValueError("Document IDs must be unique within a submission")
        return self


class PaymentClinicalRequest(BaseModel):
    """Completed-service facts; never disguised as a pre-authorization request."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    claim_id: Nonblank
    review_id: Nonblank
    claim_type: Literal["payment"] = "payment"
    procedure_code: Nonblank | None = None
    diagnosis_codes: tuple[Nonblank, ...] = ()
    service_date: date | None = None
    service_location: Nonblank | None = None
    documents: tuple[SubmissionDocument, ...] | None = None

    @model_validator(mode="after")
    def unique_documents(self):
        ids = [doc.document_id for doc in self.documents or ()]
        if len(ids) != len(set(ids)):
            raise ValueError("Document IDs must be unique")
        return self


ClinicalReviewRequest = Annotated[
    PreAuthorizationDocumentationRequest | PaymentClinicalRequest, Field(discriminator="claim_type")
]
CLINICAL_REQUEST_ADAPTER = TypeAdapter(ClinicalReviewRequest)


class TreatmentHistoryApplicability(BaseModel):
    """Trusted applicability declaration, bound to the reviewed submission."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    request: PreAuthorizationDocumentationRequest
    status: Literal["required", "not_required", "unknown"]
    source: Nonblank
    reason: Nonblank


class ClaimDocumentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    document_id: Nonblank
    quote: Nonblank


class ClinicalFinding(BaseModel):
    """Trusted clinical finding; quoted text is checked for provenance, not meaning."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    status: Literal["established", "not_established", "unknown", "conflicting"]
    source: Nonblank
    reason: Nonblank
    evidence: tuple[ClaimDocumentEvidence, ...] = ()

    @model_validator(mode="after")
    def determinate_findings_need_evidence(self):
        if self.status in {"established", "not_established"} and not self.evidence:
            raise ValueError("Determinate clinical findings require supporting document references")
        return self


class MRIClinicalAssessment(BaseModel):
    """Findings bound to this exact pre-authorization submission."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    request: ClinicalReviewRequest
    diagnosis_support: ClinicalFinding | None = None
    medical_necessity: ClinicalFinding | None = None
    conservative_treatment_attempted: ClinicalFinding | None = None
    conservative_treatment_contraindicated: ClinicalFinding | None = None


    emergency_service: ClinicalFinding | None = None
    elective_admission: ClinicalFinding | None = None
    specialty_drug: ClinicalFinding | None = None
    formulary_coverage: ClinicalFinding | None = None
    formulary_pa_required: ClinicalFinding | None = None

    @model_serializer(mode="wrap")
    def compatible_snapshot(self, handler):
        data = handler(self)
        for field in ("emergency_service", "elective_admission", "specialty_drug",
                      "formulary_coverage", "formulary_pa_required"):
            if data.get(field) is None:
                data.pop(field, None)
        return data


# Backwards-compatible name; now used by every supported service profile.
ClinicalAssessment = MRIClinicalAssessment


class EquipmentCostAssessment(BaseModel):
    """Trusted DME service cost, distinct from the bill or payable amount."""
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    request: ClinicalReviewRequest
    amount: Decimal = Field(ge=0, allow_inf_nan=False)
    source: Nonblank
    reason: Nonblank
    evidence: tuple[ClaimDocumentEvidence, ...] = Field(min_length=1)


class PolicyChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    policy_id: str
    source_file: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    section: str
    heading: str
    source_page: int = Field(ge=1)
    text: str = Field(min_length=1)


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    policy_id: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    section: str
    heading: str
    source_page: int = Field(ge=1)
    quote: str = Field(min_length=1)

    @classmethod
    def from_chunk(cls, chunk: PolicyChunk, quote: str) -> "PolicyEvidence":
        if not quote.strip() or quote not in chunk.text:
            raise ValueError("Evidence quote must be an exact, nonblank chunk excerpt")
        return cls(**chunk.model_dump(exclude={"text", "source_file"}), quote=quote)

    def validate_against(self, chunk: PolicyChunk) -> None:
        if self != self.from_chunk(chunk, self.quote):
            raise ValueError("Evidence metadata does not match its source chunk")


class ExclusionFinding(BaseModel):
    """Ruled out is an affirmative assessment, not missing evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    status: Literal["established", "ruled_out", "unknown", "conflicting"]
    source: Nonblank
    reason: Nonblank
    evidence: tuple[ClaimDocumentEvidence, ...] = ()

    @model_validator(mode="after")
    def determinate_findings_need_evidence(self):
        if self.status in {"established", "ruled_out"} and not self.evidence:
            raise ValueError("Establishing or ruling out an exclusion requires document evidence")
        return self


class PreventiveCoverageFinding(BaseModel):
    """Trusted policy assessment with policy, rather than clinical, references."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    status: Literal["established", "ruled_out", "unknown", "conflicting"]
    source: Nonblank
    reason: Nonblank
    evidence: tuple[PolicyEvidence, ...] = ()

    @model_validator(mode="after")
    def determinate_findings_need_policy_evidence(self):
        if self.status in {"established", "ruled_out"} and not self.evidence:
            raise ValueError("Preventive coverage findings require explicit policy evidence")
        return self


class MRIExclusionAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    request: ClinicalReviewRequest
    screening_without_symptoms: ExclusionFinding | None = None
    cosmetic_or_reconstructive: ExclusionFinding | None = None
    required_by_trauma_or_congenital_anomaly: ExclusionFinding | None = None
    experimental_or_investigational: ExclusionFinding | None = None
    medically_unnecessary: ExclusionFinding | None = None
    preventive_coverage: PreventiveCoverageFinding | None = None


class PaymentRequest(BaseModel):
    """Amount-determination scope; does not establish coverage or authorization."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    claim_id: Nonblank
    review_id: Nonblank
    claim_type: Literal["payment"] = "payment"
    insurer: Nonblank
    plan_name: Nonblank
    member_id: Nonblank
    provider_npi: Nonblank | None = None
    service_date: date | None = None
    procedure_code: Nonblank | None = None
    diagnosis_codes: tuple[Nonblank, ...] = ()
    claimed_amount: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    documents: tuple[SubmissionDocument, ...] | None = None

    @model_validator(mode="after")
    def unique_documents(self):
        ids = [doc.document_id for doc in self.documents or ()]
        if len(ids) != len(set(ids)):
            raise ValueError("Payment document IDs must be unique")
        return self


class PaymentDetermination(BaseModel):
    """Trusted upstream benefit calculation; never inferred from billed amount."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    request: PaymentRequest
    status: Literal["determined", "unknown", "conflicting"]
    payable_amount: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: Nonblank
    reason: Nonblank
    evidence: tuple[ClaimDocumentEvidence, ...] = ()

    @model_validator(mode="after")
    def supported_amount(self):
        if self.status == "determined" and (self.payable_amount is None or not self.evidence):
            raise ValueError("Determined payments require an amount and supporting references")
        if self.status != "determined" and self.payable_amount is not None:
            raise ValueError("Unresolved determinations must not supply a usable payment amount")
        return self


class AuthorizationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    status: Literal["approved", "not_obtained", "unknown", "conflicting"]
    source: Nonblank
    reason: Nonblank
    evidence: tuple[ClaimDocumentEvidence, ...] = ()

    @model_validator(mode="after")
    def established_status_needs_evidence(self):
        if self.status in {"approved", "not_obtained"} and not self.evidence:
            raise ValueError("Established authorization status requires references")
        return self


class PaymentAuthorizationAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    request: PaymentRequest
    prior: AuthorizationFinding | None = None
    retroactive: AuthorizationFinding | None = None


class Claim(BaseModel):
    """Unified input; assessments retain their exact immutable review binding."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    claim_id: Nonblank
    review_id: Nonblank
    insurer: Nonblank
    plan_name: Nonblank
    member_id: Nonblank
    claim_type: Literal["pre_authorization", "payment", "appeal"]
    member_status: Literal["active", "inactive"] | None = None
    service_date: date | None = None
    service_location: Nonblank | None = None
    provider_npi: Nonblank | None = None
    procedure_code: Nonblank | None = None
    procedure_description: Nonblank | None = None
    diagnosis_codes: tuple[Nonblank, ...] = ()
    claimed_amount: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    documents: tuple[SubmissionDocument, ...] | None = None
    notes: str = ""
    prior_authorization_approved: bool | None = Field(default=None, strict=True)
    prior_claims: tuple[DuplicateClaimSnapshot, ...] | None = None
    correction_declared: bool = Field(default=False, strict=True)
    corrects_claim_id: Nonblank | None = None
    coding_assessment: CodingAssessment | None = None
    treatment_history_applicability: TreatmentHistoryApplicability | None = None
    clinical_assessment: MRIClinicalAssessment | None = None
    exclusion_assessment: MRIExclusionAssessment | None = None
    payment_determination: PaymentDetermination | None = None
    authorization_assessment: PaymentAuthorizationAssessment | None = None
    equipment_cost_assessment: EquipmentCostAssessment | None = None

    @model_serializer(mode="wrap")
    def compatible_snapshot(self, handler):
        data = handler(self)
        if data.get("equipment_cost_assessment") is None:
            data.pop("equipment_cost_assessment", None)
        return data

    @model_validator(mode="after")

    def unique_documents(self):
        ids = [d.document_id for d in self.documents or ()]
        if len(ids) != len(set(ids)):
            raise ValueError("Document IDs must be unique within a review")
        return self

    def coding_request(self) -> CodingRequest:
        return CodingRequest(claim_id=self.claim_id, review_id=self.review_id,
                             procedure_code=self.procedure_code, diagnosis_codes=self.diagnosis_codes)

    def payment_request(self) -> PaymentRequest:
        if self.claim_type != "payment":
            raise ValueError("Payment snapshot requested for another workflow")
        return PaymentRequest(
            claim_id=self.claim_id, review_id=self.review_id, insurer=self.insurer, plan_name=self.plan_name,
            member_id=self.member_id, provider_npi=self.provider_npi, service_date=self.service_date,
            procedure_code=self.procedure_code, diagnosis_codes=self.diagnosis_codes,
            claimed_amount=self.claimed_amount, documents=self.documents,
        )

    def clinical_request(self) -> ClinicalReviewRequest:
        if self.claim_type == "pre_authorization":
            return self.documentation_request()
        if self.claim_type != "payment":
            raise ValueError("Clinical workflow is not implemented for appeals")
        return PaymentClinicalRequest(
            claim_id=self.claim_id, review_id=self.review_id, procedure_code=self.procedure_code,
            diagnosis_codes=self.diagnosis_codes, service_date=self.service_date,
            service_location=self.service_location, documents=self.documents,
        )

    def documentation_request(self) -> PreAuthorizationDocumentationRequest:
        if self.claim_type != "pre_authorization":
            raise ValueError("Pre-authorization snapshot requested for another workflow")
        return PreAuthorizationDocumentationRequest(
            claim_id=self.claim_id, review_id=self.review_id, procedure_code=self.procedure_code,
            diagnosis_codes=self.diagnosis_codes, expected_service_date=self.service_date,
            service_location=self.service_location, documents=self.documents,
        )

    def duplicate_snapshot(self) -> DuplicateClaimSnapshot:
        return DuplicateClaimSnapshot(
            claim_id=self.review_id, review_id=self.review_id, member_id=self.member_id,
            provider_npi=self.provider_npi, service_date=self.service_date,
            procedure_code=self.procedure_code, billed_amount=self.claimed_amount,
            diagnosis_codes=self.diagnosis_codes, procedure_description=self.procedure_description,
            documents=self.documents,
        )
