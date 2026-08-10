"""The repair loop.

These exercise the branch the offline providers can never reach: the lexical
gate passes verbatim quotes, so a real gate failure needs a model that
overreaches. Stub completers stand in for one, which also makes the loop's
*shape* testable without spending a request — the property under test is the
control flow, not the model.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.graph import MAX_ATTEMPTS, route_after_gate, run_ask_graph
from app.providers.runtime import Providers
from app.retrieval.search import Retrieved


class _ScriptedCompleter:
    """Returns a queued response per call, recording the prompts it saw."""

    name = "scripted"

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def complete_json(self, *, model, system, prompt, schema, max_tokens) -> Any:
        self.prompts.append(prompt)
        return self._responses.pop(0) if self._responses else {}


def _providers(completer) -> Providers:
    from app.providers.embeddings import HashingEmbedder

    return Providers(
        llm=completer,
        embedder=HashingEmbedder(),
        cheap_model="cheap",
        smart_model="smart",
        source="test",
    )


# --- routing ---------------------------------------------------------------


def test_a_clean_gate_accepts():
    assert route_after_gate({"downgraded": False, "attempts": 1}) == "accept"


def test_a_failed_gate_with_budget_left_repairs():
    state = {"downgraded": True, "attempts": 1, "feedback": ["unsupported claim"]}
    assert route_after_gate(state) == "repair"


def test_the_loop_is_bounded():
    """Without this, a model that keeps making the same claim never terminates."""
    state = {"downgraded": True, "attempts": MAX_ATTEMPTS, "feedback": ["still wrong"]}
    assert route_after_gate(state) == "give_up"


def test_a_downgrade_with_nothing_to_fix_gives_up():
    """Rewriting without a specific objection is guessing, so don't pay for it."""
    assert route_after_gate({"downgraded": True, "attempts": 1, "feedback": []}) == "give_up"


# --- the cycle, end to end -------------------------------------------------


@pytest.fixture
def clauses(monkeypatch):
    """Bypass the database: this suite is about control flow, not retrieval."""
    from types import SimpleNamespace

    clause = SimpleNamespace(
        id="c1",
        number="14(b)",
        heading="SUBLETTING",
        text="Tenant shall not sublet the premises for any term of less than thirty days.",
        clause_type="subletting",
        document=SimpleNamespace(kind="original"),
    )
    hits = [Retrieved(clause=clause, score=0.9)]

    async def fake_search(*_args, **_kwargs):
        from app.retrieval.search import SearchResult

        return SearchResult(results=hits)

    monkeypatch.setattr("app.graph.search", fake_search)
    return hits


async def test_a_rejected_draft_is_rewritten_not_discarded(clauses):
    """The whole point: one bad sentence shouldn't cost the tenant the answer."""
    drafter = _ScriptedCompleter(
        [
            # attempt 1 — overreaches
            {
                "status": "answered",
                "answer": "No, and you will be fined $500. [14(b)]",
                "citations": ["14(b)"],
                "nearest_topic": "",
            },
            # decompose
            {"claims": [{"text": "You will be fined $500.", "citations": ["14(b)"],
                         "load_bearing": True}]},
            # verify → fails
            {"verdicts": [{"index": 0, "verdict": "no", "reason": "no fine is stated"}]},
            # attempt 2 — corrected
            {
                "status": "answered",
                "answer": "No, subletting for under thirty days is prohibited. [14(b)]",
                "citations": ["14(b)"],
                "nearest_topic": "",
            },
            {"claims": [{"text": "Subletting under thirty days is prohibited.",
                         "citations": ["14(b)"], "load_bearing": True}]},
            {"verdicts": [{"index": 0, "verdict": "yes", "reason": "clause states it"}]},
        ]
    )
    state = await run_ask_graph(
        None, lease_id="x", question="Can I sublet for a weekend?",
        providers=_providers(drafter),
    )

    assert state["attempts"] == 2, "should have drafted twice"
    assert state["answer"].status == "answered", "the second draft should survive"
    assert "fined" not in state["answer"].answer
    # The rewrite must be told what was wrong, not just told to try again.
    assert "no fine is stated" in drafter.prompts[3]


async def test_the_first_draft_is_kept_for_the_trace(clauses):
    """A downgrade is only diagnosable against what the gate objected to."""
    drafter = _ScriptedCompleter(
        [
            {"status": "answered", "answer": "Yes, freely. [14(b)]",
             "citations": ["14(b)"], "nearest_topic": ""},
            {"claims": [{"text": "You may sublet freely.", "citations": ["14(b)"],
                         "load_bearing": True}]},
            {"verdicts": [{"index": 0, "verdict": "no", "reason": "clause prohibits it"}]},
            {"status": "answered", "answer": "Yes, freely. [14(b)]",
             "citations": ["14(b)"], "nearest_topic": ""},
            {"claims": [{"text": "You may sublet freely.", "citations": ["14(b)"],
                         "load_bearing": True}]},
            {"verdicts": [{"index": 0, "verdict": "no", "reason": "clause prohibits it"}]},
        ]
    )
    state = await run_ask_graph(
        None, lease_id="x", question="Can I sublet?", providers=_providers(drafter)
    )

    assert state["attempts"] == MAX_ATTEMPTS
    assert state["answer"].status == "not_covered", "an unfixable claim still refuses"
    assert state["first_draft"].answer.startswith("Yes, freely")
    assert len(state["history"]) == MAX_ATTEMPTS, "every attempt is recorded"
