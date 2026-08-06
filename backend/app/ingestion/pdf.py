"""PDF text extraction with a digital-vs-scanned routing check.

Digital PDFs go through pymupdf. Pages with too little extractable text are
assumed to be scans; OCR is stubbed until a real scanned lease shows up.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # pymupdf

from app.ingestion.types import Page, ParsedDocument

# Below this many extractable characters per page (on average) we assume the
# PDF is a scan. A typical lease page carries 1,500-3,500 characters.
MIN_CHARS_PER_PAGE = 200

PAGE_SEPARATOR = "\n\n"


class ScannedPdfError(NotImplementedError):
    pass


def extract_text(path: str | Path) -> ParsedDocument:
    with fitz.open(path) as doc:
        page_texts = [page.get_text("text").strip() for page in doc]

    if not page_texts:
        raise ValueError(f"{path}: PDF has no pages")

    avg_chars = sum(len(t) for t in page_texts) / len(page_texts)
    if avg_chars < MIN_CHARS_PER_PAGE:
        return _ocr_fallback(path)

    pages: list[Page] = []
    cursor = 0
    parts: list[str] = []
    for i, text in enumerate(page_texts):
        start = cursor
        parts.append(text)
        cursor += len(text)
        pages.append(Page(number=i + 1, char_start=start, char_end=cursor))
        if i < len(page_texts) - 1:
            parts.append(PAGE_SEPARATOR)
            cursor += len(PAGE_SEPARATOR)

    return ParsedDocument(full_text="".join(parts), pages=pages)


def _ocr_fallback(path: str | Path) -> ParsedDocument:
    raise ScannedPdfError(
        f"{path} looks like a scanned PDF (little extractable text). "
        "OCR ingestion is not implemented yet — re-export the lease as a "
        "digital PDF, or add a pytesseract/Textract implementation here."
    )
