"""Ingest a document: parse → classify → embed → persist.

The clause tree is written in two passes because a clause's ``parent_id`` is a
foreign key to a row that may not exist yet — insert every clause first, then
resolve parents by printed number within the document. Printed numbers are only
unique per document (the lease and its addendum both have a clause "1"), which
is why the unique index is on ``(document_id, number)`` and every lookup here is
scoped to one document.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clause, Document, Embedding
from app.ingestion import classifier, pipeline
from app.ingestion.amendments import detect_amendments
from app.providers.runtime import Providers


async def ingest_document(
    session: AsyncSession,
    *,
    path: str | Path,
    lease_id: str,
    providers: Providers,
    kind: str = "original",
    signed_date: date | None = None,
    display_name: str | None = None,
) -> Document:
    # Uploads arrive at a temp path; display_name carries the name the user
    # chose, for both error messages and the stored filename.
    name = display_name or Path(path).name
    embedder = providers.embedder
    # Vectors from different embedding models aren't comparable, and cosine
    # across two spaces fails silently — plausible scores, meaningless order.
    # An addendum embedded differently from its lease would quietly corrupt
    # retrieval for that whole lease, so reject it before writing anything.
    await require_matching_embedding_space(session, lease_id, embedder.name)

    parsed = pipeline.parse(path, display_name=name)
    clauses = await classifier.classify(parsed.clauses, providers)

    document = Document(
        lease_id=lease_id,
        filename=name,
        kind=kind,
        signed_date=signed_date,
        structure_confidence=parsed.segmentation.confidence,
        strategy=parsed.segmentation.strategy,
        full_text=parsed.document.full_text,
    )
    session.add(document)
    await session.flush()  # assigns document.id

    rows = [
        Clause(
            document_id=document.id,
            number=c.number,
            heading=c.heading,
            text=c.text,
            page=c.page,
            char_start=c.char_start,
            char_end=c.char_end,
            clause_type=c.clause_type or "other",
            ordinal=i,
        )
        for i, c in enumerate(clauses)
    ]
    session.add_all(rows)
    await session.flush()  # assigns clause ids

    by_number = {row.number: row for row in rows}
    for source, row in zip(clauses, rows, strict=True):
        if source.parent_number:
            parent = by_number.get(source.parent_number)
            if parent is not None:
                row.parent_id = parent.id

    # Container nodes (ARTICLE II, whose own text ends where its first child
    # begins) hold a heading and nothing else. Embedding them makes a heading
    # like "SECURITY DEPOSIT" an near-exact match for a deposit question, which
    # outranks the clauses that actually answer it. They stay in the tree for
    # structure and citation context; they just aren't retrievable.
    retrievable = [row for row in rows if row.text.strip()]

    vectors = await embedder.embed_documents([embedding_text(c) for c in retrievable])
    session.add_all(
        Embedding(clause_id=row.id, vector=vector, model=embedder.name)
        for row, vector in zip(retrievable, vectors, strict=True)
    )

    await session.commit()

    if kind == "addendum":
        # Rebuild the whole lease's override graph rather than just this
        # document's edges: an addendum can amend an earlier addendum, and the
        # ordering only resolves with every document present.
        await detect_amendments(session, lease_id, providers)

    return document


class EmbeddingSpaceMismatch(ValueError):
    """A document was embedded with a different model than the rest of its lease."""


async def lease_embedding_model(session: AsyncSession, lease_id: str) -> str | None:
    """Which embedding model this lease's existing vectors were built with."""
    return (
        await session.execute(
            select(Embedding.model)
            .join(Clause, Clause.id == Embedding.clause_id)
            .join(Document, Document.id == Clause.document_id)
            .where(Document.lease_id == lease_id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def require_matching_embedding_space(
    session: AsyncSession, lease_id: str, model: str
) -> None:
    """Refuse to add a document embedded in a different space than its lease.

    This matters most in bring-your-own-key mode, where the provider is chosen
    per request: uploading a lease with one provider and its addendum with
    another would leave one lease holding two incompatible vector spaces.
    Cosine between them still returns numbers, so nothing errors — retrieval
    just silently ranks by noise. Failing the upload is the only honest option,
    because the alternative is a system that looks like it works.
    """
    existing = await lease_embedding_model(session, lease_id)
    if existing is not None and existing != model:
        raise EmbeddingSpaceMismatch(
            f"This lease was indexed with '{existing}', but this upload would use "
            f"'{model}'. Vectors from different embedding models can't be compared, "
            f"so mixing them would silently break search for this lease. Use the same "
            f"embedding provider as the rest of the lease, or start a new lease id."
        )


def embedding_text(clause: Clause) -> str:
    """What actually gets embedded.

    The number and heading go into the vector alongside the body so structural
    context survives into the embedding — "15 PETS" carries topic signal that a
    clause opening "No dog, cat, or other animal shall be kept" states only
    obliquely, and sub-items like 14(b) inherit their parent's subject.
    """
    parts = [clause.number]
    if clause.heading:
        parts.append(clause.heading)
    parts.append(clause.text)
    return "\n".join(parts)


async def lease_documents(session: AsyncSession, lease_id: str) -> list[Document]:
    result = await session.execute(
        select(Document).where(Document.lease_id == lease_id).order_by(Document.signed_date)
    )
    return list(result.scalars())
