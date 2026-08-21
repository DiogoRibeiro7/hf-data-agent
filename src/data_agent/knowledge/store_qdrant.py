"""Qdrant-backed vector store.

Same `add` / `search` surface as the JSON store, so the retriever and the
ingestion pipeline are unchanged. Selected with `DA_VECTOR_BACKEND=qdrant`;
needs the `qdrant` extra and a running server (`docker compose up qdrant`).

Two details that the JSON store does not have to care about:

* **Point ids must be integers or UUIDs.** Chunk ids here are readable strings
  like `filesystem:runbook.md#3`, so each is hashed to a deterministic UUID5.
  Deterministic matters: re-ingesting the same chunk then overwrites its point
  rather than adding a duplicate alongside it.
* **The collection is created on first write**, using the width of the first
  vector, because the embedder — not this class — decides the dimension.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from data_agent.knowledge.store import Chunk, Hit

logger = logging.getLogger(__name__)

#: Namespace for turning a chunk id into a stable point id.
_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def point_id(chunk_id: str) -> str:
    """A deterministic UUID for a chunk id, so re-ingest overwrites."""
    return str(uuid.uuid5(_NAMESPACE, chunk_id))


class QdrantStore:
    """Vector store backed by a Qdrant collection."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "data_agent",
        api_key: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.collection = collection
        if client is not None:
            self._client = client
        else:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=url, api_key=api_key)

    # ------------------------------------------------------------- internals --
    @property
    def _models(self) -> Any:
        from qdrant_client import models

        return models

    def _exists(self) -> bool:
        return bool(self._client.collection_exists(self.collection))

    def _ensure_collection(self, size: int) -> None:
        if self._exists():
            return
        models = self._models
        self._client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=size, distance=models.Distance.COSINE),
        )
        logger.info(
            "created qdrant collection",
            extra={"collection": self.collection, "dim": size},
        )

    # ------------------------------------------------------------- interface --
    @property
    def dim(self) -> int | None:
        if not self._exists():
            return None
        info = self._client.get_collection(self.collection)
        params = info.config.params.vectors
        size = getattr(params, "size", None)
        return int(size) if size is not None else None

    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        models = self._models
        self._ensure_collection(len(chunks[0].embedding))
        self._client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=point_id(chunk.id),
                    vector=chunk.embedding,
                    payload={
                        "chunk_id": chunk.id,
                        "text": chunk.text,
                        "source": chunk.source,
                        "metadata": chunk.metadata,
                    },
                )
                for chunk in chunks
            ],
        )

    def clear(self) -> None:
        """Drop the collection so ingestion rebuilds rather than accumulating."""
        if self._exists():
            self._client.delete_collection(self.collection)

    def search(self, query_embedding: list[float], top_k: int) -> list[Hit]:
        if not self._exists():
            return []
        self._check_dim(len(query_embedding))
        response = self._client.query_points(
            self.collection, query=query_embedding, limit=top_k, with_payload=True
        )
        return [self._hit(point) for point in response.points]

    def _check_dim(self, query_dim: int) -> None:
        """Reject a query built by a different embedder, as the JSON store does."""
        stored = self.dim
        if stored is not None and query_dim != stored:
            raise ValueError(
                f"Embedding dimension mismatch: the query is {query_dim}-dimensional but "
                f"collection {self.collection!r} holds {stored}-dimensional vectors. "
                f"Re-run ingestion (`make ingest`) after changing DA_EMBEDDER_BACKEND "
                f"or DA_EMBEDDER_MODEL."
            )

    @staticmethod
    def _hit(point: Any) -> Hit:
        payload = point.payload or {}
        chunk = Chunk(
            id=str(payload.get("chunk_id", point.id)),
            text=str(payload.get("text", "")),
            source=str(payload.get("source", "")),
            metadata=payload.get("metadata") or {},
            # Vectors are not fetched back: nothing downstream reads them, and
            # they would dominate the response size.
            embedding=[],
        )
        return Hit(chunk=chunk, score=float(point.score))

    def save(self) -> None:
        """No-op: Qdrant persists on upsert."""

    def __len__(self) -> int:
        if not self._exists():
            return 0
        return int(self._client.count(self.collection).count)
