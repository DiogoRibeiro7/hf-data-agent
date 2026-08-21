"""Airflow adapter, result rendering, and the deliberate stubs."""

from __future__ import annotations

import httpx
import pytest

from data_agent.datasources.base import QueryResult
from data_agent.datasources.platform import AirflowSource, MetadataSource, SparkSource


class TestQueryResult:
    def test_renders_a_markdown_table(self):
        table = QueryResult(columns=["a", "b"], rows=[[1, 2]]).to_markdown()
        assert table.splitlines()[0] == "| a | b |"
        assert "| 1 | 2 |" in table

    def test_no_rows_renders_a_placeholder(self):
        assert QueryResult(columns=["a"], rows=[]).to_markdown() == "(no rows)"

    def test_truncation_is_disclosed(self):
        result = QueryResult(columns=["a"], rows=[[1]], truncated=True)
        assert "truncated" in result.to_markdown()

    def test_the_display_limit_also_discloses_truncation(self):
        result = QueryResult(columns=["a"], rows=[[i] for i in range(30)])
        assert "truncated" in result.to_markdown(limit=5)

    def test_not_truncated_says_nothing(self):
        assert "truncated" not in QueryResult(columns=["a"], rows=[[1]]).to_markdown()


class TestAirflowSource:
    def _source(self, monkeypatch, payload):
        def fake_get(url, **kwargs):
            request = httpx.Request("GET", url)
            return httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx, "get", fake_get)
        return AirflowSource("http://airflow:8080")

    def test_listing_dags(self, monkeypatch):
        payload = {"dags": [{"dag_id": "daily_revenue", "is_paused": False}]}
        result = self._source(monkeypatch, payload).query("list")
        assert result.columns == ["dag_id", "is_paused"]
        assert result.rows == [["daily_revenue", False]]

    def test_columns_are_the_union_across_items(self, monkeypatch):
        payload = {"dags": [{"dag_id": "a"}, {"owner": "data-platform"}]}
        result = self._source(monkeypatch, payload).query("list")
        assert result.columns == ["dag_id", "owner"]
        assert result.rows == [["a", None], [None, "data-platform"]]

    def test_an_empty_statement_lists_dags(self, monkeypatch):
        source = self._source(monkeypatch, {"dags": []})
        assert source.query("").columns == ["info"]

    def test_a_dag_id_fetches_its_runs(self, monkeypatch):
        source = self._source(monkeypatch, {"dag_runs": [{"state": "success"}]})
        result = source.query("daily_revenue")
        assert result.columns == ["state"]
        assert result.rows == [["success"]]

    def test_the_base_url_trailing_slash_is_normalised(self):
        assert AirflowSource("http://airflow:8080/").base_url == "http://airflow:8080"

    def test_http_errors_propagate(self, monkeypatch):
        def fake_get(url, **kwargs):
            return httpx.Response(500, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "get", fake_get)
        with pytest.raises(httpx.HTTPStatusError):
            AirflowSource("http://airflow:8080").query("list")


class TestStubs:
    """These raise by design; the test pins that they raise clearly rather than
    silently returning something wrong."""

    def test_spark_is_not_implemented(self):
        with pytest.raises(NotImplementedError, match="SparkSession"):
            SparkSource("local[*]").query("SELECT 1")

    def test_metadata_is_not_implemented(self):
        with pytest.raises(NotImplementedError, match="catalog"):
            MetadataSource("http://catalog").query("lineage")


class TestDagIdEncoding:
    """The dag id can come from the model, so it must not be able to rewrite the
    request. Unencoded, `daily_revenue?limit=1` turns the path into
    `/api/v1/dags/daily_revenue?limit=1/dagRuns` — a different call entirely."""

    def _capture(self, monkeypatch, statement):
        seen = {}

        def fake_get(url, **kwargs):
            seen["url"] = str(url)
            return httpx.Response(200, json={"dag_runs": []}, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "get", fake_get)
        AirflowSource("http://airflow:8080").query(statement)
        return seen["url"]

    def test_a_plain_dag_id_is_unchanged(self, monkeypatch):
        url = self._capture(monkeypatch, "daily_revenue")
        assert url == "http://airflow:8080/api/v1/dags/daily_revenue/dagRuns"

    @pytest.mark.parametrize(
        "injected",
        [
            pytest.param("daily_revenue?limit=1", id="query-string"),
            pytest.param("daily_revenue/../../secret", id="traversal"),
            pytest.param("daily_revenue#frag", id="fragment"),
            pytest.param("a b", id="space"),
        ],
    )
    def test_special_characters_cannot_rewrite_the_path(self, monkeypatch, injected):
        url = self._capture(monkeypatch, injected)
        tail = url.split("/api/v1/dags/", 1)[1]
        # Everything the caller supplied stays inside the one path segment.
        assert tail.endswith("/dagRuns")
        segment = tail[: -len("/dagRuns")]
        for char in "?#/":
            assert char not in segment, f"{char!r} survived into the path segment"

    def test_the_listing_path_is_untouched(self, monkeypatch):
        assert self._capture(monkeypatch, "list").endswith("/api/v1/dags")
