"""Coverage and authorization applicability across all categories in the policy.

Clinical/classification findings are explicit trusted assessments. Numeric DME
thresholds and all authorization branching remain deterministic.
"""
from decimal import Decimal

from .services import profile_for
from .rules import RuleResult, SUPPORTED_NECESSITY_PROVISION, _normalize_provision
from .payments import SUPPORTED_AUTHORIZATION
from .schemas import PolicyEvidence
from .retrieval import LexicalRetriever

SUPPORTED_BENEFITS = (
    'This Policy provides coverage for Medically Necessary services that are not otherwise excluded. '
    'Covered Benefits include, but are not limited to: Physician office visits and specialist consultations '
    'Diagnostic imaging (e.g., ultrasound, CT, MRI) Outpatient procedures Emergency services '
    'Prescription drugs (Formulary-based) Coverage is subject to member eligibility, cost-sharing, '
    'Prior Authorization requirements, and all limitations in this Policy.'
)


def provision(index, expected, scope):
    LexicalRetriever(index, **scope)
    sections = {}
    for chunk in sorted(index.chunks, key=lambda c: (c.source_page, c.chunk_id)):
        sections.setdefault(chunk.section, []).append(chunk)
    matches = []
    for chunks in sections.values():
        text = ' '.join(c.text for c in chunks).replace('\uf0b7', ' ').replace('•', ' ')
        if _normalize_provision(text) == _normalize_provision(expected):
            matches.append(tuple(PolicyEvidence.from_chunk(c, c.text) for c in chunks))
    return matches[0] if len(matches) == 1 else ()


def finding_status(claim, name, *, formulary=False):
    assessment = claim.clinical_assessment
    if assessment is None or assessment.request != claim.clinical_request():
        return 'unknown', ()
    finding = getattr(assessment, name)
    if finding is None:
        return 'unknown', ()
    docs = {d.document_id:d for d in claim.documents or ()}
    refs = []
    for ref in finding.evidence:
        doc = docs.get(ref.document_id)
        if (doc is None or doc.status != 'provided' or not doc.text or ref.quote not in doc.text
                or (formulary and doc.document_type != 'formulary')):
            return 'unknown', ()
        refs.append(ref)
    return finding.status, tuple(refs)


def authorization_required(claim):
    """None means unresolved. A generic service name never waives a specific PA rule."""
    profile = profile_for(claim.procedure_code)
    if profile is None:
        return None, ('supported_service',), ()
    key = profile.key
    if key == 'mri':
        return True, (), ()
    if key in {'ct', 'inpatient'}:
        name = 'emergency_service' if key == 'ct' else 'elective_admission'
        status, refs = finding_status(claim, name)
        if status not in {'established', 'not_established'}:
            return None, (name,), refs
        if claim.procedure_code == 'ELECTIVE-INPATIENT' and status != 'established':
            return None, ('elective_admission.contradiction',), refs
        return (status == 'not_established' if key == 'ct' else status == 'established'), (), refs
    if key == 'dme':
        cost = claim.equipment_cost_assessment
        if cost is None or cost.request != claim.clinical_request():
            return None, ('current_equipment_cost_assessment',), ()
        docs = {d.document_id:d for d in claim.documents or ()}
        for ref in cost.evidence:
            doc = docs.get(ref.document_id)
            if doc is None or doc.status != 'provided' or not doc.text or ref.quote not in doc.text:
                return None, ('equipment_cost.evidence',), ()
        return cost.amount > Decimal('500'), (), cost.evidence
    if key == 'drug':
        specialty, refs = finding_status(claim, 'specialty_drug')
        if claim.procedure_code == 'SPECIALTY-DRUG' and specialty != 'established':
            return None, ('specialty_drug.contradiction',), refs
        if specialty == 'not_established':
            return False, (), refs
        if specialty != 'established':
            return None, ('specialty_drug',), refs
        pa, extra = finding_status(claim, 'formulary_pa_required', formulary=True)
        if pa not in {'established', 'not_established'}:
            return None, ('formulary_pa_required',), refs + extra
        return pa == 'established', (), refs + extra
    return False, (), ()


def evaluate_service_clinical(claim, index, **scope):
    profile = profile_for(claim.procedure_code)
    unresolved, refs, quotes, facts = [], [], [], []
    for name, expected in [('benefits', SUPPORTED_BENEFITS), ('medical_necessity', SUPPORTED_NECESSITY_PROVISION),
                           ('authorization', SUPPORTED_AUTHORIZATION)]:
        evidence = provision(index, expected, scope)
        if not evidence:
            unresolved.append('policy.'+name)
        quotes.extend(evidence)
    if profile is None:
        unresolved.append('supported_service')
    else:
        facts.append('service_profile='+profile.key)
        for name in ('diagnosis_support', 'medical_necessity'):
            status, evidence = finding_status(claim, name)
            refs.extend(evidence)
            finding = getattr(claim.clinical_assessment, name) if claim.clinical_assessment else None
            facts.append(f'{name}={status}')
            if finding:
                facts.extend((f'{name}.source={finding.source}', f'{name}.reason={finding.reason}'))
            if status != 'established':
                unresolved.append(name)
        if not claim.diagnosis_codes:
            unresolved.append('diagnosis_codes')
        if profile.key == 'drug':
            status, evidence = finding_status(claim, 'formulary_coverage', formulary=True)
            refs.extend(evidence)
            if status != 'established':
                unresolved.append('formulary_coverage')
        required, unknown, evidence = authorization_required(claim)
        unresolved.extend(unknown)
        refs.extend(evidence)
        facts.append(f'prior_authorization_required={required}')
        for name in profile.topics[2:]:
            finding = getattr(claim.clinical_assessment, name) if claim.clinical_assessment else None
            if finding:
                facts.extend((f'{name}={finding.status}', f'{name}.source={finding.source}', f'{name}.reason={finding.reason}'))
        if profile.key == 'dme' and claim.equipment_cost_assessment:
            facts.append(f'equipment_cost={claim.equipment_cost_assessment.amount};threshold=500;comparison=strictly_greater')
    return RuleResult('unresolved' if unresolved else 'satisfied', None,
        'Service-specific clinical or benefit evidence requires review.' if unresolved else
        'Service-specific clinical and benefit requirements established; remaining gates still apply.',
        policy_evidence=tuple(quotes), clinical_evidence=tuple(dict.fromkeys(refs)),
        claim_evidence=tuple(facts), rule_id='service_clinical_conditions', unresolved_information=tuple(unresolved))
