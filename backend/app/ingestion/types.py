"""Shared datatypes for the ingestion pipeline.

Offsets are always into ``ParsedDocument.full_text`` — the single string the
frontend renders — so a clause's ``(char_start, char_end)`` can drive
scroll-and-highlight without any coordinate mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    number: int  # 1-based
    char_start: int
    char_end: int


@dataclass
class ParsedDocument:
    full_text: str
    pages: list[Page]

    def page_for_offset(self, offset: int) -> int:
        for page in self.pages:
            if page.char_start <= offset < page.char_end:
                return page.number
        return self.pages[-1].number if self.pages else 1


@dataclass
class Clause:
    """One node of the clause tree.

    ``number`` is the canonical human label ("14", "14(b)", "14.2.1", "VII").
    ``parent_number`` is None for roots. ``text`` is the clause's *own* span —
    a parent's text ends where its first child starts; subtree text is
    reassembled via the tree when needed.
    """

    number: str
    heading: str
    text: str
    parent_number: str | None
    page: int
    char_start: int
    char_end: int
    clause_type: str | None = None  # filled in by the LLM classifier at ingestion


@dataclass
class SegmentationResult:
    clauses: list[Clause]
    confidence: float  # 0..1; below settings.SEGMENTATION_CONFIDENCE_FLOOR → fallback chunker
    strategy: str = "clause_tree"  # or "fallback"

    def children_of(self, number: str) -> list[Clause]:
        return [c for c in self.clauses if c.parent_number == number]


@dataclass
class GeneratedLease:
    """Ground truth emitted by scripts/generate_leases.py (also used by evals)."""

    lease_id: str
    documents: list[str] = field(default_factory=list)
