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
from app.providers.embeddings import get_embedder


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
    clause_type: str | None = None,
    top_k: int | None = None,
) -> SearchResult:
    settings = get_settings()
    top_k = top_k or settings.top_k
    embedder = get_embedder()
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

    edges = (
        await session.execute(
            select(Amendment)
            .where(Amendment.clause_id.in_([h.clause.id for h in hits]))
            .options(selectinload(Amendment.superseded_by))
        )
    ).scalars()
    by_clause = {edge.clause_id: edge for edge in edges}
    if not by_clause:
        return hits

    out: list[Retrieved] = []
    seen: set = set()
    for hit in hits:
        edge = by_clause.get(hit.clause.id)
        if edge is None:
            if hit.clause.id not in seen:
                seen.add(hit.clause.id)
                out.append(hit)
            continue
        # Keep the amending clause's identity but the original's relevance score:
        # the question matched the original, and the amendment inherits that.
        replacement = edge.superseded_by
        if replacement.id in seen:
            continue
        seen.add(replacement.id)
        out.append(
            Retrieved(
                clause=replacement,
                score=hit.score,
                supersedes=hit.clause,
                superseded_reason=edge.detected_reason,
            )
        )
    return out
