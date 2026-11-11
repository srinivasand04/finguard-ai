"""Hybrid retrieval: dense vectors (Qdrant) + BM25 keywords, fused with Reciprocal
Rank Fusion, then optionally reranked by a cross-encoder.

Why hybrid: dense embeddings catch paraphrases ("splitting deposits" ~ "structuring")
while BM25 catches exact terms that matter in compliance ("EUR 15,000", "PEP",
"Recommendation 16"). RRF combines the two rankings without having to calibrate
their very different score scales.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import get_settings
from rag.embeddings import get_embedder, get_reranker

STOP = set("a an the of to and or in on for is are be by with as at from that this it its any all must should "
           "may can which what when how who does do".split())
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.,%]*[a-z0-9%]|[a-z0-9]")


def tokenize(s: str) -> list[str]:
    return [t.replace(",", "") for t in TOKEN_RE.findall(s.lower()) if t not in STOP]


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    title: str
    doc_type: str
    section: str | None
    page: int | None
    text: str
    scores: dict = field(default_factory=dict)
    score: float = 0.0


@lru_cache(maxsize=2)
def qdrant_client(url: str) -> QdrantClient:
    return QdrantClient(location=":memory:") if url == ":memory:" else QdrantClient(url=url, timeout=10)


def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank)."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return fused


class Retriever:
    def __init__(self, engine: Engine):
        s = get_settings()
        self.settings = s
        self.client = qdrant_client(s.qdrant_url)
        self.embedder = get_embedder(s.embedding_model)
        self.reranker = get_reranker(s.reranker_model)
        self.chunks = pd.read_sql(text(
            "SELECT c.id AS chunk_id, c.document_id, d.title, d.doc_type, c.section, c.page, c.text "
            "FROM compliance_chunks c JOIN compliance_documents d ON d.id = c.document_id ORDER BY c.id"), engine)
        self.by_id = {int(r.chunk_id): r for r in self.chunks.itertuples()}
        corpus = [tokenize(f"{r.title} {r.section or ''} {r.text}") for r in self.chunks.itertuples()]
        self.bm25 = BM25Okapi(corpus) if corpus else None
        self.ids = self.chunks["chunk_id"].astype(int).tolist()

    @property
    def size(self) -> int:
        return len(self.ids)

    def _hit(self, cid: int) -> Hit:
        r = self.by_id[cid]
        return Hit(cid, int(r.document_id), r.title, r.doc_type, r.section,
                   None if pd.isna(r.page) else int(r.page), r.text)

    def dense(self, query: str, k: int, doc_type: str | None = None) -> list[tuple[int, float]]:
        vec = self.embedder.embed([query])[0].tolist()
        flt = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type))]) if doc_type else None
        res = self.client.query_points(self.settings.qdrant_collection, query=vec, limit=k, query_filter=flt).points
        return [(int(p.id), float(p.score)) for p in res]

    def keyword(self, query: str, k: int, doc_type: str | None = None) -> list[tuple[int, float]]:
        if not self.bm25:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(-scores)
        out = []
        for i in order:
            if scores[i] <= 0 or len(out) >= k:
                break
            cid = self.ids[i]
            if doc_type and self.by_id[cid].doc_type != doc_type:
                continue
            out.append((cid, float(scores[i])))
        return out

    def search(self, query: str, k: int = 5, mode: str = "hybrid", rerank: bool = True,
               doc_type: str | None = None, candidates: int = 20) -> list[Hit]:
        """mode: dense | bm25 | hybrid. Reranking applies to the candidate pool of any mode."""
        dense = self.dense(query, candidates, doc_type) if mode in ("dense", "hybrid") else []
        kw = self.keyword(query, candidates, doc_type) if mode in ("bm25", "hybrid") else []
        if mode == "hybrid":
            fused = rrf([[c for c, _ in dense], [c for c, _ in kw]])
        elif mode == "dense":
            fused = {c: s for c, s in dense}
        else:
            fused = {c: s for c, s in kw}
        pool = sorted(fused, key=lambda c: -fused[c])[:candidates]
        dmap, kmap = dict(dense), dict(kw)
        hits = []
        for c in pool:
            h = self._hit(c)
            h.scores = {"fused": round(fused[c], 5)}
            if c in dmap:
                h.scores["dense"] = round(dmap[c], 4)
            if c in kmap:
                h.scores["bm25"] = round(kmap[c], 3)
            h.score = fused[c]
            hits.append(h)
        if rerank and self.reranker is not None and hits:
            ce = self.reranker.predict([(query, f"{h.section or ''}. {h.text}") for h in hits])
            for h, s in zip(hits, ce):
                h.scores["rerank"] = round(float(s), 4)
                h.score = float(s)
            hits.sort(key=lambda h: -h.score)
        return hits[:k]


_retriever: Retriever | None = None


def get_retriever(engine: Engine, refresh: bool = False) -> Retriever:
    global _retriever
    if _retriever is None or refresh:
        _retriever = Retriever(engine)
    return _retriever
