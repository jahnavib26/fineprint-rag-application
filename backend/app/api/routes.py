"""HTTP surface: upload a lease, ask a question, read a trace.

Response shapes are built for the UI's two hard requirements — a citation chip
must carry the offsets needed to scroll and highlight the clause in the document
pane, and a refusal must arrive as structured data (nearest topic, nearby
clauses) rather than an error, because it is a first-class answer.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Clause, Document, Trace
from app.db.session import get_session
from app.ingestion.pdf import ScannedPdfError
from app.ingestion.service import ingest_document, lease_documents
from app.pipeline import answer_question

router = APIRouter()


class ClauseOut(BaseModel):
    id: str
    number: str
    heading: str
    text: str
    page: int
    char_start: int
    char_end: int
    clause_type: str
    document_id: str

    @classmethod
    def of(cls, clause: Clause) -> ClauseOut:
        return cls(
            id=str(clause.id),
            number=clause.number,
            heading=clause.heading,
            text=clause.text,
            page=clause.page,
            char_start=clause.char_start,
            char_end=clause.char_end,
            clause_type=clause.clause_type,
            document_id=str(clause.document_id),
        )


class DocumentOut(BaseModel):
    id: str
    lease_id: str
    filename: str
    kind: str
    signed_date: date | None
    structure_confidence: float
    strategy: str
    clause_count: int

    @classmethod
    def of(cls, document: Document, clause_count: int) -> DocumentOut:
        return cls(
            id=str(document.id),
            lease_id=document.lease_id,
            filename=document.filename,
            kind=document.kind,
            signed_date=document.signed_date,
            structure_confidence=document.structure_confidence,
            strategy=document.strategy,
            clause_count=clause_count,
        )


class CitationOut(BaseModel):
    """A retrieved clause as the UI needs it: enough to highlight, plus its
    amendment history so a citation can render "originally X, amended to Y"."""

    clause: ClauseOut
    score: float
    supersedes: ClauseOut | None = None
    superseded_reason: str = ""


class VerdictOut(BaseModel):
    claim: str
    citations: list[str]
    verdict: str
    reason: str
    load_bearing: bool


class AnswerOut(BaseModel):
    status: str  # answered | not_covered
    answer: str
    citations: list[CitationOut]
    nearest_topic: str
    # True when the gate rejected a drafted answer. The UI says so plainly
    # rather than hiding it: "we found something but couldn't verify it" is
    # different from "your lease is silent", and tenants deserve the difference.
    downgraded: bool
    downgrade_reason: str
    verdicts: list[VerdictOut]
    latency_ms: int
    trace_id: str | None


class AskIn(BaseModel):
    question: str
    clause_type: str | None = None


@router.post("/documents", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    lease_id: str = Form(...),
    kind: str = Form("original"),
    signed_date: date | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    if kind not in ("original", "addendum"):
        raise HTTPException(400, "kind must be 'original' or 'addendum'")

    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        document = await ingest_document(
            session,
            path=tmp_path,
            lease_id=lease_id,
            kind=kind,
            signed_date=signed_date,
        )
    except ScannedPdfError as exc:
        # A scan isn't a server error — it's a document we can't read yet, and
        # the tenant needs to know which.
        raise HTTPException(422, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    document.filename = file.filename or document.filename
    clauses = await document.awaitable_attrs.clauses
    return DocumentOut.of(document, len(clauses))


@router.get("/leases/{lease_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    lease_id: str, session: AsyncSession = Depends(get_session)
) -> list[DocumentOut]:
    documents = await lease_documents(session, lease_id)
    out = []
    for document in documents:
        clauses = await document.awaitable_attrs.clauses
        out.append(DocumentOut.of(document, len(clauses)))
    return out


@router.get("/documents/{document_id}/text")
async def document_text(
    document_id: UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    """The extracted text the document pane renders, with clause spans.

    The UI highlights by character offset into this exact string, so it must be
    served from the same stored text the offsets were computed against.
    """
    document = await session.get(
        Document, document_id, options=[selectinload(Document.clauses)]
    )
    if document is None:
        raise HTTPException(404, "document not found")
    clauses = sorted(document.clauses, key=lambda c: c.ordinal)
    return {
        "id": str(document.id),
        "filename": document.filename,
        "full_text": document.full_text,
        "clauses": [ClauseOut.of(c).model_dump() for c in clauses],
    }


@router.post("/leases/{lease_id}/ask", response_model=AnswerOut)
async def ask(
    lease_id: str, body: AskIn, session: AsyncSession = Depends(get_session)
) -> AnswerOut:
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "question must not be empty")

    result = await answer_question(
        session, lease_id=lease_id, question=question, clause_type=body.clause_type
    )

    cited = set(result.answer.citations)
    citations = [
        CitationOut(
            clause=ClauseOut.of(hit.clause),
            score=hit.score,
            supersedes=ClauseOut.of(hit.supersedes) if hit.supersedes else None,
            superseded_reason=hit.superseded_reason,
        )
        # On a refusal there is nothing cited, so send the nearby clauses
        # instead — they're what makes "your lease doesn't say" actionable.
        for hit in result.retrieved
        if not cited or hit.clause.number in cited
    ]

    return AnswerOut(
        status=result.answer.status,
        answer=result.answer.answer,
        citations=citations,
        nearest_topic=result.answer.nearest_topic,
        downgraded=result.downgraded,
        downgrade_reason=result.downgrade_reason,
        verdicts=[VerdictOut(**v.to_trace()) for v in result.verdicts],
        latency_ms=result.latency_ms,
        trace_id=result.trace_id,
    )


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
    trace = await session.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(404, "trace not found")
    return {
        "id": str(trace.id),
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
        "lease_id": trace.lease_id,
        "question": trace.question,
        "retrieved": trace.retrieved,
        "draft": trace.draft,
        "gate_verdicts": trace.gate_verdicts,
        "final_answer": trace.final_answer,
        "latency_ms": trace.latency_ms,
        "model_versions": trace.model_versions,
    }


@router.get("/traces")
async def list_traces(
    lease_id: str | None = None, limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    stmt = select(Trace).order_by(Trace.created_at.desc()).limit(min(limit, 200))
    if lease_id:
        stmt = stmt.where(Trace.lease_id == lease_id)
    traces = (await session.execute(stmt)).scalars()
    return [
        {
            "id": str(t.id),
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "lease_id": t.lease_id,
            "question": t.question,
            "status": (t.final_answer or {}).get("status"),
            "downgraded": (t.final_answer or {}).get("downgraded", False),
            "latency_ms": t.latency_ms,
        }
        for t in traces
    ]
