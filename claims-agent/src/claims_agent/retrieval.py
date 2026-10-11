"""Deterministic BM25 retrieval over one explicitly selected policy revision."""

from collections import Counter
from dataclasses import dataclass
from math import log
import re

from .policy import PolicyError, PolicyIndex, resolve_policy
from .schemas import PolicyChunk


# No synonyms, semantic expansion, or instructions interpreted from query text.
STOP_WORDS = frozenset("a an and are as at be by for from in is it of on or the to with".split())
TOKEN = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")


def tokenize(text: str) -> tuple[str, ...]:
    """Case-fold words; retain dotted diagnosis codes as single tokens."""
    return tuple(t for t in TOKEN.findall(text.casefold()) if t not in STOP_WORDS)


@dataclass(frozen=True)
class RetrievalHit:
    chunk: PolicyChunk
    score: float
    matched_terms: tuple[str, ...]


class LexicalRetriever:
    """Resolve policy before ranking; reject mixed-policy or mixed-revision data.

    Scores are lexical relevance, not coverage confidence. Callers must evaluate
    evidence sufficiency separately and may need several focused queries.
    """

    def __init__(self, index: PolicyIndex, *, insurer: str, plan_name: str):
        spec = resolve_policy(insurer, plan_name)
        if index.policy_id != spec.policy_id or index.source_file != spec.source_file:
            raise PolicyError("Retrieved index does not match selected policy")
        if any(c.policy_id != index.policy_id or c.source_sha256 != index.source_sha256
               or c.source_file != index.source_file for c in index.chunks):
            raise PolicyError("Index contains foreign policy or revision chunks")
        if len({c.chunk_id for c in index.chunks}) != len(index.chunks):
            raise PolicyError("Index contains duplicate chunk IDs")
        self._chunks = index.chunks
        # Index title twice to modestly favor section-topic matches.
        self._counts = tuple(Counter(tokenize(f"{c.heading} {c.heading} {c.text}"))
                             for c in self._chunks)
        self._lengths = tuple(sum(count.values()) for count in self._counts)
        self._average_length = sum(self._lengths) / len(self._lengths) if self._lengths else 0
        self._document_frequency = Counter(t for counts in self._counts for t in counts)

    def search(self, query: str, *, top_k: int = 3) -> tuple[RetrievalHit, ...]:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        terms = sorted(set(tokenize(query)))
        hits = []
        count = len(self._chunks)
        for chunk, frequencies, length in zip(self._chunks, self._counts, self._lengths):
            matched = tuple(t for t in terms if frequencies[t])
            if not matched:
                continue
            score = 0.0
            for term in matched:
                frequency = frequencies[term]
                df = self._document_frequency[term]
                inverse_frequency = log(1 + (count - df + 0.5) / (df + 0.5))
                normalization = 1.2 * (1 - 0.75 + 0.75 * length / self._average_length)
                score += inverse_frequency * frequency * 2.2 / (frequency + normalization)
            hits.append(RetrievalHit(chunk, score, matched))
        return tuple(sorted(hits, key=lambda h: (-h.score, h.chunk.source_page, h.chunk.chunk_id))[:top_k])
