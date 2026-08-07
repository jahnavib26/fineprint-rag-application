"""PDF text extraction with a digital-vs-scanned routing check.

Digital PDFs go through pymupdf. Pages with too little extractable text are
assumed to be scans; OCR is stubbed until a real scanned lease shows up.

Errors here are read by a tenant who just dragged a file in, so they name the
file the user chose — not the server-side temp path it was staged at — and they
distinguish "this isn't a PDF" from "this is a PDF I can't read text out of".
Those need different actions from the user, and pymupdf will silently open a
.txt or .epub, which makes the first look like the second.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # pymupdf

from app.ingestion.types import Page, ParsedDocument

# Below this many extractable characters per page (on average) we assume the
# PDF is a scan. A typical lease page carries 1,500-3,500 characters.
MIN_CHARS_PER_PAGE = 200

PAGE_SEPARATOR = "\n\n"


class UnreadableDocumentError(ValueError):
    """The file isn't a PDF, or is damaged past reading."""


class ScannedPdfError(NotImplementedError):
    """A real PDF, but its pages carry no text layer."""


def extract_text(path: str | Path, *, display_name: str | None = None) -> ParsedDocument:
    name = display_name or Path(path).name

    try:
        with fitz.open(path) as doc:
            # pymupdf opens plenty of things that aren't PDFs (.txt, .epub,
            # images). Those extract *some* text, so without this check a text
            # file gets diagnosed as a scanned lease and the user is told to
            # re-export a PDF they never had.
            if not doc.is_pdf:
                raise UnreadableDocumentError(
                    f"{name} isn't a PDF. Upload the lease as a PDF file."
                )
            page_texts = [page.get_text("text").strip() for page in doc]
    except UnreadableDocumentError:
        raise
    except Exception as exc:  # pymupdf raises a range of types for bad input
        raise UnreadableDocumentError(
            f"{name} could not be opened as a PDF ({exc}). It may be damaged or "
            "password-protected — try re-exporting or removing the password."
        ) from exc

    if not page_texts:
        raise UnreadableDocumentError(f"{name} has no pages.")

    avg_chars = sum(len(t) for t in page_texts) / len(page_texts)
    if avg_chars < MIN_CHARS_PER_PAGE:
        return _ocr_fallback(name)

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


def _ocr_fallback(name: str) -> ParsedDocument:
    raise ScannedPdfError(
        f"{name} looks like a scanned PDF — its pages are images, with no "
        "selectable text. Reading scans isn't supported yet. If you have a "
        "digital copy from your landlord or a signing service, upload that "
        "instead."
    )
