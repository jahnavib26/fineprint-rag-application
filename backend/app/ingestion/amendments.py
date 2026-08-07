"""Detect which clauses an addendum overrides, and store the edges.

The hardest real-world problem in this system. A lease signed in June and an
addendum signed in January are two separate documents, both valid, and the
addendum silently changes what some of the original clauses mean. Retrieval on
its own always prefers the original — it is longer, more topical, and written in
the vocabulary the question uses — so without this graph the system confidently
answers with terms that no longer apply.

Two detectors:

* **LLM** — each addendum clause is shown alongside an index of the original
  lease's clause numbers and headings, and asked what it modifies. Handles
  override language that doesn't cite a clause number at all.
* **Offline regex** — override verbs near an explicit cross-reference
  ("Section 4 ... is hereby amended", "Notwithstanding Section 15 ... hereby
  superseded"). Narrower, but exact when the addendum does cite a number.

The regex detector is the mirror image of a rule in the segmenter: a line
reading "Section 4 of the Lease is hereby amended" is deliberately *not* treated
as a clause marker there, because it's a cross-reference. Here that same
cross-reference is the signal.

Edges are stored rather than applied. Rewriting the original clause would make
the amendment invisible — and the UI has to be able to say "originally $2,100,
amended to $3,150", which is usually the thing the tenant most needs to know.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Amendment, Clause, Document
from app.providers.llm import LLMUnavailable, object_schema
from app.providers.runtime import Providers

REPLACES = "replaces"
AMENDS = "amends"

_SYSTEM = """You read a paragraph from a lease addendum and identify which \
clauses of the original lease it changes.

An addendum paragraph changes an original clause when it amends, restates, \
replaces, supersedes, or overrides it, or when it states a term that \
contradicts one. Language to look for: "is hereby amended", "amended and \
restated", "is hereby superseded", "notwithstanding Section N", "in lieu of", \
"shall be replaced by".

