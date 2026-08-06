"""Initial schema: documents, clauses, embeddings, amendments, traces.

The amendments table ships in the first migration even though the override
detection that populates it lands in M5 — the edge is part of the data model,
and having the table from the start means the retrieval post-filter can be
written (and tested against an empty graph) before the writer exists.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op
from app.config import EMBEDDING_DIMENSIONS

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lease_id", sa.String(128), nullable=False, index=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("signed_date", sa.Date(), nullable=True),
        sa.Column("structure_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("strategy", sa.String(16), nullable=False, server_default="clause_tree"),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("kind in ('original','addendum')", name="ck_documents_kind"),
    )

    op.create_table(
        "clauses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("heading", sa.String(256), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "parent_id", UUID(as_uuid=True), sa.ForeignKey("clauses.id", ondelete="SET NULL")
        ),
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
        # Offsets into documents.full_text — these drive scroll-and-highlight.
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("clause_type", sa.String(32), nullable=False, server_default="other", index=True),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_clauses_document_number", "clauses", ["document_id", "number"], unique=True
    )

    op.create_table(
        "embeddings",
        sa.Column(
            "clause_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clauses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("vector", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
    )
    # IVFFlat needs training data to be worth building; at three synthetic
    # leases an exact scan is faster. Add the index when the corpus justifies it:
    #   CREATE INDEX ON embeddings USING ivfflat (vector vector_cosine_ops);

    op.create_table(
        "amendments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clause_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clauses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "superseded_by_clause_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clauses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("action", sa.String(16), nullable=False, server_default="amends"),
        sa.Column("detected_reason", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "traces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("lease_id", sa.String(128), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("retrieved", JSONB(), nullable=False, server_default="[]"),
        sa.Column("draft", JSONB(), nullable=False, server_default="{}"),
        sa.Column("gate_verdicts", JSONB(), nullable=False, server_default="[]"),
        sa.Column("final_answer", JSONB(), nullable=False, server_default="{}"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_versions", JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_table("traces")
    op.drop_table("amendments")
    op.drop_table("embeddings")
    op.drop_index("ix_clauses_document_number", table_name="clauses")
    op.drop_table("clauses")
    op.drop_table("documents")
