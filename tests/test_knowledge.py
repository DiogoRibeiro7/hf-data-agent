"""Offline ingestion, the vector store, embedders, and online retrieval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.config import Settings
from data_agent.knowledge.embedder import HashingEmbedder, build_embedder
from data_agent.knowledge.ingest import chunk_text, ingest
from data_agent.knowledge.retriever import Retriever
from data_agent.knowledge.sources.base import Document
from data_agent.knowledge.sources.filesystem import FilesystemSource
from data_agent.knowledge.store import Chunk, VectorStore


class ListSource:
    name = "test"

    def __init__(self, docs):
        self._docs = docs

    def fetch(self):
        yield from self._docs


DOCS = [Document(id="1", text="The revenue DAG runs nightly at 02:00 UTC.", source="kb")]


class TestChunking:
    def test_long_text_produces_overlapping_chunks(self):
        chunks = chunk_text("word " * 500, size=800, overlap=100)
        assert len(chunks) >= 2

    def test_empty_text_produces_nothing(self):
        assert chunk_text("   \n\t ") == []

    def test_whitespace_is_normalised(self):
        assert chunk_text("a\n\n  b") == ["a b"]

    def test_zero_step_does_not_hang(self):
        # overlap >= size would make the stride non-positive.
        assert chunk_text("abcdef", size=2, overlap=5)


class TestIngestion:
    def test_repeated_ingestion_is_idempotent(self, settings):
        """The regression: each run used to append to the store it had just loaded,
        so `make ingest` twice doubled every chunk and skewed retrieval."""
        first = len(ingest([ListSource(DOCS)], settings))
        second = len(ingest([ListSource(DOCS)], settings))
        third = len(ingest([ListSource(DOCS)], settings))
        assert first == second == third

    def test_removed_documents_disappear_on_reingest(self, settings):
        ingest([ListSource(DOCS)], settings)
        assert len(ingest([ListSource([])], settings)) == 0

    def test_append_mode_is_available_but_opt_in(self, settings):
        base = len(ingest([ListSource(DOCS)], settings))
        grown = len(ingest([ListSource(DOCS)], settings, rebuild=False))
        assert grown == base * 2

    def test_store_is_persisted_to_the_configured_path(self, settings):
        ingest([ListSource(DOCS)], settings)
        saved = json.loads(Path(settings.vector_store_path).read_text(encoding="utf-8"))
        assert saved
        assert saved[0]["source"] == "kb"

    def test_no_temporary_file_is_left_behind(self, settings, tmp_path):
        ingest([ListSource(DOCS)], settings)
        assert not list(tmp_path.glob("*.tmp"))


class TestRetrieval:
    def test_relevant_chunk_is_returned(self, settings):
        ingest([ListSource(DOCS)], settings)
        hits = Retriever(settings).retrieve("when does the revenue dag run")
        assert hits
        assert "revenue" in hits[0].text.lower()

    def test_empty_store_returns_nothing(self, settings):
        assert Retriever(settings).retrieve("anything") == []

    def test_top_k_is_respected(self, settings):
        many = [Document(id=str(i), text=f"doc number {i}", source="kb") for i in range(10)]
        ingest([ListSource(many)], settings)
        settings_k2 = settings.model_copy(update={"retrieval_top_k": 2})
        assert len(Retriever(settings_k2).retrieve("doc")) == 2


class TestVectorStore:
    def test_querying_with_a_mismatched_dimension_raises(self, tmp_path):
        """Silently zipping a short query against long vectors used to score 1.0."""
        store = VectorStore(str(tmp_path / "vs.json"))
        store.add([Chunk(id="a", text="t", source="s", metadata={}, embedding=[1.0] * 768)])
        with pytest.raises(ValueError, match="dimension mismatch"):
            store.search([1.0] * 384, top_k=1)

    def test_dim_is_none_while_empty(self, tmp_path):
        assert VectorStore(str(tmp_path / "vs.json")).dim is None

    def test_round_trip_through_disk(self, tmp_path):
        path = str(tmp_path / "vs.json")
        store = VectorStore(path)
        store.add([Chunk(id="a", text="hello", source="s", metadata={"k": "v"}, embedding=[1.0])])
        store.save()
        assert len(VectorStore(path)) == 1

    def test_clear_empties_the_store(self, tmp_path):
        store = VectorStore(str(tmp_path / "vs.json"))
        store.add([Chunk(id="a", text="t", source="s", metadata={}, embedding=[1.0])])
        store.clear()
        assert len(store) == 0


class TestEmbedder:
    def test_hashing_embedder_is_deterministic(self):
        embedder = HashingEmbedder(dim=64)
        assert embedder.embed("hello world") == embedder.embed("hello world")

    def test_vectors_are_l2_normalised(self):
        vec = HashingEmbedder(dim=64).embed("hello world")
        assert sum(v * v for v in vec) == pytest.approx(1.0)

    def test_empty_text_does_not_divide_by_zero(self):
        assert HashingEmbedder(dim=8).embed("") == [0.0] * 8

    def test_backend_selection_defaults_to_hashing(self):
        assert isinstance(build_embedder(Settings(embedder_backend="hashing")), HashingEmbedder)


class TestFilesystemSource:
    def test_markdown_and_text_files_are_picked_up(self, tmp_path):
        (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
        (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
        (tmp_path / "c.png").write_text("ignored", encoding="utf-8")
        docs = list(FilesystemSource(str(tmp_path)).fetch())
        assert {d.text for d in docs} == {"alpha", "beta"}

    def test_nested_directories_are_walked(self, tmp_path):
        nested = tmp_path / "deep" / "deeper"
        nested.mkdir(parents=True)
        (nested / "note.md").write_text("buried", encoding="utf-8")
        assert [d.text for d in FilesystemSource(str(tmp_path)).fetch()] == ["buried"]

    def test_metadata_records_the_path(self, tmp_path):
        (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
        doc = next(iter(FilesystemSource(str(tmp_path)).fetch()))
        assert doc.metadata["path"].endswith("a.md")