Rules:
- Only report a clause number that appears in the provided index of the \
original lease.
- Report nothing for a paragraph that adds a new term without changing an \
existing one. Most addendum paragraphs do not override anything, and a false \
edge is worse than a missing one: it makes retrieval hide a clause that still \
governs.
- action is "replaces" when the original no longer applies at all, "amends" \
when it is modified but otherwise still in force.
- reason: one short sentence quoting the override language you relied on."""

_SCHEMA = object_schema(
    {
        "overrides": {
            "type": "array",
            "items": object_schema(
                {
                    "addendum_clause": {"type": "string"},
                    "original_clause": {"type": "string"},
                    "action": {"type": "string", "enum": [AMENDS, REPLACES]},
                    "reason": {"type": "string"},
                },
                ["addendum_clause", "original_clause", "action", "reason"],
            ),
        }
    },
    ["overrides"],
)

# "Section 4", "Clause 14(b)", "Paragraph 2.1.1", "Article VII", and the plural
# list form addenda actually use: "Sections 4 and 5 are hereby amended".
_NUMBER = r"[0-9]+(?:\.[0-9]+)*(?:\([a-z]\))?|[IVXLCDM]+"
_REFERENCE = re.compile(
    rf"\b(?:sections?|clauses?|paragraphs?|articles?)\s+"
    rf"((?:{_NUMBER})(?:\s*(?:,|and)\s*(?:{_NUMBER}))*)\b",
    re.IGNORECASE,
)
_LIST_SEPARATOR = re.compile(r"\s*(?:,|\band\b)\s*", re.IGNORECASE)
_REPLACES_VERB = re.compile(
    r"\b(?:superseded|supersedes|replaced\s+in\s+its\s+entirety|amended\s+and\s+restated"
    r"|restated\s+in\s+its\s+entirety|of\s+no\s+further\s+force)\b",
    re.IGNORECASE,
)
_AMENDS_VERB = re.compile(
    r"\b(?:hereby\s+amended|is\s+amended|are\s+amended|notwithstanding|in\s+lieu\s+of"
    r"|shall\s+be\s+replaced|deleted\s+and\s+replaced)\b",
    re.IGNORECASE,
)


async def detect_amendments(
    session: AsyncSession, lease_id: str, providers: Providers
) -> list[Amendment]:
    """(Re)build the override graph for one lease. Idempotent."""
    documents = list(
        (
            await session.execute(
                select(Document)
                .where(Document.lease_id == lease_id)
                .options(selectinload(Document.clauses))
                .order_by(Document.signed_date, Document.created_at)
            )
        ).scalars()
    )
    addenda = [d for d in documents if d.kind == "addendum"]
    if not addenda:
        return []

    await _clear_existing(session, documents)

    edges: list[Amendment] = []
    for addendum in addenda:
        # A clause can only be overridden by something signed after it, so the
        # candidate pool is every document that came before this addendum.
        earlier = [d for d in documents if d is not addendum and _is_before(d, addendum)]
        targets = {c.number: c for d in earlier for c in d.clauses}
        if not targets:
            continue

        detected = await _detect_for_document(addendum, targets, providers)
        for addendum_number, original_number, action, reason in detected:
            source = next((c for c in addendum.clauses if c.number == addendum_number), None)
            target = targets.get(original_number)
            if source is None or target is None or source.id == target.id:
                continue
            edge = Amendment(
                clause_id=target.id,
                superseded_by_clause_id=source.id,
                effective_date=addendum.signed_date,
                action=action,
                detected_reason=reason,
            )
            session.add(edge)
            edges.append(edge)

    await session.commit()
    return edges


def _is_before(candidate: Document, addendum: Document) -> bool:
    if candidate.signed_date and addendum.signed_date:
        return candidate.signed_date < addendum.signed_date
    return candidate.kind == "original"


async def _clear_existing(session: AsyncSession, documents: list[Document]) -> None:
    clause_ids = [c.id for d in documents for c in d.clauses]
    if not clause_ids:
        return
    existing = (
        await session.execute(
            select(Amendment).where(Amendment.clause_id.in_(clause_ids))
        )
    ).scalars()
    for edge in existing:
        await session.delete(edge)
    await session.flush()


async def _detect_for_document(
    addendum: Document, targets: dict[str, Clause], providers: Providers
) -> list[tuple[str, str, str, str]]:
    if providers.llm_available:
        try:
            return await _detect_with_llm(addendum, targets, providers)
        except LLMUnavailable:
            pass
    return _detect_with_regex(addendum, targets)


async def _detect_with_llm(
    addendum: Document, targets: dict[str, Clause], providers: Providers
) -> list[tuple[str, str, str, str]]:
    index_lines = [
        f"[{number}] {clause.heading or clause.text[:70]}"
        for number, clause in sorted(targets.items())
    ]
    body = [f"[{c.number}] {c.heading}\n{c.text}" for c in addendum.clauses if c.text.strip()]

    result = await providers.require_llm().complete_json(
        model=providers.model_for("smart"),
        system=_SYSTEM,
        prompt=(
            "Clauses in the original lease:\n"
            + "\n".join(index_lines)
            + "\n\nParagraphs in this addendum:\n\n"
            + "\n\n".join(body)
        ),
        schema=_SCHEMA,
        max_tokens=2048,
    )
    out = []
    for item in result.get("overrides", []):
        original = item.get("original_clause", "")
        if original not in targets:
            continue  # a number the model invented, or one from another lease
        out.append(
            (
                item.get("addendum_clause", ""),
                original,
                item.get("action") if item.get("action") in (AMENDS, REPLACES) else AMENDS,
                item.get("reason", ""),
            )
        )
    return out


def _detect_with_regex(
    addendum: Document, targets: dict[str, Clause]
) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    for clause in addendum.clauses:
        haystack = f"{clause.heading}\n{clause.text}"
        replaces = bool(_REPLACES_VERB.search(haystack))
        if not replaces and not _AMENDS_VERB.search(haystack):
            continue
        for match in _REFERENCE.finditer(haystack):
            reason = _snippet(haystack, match.start())
            for raw in _LIST_SEPARATOR.split(match.group(1)):
                number = raw.strip()
                if number.isalpha():
                    number = number.upper()  # roman numerals
                if not number or number not in targets:
                    continue
                out.append(
                    (
                        clause.number,
                        number,
                        REPLACES if replaces else AMENDS,
                        reason,
                    )
                )
    return _dedupe(out)


def _snippet(text: str, index: int, width: int = 90) -> str:
    start = max(0, index - 10)
    return " ".join(text[start : start + width].split())


def _dedupe(edges: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for edge in edges:
        key = (edge[0], edge[1])
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out
