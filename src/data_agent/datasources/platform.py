"""Stubs for the remaining 'Data Platform Sources' in the diagram. Implement the
`query` (or trigger/list) surface against your cluster and remove the raise."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from data_agent.datasources.base import QueryResult


class SparkSource:
    name = "spark"

    def __init__(self, master: str) -> None:
        self.master = master

    def query(self, statement: str) -> QueryResult:
        # TODO: submit via spark-connect / pyspark SparkSession.sql(statement).
        raise NotImplementedError("Wire a SparkSession (spark-connect) and run SQL.")


class AirflowSource:
    """Operational metadata: DAG/run status. 'query' = '<dag_id>' or 'list'."""

    name = "airflow"

    def __init__(self, base_url: str, auth: tuple[str, str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth

    def query(self, statement: str) -> QueryResult:
        dag_id = statement.strip()
        # The dag id can come from the model, so it is escaped rather than
        # interpolated: an unencoded '?' or '/' would rewrite the path and query
        # actually sent to Airflow.
        path = (
            "/api/v1/dags"
            if dag_id in {"", "list"}
            else f"/api/v1/dags/{quote(dag_id, safe='')}/dagRuns"
        )
        resp = httpx.get(self.base_url + path, auth=self.auth, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        key = "dags" if "dags" in data else "dag_runs"
        items = data.get(key, [])
        cols = sorted({k for it in items for k in it}) if items else ["info"]
        rows = [[it.get(c) for c in cols] for it in items]
        return QueryResult(columns=cols, rows=rows)


class MetadataSource:
    """Data catalog / lineage lookups (DataHub, OpenMetadata, ...)."""

    name = "metadata"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def query(self, statement: str) -> QueryResult:
        # TODO: call your catalog's search/lineage API.
        raise NotImplementedError("Wire your data catalog API.")
