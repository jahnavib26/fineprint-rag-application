"""Parse a document into clauses, choosing the segmentation strategy.

The one function the rest of the system calls. Everything downstream —
classification, embedding, retrieval, citation — works on ``Clause`` records and
doesn't care which strategy produced them; only the UI does, via
``SegmentationResult.strategy`` and ``confidence`` (the structure-confidence
badge).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ingestion import fallback, pdf, segmenter
from app.ingestion.types import ParsedDocument, SegmentationResult


@dataclass
class ParseResult:
    document: ParsedDocument
    segmentation: SegmentationResult

    @property
    def clauses(self):
        return self.segmentation.clauses


def parse(path: str | Path, *, display_name: str | None = None) -> ParseResult:
    # display_name is the name the user knows the file by. Uploads are staged
    # under a temp path, which must never surface in an error message.
    doc = pdf.extract_text(path, display_name=display_name)
    return ParseResult(document=doc, segmentation=segment_text(doc))


def segment_text(doc: ParsedDocument) -> SegmentationResult:
    result = segmenter.segment(doc)
    if result.confidence < segmenter.CONFIDENCE_FLOOR or not result.clauses:
        chunked = fallback.chunk(doc)
        # Keep the tree attempt's confidence so the UI can report *how*
        # unstructured the document was, not just that it fell back.
        chunked.confidence = result.confidence
        return chunked
    return result
