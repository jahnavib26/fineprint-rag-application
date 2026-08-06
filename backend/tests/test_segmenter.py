"""Segmenter tests, driven by the synthetic leases' ground truth.

The assertions that matter for retrieval quality:

* every printed clause is found, with its printed number
* the tree is right — 14(b) is a child of 14, 2.1.1 a child of 2.1
* char offsets round-trip back to the source text (they drive UI highlighting)
* an unstructured document is *not* forced into a tree
"""

from __future__ import annotations

import pytest

from app.ingestion import pdf, segmenter
from app.ingestion.pipeline import segment_text
from tests.conftest import SYNTHETIC, iter_documents

DOCUMENTS = iter_documents()
IDS = [d["doc_id"] for _, d in DOCUMENTS]


def _parse(doc_meta: dict):
    parsed = pdf.extract_text(SYNTHETIC / doc_meta["file"])
    return parsed, segmenter.segment(parsed)


@pytest.mark.parametrize("lease,doc_meta", DOCUMENTS, ids=IDS)
def test_finds_every_printed_clause(lease, doc_meta):
    expected = [c["number"] for c in doc_meta["clauses"]]
    if not expected:
        pytest.skip("unstructured document; covered by the fallback tests")
    _, result = _parse(doc_meta)
    assert [c.number for c in result.clauses] == expected


@pytest.mark.parametrize("lease,doc_meta", DOCUMENTS, ids=IDS)
def test_tree_parents_match_ground_truth(lease, doc_meta):
    expected = {c["number"]: c["parent"] for c in doc_meta["clauses"]}
    if not expected:
        pytest.skip("unstructured document")
    _, result = _parse(doc_meta)
    assert {c.number: c.parent_number for c in result.clauses} == expected


@pytest.mark.parametrize("lease,doc_meta", DOCUMENTS, ids=IDS)
def test_offsets_round_trip_to_source_text(lease, doc_meta):
    parsed, result = _parse(doc_meta)
    if not result.clauses:
        pytest.skip("unstructured document")
    for clause in result.clauses:
        span = parsed.full_text[clause.char_start : clause.char_end]
        assert clause.text in span, f"{clause.number}: text not inside its own span"
        if clause.heading:
            assert clause.heading.split()[0] in span


@pytest.mark.parametrize("lease,doc_meta", DOCUMENTS, ids=IDS)
def test_spans_are_ordered_and_disjoint(lease, doc_meta):
    _, result = _parse(doc_meta)
    spans = [(c.char_start, c.char_end) for c in result.clauses]
    for (_, prev_end), (start, _) in zip(spans, spans[1:], strict=False):
        assert start >= prev_end, "clause spans must not overlap"


@pytest.mark.parametrize("lease,doc_meta", DOCUMENTS, ids=IDS)
def test_confidence_matches_expected_strategy(lease, doc_meta):
    _, result = _parse(doc_meta)
    if lease["strategy"] == "fallback":
        assert result.confidence < segmenter.CONFIDENCE_FLOOR
    else:
        assert result.confidence >= segmenter.CONFIDENCE_FLOOR


@pytest.mark.parametrize("lease,doc_meta", DOCUMENTS, ids=IDS)
def test_pipeline_picks_the_expected_strategy(lease, doc_meta):
    parsed = pdf.extract_text(SYNTHETIC / doc_meta["file"])
    assert segment_text(parsed).strategy == lease["strategy"]


def test_all_three_numbering_styles_parse():
    """ARTICLE VII / 14(b) / 2.1.1 — the M1 gate, stated explicitly."""
    maple = next(d for _, d in DOCUMENTS if d["doc_id"] == "maple-court-lease")
    birch = next(d for _, d in DOCUMENTS if d["doc_id"] == "birch-lane-lease")

    _, maple_result = _parse(maple)
    numbers = {c.number: c for c in maple_result.clauses}
    assert numbers["III"].heading == "USE AND OCCUPANCY"  # roman article
    assert numbers["14(b)"].parent_number == "14"  # number-letter child
    assert "short-term" in numbers["14(b)"].text  # the clause that matters

    _, birch_result = _parse(birch)
    birch_numbers = {c.number: c for c in birch_result.clauses}
    assert birch_numbers["2.1.1"].parent_number == "2.1"  # dotted nesting
    assert birch_numbers["2.1"].parent_number == "2"


def test_cross_reference_is_not_a_clause_marker():
    """"Section 4 of the Lease is hereby amended" is a citation, not a clause."""
    addendum = next(d for _, d in DOCUMENTS if d["doc_id"] == "maple-court-addendum-1")
    _, result = _parse(addendum)
    assert [c.number for c in result.clauses] == ["A1", "A2"]
    assert "Section 4 of the Lease is hereby amended" in result.clauses[0].text


def test_parent_text_excludes_child_text():
    """A parent's own span stops where its first child begins."""
    maple = next(d for _, d in DOCUMENTS if d["doc_id"] == "maple-court-lease")
    _, result = _parse(maple)
    by_number = {c.number: c for c in result.clauses}
    assert by_number["14"].char_end <= by_number["14(a)"].char_start
    assert "short-term" not in by_number["14"].text
