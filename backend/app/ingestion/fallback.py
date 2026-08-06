"""Recursive overlap chunker for documents the segmenter can't structure.

Chunks are emitted as ``Clause`` records with synthetic numbers ("chunk-1",
"chunk-2", …) and no tree, so the rest of the pipeline (classify → embed →
retrieve → cite) treats them uniformly. Documents that land here are flagged
via ``SegmentationResult.strategy == "fallback"`` and get a low
structure-confidence badge in the UI.
"""

from __future__ import annotations

from app.ingestion.types import Clause, ParsedDocument, SegmentationResult

TARGET_SIZE = 1200
OVERLAP = 200
_SEPARATORS = ["\n\n", "\n", ". ", " "]


def chunk(doc: ParsedDocument) -> SegmentationResult:
    spans = _split_span(doc.full_text, 0, len(doc.full_text))
    clauses = []
    for i, (start, end) in enumerate(_with_overlap(spans)):
        text = doc.full_text[start:end].strip()
        if not text:
            continue
        clauses.append(
            Clause(
                number=f"chunk-{i + 1}",
                heading="",
                text=text,
                parent_number=None,
                page=doc.page_for_offset(start),
                char_start=start,
                char_end=end,
            )
        )
    return SegmentationResult(clauses=clauses, confidence=0.0, strategy="fallback")


def _split_span(text: str, start: int, end: int, sep_index: int = 0) -> list[tuple[int, int]]:
    if end - start <= TARGET_SIZE:
        return [(start, end)]
    if sep_index >= len(_SEPARATORS):
        # No separator left: hard-split.
        return [(s, min(s + TARGET_SIZE, end)) for s in range(start, end, TARGET_SIZE)]

    sep = _SEPARATORS[sep_index]
    pieces: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        idx = text.find(sep, cursor + 1, end)
        piece_end = end if idx == -1 else idx + len(sep)
        pieces.append((cursor, piece_end))
        cursor = piece_end

    # Greedily merge separator-delimited pieces up to TARGET_SIZE, recursing
    # into any single piece that is itself too large.
    merged: list[tuple[int, int]] = []
    run_start: int | None = None
    for s, e in pieces:
        if e - s > TARGET_SIZE:
            if run_start is not None:
                merged.append((run_start, s))
                run_start = None
            merged.extend(_split_span(text, s, e, sep_index + 1))
            continue
        if run_start is None:
            run_start = s
        if e - run_start >= TARGET_SIZE:
            merged.append((run_start, e))
            run_start = None
    if run_start is not None:
        merged.append((run_start, end))
    return merged


def _with_overlap(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i, (start, end) in enumerate(spans):
        if i > 0:
            start = max(spans[i - 1][0], start - OVERLAP)
        out.append((start, end))
    return out
