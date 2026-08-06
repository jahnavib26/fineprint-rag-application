"""Clause-tree segmentation.

Turns a lease's extracted text into a tree of clauses keyed by their printed
numbers, handling the numbering styles leases actually use:

    ARTICLE VII            → root
    Section 8 – QUIET USE  → child of the current article (root if none)
    14. PETS               → root-level numbered clause
    14(b) ...              → child of 14
    (b) ...                → child of the nearest preceding numbered clause
    14.2.1 ...             → child of 14.2, which is a child of 14

A clause's span runs from its marker to the next marker of any kind, so spans
never overlap and a parent's own text is its preamble before the first child.
Confidence reflects how much of the document the detected structure explains;
callers route low-confidence documents to the fallback chunker instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.types import Clause, ParsedDocument, SegmentationResult

CONFIDENCE_FLOOR = 0.5  # below this, callers should use fallback.chunk()
MIN_MARKERS = 2

_ROMAN = r"[IVXLCDM]+"

# Order matters: first match wins for a given line.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("article", re.compile(rf"^ARTICLE\s+({_ROMAN})\b\s*[.\-–—:]?\s*(.*)$", re.IGNORECASE)),
    ("section_word", re.compile(r"^Section\s+(\d+(?:\.\d+)*)\s*[.\-–—:]?\s*(.*)$", re.IGNORECASE)),
    ("number_letter", re.compile(r"^(\d+)\(([a-z])\)\s*[.\-–—:]?\s*(.*)$")),
    ("dotted", re.compile(r"^(\d+(?:\.\d+)+)\s*[.\-–—:]?\s+(.*)$")),
    ("plain", re.compile(r"^(\d+)[.)]\s+(.*)$")),
    # Addenda commonly label their own paragraphs "A1." / "B-2." to avoid
    # colliding with the original lease's numbering.
    ("alnum", re.compile(r"^([A-Z]-?\d+)[.)]\s+(.*)$")),
    ("letter", re.compile(r"^\(([a-z])\)\s*(.*)$")),
]

# Body sentences that wrap onto a new line can start with a bare number
# ("14. Tenant shall…" is a marker; "14 days after…" is not). The plain/dotted
# patterns already require the trailing '.'/')'; this cap rejects years and
# dollar amounts that happen to be followed by a period.
_MAX_CLAUSE_NUMBER = 200


@dataclass
class _Marker:
    kind: str
    number: str
    heading_candidate: str
    line_start: int  # offset of the marker line in full_text
    body_start: int  # offset just past the marker line


def segment(doc: ParsedDocument) -> SegmentationResult:
    markers = _find_markers(doc.full_text)
    # A two-clause addendum is a legitimate document; a lone marker in a wall of
    # prose is noise. Two is the smallest count that can describe a structure.
    if len(markers) < MIN_MARKERS:
        return SegmentationResult(
            clauses=[], confidence=_low_confidence(markers), strategy="clause_tree"
        )

    clauses: list[Clause] = []
    by_number: dict[str, Clause] = {}
    current_article: str | None = None
    current_numbered: str | None = None  # nearest "14."-style clause, for bare "(b)" items

    document_end = _content_end(doc.full_text)

    for i, marker in enumerate(markers):
        end = markers[i + 1].line_start if i + 1 < len(markers) else document_end
        number, parent = _resolve(marker, by_number, current_article, current_numbered)

        heading, body_offset = _split_heading(marker, doc.full_text, end)
        text = doc.full_text[body_offset:end].strip()

        clause = Clause(
            number=number,
            heading=heading,
            text=text,
            parent_number=parent,
            page=doc.page_for_offset(marker.line_start),
            char_start=marker.line_start,
            char_end=end,
        )
        clauses.append(clause)
        by_number[number] = clause

        if marker.kind == "article":
            current_article = number
        elif marker.kind in ("plain", "section_word") and "." not in marker.number:
            current_numbered = number

    confidence = _confidence(doc.full_text, clauses)
    return SegmentationResult(clauses=clauses, confidence=confidence, strategy="clause_tree")


# Signature and execution blocks sit after the last clause with no marker of
# their own, so the final clause's span would otherwise absorb them — and that
# text then gets embedded, retrieved, and quoted back to the tenant as if it
# were part of the clause.
_BOILERPLATE = re.compile(
    r"^\s*(?:executed\s+on\b|in\s+witness\s+whereof\b|landlord\s*_|tenant\s*_"
    r"|signature\b|date[d]?\s*:?\s*_)",
    re.IGNORECASE,
)


def _content_end(full_text: str) -> int:
    """Offset where the document's substantive text stops."""
    offset = 0
    for line in full_text.splitlines(keepends=True):
        if _BOILERPLATE.match(line):
            return offset
        offset += len(line)
    return len(full_text)


