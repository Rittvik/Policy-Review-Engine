"""Explicit human-reviewed bridge from extraction to a fresh clinical assessment.

Reviewer identities are trusted local labels, not authenticated clinical sign-off.
"""
from hashlib import sha256
import json
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .controller import ReviewController
from .decisions import Decision, FrozenModel, InputValidationFailure
from .llm import (ExtractionResult, ModelPayload, Topic, prepare_extraction,
                  validate_response)
from .policy import PolicyIndex
from .reviews import ReviewStore
from .services import PROFILES, topics_for
from .schemas import Claim, ClaimDocumentEvidence, ClinicalFinding, MRIClinicalAssessment, Nonblank


CarryField = Literal['coding_assessment', 'treatment_history_applicability',
                     'exclusion_assessment', 'payment_determination', 'authorization_assessment', 'equipment_cost_assessment']
CARRY_FIELDS = ('coding_assessment', 'treatment_history_applicability', 'exclusion_assessment',
                'payment_determination', 'authorization_assessment', 'equipment_cost_assessment')


class AssessmentReviewError(ValueError):
    """Invalid, stale or incomplete local assessment review."""


class AssessmentPacket(FrozenModel):
    version: Literal['clinical-review-v1'] = 'clinical-review-v1'
    source_claim: Claim
    source_decision: Decision
    document_ids: tuple[Nonblank, ...]
    payload: ModelPayload
    extraction: ExtractionResult
    packet_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class ReviewedFinding(FrozenModel):
    topic: Topic
    status: Literal['established', 'not_established', 'unknown', 'conflicting']
    reason: Nonblank
    evidence: tuple[ClaimDocumentEvidence, ...] = ()

    @model_validator(mode='after')
    def evidence_required(self):
        if self.status in {'established', 'not_established'} and not self.evidence:
            raise ValueError('Determinate findings require reviewed document evidence')
        if self.status == 'conflicting' and len(set(self.evidence)) < 2:
            raise ValueError('Conflicting findings require two distinct references')
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError('Evidence references must not repeat')
        return self


class ReviewerAssessment(FrozenModel):
    packet_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewer_id: Nonblank
    reviewed_at: AwareDatetime
    new_review_id: Nonblank
    confirmed_sources: bool = Field(strict=True)
    # Each selected assessment is explicitly acknowledged for the unchanged input.
    carry_forward_assessments: tuple[CarryField, ...] = ()
    findings: tuple[ReviewedFinding, ...]

    @model_validator(mode='after')
    def fully_reviewed(self):
        if not self.confirmed_sources:
            raise ValueError('Reviewer must explicitly confirm source review')
        if tuple(f.topic for f in self.findings) not in {p.topics for p in PROFILES.values()}:
            raise ValueError('All service predicates must be explicitly reviewed in order')
        if len(set(self.carry_forward_assessments)) != len(self.carry_forward_assessments):
            raise ValueError('Carry-forward selections must be unique')
        return self


def packet_digest(packet):
    data = packet.model_dump(mode='json', exclude={'packet_sha256'}) if isinstance(packet, AssessmentPacket) else {
        k: v for k, v in packet.items() if k != 'packet_sha256'}
    if isinstance(data, dict) and isinstance(data.get('extraction'), dict):
        data['extraction'].pop('evidence_reliability', None)
    return sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                             allow_nan=False).encode()).hexdigest()


def parse_packet(data):
    # JSON parsing preserves strict nested extraction tuple/date semantics.
    raw = data.model_dump_json() if isinstance(data, AssessmentPacket) else (
        json.dumps(data) if isinstance(data, dict) else data
    )
    parsed_json = json.loads(raw)
    if isinstance(parsed_json, dict) and isinstance(parsed_json.get('extraction'), dict):
        parsed_json['extraction'].pop('evidence_reliability', None)
    return AssessmentPacket.model_validate_json(json.dumps(parsed_json))


def validate_packet(packet, index, reviewer):
    packet = parse_packet(packet)
    digest = packet_digest(packet)
    if digest != packet.packet_sha256:
        raise AssessmentReviewError(f'Review packet was changed (digest {digest[:12]} != expected {packet.packet_sha256[:12]})')
    if packet.source_claim.clinical_assessment is not None:
        raise AssessmentReviewError('An existing clinical assessment must not be overwritten')
    prepared = prepare_extraction(packet.source_claim, index, document_ids=packet.document_ids)
    extraction = packet.extraction
    if (prepared.payload != packet.payload or extraction.status != 'validated_candidates'
            or extraction.candidates is None or extraction.input_sha256 != prepared.input_sha256
            or extraction.request_id != prepared.payload.request_id):
        raise AssessmentReviewError('Extraction does not match the current source snapshot')
    validate_response(extraction.candidates.model_dump_json(), prepared.payload)
    if reviewer.review(packet.source_claim) != packet.source_decision:
        raise AssessmentReviewError('Source decision changed; prepare a fresh packet')
    return packet


