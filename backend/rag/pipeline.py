"""Index build: corpus files -> extraction -> chunks (Postgres) -> embeddings (Qdrant)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from qdrant_client import models
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, ComplianceChunk, ComplianceDocument
from rag.corpus import doc_type_for, write_corpus
from rag.documents import SUPPORTED, chunk_segments, extract
from rag.embeddings import get_embedder
from rag.retrieval import get_retriever, qdrant_client


def build_index(engine: Engine, regenerate_corpus: bool = True) -> dict:
    s = get_settings()
    started = datetime.now()
    root = Path(s.documents_dir)
    if regenerate_corpus:
        write_corpus(root)
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in SUPPORTED and p.is_file())

    with Session(engine) as session:
        session.execute(delete(ComplianceChunk))
        session.execute(delete(ComplianceDocument))
        seen: set[str] = set()
        report = []
        for f in files:
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            if sha in seen:                      # identical file stored twice
                continue
            seen.add(sha)
            segments, pages = extract(f)
            chunks = chunk_segments(segments)
            doc_type, title = doc_type_for(f)
            doc = ComplianceDocument(title=title or f.stem.replace("_", " ").title(), doc_type=doc_type,
                                     source_path=f.relative_to(root).as_posix(), file_format=f.suffix.lstrip(".").lower(),
                                     pages=pages, sha256=sha, chunk_count=len(chunks), synthetic=title is not None)
            session.add(doc)
            session.flush()
            for c in chunks:
                session.add(ComplianceChunk(document_id=doc.id, chunk_index=c.chunk_index, section=c.section,
                                            page=c.page, text=c.text, char_count=len(c.text)))
            report.append({"file": doc.source_path, "format": doc.file_format, "pages": pages,
                           "sections": len({c.section for c in chunks}), "chunks": len(chunks)})
        session.commit()

        rows = session.query(ComplianceChunk, ComplianceDocument).join(
            ComplianceDocument, ComplianceDocument.id == ComplianceChunk.document_id).order_by(ComplianceChunk.id).all()
        embedder = get_embedder(s.embedding_model)
        # embed title + section with the text so short passages keep their context
        vectors = embedder.embed([f"{d.title}. {c.section or ''}. {c.text}" for c, d in rows]) if rows else []
        client = qdrant_client(s.qdrant_url)
        if client.collection_exists(s.qdrant_collection):
            client.delete_collection(s.qdrant_collection)
        client.create_collection(s.qdrant_collection,
                                 vectors_config=models.VectorParams(size=embedder.dim, distance=models.Distance.COSINE))
        if s.qdrant_url != ":memory:":           # payload indexes only exist on a real Qdrant server
            client.create_payload_index(s.qdrant_collection, "doc_type", models.PayloadSchemaType.KEYWORD)
        if rows:
            client.upsert(s.qdrant_collection, points=[
                models.PointStruct(id=c.id, vector=v.tolist(), payload={
                    "document_id": d.id, "title": d.title, "doc_type": d.doc_type, "section": c.section,
                    "page": c.page, "chunk_index": c.chunk_index})
                for (c, d), v in zip(rows, vectors)])
        summary = {"documents": len(report), "chunks": len(rows), "embedding_model": embedder.name,
                   "embedding_dim": embedder.dim, "qdrant_collection": s.qdrant_collection,
                   "duration_seconds": round((datetime.now() - started).total_seconds(), 1), "files": report}
        session.add(AuditLog(actor="system:rag", action="RAG_INDEX_BUILT", entity_type="collection",
                             entity_id=s.qdrant_collection, details=json.loads(json.dumps(summary, default=str))))
        session.commit()
    get_retriever(engine, refresh=True)
    return summary
