"""Tools are defined once and shared by the HTTP route and the MCP server, so
their behaviour is asserted here rather than through each entrypoint."""

from __future__ import annotations

import pytest

from data_agent.datasources.sql_guard import UnsafeSQLError
from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.sources.base import Document
from data_agent.mcp.tools import TOOLS, knowledge_search, list_dags, warehouse_query


class ListSource:
    name = "test"

    def __init__(self, docs):
        self._docs = docs

    def fetch(self):
        yield from self._docs


class TestRegistry:
    def test_every_tool_has_a_description(self):
        assert all(spec.description for spec in TOOLS.values())

    def test_every_tool_is_callable(self):
        assert all(callable(spec.fn) for spec in TOOLS.values())

    def test_the_registry_key_matches_the_spec_name(self):
        assert all(key == spec.name for key, spec in TOOLS.items())

    def test_required_arguments_are_declared_parameters(self):
        for spec in TOOLS.values():
            assert set(spec.required) <= set(spec.parameters), spec.name

    def test_every_parameter_is_documented(self):
        assert all(all(spec.parameters.values()) for spec in TOOLS.values())

    def test_the_expected_tools_are_registered(self):
        assert set(TOOLS) == {"knowledge_search", "warehouse_query", "list_dags"}


class TestKnowledgeSearch:
    def test_an_empty_store_says_so_instead_of_failing(self, runtime):
        assert "No knowledge-base results" in knowledge_search(runtime, "anything")

    def test_hits_are_rendered_with_source_and_score(self, runtime, settings):
        ingest([ListSource([Document(id="1", text="revenue runs nightly", source="kb")])], settings)
        runtime.retriever.store.load()
        out = knowledge_search(runtime, "revenue")
        assert "[kb |" in out
        assert "revenue runs nightly" in out


class TestWarehouseQuery:
    def test_returns_a_markdown_table(self, runtime):
        out = warehouse_query(runtime, "select region from revenue order by region")
        assert out.startswith("| region |")
        assert "AMER" in out

    def test_destructive_sql_raises_rather_than_running(self, runtime):
        with pytest.raises(UnsafeSQLError):
            warehouse_query(runtime, "DROP TABLE revenue")

    def test_the_table_survives_a_rejected_statement(self, runtime):
        with pytest.raises(UnsafeSQLError):
            warehouse_query(runtime, "DELETE FROM revenue")
        assert "EMEA" in warehouse_query(runtime, "select * from revenue")


class TestListDags:
    def test_delegates_to_the_airflow_source(self, runtime):
        class FakeAirflow:
            name = "airflow"

            def __init__(self):
                self.seen: list[str] = []

            def query(self, statement):
                from data_agent.datasources.base import QueryResult

                self.seen.append(statement)
                return QueryResult(columns=["dag_id"], rows=[["daily_revenue"]])

        fake = FakeAirflow()
        runtime.datasources["airflow"] = fake
        assert "daily_revenue" in list_dags(runtime, "list")
        assert fake.seen == ["list"]
