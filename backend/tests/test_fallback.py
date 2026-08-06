from __future__ import annotations

from app.ingestion import fallback, pdf
from tests.conftest import SYNTHETIC

MESSY = "messy-loft-agreement.pdf"


def test_chunks_cover_the_whole_document():
    parsed = pdf.extract_text(SYNTHETIC / MESSY)
    result = fallback.chunk(parsed)
    assert result.strategy == "fallback"
    assert result.clauses

    assert result.clauses[0].char_start == 0
    assert result.clauses[-1].char_end == len(parsed.full_text)
    for prev, nxt in zip(result.clauses, result.clauses[1:]):
        assert nxt.char_start <= prev.char_end, "gap between chunks would lose text"


def test_chunks_overlap_their_predecessor():
    parsed = pdf.extract_text(SYNTHETIC / MESSY)
    result = fallback.chunk(parsed)
    for prev, nxt in zip(result.clauses, result.clauses[1:]):
        assert nxt.char_start < prev.char_end, "overlap keeps split sentences retrievable"


def test_chunk_offsets_round_trip():
    parsed = pdf.extract_text(SYNTHETIC / MESSY)
    for clause in fallback.chunk(parsed).clauses:
        assert clause.text in parsed.full_text[clause.char_start : clause.char_end]
        assert clause.page >= 1


def test_chunks_respect_the_target_size():
    parsed = pdf.extract_text(SYNTHETIC / MESSY)
    for clause in fallback.chunk(parsed).clauses:
        assert clause.char_end - clause.char_start <= fallback.TARGET_SIZE + fallback.OVERLAP


def test_the_messy_lease_still_carries_its_key_terms():
    """Fallback chunks must remain retrievable for the questions evals ask."""
    parsed = pdf.extract_text(SYNTHETIC / MESSY)
    text = " ".join(c.text for c in fallback.chunk(parsed).clauses)
    for term in ("deposit", "sublet", "notice"):
        assert term in text.lower()
