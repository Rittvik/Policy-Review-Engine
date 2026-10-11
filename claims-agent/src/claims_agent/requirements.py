"""Explicit lexical evidence checklists; not claim eligibility/coverage rules.

MRI is the only service checklist currently approved and implemented. Future
workflow/service checklists can supply requirements to the shared collector.
"""

from dataclasses import dataclass

@dataclass(frozen=True)
class EvidenceRequirement:
    key: str
    query: str
    # Each group requires at least one exact token; all groups must match.
    term_groups: tuple[tuple[str, ...], ...]


ELIGIBILITY_REQUIREMENT = EvidenceRequirement(
    "eligibility", "member eligibility active inactive date service",
    (("member",), ("active", "inactive"), ("service",)),
)

DUPLICATE_REQUIREMENTS = (
    EvidenceRequirement("duplicate_criteria", "duplicate claims member provider NPI date procedure billed amount",
                        (("duplicate",), ("member",), ("npi",), ("procedure",), ("amount",))),
    EvidenceRequirement("corrected_submission", "duplicate corrected resubmitted",
                        (("duplicate",), ("corrected",), ("resubmitted",))),
)

CODING_REQUIREMENT = EvidenceRequirement(
    "coding_consistency", "coding review diagnosis procedure clinically inconsistent guidelines",
    (("coding",), ("review",), ("diagnosis",), ("procedure",), ("inconsistent",)),
)

DOCUMENTATION_REQUIREMENT = EvidenceRequirement(
    "documentation", "documentation clinical note diagnosis treatment history service location",
    (("clinical",), ("note", "notes"), ("diagnosis",), ("documentation",)),
)

APPEAL_REQUIREMENT = EvidenceRequirement(
    "appeal_evidence", "appeals denial new relevant clinical documentation upheld",
    (("appeals",), ("denial",), ("documentation",), ("relevant",), ("upheld",)),
)


MRI_REQUIREMENTS = (
    ELIGIBILITY_REQUIREMENT,
    EvidenceRequirement("authorization", "MRI services requiring prior authorization",
                        (("mri",), ("prior",), ("authorization",),
                         ("required", "requires", "requiring", "require"))),
    DOCUMENTATION_REQUIREMENT,
    EvidenceRequirement("mri_coverage", "MRI covered diagnosis conservative treatment",
                        (("mri",), ("diagnosis", "diagnoses"), ("conservative",), ("treatment",))),
    EvidenceRequirement("medical_necessity", "medical necessity clinically appropriate standards practice",
                        (("medically", "medical"), ("necessary", "necessity"),
                         ("clinically",), ("appropriate",), ("standards",))),
    EvidenceRequirement("exclusions", "exclusions cosmetic experimental investigational authorization",
                        (("not",), ("cover", "covered"), ("cosmetic", "experimental", "investigational"))),
    EvidenceRequirement("screening_exception", "imaging screening symptoms preventive care",
                        (("imaging",), ("screening",), ("symptoms",), ("preventive",))),
    EvidenceRequirement("retroactive_authorization", "retroactive authorization approval",
                        (("retroactive",), ("authorization",))),
)
