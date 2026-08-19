"""Embedders. Default is dependency-free and deterministic (hashing bag-of-words)
so RAG works with no model download; swap to sentence-transformers for quality."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from data_agent.config import Settings

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Hashing trick + L2 norm. No deps, no downloads. Fine for dev/CI."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN.findall(text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder_backend == "sentence_transformers":
        return SentenceTransformerEmbedder(settings.embedder_model)
    return HashingEmbedder(settings.embedding_dim)
