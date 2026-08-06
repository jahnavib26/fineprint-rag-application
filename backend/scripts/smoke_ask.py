"""Run the full /ask path against the ingested leases and print the traces.

    python scripts/smoke_ask.py

The M3 gate: an off-lease question returns not_covered, and the trace shows the
per-claim verdicts that produced it. Run scripts/smoke_retrieval.py first to
populate the database.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.pipeline import answer_question  # noqa: E402

QUESTIONS = [
    ("maple-court", "Can I have a cat?"),
    ("maple-court", "How much is my security deposit?"),
    ("maple-court", "Does my landlord pay my electric bill?"),
    ("maple-court", "Do I need renters insurance?"),
    ("birch-lane", "When do I get my deposit back after I move out?"),
]


async def main() -> int:
    settings = get_settings()
    print(
        f"llm: {settings.resolved_llm_provider()}  |  "
        f"embeddings: {settings.resolved_embedding_provider()}\n"
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        for lease_id, question in QUESTIONS:
            result = await answer_question(session, lease_id=lease_id, question=question)

            print(f"Q ({lease_id}): {question}")
            print(f"  retrieved: {[r.clause.number for r in result.retrieved] or '—'}")
            if result.is_covered:
                print(f"  ANSWER: {result.answer.answer[:180]}")
            else:
                topic = result.answer.nearest_topic or "—"
                print(f"  NOT COVERED (nearest topic: {topic})")
                if result.downgraded:
                    print(f"  ↓ downgraded by the gate: {result.downgrade_reason}")
            for v in result.verdicts:
                flag = {"yes": "✓", "partial": "~", "no": "✗"}.get(v.verdict, "?")
                cites = ",".join(v.citations) or "no citation"
                print(f"    {flag} [{cites}] {v.claim[:88]}")
            print(f"  {result.latency_ms}ms  trace={result.trace_id}\n")

    await get_engine().dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
