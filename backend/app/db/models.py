"""SQLAlchemy models.

One database for everything — clause text, vectors, override edges, and traces —
so a trace can join straight back to the exact clause rows a bad answer used.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import EMBEDDING_DIMENSIONS

CLAUSE_TYPES = (
    "deposit",
    "subletting",
    "termination",
    "fees",
    "maintenance",
    "pets",
    "other",
)

EMBEDDING_DIM = EMBEDDING_DIMENSIONS


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    lease_id: Mapped[str] = mapped_column(String(128), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(16))  # original | addendum
    signed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 0..1 from the segmenter; drives the "low structure confidence" UI badge
    structure_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    strategy: Mapped[str] = mapped_column(String(16), default="clause_tree")
    full_text: Mapped[str] = mapped_column(Text)  # what the document pane renders
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clauses: Mapped[list[Clause]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("kind in ('original','addendum')", name="ck_documents_kind"),
    )


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[str] = mapped_column(String(32))
    heading: Mapped[str] = mapped_column(String(256), default="")
    text: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clauses.id", ondelete="SET NULL"), nullable=True
    )
    page: Mapped[int] = mapped_column(Integer, default=1)
    # Offsets into Document.full_text — these drive scroll-and-highlight in the UI.
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    clause_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)  # printed order

    document: Mapped[Document] = relationship(back_populates="clauses")
    embedding: Mapped[Embedding | None] = relationship(
        back_populates="clause", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        Index("ix_clauses_document_number", "document_id", "number", unique=True),
    )

    @property
    def citation(self) -> str:
        """What the model is told to cite and the UI renders as a chip."""
        return self.number


class Embedding(Base):
    __tablename__ = "embeddings"

    clause_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clauses.id", ondelete="CASCADE"), primary_key=True
    )
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    model: Mapped[str] = mapped_column(String(64))

    clause: Mapped[Clause] = relationship(back_populates="embedding")


class Amendment(Base):
    """An addendum clause that supersedes an original clause (M5).

    Stored as an edge rather than by mutating the original, because the UI has to
    be able to say "originally X, amended to Y" — and because an eval that only
    checks the final answer can't tell a correct override from a lucky retrieval.
    """

    __tablename__ = "amendments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    clause_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clauses.id", ondelete="CASCADE"), index=True
    )
    superseded_by_clause_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clauses.id", ondelete="CASCADE")
    )
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    action: Mapped[str] = mapped_column(String(16), default="amends")  # amends | replaces
    detected_reason: Mapped[str] = mapped_column(Text, default="")


class Trace(Base):
    """One row per /ask. The reason a bad answer is debuggable after the fact."""

    __tablename__ = "traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_id: Mapped[str] = mapped_column(String(128), index=True)
    question: Mapped[str] = mapped_column(Text)
    retrieved: Mapped[list] = mapped_column(JSONB, default=list)  # [{clause_id, number, score}]
    draft: Mapped[dict] = mapped_column(JSONB, default=dict)  # pre-gate answer
    gate_verdicts: Mapped[list] = mapped_column(JSONB, default=list)  # per-claim yes/partial/no
    final_answer: Mapped[dict] = mapped_column(JSONB, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    model_versions: Mapped[dict] = mapped_column(JSONB, default=dict)
