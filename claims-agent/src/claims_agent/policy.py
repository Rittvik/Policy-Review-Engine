"""Local, versioned policy ingestion. No retrieval or claim decisions occur here."""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile

import pypdf
from pydantic import BaseModel, ConfigDict, ValidationError

from .schemas import PolicyChunk


FORMAT_VERSION = 2
NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)(?:\.)?\s+(.+)$")


@dataclass(frozen=True)
class TextLine:
    text: str
    font_size: float | None = None
    bold: bool = False
    margin: bool = False


def _normalize(text: str) -> str:
    return " ".join(text.split())


def extract_pages(reader: pypdf.PdfReader) -> list[list[TextLine]]:
    """Attach visitor typography to extracted lines; unknown styles stay unknown."""
    pages = []
    for page in reader.pages:
        styles: dict[str, list[TextLine]] = {}

        def visitor(text, cm, tm, font, size):
            # Map the text origin through the current transformation matrix.
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            bottom, top = float(page.mediabox.bottom), float(page.mediabox.top)
            margin = y < bottom + 54 or y > top - 36
            name = str(font.get("/BaseFont", "")) if font else ""
            for raw in text.splitlines():
                normalized = _normalize(raw)
                if normalized:
                    styles.setdefault(normalized, []).append(TextLine(
                        normalized, float(size) if font else None,
                        any(weight in name.casefold() for weight in ("bold", "black", "demi")),
                        margin,
                    ))

        text = page.extract_text(visitor_text=visitor) or ""
        lines = []
        for raw in text.splitlines():
            normalized = _normalize(raw)
            if not normalized:
                continue
            matches = styles.get(normalized, [])
            # Ambiguous font mapping is never treated as reliable heading evidence.
            signatures = {(m.font_size, m.bold, m.margin) for m in matches}
            lines.append(matches[0] if len(signatures) == 1 else TextLine(normalized))
        pages.append(lines)
    return pages


class PolicyError(ValueError):
    """Policy selection, extraction, or structural validation failed."""


@dataclass(frozen=True)
class PolicySpec:
    policy_id: str
    insurer: str
    plan_name: str
    source_file: str


HORIZONCARE = PolicySpec(
    policy_id="horizoncare_silver_ppo_2500_v3_2",
    insurer="HorizonCare",
    plan_name="Silver PPO 2500",
    source_file="horizoncare_silver_ppo_2500.pdf",
)


def resolve_policy(insurer: str, plan_name: str) -> PolicySpec:
    """Exact identity matching after case/whitespace normalization; no fallback."""
    normalize = lambda value: " ".join(value.split()).casefold()
    if (normalize(insurer), normalize(plan_name)) != (
        normalize(HORIZONCARE.insurer), normalize(HORIZONCARE.plan_name)
    ):
        raise PolicyError("No policy registered for this insurer and plan")
    return HORIZONCARE


def chunk_pages(
    pages: list[list[TextLine]], spec: PolicySpec, source_sha256: str
) -> tuple[PolicyChunk, ...]:
    """Infer numbered headings from typography, retaining cross-page context.

    Larger numbered text is a heading. Regular body-sized numbering is a list.
    Bold body-sized numbering, missing font data, duplicate identifiers, orphan
    subsections, and prominent unnumbered text within sections require inspection.
    """
    weights: Counter[float] = Counter()
    margins: Counter[str] = Counter()
    for page in pages:
        margins.update({line.text for line in page if line.margin})
        for line in page:
            if line.font_size and not line.bold and not line.margin:
                weights[line.font_size] += len(line.text)
    if not weights:
        raise PolicyError("Cannot determine body typography; extraction needs inspection")
    body_size = weights.most_common(1)[0][0]
    chunks = []
    seen: set[str] = set()
    current = None
    for page_number, page in enumerate(pages, 1):
        if not page:
            raise PolicyError(f"Page {page_number} has no text; OCR is not supported")
        lines = []

        def flush():
            text = "\n".join(lines).strip()
            if current is not None and text:
                section, heading = current
                chunks.append(PolicyChunk(
                    chunk_id=f"{spec.policy_id}:{source_sha256}:p{page_number}:s{section}:1",
                    policy_id=spec.policy_id, source_file=spec.source_file,
                    source_sha256=source_sha256, section=section, heading=heading,
                    source_page=page_number, text=text,
                ))
            lines.clear()

        for line in page:
            # Remove only repeated, small margin text; no insurer-specific strings.
            if (line.margin and margins[line.text] >= 2 and line.font_size
                    and line.font_size < body_size):
                continue
            match = NUMBERED_HEADING.fullmatch(line.text)
            prominent = line.font_size is not None and line.font_size >= body_size + 0.5
            if match and prominent:
                section, heading = match.groups()
                if section in seen:
                    raise PolicyError(f"Duplicate section {section}; extraction needs inspection")
                if "." in section:
                    parent = section.rsplit(".", 1)[0]
                    if current is None or current[0] != parent and not current[0].startswith(parent + "."):
                        raise PolicyError(f"Orphan subsection {section}; extraction needs inspection")
                flush()
                current = (section, heading)
                seen.add(section)
            elif match and (line.font_size is None or line.bold):
                raise PolicyError(f"Ambiguous numbered line on page {page_number}: {line.text}")
            elif current is not None:
                if prominent:
                    raise PolicyError(f"Unnumbered prominent text on page {page_number}; inspection required")
                lines.append(line.text)
        flush()
    if not chunks:
        raise PolicyError("No reliable numbered headings/content; extraction needs inspection")
    return tuple(chunks)


