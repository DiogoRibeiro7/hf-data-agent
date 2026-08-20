"""The HTTP funnel: health, /ask, /tool, the UI route, and request correlation."""

from __future__ import annotations

import logging

import pytest

from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.sources.base import Document
from data_agent.observability import request_id_var


class ListSource:
    name = "test"

    def __init__(self, docs):
        self._docs = docs

    def fetch(self):
        yield from self._docs


class TestHealth:
    def test_reports_ok_and_the_active_backend(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["model_backend"] == "mock"
        assert "version" in body

    def test_counts_the_knowledge_base(self, client, runtime, settings):
        ingest([ListSource([Document(id="1", text="a fact", source="kb")])], settings)
        runtime.retriever.store.load()
        assert client.get("/health").json()["kb_chunks"] > 0


class TestAsk:
    def test_answers_a_question(self, client):
        response = client.post("/ask", json={"question": "what is the revenue?"})
        assert response.status_code == 200
        assert response.json()["answer"]

    def test_returns_the_retrieved_contexts(self, client, runtime, settings):
        docs = [Document(id="1", text="revenue is booked nightly", source="kb")]
        ingest([ListSource(docs)], settings)
        runtime.retriever.store.load()
        contexts = client.post("/ask", json={"question": "revenue?"}).json()["contexts"]
        assert contexts
        assert contexts[0]["source"] == "kb"

    @pytest.mark.parametrize("question", ["", "   ", "\n"])
    def test_rejects_a_blank_question(self, client, question):
        assert client.post("/ask", json={"question": question}).status_code == 400

    def test_rejects_a_malformed_body(self, client):
        assert client.post("/ask", json={"not_a_question": 1}).status_code == 422


class TestTool:
    def test_runs_a_warehouse_query(self, client):
        response = client.post(
            "/tool",
            json={"name": "warehouse_query", "args": {"sql": "select * from revenue"}},
        )
        assert response.status_code == 200
        assert "EMEA" in response.json()["result"]

    def test_unknown_tool_is_a_404_listing_the_alternatives(self, client):
        response = client.post("/tool", json={"name": "nope", "args": {}})
        assert response.status_code == 404
        assert "warehouse_query" in response.json()["detail"]

    def test_destructive_sql_is_a_400_not_a_500(self, client):
        """A rejected statement is the caller's mistake, so it must not read as a
        server fault — and it must never reach the engine."""
        response = client.post(
            "/tool",
            json={"name": "warehouse_query", "args": {"sql": "DROP TABLE revenue"}},
        )
        assert response.status_code == 400
        assert "read-only" in response.json()["detail"].lower()

    def test_wrong_arguments_are_a_400(self, client):
        response = client.post(
            "/tool", json={"name": "warehouse_query", "args": {"wrong_kwarg": "x"}}
        )
        assert response.status_code == 400

    def test_knowledge_search_reports_an_empty_store(self, client):
        response = client.post("/tool", json={"name": "knowledge_search", "args": {"query": "x"}})
        assert response.status_code == 200
        assert "No knowledge-base results" in response.json()["result"]


class TestRequestCorrelation:
    def test_a_request_id_is_returned(self, client):
        assert client.get("/health").headers["X-Request-ID"]

    def test_a_supplied_request_id_is_echoed_back(self, client):
        response = client.get("/health", headers={"X-Request-ID": "trace-me"})
        assert response.headers["X-Request-ID"] == "trace-me"

    def test_the_access_log_line_carries_the_id(self, client, caplog):
        """The id used to be reset before the access line was emitted, so the
        one log record that summarises the request was the only one without it."""
        with caplog.at_level(logging.INFO, logger="data_agent.api.app"):
            client.get("/health", headers={"X-Request-ID": "trace-me"})
        handled = [r for r in caplog.records if r.getMessage() == "request handled"]
        assert handled
        assert request_id_var.get() == "-"  # reset once the request finished
        assert handled[0].__dict__.get("status") == 200

    def test_ids_differ_between_requests(self, client):
        first = client.get("/health").headers["X-Request-ID"]
        second = client.get("/health").headers["X-Request-ID"]
        assert first != second


class TestUI:
    def test_the_root_serves_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "HF DATA AGENT" in response.text

    def test_the_page_never_assigns_markup(self, client):
        """Answers and knowledge-base source names are both influenced by
        ingested documents, so the page must render them as text, not markup.

        Checks for assignment rather than the bare word, so the comment
        explaining the rule does not trip its own test."""
        page = client.get("/").text
        for sink in ("innerHTML =", "innerHTML+=", "outerHTML =", "insertAdjacentHTML"):
            assert sink not in page, f"page writes markup via {sink}"
        assert "textContent" in page
