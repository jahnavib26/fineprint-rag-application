"""The grounding gate: verify a draft before anyone sees it.

Two calls, deliberately separate from the one that wrote the answer:

1. **Decompose** the draft into atomic claims, each tagged with the clause it
   cites. A sentence can carry two claims ("you may sublet [14(a)] but not
   short-term [14(b)]"), and they can have different support.
2. **Verify** each claim against the text of the clause it cites — yes, partial,
   or no. Any load-bearing "no" downgrades the whole answer to not_covered.

Two design decisions carry this:

**Verification is a separate call, not an instruction in the answer prompt.**
Asking a model to check a specific claim against a specific passage is a much
easier, more reliable task than asking it not to hallucinate while composing.
The gate doesn't need to know *why* a claim is unsupported to catch it.

**Support is judged semantically, not lexically.** The first version of this
gate rejected correct answers that paraphrased legalese into plain English —
"you can't rent it out on Airbnb" is fully supported by "shall not sublet on
any short-term basis, including through any hosting platform", and shares
almost no words with it. The prompt says so explicitly, because a plain
"is this supported?" reads as a word-matching task to a model too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.providers.llm import LLMUnavailable, object_schema
from app.providers.runtime import Providers
from app.retrieval.search import Retrieved
from app.synthesis.answer import Draft, not_covered

YES, PARTIAL, NO = "yes", "partial", "no"

_DECOMPOSE_SYSTEM = """You split a drafted answer about a lease into atomic \
factual claims so each can be checked separately.

- One claim per independently checkable fact. "You may sublet with 30 days' \
notice [14(a)], but never for less than 30 days [14(b)]" is two claims.
- Record the clause number(s) cited for each claim. If a claim carries no \
citation, return an empty list for it — an uncited factual claim is exactly \
what this pipeline needs to catch.
- Mark a claim load_bearing when the answer's usefulness depends on it. The \
direct answer to the question is load-bearing; incidental context and \
restatements of the question are not.
- Do not evaluate the claims. Only split them."""

_DECOMPOSE_SCHEMA = object_schema(
    {
        "claims": {
            "type": "array",
            "items": object_schema(
                {
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                    "load_bearing": {"type": "boolean"},
                },
                ["text", "citations", "load_bearing"],
            ),
        }
    },
    ["claims"],
)

_VERIFY_SYSTEM = """You check whether a lease clause supports a specific claim.

Judge meaning, not wording. The claim is written in plain English for a tenant; \
the clause is written in legalese. A correct paraphrase shares almost no \
vocabulary with the clause it paraphrases, and that is not a problem — \
"you can't rent it out on Airbnb for a weekend" is fully supported by "shall \
not sublet on any short-term basis, including through any hosting platform".

Verdicts:
- "yes"     — the clause states this, or it follows directly from what the \
clause states.
- "partial" — the clause supports part of the claim, or supports it with a \
condition or exception the claim omits.
- "no"      — the clause does not support the claim. Use this when the claim \
adds a specific the clause never states (a number, a deadline, a fee, an \
exception), even if the general topic matches. A claim that is plausible for \
leases in general but absent from this clause is "no".

Give a one-sentence reason. When the verdict is partial or no, say precisely \
what is missing or wrong."""

_VERIFY_SCHEMA = object_schema(
    {
        "verdicts": {
            "type": "array",
            "items": object_schema(
                {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": [YES, PARTIAL, NO]},
                    "reason": {"type": "string"},
                },
                ["index", "verdict", "reason"],
            ),
        }
    },
    ["verdicts"],
)


@dataclass
class Claim:
    text: str
    citations: list[str] = field(default_factory=list)
    load_bearing: bool = True


@dataclass
class Verdict:
    claim: str
    citations: list[str]
    verdict: str
    reason: str
    load_bearing: bool

    @property
    def failed(self) -> bool:
        return self.verdict == NO

    def to_trace(self) -> dict:
        return {
            "claim": self.claim,
            "citations": self.citations,
            "verdict": self.verdict,
            "reason": self.reason,
            "load_bearing": self.load_bearing,
        }


@dataclass
class GateResult:
    answer: Draft
    verdicts: list[Verdict] = field(default_factory=list)
    downgraded: bool = False
    downgrade_reason: str = ""

    def to_trace(self) -> list[dict]:
        return [v.to_trace() for v in self.verdicts]


async def gate(
    draft: Draft, retrieved: list[Retrieved], providers: Providers
) -> GateResult:
    """Verify a draft; downgrade it to not_covered if it doesn't hold up."""
    if not draft.is_covered:
        return GateResult(answer=draft)

    by_number = {hit.clause.number: hit for hit in retrieved}
    claims = await decompose(draft, providers)
    verdicts = await verify(claims, by_number, providers)

    failures = [v for v in verdicts if v.failed and v.load_bearing]
    if failures:
        return GateResult(
            answer=not_covered(
                nearest_topic=_nearest_topic(retrieved),
                model=draft.model,
            ),
            verdicts=verdicts,
            downgraded=True,
            downgrade_reason=failures[0].reason,
        )
    return GateResult(answer=draft, verdicts=verdicts)


