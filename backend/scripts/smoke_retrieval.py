"""Ingest the synthetic leases and run canned queries against them.

    python scripts/smoke_retrieval.py [--reset]

The M2 gate in one command: "can I have a cat?" must retrieve the pet clause,
not the parking clause. Prints the top hits per query with scores so a bad
retrieval is visible rather than inferred.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.ingestion.service import ingest_document  # noqa: E402
from app.retrieval.search import search  # noqa: E402

SYNTHETIC = Path(__file__).resolve().parents[2] / "data" / "synthetic"

DOCUMENTS = [
    ("maple-court", "maple-court-lease.pdf", "original", date(2024, 6, 1)),
    ("maple-court", "maple-court-addendum-1.pdf", "addendum", date(2024, 9, 15)),
    ("maple-court", "maple-court-addendum-2.pdf", "addendum", date(2025, 1, 10)),
    ("birch-lane", "birch-lane-lease.pdf", "original", date(2025, 2, 1)),
    ("messy-loft", "messy-loft-agreement.pdf", "original", date(2025, 3, 20)),
]

QUERIES = [
    ("maple-court", "Can I have a cat in the apartment?", None),
    ("maple-court", "Can I list my apartment on Airbnb for a weekend?", None),
    ("maple-court", "How long can a friend stay with me?", None),
    ("maple-court", "What happens if I pay rent late?", "fees"),
    ("maple-court", "How much is my security deposit?", "deposit"),
    ("maple-court", "Does my landlord pay my electric bill?", None),
    ("birch-lane", "When do I get my deposit back after moving out?", None),
]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete existing rows first")
    args = parser.parse_args()

    settings = get_settings()
    print(f"llm provider:       {settings.resolved_llm_provider()}")
    print(f"embedding provider: {settings.resolved_embedding_provider()}")
    print(f"embedding model:    {settings.resolved_embedding_model()}\n")

    sessionmaker = get_sessionmaker()

    if args.reset:
        async with sessionmaker() as session:
            await session.execute(text("TRUNCATE documents CASCADE"))
            await session.commit()

    async with sessionmaker() as session:
        for lease_id, filename, kind, signed in DOCUMENTS:
            doc = await ingest_document(
                session,
                path=SYNTHETIC / filename,
                lease_id=lease_id,
                kind=kind,
                signed_date=signed,
            )
            count = len(await doc.awaitable_attrs.clauses)
            print(
                f"ingested {filename:32} {count:3} clauses  "
                f"{doc.strategy:12} confidence={doc.structure_confidence:.2f}"
            )

    print()
    async with sessionmaker() as session:
        for lease_id, question, clause_type in QUERIES:
            result = await search(
                session, lease_id=lease_id, query=question, clause_type=clause_type, top_k=3
            )
            filter_note = f"  [type={clause_type}]" if clause_type else ""
            print(f"{lease_id}: {question}{filter_note}")
            if result.is_empty:
                print("    (nothing cleared the relevance floor → refusal)\n")
                continue
            for hit in result.results:
                arrow = f" (supersedes {hit.supersedes.number})" if hit.supersedes else ""
                heading = hit.clause.heading or hit.clause.text[:40]
                print(f"    {hit.score:.3f}  [{hit.clause.number}] {heading}{arrow}")
            print()

    await get_engine().dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