def _find_markers(full_text: str) -> list[_Marker]:
    markers: list[_Marker] = []
    offset = 0
    for line in full_text.splitlines(keepends=True):
        stripped = line.strip()
        line_start = offset + (len(line) - len(line.lstrip()))
        offset += len(line)
        if not stripped:
            continue
        for kind, pattern in _PATTERNS:
            m = pattern.match(stripped)
            if not m:
                continue
            if kind in ("plain", "dotted", "number_letter", "section_word"):
                lead = int(m.group(1).split(".")[0].rstrip(")"))
                if lead > _MAX_CLAUSE_NUMBER:
                    break
            if kind in ("article", "section_word") and _is_cross_reference(m):
                break
            number = _canonical_number(kind, m)
            markers.append(
                _Marker(
                    kind=kind,
                    number=number,
                    heading_candidate=m.group(m.lastindex).strip(),
                    line_start=line_start,
                    body_start=offset,
                )
            )
            break
    return markers


def _is_cross_reference(m: re.Match[str]) -> bool:
    """True for "Section 4 of the Lease is hereby amended…" — a citation, not a marker.

    A clause opener is followed by a heading or the start of a sentence; a
    cross-reference continues in lowercase ("of", "is", "shall"). Only applied
    to the ``ARTICLE``/``Section`` forms, which are the ones leases actually
    cite mid-sentence — sub-item markers like "(b)" legitimately continue a
    lowercase list.
    """
    rest = m.group(m.lastindex).lstrip()
    return bool(rest) and rest[0].islower()


def _canonical_number(kind: str, m: re.Match[str]) -> str:
    if kind == "article":
        return m.group(1).upper()
    if kind == "number_letter":
        return f"{m.group(1)}({m.group(2)})"
    if kind == "letter":
        return f"({m.group(1)})"  # parent is attached during _resolve
    return m.group(1)


def _resolve(
    marker: _Marker,
    by_number: dict[str, Clause],
    current_article: str | None,
    current_numbered: str | None,
) -> tuple[str, str | None]:
    """Return (canonical number, parent number) for a marker."""
    if marker.kind == "article":
        return marker.number, None

    if marker.kind == "number_letter":
        parent = marker.number.split("(")[0]
        return marker.number, parent if parent in by_number else current_numbered

    if marker.kind == "letter":
        if current_numbered is None:
            return marker.number, None
        return f"{current_numbered}{marker.number}", current_numbered

    if marker.kind == "dotted":
        parent = marker.number.rsplit(".", 1)[0]
        return marker.number, parent if parent in by_number else current_numbered

    # plain / section_word
    return marker.number, current_article


def _split_heading(marker: _Marker, full_text: str, clause_end: int) -> tuple[str, int]:
    """Decide whether the text after the marker is a heading or body.

    "14. PETS" and "Section 8 – Quiet Enjoyment" are headings (short, no
    sentence punctuation at depth); "(a) Tenant shall not…" is body.
    Returns (heading, offset where body text starts).
    """
    candidate = marker.heading_candidate
    if not candidate:
        return "", min(marker.body_start, clause_end)
    looks_like_heading = (
        len(candidate) <= 60
        and not candidate.rstrip().endswith((",", ";"))
        and (candidate.isupper() or _is_title_case(candidate))
    )
    if looks_like_heading:
        return candidate.rstrip(".").strip(), min(marker.body_start, clause_end)
    # The marker line itself is body text.
    body_start = full_text.find(candidate, marker.line_start, clause_end)
    return "", body_start if body_start != -1 else marker.line_start


def _is_title_case(s: str) -> bool:
    words = [w for w in re.split(r"[\s\-–—/]+", s) if w and w.isalpha()]
    if not words:
        return False
    capitalized = sum(1 for w in words if w[0].isupper())
    return capitalized / len(words) >= 0.7


def _confidence(full_text: str, clauses: list[Clause]) -> float:
    if not clauses:
        return 0.0
    covered = clauses[-1].char_end - clauses[0].char_start
    coverage = covered / max(len(full_text), 1)
    # ~1 marker per 800 chars is typical for a well-structured lease.
    density = min(1.0, len(clauses) / (len(full_text) / 800))
    return round(min(1.0, 0.6 * coverage + 0.4 * density), 3)


def _low_confidence(markers: list[_Marker]) -> float:
    return round(0.1 * len(markers), 3)
