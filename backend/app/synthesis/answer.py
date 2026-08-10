"""Draft an answer from retrieved clauses — or decline to.

The model is given only the retrieved clauses and told to answer from them
alone, citing clause numbers inline as ``[14(b)]``. It has an explicit escape
hatch: returning ``not_covered`` is a correct, expected outcome, not a failure.
Half of real tenant questions aren't addressed by the lease, and a model with no
way to say so will invent an answer that sounds right.

This is the *draft*. Nothing here is shown to a user until the grounding gate in
``grounding.py`` has checked every claim in it against the clause it cites.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.providers.llm import LLMUnavailable, object_schema
from app.providers.runtime import Providers
from app.retrieval.search import Retrieved

ANSWERED = "answered"
NOT_COVERED = "not_covered"

_SYSTEM = """You answer questions about a tenant's own lease, using only the \
clauses provided to you.

Rules:
- Use only the provided clauses. Never use general knowledge about leases, \
landlord-tenant law, or what is typical — this tenant's lease is the only source.
- Cite the clause number inline in square brackets immediately after each claim \
it supports, like [14(b)] or [2.1.1]. Every factual sentence needs a citation.
- Write in plain English, not legalese. The tenant has to act on this.
- If the provided clauses do not answer the question, set status to \
"not_covered". Do not stretch a loosely related clause into an answer. \
"Your lease doesn't address this" is a correct answer and a useful one.
- If the clauses partially answer it, answer the part they cover and say plainly \
what they don't.
- Do not give legal advice or predict how a court would rule. Report what the \
lease says."""

_SCHEMA = object_schema(
    {
        "status": {"type": "string", "enum": [ANSWERED, NOT_COVERED]},
        "answer": {
            "type": "string",
            "description": (
                "Plain-English answer with inline [clause] citations. "
                "Empty string when status is not_covered."
            ),
        },
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Clause numbers cited, e.g. ['14(b)', '15'].",
        },
        "nearest_topic": {
            "type": "string",
            "description": (
                "When not_covered: the closest subject the lease does address, "
                "in a few words. Empty otherwise."
            ),
        },
    },
    ["status", "answer", "citations", "nearest_topic"],
)


@dataclass
class Draft:
    status: str
    answer: str
    citations: list[str] = field(default_factory=list)
    nearest_topic: str = ""
    model: str = ""

    @property
    def is_covered(self) -> bool:
        return self.status == ANSWERED and bool(self.answer.strip())

    def to_trace(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "citations": self.citations,
            "nearest_topic": self.nearest_topic,
            "model": self.model,
        }


def not_covered(nearest_topic: str = "", model: str = "") -> Draft:
    return Draft(status=NOT_COVERED, answer="", nearest_topic=nearest_topic, model=model)


async def draft_answer(
    question: str,
    retrieved: list[Retrieved],
    providers: Providers,
    feedback: list[str] | None = None,
) -> Draft:
    """Draft an answer. ``feedback`` carries the grounding gate's objections
    from a previous attempt, so a rewrite can address them specifically
    instead of re-deriving the same unsupported claim."""
    if not retrieved:
        # Nothing cleared the relevance floor. Refuse without spending a call —
        # a model given no clauses can only guess.
        return not_covered(model="none")
    if not providers.llm_available:
        return _offline_draft(question, retrieved)
    try:
        return await _llm_draft(question, retrieved, providers, feedback)
    except LLMUnavailable:
        return _offline_draft(question, retrieved)


async def _llm_draft(
    question: str,
    retrieved: list[Retrieved],
    providers: Providers,
    feedback: list[str] | None = None,
) -> Draft:
    model = providers.model_for("smart")
    result = await providers.require_llm().complete_json(
        model=model,
        system=_SYSTEM,
        prompt=_prompt(question, retrieved, feedback),
        schema=_SCHEMA,
        max_tokens=2048,
    )
    return Draft(
        status=result.get("status", NOT_COVERED),
        answer=result.get("answer", "").strip(),
        citations=[c for c in result.get("citations", []) if c],
        nearest_topic=result.get("nearest_topic", ""),
        model=model,
    )


def _prompt(
    question: str, retrieved: list[Retrieved], feedback: list[str] | None = None
) -> str:
    lines = ["Clauses from this tenant's lease:", ""]
    for hit in retrieved:
        lines.append(format_clause(hit))
        lines.append("")
    lines.append(f"Question: {question}")
    if feedback:
        # Naming the specific claim that failed beats a generic 'be careful':
        # the model rewrites that sentence rather than hedging the whole answer.
        lines.append("")
        lines.append(
            "A previous attempt at this answer was rejected because these "
            "statements were not supported by the clauses above:"
        )
        lines.extend(f"- {item}" for item in feedback)
        lines.append(
            "Rewrite the answer using only what the clauses actually state. "
            "If they do not answer the question, return not_covered."
        )
    return "\n".join(lines)


def format_clause(hit: Retrieved) -> str:
    """Render one clause for a prompt, including its amendment history.

    When a clause supersedes another, the model is told so explicitly — it has
    to answer from the version that governs, and it also has to be able to say
    the terms changed, which is often the thing the tenant most needs to know.
    """
    heading = f" — {hit.clause.heading}" if hit.clause.heading else ""
    header = f"[{hit.clause.number}]{heading}"
    if hit.supersedes is not None:
        header += (
            f"  (amends clause {hit.supersedes.number}; the text below is what"
            " currently governs)"
        )
    return f"{header}\n{hit.clause.text}"


def _offline_draft(question: str, retrieved: list[Retrieved]) -> Draft:
    """Extractive stand-in when no model is configured.

    Quotes the best-matching clause verbatim rather than composing anything.
    It is trivially grounded by construction, which is the point: it keeps the
    pipeline and the eval harness runnable end to end without pretending to be
    a substitute for synthesis.
    """
    best = retrieved[0]
    return Draft(
        status=ANSWERED,
        answer=f"Your lease says, in clause [{best.clause.number}]: “{best.clause.text}”",
        citations=[best.clause.number],
        model="offline-extractive",
    )
