"""Clause-type tagging.

The one metadata field that does the most work at retrieval time. "Termination"
clauses about the lease and about utility service embed almost identically in
legalese; a type filter separates them where a better embedding model doesn't.

The configured cheap-tier model tags clauses in batches at ingestion. Without an
API key a keyword classifier stands in, so the pipeline stays runnable offline —
it is weaker on clauses that describe a topic without naming it, which the evals
will show.
"""

from __future__ import annotations

import re

from app.config import get_settings
from app.db.models import CLAUSE_TYPES
from app.ingestion.types import Clause
from app.providers.llm import LLMUnavailable, get_llm, llm_available, object_schema

BATCH_SIZE = 20

_SYSTEM = (
    "You label clauses from residential lease agreements by topic. "
    "Answer only with the allowed labels. Use 'other' when a clause is "
    "administrative (definitions, notices, signatures, severability) or fits "
    "no other label — do not stretch a label to fit."
)

_SCHEMA = object_schema(
    {
        "labels": {
            "type": "array",
            "items": object_schema(
                {
                    "number": {"type": "string"},
                    "clause_type": {"type": "string", "enum": list(CLAUSE_TYPES)},
                },
                ["number", "clause_type"],
            ),
        }
    },
    ["labels"],
)

# Ordered: the first pattern that matches wins, so specific topics precede the
# generic money catch-all (nearly every clause mentions rent or a dollar figure).
# Stems end in \w* rather than \b — legalese inflects heavily ("terminate",
# "termination", "repairs", "utilities") and a trailing boundary matches none of
# them.
def _stems(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")", re.I)


_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    ("pets", _stems(r"pets?\b", r"dogs?\b", r"cats?\b", r"animals?\b")),
    # "occupant" is a subletting signal; "occupancy" is just a use clause.
    ("subletting", _stems("sublet", "subleas", "subtenant", "assign", "guest", r"occupants?\b")),
    ("deposit", _stems("deposit")),
    ("maintenance", _stems("repair", "maintain", "maintenanc", "habitab", "clean")),
    ("termination", _stems("terminat", "holdover", "vacat", r"move[- ]out", "notice to quit")),
    ("fees", _stems("rent", "fee", "charge", "utilit", r"\$")),
]


async def classify(clauses: list[Clause]) -> list[Clause]:
    """Fill in ``clause_type`` on each clause, in place, and return them."""
    if not clauses:
        return clauses
    if llm_available():
        try:
            return await _classify_with_llm(clauses)
        except LLMUnavailable:
            pass
    return _classify_with_keywords(clauses)


async def _classify_with_llm(clauses: list[Clause]) -> list[Clause]:
    llm = get_llm()
    model = get_settings().model_for("cheap")
    by_number = {c.number: c for c in clauses}

    for batch in _batches(clauses, BATCH_SIZE):
        result = await llm.complete_json(
            model=model,
            system=_SYSTEM,
            prompt=_prompt(batch),
            schema=_SCHEMA,
            max_tokens=1024,
        )
        for label in result.get("labels", []):
            clause = by_number.get(label.get("number", ""))
            if clause and label.get("clause_type") in CLAUSE_TYPES:
                clause.clause_type = label["clause_type"]

    # Anything the model skipped still needs a value.
    for clause in clauses:
        if clause.clause_type is None:
            clause.clause_type = _keyword_type(clause)
    return clauses


def _prompt(batch: list[Clause]) -> str:
    lines = [f"Allowed labels: {', '.join(CLAUSE_TYPES)}", "", "Clauses:"]
    for clause in batch:
        heading = f" — {clause.heading}" if clause.heading else ""
        lines.append(f"[{clause.number}]{heading}\n{clause.text[:600]}\n")
    lines.append("Return one label for every clause number listed above.")
    return "\n".join(lines)


def _classify_with_keywords(clauses: list[Clause]) -> list[Clause]:
    for clause in clauses:
        clause.clause_type = _keyword_type(clause)
    return clauses


def _keyword_type(clause: Clause) -> str:
    haystack = f"{clause.heading} {clause.text}"
    for clause_type, pattern in _KEYWORDS:
        if pattern.search(haystack):
            return clause_type
    return "other"


def _batches(items: list[Clause], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
