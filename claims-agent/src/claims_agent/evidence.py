"""Shared policy-candidate collection, separate from clinical/coverage assessment.

Lexical topic gates are transparent search heuristics, not insurer business
rules. Finding every topic does not prove completeness or support an approval.
"""

from dataclasses import dataclass
from typing import Literal

from .policy import PolicyIndex
from .requirements import EvidenceRequirement, MRI_REQUIREMENTS
from .retrieval import LexicalRetriever, RetrievalHit, tokenize
from .schemas import PolicyChunk


@dataclass(frozen=True)
class RequirementCandidates:
    requirement: EvidenceRequirement
    status: Literal["candidates_found", "missing_candidates"]
    initial_hits: tuple[RetrievalHit, ...]
    expanded_search: bool
    rejected_section_ids: tuple[str, ...]
    chunks: tuple[PolicyChunk, ...]
    # This module never assesses support, contradiction, or medical necessity.
    assessment: Literal["unresolved"] = "unresolved"


@dataclass(frozen=True)
class EvidenceBundle:
    policy_id: str
    source_sha256: str
    requirements: tuple[RequirementCandidates, ...]
    chunks: tuple[PolicyChunk, ...]

    @property
    def missing_requirements(self) -> tuple[str, ...]:
        return tuple(r.requirement.key for r in self.requirements if r.status == "missing_candidates")


def retrieve_evidence(
    index: PolicyIndex, *, insurer: str, plan_name: str,
    requirements: tuple[EvidenceRequirement, ...], initial_top_k: int = 3
) -> EvidenceBundle:
    """Search an explicit checklist, broaden recall, and retain section fragments.

    Expanding beyond initial top-k happens even if a candidate was already found:
    additional matching sections may contain qualifications or contradictions.
    All retained sections still require assessment before use in a decision.
    """
    if not requirements:
        raise ValueError("An explicit nonempty evidence checklist is required")
    keys = [r.key for r in requirements]
    if any(not key.strip() for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Requirement keys must be nonblank and unique")
    for requirement in requirements:
        if not tokenize(requirement.query):
            raise ValueError(f"Requirement {requirement.key} has no searchable query terms")
        if not requirement.term_groups or any(not group for group in requirement.term_groups):
            raise ValueError(f"Requirement {requirement.key} needs nonempty term groups")
        for group in requirement.term_groups:
            if any(tokenize(term) != (term,) for term in group):
                raise ValueError("Topic gates require single normalized searchable tokens")
    retriever = LexicalRetriever(index, insurer=insurer, plan_name=plan_name)
    sections: dict[str, list[PolicyChunk]] = {}
    for chunk in index.chunks:
        sections.setdefault(chunk.section, []).append(chunk)
    results = []
    for requirement in requirements:
        initial = retriever.search(requirement.query, top_k=initial_top_k)
        expanded = len(index.chunks) > initial_top_k
        hits = retriever.search(requirement.query, top_k=max(1, len(index.chunks))) if expanded else initial
        accepted = []
        rejected = []
        visited = set()
        for hit in hits:
            section = hit.chunk.section
            if section in visited:
                continue
            visited.add(section)
            fragments = sections[section]
            # Body only: a suggestive heading alone cannot pass the topic gate.
            terms = set(tokenize(" ".join(c.text for c in fragments)))
            if all(terms.intersection(group) for group in requirement.term_groups):
                accepted.extend(fragments)
            else:
                rejected.append(section)
        results.append(RequirementCandidates(
            requirement=requirement,
            status="candidates_found" if accepted else "missing_candidates",
            initial_hits=initial, expanded_search=expanded,
            rejected_section_ids=tuple(rejected), chunks=tuple(accepted),
        ))
    unique = {chunk.chunk_id: chunk for result in results for chunk in result.chunks}
    return EvidenceBundle(
        policy_id=index.policy_id, source_sha256=index.source_sha256,
        requirements=tuple(results),
        chunks=tuple(sorted(unique.values(), key=lambda c: (c.source_page, c.chunk_id))),
    )


def retrieve_mri_evidence(
    index: PolicyIndex, *, insurer: str, plan_name: str, initial_top_k: int = 3
) -> EvidenceBundle:
    """Compatibility entry point selecting the explicit MRI checklist."""
    return retrieve_evidence(
        index, insurer=insurer, plan_name=plan_name,
        requirements=MRI_REQUIREMENTS, initial_top_k=initial_top_k,
    )
