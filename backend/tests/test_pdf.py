from __future__ import annotations

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.ingestion import pdf
from tests.conftest import SYNTHETIC


def test_page_offsets_partition_the_text():
    parsed = pdf.extract_text(SYNTHETIC / "maple-court-lease.pdf")
    assert len(parsed.pages) >= 2
    for page in parsed.pages:
        assert parsed.full_text[page.char_start : page.char_end].strip()
    for prev, nxt in zip(parsed.pages, parsed.pages[1:]):
        assert nxt.char_start >= prev.char_end


def test_page_lookup_for_offset():
    parsed = pdf.extract_text(SYNTHETIC / "maple-court-lease.pdf")
    assert parsed.page_for_offset(0) == 1
    assert parsed.page_for_offset(len(parsed.full_text) - 1) == parsed.pages[-1].number
    second = parsed.pages[1]
    assert parsed.page_for_offset(second.char_start) == 2


def test_scanned_pdf_raises_a_helpful_error(tmp_path):
    """A page with no extractable text is a scan; OCR is deliberately unbuilt."""
    path = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.rect(100, 100, 200, 200, fill=0)  # a drawing, no text
    c.showPage()
    c.save()

    with pytest.raises(pdf.ScannedPdfError) as exc:
        pdf.extract_text(path)
    assert "OCR" in str(exc.value)
