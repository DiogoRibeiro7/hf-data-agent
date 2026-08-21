"""Vector store selection.

The JSON store stays the default: it needs no service, no dependency and no
container, which is what keeps the offline quickstart honest. Qdrant is opt-in
via `DA_VECTOR_BACKEND=qdrant` for corpora where an in-memory scan is no longer
reasonable.

Both satisfy `VectorStoreProtocol`, so the retriever and the ingestion pipeline
do not know which one they are talking to.
"""

from __future__ import annotations

from typing import Protocol

from data_agent.config import Settings
from data_agent.knowledge.store import Chunk, Hit, VectorStore


class VectorStoreProtocol(Protocol):
    """What the rest of the system needs from a vector store."""

    @property
    def dim(self) -> int | None:
        """Embedding width of the stored vectors, or None while empty."""

    def add(self, chunks: list[Chunk]) -> None: ...

    def clear(self) -> None:
        """Drop every chunk, so ingestion rebuilds rather than accumulating."""

    def search(self, query_embedding: list[float], top_k: int) -> list[Hit]: ...

    def save(self) -> None:
        """Persist. A no-op for backends that write on `add`."""

    def __len__(self) -> int: ...


def build_store(settings: Settings) -> VectorStoreProtocol:
    """Pick a store from settings. Qdrant is imported lazily with its extra."""
    if settings.vector_backend == "qdrant":
        from data_agent.knowledge.store_qdrant import QdrantStore

        return QdrantStore(
            url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            api_key=settings.qdrant_api_key or None,
        )
    return VectorStore(settings.vector_store_path)
