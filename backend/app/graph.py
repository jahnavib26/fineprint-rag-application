"""The /ask pipeline as a LangGraph state machine, with a repair loop.

Before this, a failed grounding gate discarded the answer outright: one
unsupported sentence and the tenant got "your lease doesn't address this", even
when the lease plainly did and the draft had merely overreached. That is safe
but blunt, and it trades a wrong answer for a wrong refusal — the eval suite
calls the second one a false refusal and counts it as a failure too.

A human wouldn't give up there; they'd rewrite the sentence. So the gate's
verdict now routes:

    retrieve → draft → gate ─┬─ passes ─────────────────→ answer
                             ├─ fails, attempts < MAX ──→ repair → draft
                             └─ fails, attempts = MAX ──→ refuse

That back-edge is the reason this is a graph rather than a function. LangGraph
owns the state, the branch, and the cycle; the nodes are the same retrieval,
drafting, and gating functions the rest of the system already uses, so the
graph adds control flow and nothing else.

The bound matters. Without it a model that keeps making the same unsupported
claim would loop until something else stopped it, and each turn costs a draft
plus a full gate pass. Two attempts is enough for "you overreached on one
sentence" and cheap enough to be worth trying.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.runtime import Providers
from app.retrieval.search import Retrieved, search
from app.synthesis import grounding
from app.synthesis.answer import Draft, not_covered
from app.synthesis.answer import draft_answer as write_draft

# One repair attempt after the first failure. Raising this buys little: a claim
# that survives one round of specific feedback is usually one the clauses
# genuinely don't support.
MAX_ATTEMPTS = 2


class AskState(TypedDict, total=False):
    # Inputs
    question: str
    lease_id: str
    clause_type: str | None
    providers: Providers
    session: AsyncSession

    # Working state
    retrieved: list[Retrieved]
    draft: Draft
    first_draft: Draft  # kept for the trace: what the gate originally saw
    verdicts: list[grounding.Verdict]
    feedback: list[str]
    attempts: int

    # Outputs
    answer: Draft
    downgraded: bool
    downgrade_reason: str
    # Appended rather than replaced, so the trace shows every repair attempt
    # instead of only the last one.
    history: Annotated[list[dict], operator.add]


async def retrieve_node(state: AskState) -> dict:
    found = await search(
        state["session"],
        lease_id=state["lease_id"],
        query=state["question"],
        providers=state["providers"],
        clause_type=state.get("clause_type"),
    )
    return {"retrieved": found.results, "attempts": 0, "feedback": [], "history": []}


async def draft_node(state: AskState) -> dict:
    draft = await write_draft(
        state["question"],
        state["retrieved"],
        state["providers"],
        feedback=state.get("feedback") or None,
    )
    update: dict = {"draft": draft, "attempts": state.get("attempts", 0) + 1}
    if state.get("attempts", 0) == 0:
        update["first_draft"] = draft
    return update


async def gate_node(state: AskState) -> dict:
    checked = await grounding.gate(state["draft"], state["retrieved"], state["providers"])
    failures = [
        v for v in checked.verdicts if v.failed and v.load_bearing
    ]
    return {
        "verdicts": checked.verdicts,
        "downgraded": checked.downgraded,
        "downgrade_reason": checked.downgrade_reason,
        # The gate already produced the downgraded answer; keep it in case this
        # turns out to be the final attempt.
        "answer": checked.answer,
        "feedback": [f"{v.claim} ({v.reason})" for v in failures],
        "history": [
            {
                "attempt": state.get("attempts", 1),
                "status": state["draft"].status,
                "failed_claims": [v.claim for v in failures],
            }
        ],
    }


async def repair_node(state: AskState) -> dict:
    """A no-op on state: the feedback the next draft needs was set by the gate.

    It exists as a named node so the cycle is visible in the graph — an edge
    labelled "repair" reads far better than draft pointing at itself.
    """
    return {}


def route_after_gate(state: AskState) -> str:
    """Pass, repair, or give up."""
    if not state.get("downgraded"):
        return "accept"
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        return "give_up"
    if not state.get("feedback"):
        # Downgraded with nothing specific to fix — rewriting would be guessing.
        return "give_up"
    return "repair"


def build_graph():
    graph = StateGraph(AskState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("draft", draft_node)
    graph.add_node("gate", gate_node)
    graph.add_node("repair", repair_node)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", "gate")
    graph.add_conditional_edges(
        "gate",
        route_after_gate,
        {"accept": END, "give_up": END, "repair": "repair"},
    )
    graph.add_edge("repair", "draft")  # the cycle
    return graph.compile()


# Compiled once at import: the topology is static, only the state varies.
ASK_GRAPH = build_graph()


async def run_ask_graph(
    session: AsyncSession,
    *,
    lease_id: str,
    question: str,
    providers: Providers,
    clause_type: str | None = None,
) -> AskState:
    return await ASK_GRAPH.ainvoke(
        {
            "session": session,
            "lease_id": lease_id,
            "question": question,
            "providers": providers,
            "clause_type": clause_type,
        }
    )


def final_answer(state: AskState) -> Draft:
    """The answer to show, whichever branch the graph took."""
    return state.get("answer") or not_covered()
