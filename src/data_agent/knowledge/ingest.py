"""Offline ingestion = the diagram's 'Pre-processed offline' arrow.

Run periodically (cron / Airflow DAG). Pulls each source, chunks, embeds, and
persists to the vector store. The online request path only ever reads.
"""

from __future__ import annotations

from data_agent.config import Settings
from data_agent.knowledge.embedder import build_embedder
from data_agent.knowledge.sources.base import Document, KnowledgeSource
from data_agent.knowledge.store import Chunk, VectorStore


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    step = max(size - overlap, 1)
    return [text[i : i + size] for i in range(0, len(text), step)]


def ingest(sources: list[KnowledgeSource], settings: Settings) -> VectorStore:
    embedder = build_embedder(settings)
    store = VectorStore(settings.vector_store_path)
    for source in sources:
        for doc in source.fetch():
            for j, piece in enumerate(chunk_text(doc.text)):
                store.add(
                    [
                        Chunk(
                            id=f"{doc.source}#{doc.id}#{j}",
                            text=piece,
                            source=doc.source,
                            metadata=doc.metadata,
                            embedding=embedder.embed(piece),
                        )
                    ]
                )
    store.save()
    return store


__all__ = ["Document", "chunk_text", "ingest"]
