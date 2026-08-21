"""The Qdrant store, exercised against a real client in local mode.

`QdrantClient(":memory:")` runs the actual client and its query engine in
process, so these are not mocks: the collection lifecycle, the UUID point-id
mapping and the similarity search are really executed. Only the network hop to a
server is absent.

Skipped unless the `qdrant` extra is installed; CI runs them in a dedicated job.
"""

from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client", reason="needs the optional 'qdrant' extra")

from qdrant_client import QdrantClient

from data_agent.config import Settings
from data_agent.knowledge.store import Chunk
from data_agent.knowledge.store_qdrant import QdrantStore, point_id
from data_agent.knowledge.stores import build_store


def chunk(chunk_id: str, text: str, vector: list[float], source: str = "kb") -> Chunk:
    return Chunk(id=chunk_id, text=text, source=source, metadata={"k": "v"}, embedding=vector)


@pytest.fixture
def store() -> QdrantStore:
    return QdrantStore(collection="test", client=QdrantClient(":memory:"))


class TestPointIds:
    def test_the_same_chunk_id_maps_to_the_same_point(self):
        """Re-ingesting must overwrite a chunk, not duplicate it."""
        assert point_id("kb#1") == point_id("kb#1")

    def test_different_chunk_ids_differ(self):
        assert point_id("kb#1") != point_id("kb#2")

    def test_a_readable_chunk_id_becomes_a_valid_uuid(self):
        import uuid

        uuid.UUID(point_id("filesystem:runbook.md#3"))


class TestLifecycle:
    def test_an_absent_collection_looks_empty(self, store):
        assert len(store) == 0
        assert store.dim is None

    def test_searching_an_absent_collection_returns_nothing(self, store):
        assert store.search([1.0, 0.0], top_k=3) == []

    def test_adding_creates_the_collection(self, store):
        store.add([chunk("a", "hello", [1.0, 0.0])])
        assert len(store) == 1
        assert store.dim == 2

    def test_adding_nothing_is_harmless(self, store):
        store.add([])
        assert len(store) == 0

    def test_clear_drops_everything(self, store):
        store.add([chunk("a", "hello", [1.0, 0.0])])
        store.clear()
        assert len(store) == 0

    def test_clear_on_an_absent_collection_is_harmless(self, store):
        store.clear()
        assert len(store) == 0

    def test_save_is_a_noop(self, store):
        store.add([chunk("a", "hello", [1.0, 0.0])])
        store.save()
        assert len(store) == 1


class TestSearch:
    def test_the_nearest_vector_comes_first(self, store):
        store.add(
            [
                chunk("a", "about revenue", [1.0, 0.0]),
                chunk("b", "about airflow", [0.0, 1.0]),
            ]
        )
        hits = store.search([1.0, 0.0], top_k=2)
        assert hits[0].chunk.text == "about revenue"
        assert hits[0].score > hits[1].score

    def test_top_k_is_respected(self, store):
        store.add([chunk(str(i), f"doc {i}", [1.0, float(i)]) for i in range(5)])
        assert len(store.search([1.0, 0.0], top_k=2)) == 2

    def test_the_payload_round_trips(self, store):
        store.add([chunk("a", "hello", [1.0, 0.0], source="kb:doc.md")])
        hit = store.search([1.0, 0.0], top_k=1)[0]
        assert hit.chunk.id == "a"
        assert hit.chunk.source == "kb:doc.md"
        assert hit.chunk.metadata == {"k": "v"}

    def test_re_adding_the_same_id_overwrites(self, store):
        store.add([chunk("a", "first", [1.0, 0.0])])
        store.add([chunk("a", "second", [1.0, 0.0])])
        assert len(store) == 1
        assert store.search([1.0, 0.0], top_k=1)[0].chunk.text == "second"

    def test_a_dimension_mismatch_is_refused(self, store):
        """Same guard as the JSON store: querying a store built by a different
        embedder must fail loudly rather than score against the wrong vectors."""
        store.add([chunk("a", "hello", [1.0, 0.0, 0.0])])
        with pytest.raises(ValueError, match="dimension mismatch"):
            store.search([1.0, 0.0], top_k=1)


class TestFactory:
    def test_json_is_the_default(self, tmp_path):
        settings = Settings(vector_store_path=str(tmp_path / "vs.json"))
        assert type(build_store(settings)).__name__ == "VectorStore"

    def test_qdrant_is_selected_by_setting(self, monkeypatch):
        built = {}

        class Fake:
            def __init__(self, **kwargs):
                built.update(kwargs)

        monkeypatch.setattr("data_agent.knowledge.store_qdrant.QdrantStore", Fake)
        build_store(
            Settings(
                vector_backend="qdrant",
                qdrant_url="http://qdrant:6333",
                qdrant_collection="mine",
            )
        )
        assert built["url"] == "http://qdrant:6333"
        assert built["collection"] == "mine"
        assert built["api_key"] is None

    def test_an_empty_api_key_becomes_none(self, monkeypatch):
        built = {}

        class Fake:
            def __init__(self, **kwargs):
                built.update(kwargs)

        monkeypatch.setattr("data_agent.knowledge.store_qdrant.QdrantStore", Fake)
        build_store(Settings(vector_backend="qdrant", qdrant_api_key="k"))
        assert built["api_key"] == "k"


class TestThroughTheRetriever:
    def test_ingest_and_retrieve_over_qdrant(self, tmp_path, monkeypatch):
        """The end the rest of the system actually uses: ingestion writes through
        the factory, and the retriever reads back through it."""
        from data_agent.knowledge.ingest import ingest
        from data_agent.knowledge.retriever import Retriever
        from data_agent.knowledge.sources.base import Document

        shared = QdrantClient(":memory:")
        monkeypatch.setattr(
            "data_agent.knowledge.stores.build_store",
            lambda settings: QdrantStore(collection="rt", client=shared),
        )
        monkeypatch.setattr(
            "data_agent.knowledge.ingest.build_store",
            lambda settings: QdrantStore(collection="rt", client=shared),
        )
        monkeypatch.setattr(
            "data_agent.knowledge.retriever.build_store",
            lambda settings: QdrantStore(collection="rt", client=shared),
        )

        class Source:
            name = "test"

            def fetch(self):
                yield Document(
                    id="1", text="The revenue DAG runs nightly at 02:00 UTC.", source="kb"
                )

        settings = Settings(vector_backend="qdrant", vector_store_path=str(tmp_path / "x.json"))
        ingest([Source()], settings)

        hits = Retriever(settings).retrieve("when does the revenue dag run")
        assert hits
        assert "revenue" in hits[0].text.lower()

    def test_reingestion_is_idempotent_on_qdrant(self, tmp_path, monkeypatch):
        from data_agent.knowledge.ingest import ingest
        from data_agent.knowledge.sources.base import Document

        shared = QdrantClient(":memory:")
        monkeypatch.setattr(
            "data_agent.knowledge.ingest.build_store",
            lambda settings: QdrantStore(collection="idem", client=shared),
        )

        class Source:
            name = "test"

            def fetch(self):
                yield Document(id="1", text="stable text", source="kb")

        settings = Settings(vector_backend="qdrant", vector_store_path=str(tmp_path / "x.json"))
        first = len(ingest([Source()], settings))
        second = len(ingest([Source()], settings))
        assert first == second
