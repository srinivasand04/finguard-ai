"""Compliance knowledge API: documents, hybrid search and citation-grounded Q&A."""
from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import AuditLog, ComplianceChunk, ComplianceDocument

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])
SessionDep = Annotated[Session, Depends(get_session)]
RAG_DISCLAIMER = ("Answers are generated from the indexed policy documents (synthetic FinGuard Bank policies and "
                  "paraphrased study notes). Always check the cited source; this is not legal advice.")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    k: int = Field(5, ge=1, le=10)
    mode: Literal["hybrid", "dense", "bm25"] = "hybrid"
    rerank: bool = True
    provider: Literal["auto", "anthropic", "openai", "ollama", "extractive"] | None = None
    doc_type: str | None = None


def _retriever(session: Session):
    from rag.retrieval import get_retriever

    if not session.scalar(select(func.count()).select_from(ComplianceChunk)):
        raise HTTPException(503, "Compliance index not built - run `python -m app.cli rag-build`")
    try:
        return get_retriever(session.get_bind())
    except Exception as e:  # Qdrant down, model missing, ...
        raise HTTPException(503, f"Retriever unavailable: {e}") from e


@router.get("/status", summary="Index size and which LLM provider would answer")
def status(session: SessionDep):
    from rag.llm import provider_status

    s = get_settings()
    return {"documents": session.scalar(select(func.count()).select_from(ComplianceDocument)) or 0,
            "chunks": session.scalar(select(func.count()).select_from(ComplianceChunk)) or 0,
            "embedding_model": s.embedding_model, "reranker_model": s.reranker_model or None,
            "vector_store": "qdrant", "collection": s.qdrant_collection, "llm": provider_status()}


@router.get("/documents", summary="Indexed compliance documents")
def documents(session: SessionDep):
    docs = session.scalars(select(ComplianceDocument).order_by(ComplianceDocument.doc_type, ComplianceDocument.title)).all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "source_path": d.source_path,
             "file_format": d.file_format, "pages": d.pages, "chunk_count": d.chunk_count, "synthetic": d.synthetic,
             "ingested_at": d.ingested_at} for d in docs]


@router.get("/documents/{doc_id}", summary="Document with its chunks (sections, pages)")
def document(doc_id: int, session: SessionDep):
    d = session.get(ComplianceDocument, doc_id)
    if not d:
        raise HTTPException(404, f"Document {doc_id} not found")
    chunks = session.scalars(select(ComplianceChunk).where(ComplianceChunk.document_id == doc_id)
                             .order_by(ComplianceChunk.chunk_index)).all()
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "source_path": d.source_path,
            "file_format": d.file_format, "pages": d.pages,
            "chunks": [{"id": c.id, "chunk_index": c.chunk_index, "section": c.section, "page": c.page,
                        "text": c.text} for c in chunks]}


@router.get("/search", summary="Retrieve passages (hybrid / dense / bm25, optional reranking)")
def search(session: SessionDep, q: str = Query(min_length=2, max_length=500), k: int = Query(5, ge=1, le=20),
           mode: Literal["hybrid", "dense", "bm25"] = "hybrid", rerank: bool = True, doc_type: str | None = None):
    r = _retriever(session)
    hits = r.search(q, k=k, mode=mode, rerank=rerank, doc_type=doc_type)
    return {"query": q, "mode": mode, "rerank": rerank and r.reranker is not None,
            "results": [{"chunk_id": h.chunk_id, "document_id": h.document_id, "title": h.title, "doc_type": h.doc_type,
                         "section": h.section, "page": h.page, "text": h.text, "scores": h.scores} for h in hits]}


@router.post("/ask", summary="Answer a compliance question with citations")
def ask(req: AskRequest, session: SessionDep):
    from rag.answer import answer_question

    r = _retriever(session)
    out = answer_question(r, req.question, k=req.k, mode=req.mode, rerank=req.rerank, provider=req.provider,
                          doc_type=req.doc_type)
    session.add(AuditLog(actor="api:anonymous", action="COMPLIANCE_QUESTION", entity_type="rag",
                         entity_id=out["provider"],
                         details={"question": out["question"], "answer_type": out["answer_type"], "cited": out["cited"],
                                  "sources": [s["chunk_id"] for s in out["sources"]], "warnings": out["warnings"],
                                  "latency_ms": out["latency_ms"]}))
    session.commit()
    return {**out, "disclaimer": RAG_DISCLAIMER}


@router.get("/evaluation", summary="Latest RAG evaluation results")
def evaluation():
    p = get_settings().models_dir / "rag" / "rag_evaluation_latest.json"
    if not p.exists():
        raise HTTPException(404, "No evaluation yet - run `python -m app.cli rag-eval`")
    data = json.loads(p.read_text())
    if "answers" in data:
        data["answers"] = {k: v for k, v in data["answers"].items() if k != "per_question"} | {
            "examples": data["answers"].get("per_question", [])[:5]}
    return data