def prepare_packet(claim, extraction, document_ids, index, reviewer):
    claim = Claim.model_validate(claim.model_dump() if isinstance(claim, Claim) else claim)
    extraction = ExtractionResult.model_validate_json(
        extraction.model_dump_json() if isinstance(extraction, ExtractionResult) else json.dumps(extraction))
    if extraction.evidence_reliability is not None:
        extraction = extraction.model_copy(update={'evidence_reliability': None})
    prepared = prepare_extraction(claim, index, document_ids=tuple(document_ids))
    decision = reviewer.review(claim)
    if isinstance(decision, InputValidationFailure):
        raise AssessmentReviewError('Invalid source claim')
    data = dict(source_claim=claim, source_decision=decision, document_ids=tuple(document_ids),
                payload=prepared.payload, extraction=extraction, packet_sha256='0'*64)
    provisional = AssessmentPacket(**data)
    packet = provisional.model_copy(update={'packet_sha256':packet_digest(provisional)})
    return validate_packet(packet, index, reviewer)


def review_template(packet):
    """No verdict is inferred from documented, not_found or conflicting statuses."""
    return dict(packet_sha256=packet.packet_sha256, reviewer_id=None, reviewed_at=None,
                new_review_id=None, confirmed_sources=False, carry_forward_assessments=[],
                findings=[dict(topic=f.topic, status='pending', reason='',
                    evidence=[r.model_dump() for r in f.document_refs])
                    for f in packet.extraction.candidates.findings])


def request_for(claim, field):
    if field == 'coding_assessment':
        return claim.coding_request()
    if field == 'treatment_history_applicability':
        return claim.documentation_request()
    if field in {'exclusion_assessment', 'equipment_cost_assessment'}:
        return claim.clinical_request()
    return claim.payment_request()


def reviewed_claim(packet, assessment):
    """Construct a new snapshot only after explicit, per-predicate human choices."""
    source = packet.source_claim
    if tuple(f.topic for f in assessment.findings) != topics_for(source.procedure_code):
        raise AssessmentReviewError("Reviewer predicates do not match the service profile")
    if assessment.packet_sha256 != packet.packet_sha256:
        raise AssessmentReviewError('Reviewer response belongs to another packet')
    if assessment.new_review_id == source.review_id:
        raise AssessmentReviewError('A new review ID is required')
    selected = {d.document_id:d for d in packet.payload.documents}
    for finding in assessment.findings:
        for ref in finding.evidence:
            if ref.document_id not in selected or ref.quote not in selected[ref.document_id].text:
                raise AssessmentReviewError('Reviewer evidence is not in selected source documents')
    data = source.model_dump() | dict(review_id=assessment.new_review_id, clinical_assessment=None)
    # Omitted carry-forward fields become unknown; they are never silently copied.
    data.update({field:None for field in CARRY_FIELDS})
    target = Claim.model_validate(data)
    for field in assessment.carry_forward_assessments:
        earlier = getattr(source, field)
        if earlier is None or earlier.request != request_for(source, field):
            raise AssessmentReviewError('Selected earlier assessment is missing or stale')
        data[field] = earlier.model_copy(update={'request':request_for(target, field)})
    data['clinical_assessment'] = MRIClinicalAssessment(request=target.clinical_request(), **{
        f.topic:ClinicalFinding(status=f.status, source='reviewer:'+assessment.reviewer_id,
            reason=f.reason, evidence=f.evidence) for f in assessment.findings})
    return Claim.model_validate(data)


def apply_review(packet, assessment, index: PolicyIndex, reviewer: ReviewController, store: ReviewStore):
    packet = validate_packet(packet, index, reviewer)
    assessment = ReviewerAssessment.model_validate(
        assessment.model_dump() if isinstance(assessment, ReviewerAssessment) else assessment)
    target = reviewed_claim(packet, assessment)
    if store.get(target.review_id) is not None:
        raise AssessmentReviewError('New review ID already exists')
    earlier = store.get(packet.source_claim.review_id)
    if earlier is not None and (earlier.claim != packet.source_claim or earlier.decision != packet.source_decision):
        raise AssessmentReviewError('Stored source review differs from this packet')
    decision = reviewer.review_confirmed_assessment(target, packet.source_claim, store)
    if isinstance(decision, InputValidationFailure):
        raise AssessmentReviewError('Reviewed claim failed validation')
    if earlier is None:
        store.save(packet.source_claim, packet.source_decision)
    audit = json.dumps(dict(kind='reviewer_confirmed_clinical_assessment', packet=packet.model_dump(mode='json'),
                            reviewer_assessment=assessment.model_dump(mode='json')), ensure_ascii=False)
    # Return a decision only after saving its complete model/reviewer provenance.
    saved = store.save(target, decision, previous_review_id=packet.source_claim.review_id,
                       supplemental_input_json=audit)
    return saved
