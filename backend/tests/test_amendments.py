"""Override detection, tested without a database.

``_detect_with_regex`` is pure, so the cases that matter — real override
language, and text that merely mentions another clause — can be checked
directly on in-memory rows.
"""

from __future__ import annotations

import uuid

from app.db.models import Clause, Document
from app.ingestion.amendments import AMENDS, REPLACES, _detect_with_regex


def _clause(number: str, text: str, heading: str = "") -> Clause:
    return Clause(
        id=uuid.uuid4(),
        number=number,
        heading=heading,
        text=text,
        page=1,
        char_start=0,
        char_end=len(text),
        clause_type="other",
    )


def _addendum(*clauses: Clause) -> Document:
    doc = Document(
        id=uuid.uuid4(),
        lease_id="test",
        filename="addendum.pdf",
        kind="addendum",
        full_text="",
    )
    doc.clauses = list(clauses)
    return doc


TARGETS = {
    "4": _clause("4", "Tenant shall deposit $2,100.", "AMOUNT OF DEPOSIT"),
    "5": _clause("5", "Landlord shall return the deposit within 45 days.", "RETURN"),
    "15": _clause("15", "No animal shall be kept upon the premises.", "PETS"),
}


def test_detects_amend_and_restate():
    addendum = _addendum(
        _clause("A1", "Section 4 of the Lease is hereby amended and restated in its entirety.")
    )
    edges = _detect_with_regex(addendum, TARGETS)
    assert edges == [("A1", "4", REPLACES, edges[0][3])]
    assert "Section 4" in edges[0][3]


def test_detects_notwithstanding_supersede():
    addendum = _addendum(
        _clause("B1", "Notwithstanding Section 15 of the Lease, which is hereby superseded, "
                      "Tenant may keep one cat.")
    )
    edges = _detect_with_regex(addendum, TARGETS)
    assert [(e[0], e[1], e[2]) for e in edges] == [("B1", "15", REPLACES)]


def test_partial_amendment_is_not_a_replacement():
    addendum = _addendum(
        _clause("A2", "Section 5 of the Lease is hereby amended to substitute twenty-one (21) "
                      "days for forty-five (45) days.")
    )
    edges = _detect_with_regex(addendum, TARGETS)
    assert [(e[0], e[1], e[2]) for e in edges] == [("A2", "5", AMENDS)]


def test_mentioning_a_clause_is_not_overriding_it():
    """A false edge is worse than a missing one — it hides a clause that still
    governs, so a mere cross-reference must not produce one."""
    addendum = _addendum(
        _clause("B2", "Tenant shall be liable for all damage caused by the permitted animal, "
                      "including damage in excess of the deposit described in Section 4.")
    )
    assert _detect_with_regex(addendum, TARGETS) == []


def test_ignores_references_to_clauses_that_do_not_exist():
    addendum = _addendum(
        _clause("C1", "Section 99 of the Lease is hereby amended and restated.")
    )
    assert _detect_with_regex(addendum, TARGETS) == []


def test_one_paragraph_can_override_several_clauses():
    addendum = _addendum(
        _clause("D1", "Sections 4 and 5 of the Lease are amended as set forth herein.")
    )
    edges = _detect_with_regex(addendum, TARGETS)
    assert sorted(e[1] for e in edges) == ["4", "5"]