class PolicyIndex(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format_version: int
    extractor_version: str
    policy_id: str
    source_file: str
    source_sha256: str
    page_count: int
    chunks_sha256: str
    chunks: tuple[PolicyChunk, ...]


def _chunks_digest(chunks: tuple[PolicyChunk, ...]) -> str:
    payload = json.dumps([c.model_dump() for c in chunks], sort_keys=True)
    return sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class IngestionResult:
    index: PolicyIndex
    cache_path: Path
    cache_hit: bool


def ingest_policy(spec: PolicySpec, policy_dir: Path, cache_dir: Path) -> IngestionResult:
    """Validate a cache or rebuild it from the PDF; retain older source revisions."""
    source_path = policy_dir / spec.source_file
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"Cannot read policy PDF: {source_path}") from exc
    source_hash = sha256(source_bytes).hexdigest()
    cache_path = cache_dir / f"{spec.policy_id}-{source_hash}-v{FORMAT_VERSION}.json"
    try:
        index = PolicyIndex.model_validate_json(cache_path.read_text(encoding="utf-8"))
        valid = (
            index.format_version == FORMAT_VERSION
            and index.extractor_version == pypdf.__version__
            and index.policy_id == spec.policy_id
            and index.source_file == spec.source_file
            and index.source_sha256 == source_hash
            and index.page_count > 0
            and bool(index.chunks)
            and index.chunks_sha256 == _chunks_digest(index.chunks)
            and len({c.chunk_id for c in index.chunks}) == len(index.chunks)
            and all(
                c.policy_id == spec.policy_id
                and c.source_file == spec.source_file
                and c.source_sha256 == source_hash
                and c.source_page <= index.page_count
                and re.fullmatch(r"\d+(?:\.\d+)*", c.section) is not None
                and bool(c.heading.strip())
                and c.chunk_id == f"{spec.policy_id}:{source_hash}:p{c.source_page}:s{c.section}:1"
                for c in index.chunks
            )
        )
        if valid:
            return IngestionResult(index, cache_path, True)
    except (OSError, ValueError, ValidationError):
        pass  # Missing, unreadable, or corrupt derived data is rebuilt.

    try:
        reader = pypdf.PdfReader(BytesIO(source_bytes), strict=True)
        pages = extract_pages(reader)
    except Exception as exc:
        raise PolicyError("Cannot extract policy PDF") from exc
    chunks = chunk_pages(pages, spec, source_hash)
    index = PolicyIndex(
        format_version=FORMAT_VERSION,
        extractor_version=pypdf.__version__,
        policy_id=spec.policy_id,
        source_file=spec.source_file,
        source_sha256=source_hash,
        page_count=len(pages),
        chunks_sha256=_chunks_digest(chunks),
        chunks=chunks,
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Atomic replacement keeps readers from observing partially written JSON.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache_dir,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(index.model_dump_json(indent=2))
        os.replace(temporary, cache_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return IngestionResult(index, cache_path, False)
