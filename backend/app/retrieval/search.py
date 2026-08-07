"""Clause retrieval: vector search, then an amendment-aware post-filter.

The override walk runs *after* the vector search, not inside it. Semantic search
will correctly surface the original deposit clause — it is the best match for a
question about deposits — and only then does the graph tell us that an addendum
superseded it. Doing this as a post-filter keeps the vector index simple, keeps
the override logic independently testable, and preserves both clauses so the
answer can say "originally X, amended to Y" instead of silently swapping.

Until M5 populates the ``amendments`` table this walk is a no-op over an empty
graph, which is deliberate: the eval suite's override cases fail against it, and
that failure is the regression fixture proving M5 works.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import Amendment, Clause, Document, Embedding
from app.providers.runtime import Providers


@dataclass
class Retrieved:
    """A clause that survived retrieval, plus how it got here."""

    clause: Clause
    score: float
    # Set when this clause replaced one the vector search actually matched.
    supersedes: Clause | None = None
    superseded_reason: str = ""

    @property
    def citation(self) -> str:
        return self.clause.number

    def to_trace(self) -> dict:
        entry = {
            "clause_id": str(self.clause.id),
            "number": self.clause.number,
            "clause_type": self.clause.clause_type,
            "score": round(self.score, 4),
        }
        if self.supersedes is not None:
            entry["supersedes"] = self.supersedes.number
            entry["superseded_reason"] = self.superseded_reason
        return entry


@dataclass
class SearchResult:
    results: list[Retrieved] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Nothing cleared the relevance floor — refuse without asking a model."""
        return not self.results

    def to_trace(self) -> list[dict]:
        return [r.to_trace() for r in self.results]


async def search(
    session: AsyncSession,
    *,
    lease_id: str,
    query: str,
    providers: Providers,
    clause_type: str | None = None,
    top_k: int | None = None,
) -> SearchResult:
    settings = get_settings()
    top_k = top_k or settings.top_k
    embedder = providers.embedder
    floor = settings.min_similarity
    if floor is None:
        floor = embedder.relevance_floor

    vector = await embedder.embed_query(query)
    distance = Embedding.vector.cosine_distance(vector)

    stmt = (
        select(Clause, distance.label("distance"))
        .join(Embedding, Embedding.clause_id == Clause.id)
        .join(Document, Document.id == Clause.document_id)
        .where(Document.lease_id == lease_id)
        .options(selectinload(Clause.document))
        .order_by(distance)
        .limit(top_k)
    )
    if clause_type:
        stmt = stmt.where(Clause.clause_type == clause_type)

    rows = (await session.execute(stmt)).all()

    hits = [
        Retrieved(clause=clause, score=1.0 - float(dist))
        for clause, dist in rows
        if 1.0 - float(dist) >= floor
    ]
    return SearchResult(results=await apply_overrides(session, hits))


async def apply_overrides(session: AsyncSession, hits: list[Retrieved]) -> list[Retrieved]:
    """Swap superseded clauses for the ones that actually govern.

    Both clauses stay in the payload — dropping the original would make the
    override invisible in the trace, and an eval that only checks the final
    answer can't tell a correct override from a lucky retrieval.
    """
    if not hits:
        return hits

    out: list[Retrieved] = []
    seen: set = set()
    for hit in hits:
        governing, original, reason = await _follow_chain(session, hit.clause)
        if governing.id in seen:
            # The amendment was already pulled in by another hit — or was
            # itself retrieved directly, which is common: it's about the same
            # topic, so it usually ranks too.
            continue
        seen.add(governing.id)
        if original is None:
            out.append(hit)
        else:
            # Keep the amending clause's identity but the original's relevance
            # score: the question matched the original, and the clause that
            # replaced it inherits that relevance.
            out.append(
                Retrieved(
                    clause=governing,
                    score=hit.score,
                    supersedes=original,
                    superseded_reason=reason,
                )
            )
    return out


# An addendum can amend an earlier addendum, so the walk follows the chain to
# whatever governs now. Bounded because a cycle in the graph (a detector
# hallucinating a mutual override) would otherwise hang the request.
MAX_OVERRIDE_DEPTH = 8


async def _follow_chain(
    session: AsyncSession, clause: Clause
) -> tuple[Clause, Clause | None, str]:
    """Return (governing clause, the clause it replaced or None, reason)."""
    original: Clause | None = None
    reason = ""
    current = clause
    visited = {clause.id}

    for _ in range(MAX_OVERRIDE_DEPTH):
        edge = (
            await session.execute(
                select(Amendment)
                .where(Amendment.clause_id == current.id)
                .options(selectinload(Amendment.superseded_by))
                .order_by(Amendment.effective_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if edge is None or edge.superseded_by.id in visited:
            break
        if original is None:
            original = clause  # report what the *question* actually matched
            reason = edge.detected_reason
        current = edge.superseded_by
        visited.add(current.id)

    return current, original, reason
