"""Working warehouse adapter via SQLAlchemy. DA_WAREHOUSE_DSN defaults to a local
SQLite file; point it at Postgres/Snowflake/BigQuery/DuckDB in production."""

from __future__ import annotations

from data_agent.datasources.base import QueryResult


class WarehouseSource:
    name = "warehouse"

    def __init__(self, dsn: str) -> None:
        from sqlalchemy import create_engine

        self._engine = create_engine(dsn, future=True)

    def query(self, statement: str) -> QueryResult:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            result = conn.execute(text(statement))
            cols = list(result.keys())
            rows = [list(r) for r in result.fetchall()]
        return QueryResult(columns=cols, rows=rows)
