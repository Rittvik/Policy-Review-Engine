"""Explicit service profiles for the supplied policy; symbolic IDs are not CPT codes."""
from dataclasses import dataclass

MRI_TOPICS = ('diagnosis_support', 'medical_necessity', 'conservative_treatment_attempted',
              'conservative_treatment_contraindicated')
BASIC_TOPICS = ('diagnosis_support', 'medical_necessity')

@dataclass(frozen=True)
class ServiceProfile:
    key: str
    imaging: bool
    topics: tuple[str, ...]

PROFILES = {
    'mri': ServiceProfile('mri', True, MRI_TOPICS),
    'ct': ServiceProfile('ct', True, BASIC_TOPICS + ('emergency_service',)),
    'ultrasound': ServiceProfile('ultrasound', True, BASIC_TOPICS),
    'office': ServiceProfile('office', False, BASIC_TOPICS),
    'specialist': ServiceProfile('specialist', False, BASIC_TOPICS),
    'outpatient': ServiceProfile('outpatient', False, BASIC_TOPICS),
    'emergency': ServiceProfile('emergency', False, BASIC_TOPICS),
    'inpatient': ServiceProfile('inpatient', False, BASIC_TOPICS + ('elective_admission',)),
    'dme': ServiceProfile('dme', False, BASIC_TOPICS),
    'drug': ServiceProfile('drug', False, BASIC_TOPICS + ('formulary_coverage', 'specialty_drug', 'formulary_pa_required')),
}
CODES = {'CT':'ct', 'ULTRASOUND':'ultrasound', 'OFFICE-VISIT':'office',
         'SPECIALIST-CONSULTATION':'specialist', 'OUTPATIENT-PROCEDURE':'outpatient',
         'EMERGENCY-SERVICE':'emergency', 'INPATIENT-ADMISSION':'inpatient',
         'ELECTIVE-INPATIENT':'inpatient', 'DME':'dme', 'PRESCRIPTION-DRUG':'drug',
         'SPECIALTY-DRUG':'drug'}

def profile_for(code):
    if code and (code == 'MRI' or code.startswith('MRI-')):
        return PROFILES['mri']
    if code and code.startswith('CT-'):
        return PROFILES['ct']
    return PROFILES.get(CODES.get(code))

def topics_for(code):
    profile = profile_for(code)
    return profile.topics if profile else ()
