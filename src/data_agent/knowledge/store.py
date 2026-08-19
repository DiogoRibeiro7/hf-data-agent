"""A tiny JSON-backed vector store: cosine search over an in-memory matrix.

Deliberately swappable. For real scale, replace `VectorStore` with a Chroma /
Qdrant / pgvector adapter exposing the same `add` / `search` surface.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    metadata: dict
    embedding: list[float]


@dataclass
class Hit:
    chunk: Chunk
    score: float


class VectorStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._chunks: list[Chunk] = []
        if self.path.exists():
            self.load()

    def add(self, chunks: list[Chunk]) -> None:
        self._chunks.extend(chunks)

    def search(self, query_embedding: list[float], top_k: int) -> list[Hit]:
        hits = [Hit(c, _cosine(query_embedding, c.embedding)) for c in self._chunks]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def __len__(self) -> int:
        return len(self._chunks)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(c) for c in self._chunks]))

    def load(self) -> None:
        self._chunks = [Chunk(**c) for c in json.loads(self.path.read_text())]


def _cosine(a: list[float], b: list[float]) -> float:
    # embeddings are stored L2-normalised, so dot product == cosine.
    return sum(x * y for x, y in zip(a, b))
