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
    for prev, nxt in zip(parsed.pages, parsed.pages[1:], strict=False):
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
    message = str(exc.value)
    assert "scan.pdf" in message
    # Advice a tenant can act on, not an implementation note.
    assert "digital copy" in message


def test_non_pdf_is_not_diagnosed_as_a_scan(tmp_path):
    """pymupdf opens .txt files happily, and they extract almost no text — so
    without an explicit format check a text file gets reported as a scanned
    lease and the user is told to re-export a PDF they never had."""
    path = tmp_path / "notalease.txt"
    path.write_text("this is not a lease")

    with pytest.raises(pdf.UnreadableDocumentError) as exc:
        pdf.extract_text(path)
    assert "isn't a PDF" in str(exc.value)
    assert not isinstance(exc.value, pdf.ScannedPdfError)


def test_errors_name_the_users_file_not_the_temp_path(tmp_path):
    """Uploads are staged under a temp name; the message must not leak it."""
    staged = tmp_path / "tmpXk92la.pdf"
    c = canvas.Canvas(str(staged), pagesize=LETTER)
    c.rect(100, 100, 200, 200, fill=0)
    c.showPage()
    c.save()

    with pytest.raises(pdf.ScannedPdfError) as exc:
        pdf.extract_text(staged, display_name="My Lease 2024.pdf")
    message = str(exc.value)
    assert "My Lease 2024.pdf" in message
    assert "tmpXk92la" not in message
