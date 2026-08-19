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

    @property
    def dim(self) -> int | None:
        """Embedding width of the stored vectors, or None while empty."""
        return len(self._chunks[0].embedding) if self._chunks else None

    def add(self, chunks: list[Chunk]) -> None:
        self._chunks.extend(chunks)

    def clear(self) -> None:
        """Drop every chunk. Ingestion rebuilds from scratch rather than appending."""
        self._chunks = []

    def search(self, query_embedding: list[float], top_k: int) -> list[Hit]:
        self._check_dim(len(query_embedding))
        hits = [Hit(c, _cosine(query_embedding, c.embedding)) for c in self._chunks]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def _check_dim(self, query_dim: int) -> None:
        """Guard against querying a store built by a different embedder.

        Without this the cosine loop would silently zip over the shorter vector
        and return a plausible-looking score computed from a prefix.
        """
        if self.dim is not None and query_dim != self.dim:
            raise ValueError(
                f"Embedding dimension mismatch: the query is {query_dim}-dimensional but "
                f"{self.path} holds {self.dim}-dimensional vectors. The store was built "
                f"with a different embedder — re-run ingestion (`make ingest`) after "
                f"changing DA_EMBEDDER_BACKEND or DA_EMBEDDER_MODEL."
            )

    def __len__(self) -> int:
        return len(self._chunks)

    def save(self) -> None:
        """Persist atomically, so a crash mid-write cannot leave a half-store on disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps([asdict(c) for c in self._chunks]), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._chunks = [Chunk(**c) for c in raw]


def _cosine(a: list[float], b: list[float]) -> float:
    # embeddings are stored L2-normalised, so dot product == cosine.
    return sum(x * y for x, y in zip(a, b, strict=True))
