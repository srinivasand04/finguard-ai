"""Embedding and reranking models.

Production uses Sentence Transformers (all-MiniLM-L6-v2, 384-d) and a MS MARCO
cross-encoder for reranking. Tests use a deterministic hashing embedder so the suite
runs offline without downloading models.
"""
from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache

# The models used here are public. Don't send a locally saved Hugging Face token: an expired one turns
# public downloads into 401 errors. Set HF_HUB_DISABLE_IMPLICIT_TOKEN=0 to opt back in.
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
from typing import Protocol

import numpy as np

TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)


class HashingEmbedder:
    """Bag-of-words feature hashing (unigrams + bigrams), L2-normalised. Offline, deterministic."""
    name = "hashing"

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = TOKEN_RE.findall(t.lower())
            for tok in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
                h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
                out[i, h % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)


@lru_cache(maxsize=4)
def get_embedder(name: str) -> Embedder:
    return HashingEmbedder() if name == "hashing" else SentenceTransformerEmbedder(name)


@lru_cache(maxsize=2)
def get_reranker(name: str):
    if not name:
        return None
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name, device="cpu")
