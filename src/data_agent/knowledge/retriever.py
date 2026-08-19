"""Online retrieval: embed the query, cosine-search the pre-built store."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.config import Settings
from data_agent.knowledge.embedder import build_embedder
from data_agent.knowledge.store import VectorStore


@dataclass
class RetrievedContext:
    text: str
    source: str
    score: float


class Retriever:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedder = build_embedder(settings)
        self.store = VectorStore(settings.vector_store_path)

    def retrieve(self, query: str) -> list[RetrievedContext]:
        if len(self.store) == 0:
            return []
        q = self.embedder.embed(query)
        hits = self.store.search(q, self.settings.retrieval_top_k)
        return [RetrievedContext(h.chunk.text, h.chunk.source, h.score) for h in hits]
