"""Explicitly synthetic claims for integration tests; no real clinical decisions."""

from pathlib import Path

import pytest

from claims_agent.controller import ReviewController
from claims_agent.schemas import (
    Claim, ClaimDocumentEvidence, ClinicalFinding, CodingAssessment, ExclusionFinding,
    MRIClinicalAssessment, MRIExclusionAssessment, SubmissionDocument, TreatmentHistoryApplicability,
)


@pytest.fixture
def reviewer(tmp_path):
    return ReviewController(Path(__file__).resolve().parents[1] / "policies", tmp_path / "cache")


@pytest.fixture
def claim_factory():
    def build(**changes):
        note = SubmissionDocument(document_id="NOTE", document_type="clinical_note", status="provided",
            text="Synthetic clinician assessment: diagnosis supported; MRI medically necessary. "
                 "Symptomatic diagnostic request, not cosmetic, experimental, or medically unnecessary.")
        history = SubmissionDocument(document_id="HISTORY", document_type="prior_treatment_history", status="provided",
            text="Synthetic treatment history: conservative treatment attempted.")
        claim = Claim(**(dict(claim_id="CLM-1", review_id="REVIEW-1", insurer="HorizonCare",
            plan_name="Silver PPO 2500", member_id="MEMBER-1", claim_type="pre_authorization",
            member_status="active", service_date="2025-03-10", service_location="Synthetic clinic",
            provider_npi="1234567890", procedure_code="MRI-LUMBAR", diagnosis_codes=("M54.5",),
            claimed_amount="1200", documents=(note, history), prior_claims=()) | changes))
        if claim.claim_type != "pre_authorization":
            return claim
        req = claim.documentation_request()
        ref = ClaimDocumentEvidence(document_id=note.document_id, quote=note.text)
        history_ref = ClaimDocumentEvidence(document_id=history.document_id, quote=history.text)
        clinical = ClinicalFinding(status="established", source="synthetic-clinician",
            reason="Synthetic finding for controller testing.", evidence=(ref,))
        excluded = ExclusionFinding(status="ruled_out", source="synthetic-clinician",
            reason="Synthetic negative exclusion finding.", evidence=(ref,))
        defaults = dict(
            coding_assessment=CodingAssessment(request=claim.coding_request(), status="consistent",
                source="synthetic-coding-reviewer", reason="Synthetic coding assessment."),
            treatment_history_applicability=TreatmentHistoryApplicability(request=req, status="required",
                source="synthetic-clinician", reason="Treatment history applicable in this synthetic case."),
            clinical_assessment=MRIClinicalAssessment(request=req, diagnosis_support=clinical, medical_necessity=clinical,
                conservative_treatment_attempted=clinical.model_copy(update={"evidence": (history_ref,)})),
            exclusion_assessment=MRIExclusionAssessment(request=req, screening_without_symptoms=excluded,
                cosmetic_or_reconstructive=excluded, experimental_or_investigational=excluded, medically_unnecessary=excluded),
        )
        return Claim.model_validate(claim.model_dump() | {k: v for k, v in defaults.items() if k not in changes})
    return build


@pytest.fixture
def payment_factory(claim_factory):
    """Bind independently supplied synthetic assessments to a completed service."""
    from claims_agent.schemas import PaymentDetermination, PaymentAuthorizationAssessment, AuthorizationFinding

    def build(payable="900", authorization="prior", **changes):
        original = claim_factory()
        calculation = SubmissionDocument(document_id="CALC", document_type="payment_calculation", status="provided",
            text=f"Synthetic trusted benefit calculation: payable amount {payable} dollars.")
        auth = SubmissionDocument(document_id="AUTH", document_type="authorization", status="provided",
            text="Synthetic authorization reviewer: authorization approved for this completed service.")
        data = original.model_dump() | dict(claim_type="payment", treatment_history_applicability=None,
            clinical_assessment=None, exclusion_assessment=None, documents=original.documents + (calculation, auth))
        claim = Claim.model_validate(data | changes)
        defaults = dict(
            coding_assessment=original.coding_assessment.model_copy(update={"request": claim.coding_request()}),
            clinical_assessment=original.clinical_assessment.model_copy(update={"request": claim.clinical_request()}),
            exclusion_assessment=original.exclusion_assessment.model_copy(update={"request": claim.clinical_request()}),
            payment_determination=PaymentDetermination(request=claim.payment_request(), status="determined",
                payable_amount=payable, source="synthetic-benefits-reviewer", reason="Synthetic calculation.",
                evidence=(ClaimDocumentEvidence(document_id="CALC", quote=calculation.text),)),
            authorization_assessment=PaymentAuthorizationAssessment(request=claim.payment_request(), **{
                authorization: AuthorizationFinding(status="approved", source="synthetic-authorization-reviewer",
                    reason="Synthetic authorization.", evidence=(ClaimDocumentEvidence(document_id="AUTH", quote=auth.text),))}),
        )
        return Claim.model_validate(claim.model_dump() | {k: v for k, v in defaults.items() if k not in changes})
    return build
