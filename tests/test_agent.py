from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from data_agent.config import Settings
from data_agent.knowledge.ingest import chunk_text, ingest
from data_agent.knowledge.sources.base import Document
from data_agent.model.base import Message, build_provider
from data_agent.orchestrator.agent import Orchestrator
from data_agent.runtime import Runtime


class _ListSource:
    name = "test"

    def __init__(self, docs):
        self._docs = docs

    def fetch(self):
        yield from self._docs


@pytest.fixture
def settings(tmp_path):
    return Settings(
        model_backend="mock",
        embedder_backend="hashing",
        vector_store_path=str(tmp_path / "vs.json"),
        warehouse_dsn=f"sqlite:///{tmp_path / 'wh.db'}",
    )


def test_chunk_text_overlaps():
    chunks = chunk_text("word " * 500, size=800, overlap=100)
    assert len(chunks) >= 2


def test_ingest_and_retrieve(settings):
    docs = [Document(id="1", text="The revenue DAG runs nightly at 02:00 UTC.", source="kb")]
    ingest([_ListSource(docs)], settings)
    rt = Runtime(settings)
    hits = rt.retriever.retrieve("when does the revenue dag run")
    assert hits and "revenue" in hits[0].text.lower()


@pytest.mark.asyncio
async def test_mock_provider_grounds_on_context(settings):
    provider = build_provider(settings)
    out = await provider.generate(
        [Message("system", "CONTEXT: x"), Message("user", "hello")]
    )
    assert "context provided" in out


@pytest.mark.asyncio
async def test_orchestrator_end_to_end(settings):
    docs = [Document(id="1", text="Quarterly board numbers come from the revenue table.", source="kb")]
    ingest([_ListSource(docs)], settings)
    rt = Runtime(settings)
    reply = await Orchestrator(rt).answer("where do board numbers come from?")
    assert reply.answer
    assert reply.contexts  # retrieval fired


def test_api_health_and_tool(settings, monkeypatch):
    import data_agent.runtime as runtime_mod

    runtime_mod.get_runtime.cache_clear()
    monkeypatch.setattr(runtime_mod, "get_settings", lambda: settings)
    # seed the file-backed warehouse table
    rt = Runtime(settings)
    from sqlalchemy import text

    with rt.datasources["warehouse"]._engine.begin() as c:
        c.execute(text("CREATE TABLE revenue (region TEXT, revenue_usd INT)"))
        c.execute(text("INSERT INTO revenue VALUES ('EMEA', 100), ('AMER', 200)"))
    monkeypatch.setattr(runtime_mod, "get_runtime", lambda: rt)
    import data_agent.api.app as app_mod

    monkeypatch.setattr(app_mod, "get_runtime", lambda: rt)

    client = TestClient(app_mod.app)
    assert client.get("/health").json()["status"] == "ok"
    r = client.post("/tool", json={"name": "warehouse_query", "args": {"sql": "select * from revenue"}})
    assert r.status_code == 200 and "EMEA" in r.json()["result"]