async def decompose(draft: Draft, providers: Providers) -> list[Claim]:
    if providers.llm_available:
        try:
            result = await providers.require_llm().complete_json(
                model=providers.model_for("cheap"),
                system=_DECOMPOSE_SYSTEM,
                prompt=f"Drafted answer:\n\n{draft.answer}",
                schema=_DECOMPOSE_SCHEMA,
                max_tokens=1536,
            )
            claims = [
                Claim(
                    text=c["text"],
                    citations=[x for x in c.get("citations", []) if x],
                    load_bearing=bool(c.get("load_bearing", True)),
                )
                for c in result.get("claims", [])
                if c.get("text", "").strip()
            ]
            if claims:
                return claims
        except LLMUnavailable:
            pass
    return _split_sentences(draft)


async def verify(
    claims: list[Claim], by_number: dict[str, Retrieved], providers: Providers
) -> list[Verdict]:
    if not claims:
        return []
    if providers.llm_available:
        try:
            return await _verify_with_llm(claims, by_number, providers)
        except LLMUnavailable:
            pass
    return [_verify_lexically(c, by_number) for c in claims]


async def _verify_with_llm(
    claims: list[Claim], by_number: dict[str, Retrieved], providers: Providers
) -> list[Verdict]:
    result = await providers.require_llm().complete_json(
        model=providers.model_for("cheap"),
        system=_VERIFY_SYSTEM,
        prompt=_verify_prompt(claims, by_number),
        schema=_VERIFY_SCHEMA,
        max_tokens=2048,
    )
    scored = {v["index"]: v for v in result.get("verdicts", []) if "index" in v}
    out: list[Verdict] = []
    for i, claim in enumerate(claims):
        raw = scored.get(i)
        if raw is None:
            # A claim the verifier skipped is unverified, and unverified is not
            # the same as supported — fail closed.
            out.append(
                Verdict(claim.text, claim.citations, NO, "not evaluated", claim.load_bearing)
            )
            continue
        out.append(
            Verdict(
                claim=claim.text,
                citations=claim.citations,
                verdict=raw.get("verdict", NO),
                reason=raw.get("reason", ""),
                load_bearing=claim.load_bearing,
            )
        )
    return out


def _verify_prompt(claims: list[Claim], by_number: dict[str, Retrieved]) -> str:
    lines: list[str] = []
    for i, claim in enumerate(claims):
        lines.append(f"### Claim {i}")
        lines.append(claim.text)
        if not claim.citations:
            lines.append("\nCited clause: none — the answer cited nothing for this claim.")
        for number in claim.citations:
            hit = by_number.get(number)
            if hit is None:
                lines.append(f"\nCited clause [{number}]: NOT AMONG THE RETRIEVED CLAUSES.")
            else:
                lines.append(f"\nCited clause [{number}]:\n{hit.clause.text}")
        lines.append("")
    lines.append("Return one verdict per claim index above.")
    return "\n".join(lines)


def _split_sentences(draft: Draft) -> list[Claim]:
    """Offline claim decomposition: one claim per sentence, citations by regex.

    An inline citation governs until another replaces it — "…[15]. This does not
    apply to service animals." is two sentences about clause 15, not one cited
    claim followed by an uncited one. Carrying the citation forward matters:
    without it, every multi-sentence answer fails the gate on its own second
    sentence.
    """
    claims: list[Claim] = []
    current: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", draft.answer.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        cited = re.findall(r"\[([^\]]+)\]", sentence)
        if cited:
            current = cited
        claims.append(Claim(text=sentence, citations=cited or list(current)))
    return claims


_WORD = re.compile(r"[a-z0-9]+")


def _verify_lexically(claim: Claim, by_number: dict[str, Retrieved]) -> Verdict:
    """Offline verification: word overlap against the cited clause.

    This is the naive check the real gate exists to replace — it cannot tell a
    paraphrase from a fabrication, so it passes the extractive offline draft
    (which quotes verbatim) and little else. It keeps the pipeline runnable; it
    is not a measurement of grounding quality, and the eval report says so.
    """
    if not claim.citations:
        return Verdict(claim.text, [], NO, "no clause cited", claim.load_bearing)

    claim_words = {w for w in _WORD.findall(claim.text.lower()) if len(w) > 3}
    if not claim_words:
        return Verdict(claim.text, claim.citations, YES, "no checkable content", False)

    best = 0.0
    for number in claim.citations:
        hit = by_number.get(number)
        if hit is None:
            continue
        clause_words = {w for w in _WORD.findall(hit.clause.text.lower()) if len(w) > 3}
        if clause_words:
            best = max(best, len(claim_words & clause_words) / len(claim_words))

    verdict = YES if best >= 0.6 else PARTIAL if best >= 0.3 else NO
    return Verdict(
        claim=claim.text,
        citations=claim.citations,
        verdict=verdict,
        reason=f"lexical overlap {best:.2f} with cited clause (offline check)",
        load_bearing=claim.load_bearing,
    )


def _nearest_topic(retrieved: list[Retrieved]) -> str:
    """What the lease *does* talk about near the question — the useful half of
    a refusal. A bare "not covered" is honest; this makes it actionable."""
    for hit in retrieved:
        if hit.clause.heading:
            return hit.clause.heading.title()
    return retrieved[0].clause.clause_type if retrieved else ""
