"""The /ask path, end to end, with a trace row per request.

    retrieve → draft → gate → persist trace → respond

The trace is written on every request, including the ones that go fine. That's
the point: "it said something weird about my deposit" isn't a bug report, but a
row containing the question, the clauses retrieved and their scores, the answer
before the gate saw it, and the per-claim verdicts is one you can actually run
down. It costs one insert.

The eval harness calls ``answer_question`` directly rather than over HTTP, so
what the suite measures is the same code path the API serves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Trace
from app.graph import MAX_ATTEMPTS, final_answer, run_ask_graph
from app.providers.runtime import Providers
from app.retrieval.search import Retrieved
from app.synthesis import grounding
from app.synthesis.answer import Draft


@dataclass
class AskResult:
    question: str
    lease_id: str
    answer: Draft
    retrieved: list[Retrieved] = field(default_factory=list)
    verdicts: list[grounding.Verdict] = field(default_factory=list)
    downgraded: bool = False
    downgrade_reason: str = ""
    latency_ms: int = 0
    trace_id: str | None = None
    # How many drafts it took. >1 means the gate rejected one and the repair
    # loop rewrote it.
    attempts: int = 1
    history: list[dict] = field(default_factory=list)

    @property
    def is_covered(self) -> bool:
        return self.answer.is_covered


async def answer_question(
    session: AsyncSession,
    *,
    lease_id: str,
    question: str,
    providers: Providers,
    clause_type: str | None = None,
    persist_trace: bool = True,
) -> AskResult:
    started = time.perf_counter()

    state = await run_ask_graph(
        session,
        lease_id=lease_id,
        question=question,
        providers=providers,
        clause_type=clause_type,
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    result = AskResult(
        question=question,
        lease_id=lease_id,
        answer=final_answer(state),
        retrieved=state.get("retrieved", []),
        verdicts=state.get("verdicts", []),
        downgraded=state.get("downgraded", False),
        downgrade_reason=state.get("downgrade_reason", ""),
        latency_ms=latency_ms,
        attempts=state.get("attempts", 1),
        history=state.get("history", []),
    )

    if persist_trace:
        # The first draft, not the last: a downgrade is only diagnosable
        # against what the gate originally objected to.
        first = state.get("first_draft") or result.answer
        result.trace_id = str(await write_trace(session, result, first, providers))
    return result


async def write_trace(
    session: AsyncSession, result: AskResult, draft: Draft, providers: Providers
):
    trace = Trace(
        lease_id=result.lease_id,
        question=result.question,
        retrieved=[r.to_trace() for r in result.retrieved],
        draft=draft.to_trace(),  # pre-gate, so a downgrade can be diagnosed
        gate_verdicts=[v.to_trace() for v in result.verdicts],
        final_answer={
            **result.answer.to_trace(),
            "downgraded": result.downgraded,
            "downgrade_reason": result.downgrade_reason,
        },
        latency_ms=result.latency_ms,
        # describe() carries provider and model names but never key material.
        model_versions={
            **providers.describe(),
            "attempts": result.attempts,
            "max_attempts": MAX_ATTEMPTS,
            "repair_history": result.history,
        },
    )
    session.add(trace)
    await session.commit()
    return trace.id
