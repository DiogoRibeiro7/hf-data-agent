"""Working warehouse adapter via SQLAlchemy. DA_WAREHOUSE_DSN defaults to a local
SQLite file; point it at Postgres/Snowflake/BigQuery/DuckDB in production.

Every statement passes through `sql_guard` first. That guard is a safety net
against a careless caller or a model emitting something destructive — the actual
security boundary is the database user in the DSN, which should hold SELECT and
nothing else. See SECURITY.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from data_agent.datasources.base import QueryResult
from data_agent.datasources.sql_guard import guard_select

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


class WarehouseSource:
    name = "warehouse"

    def __init__(
        self,
        dsn: str,
        *,
        max_rows: int = 1000,
        allowed_tables: frozenset[str] | None = None,
    ) -> None:
        from sqlalchemy import create_engine

        self._engine: Engine = create_engine(dsn, future=True)
        self.max_rows = max_rows
        self.allowed_tables = allowed_tables

    def query(self, statement: str) -> QueryResult:
        """Run a guarded read-only query.

        Raises:
            UnsafeSQLError: if the statement is not a single read-only query.
        """
        from sqlalchemy import text

        # Ask for one row beyond the cap so truncation is detectable; without the
        # spare row an appended `LIMIT max_rows` would make every result look complete.
        probe = self.max_rows + 1
        safe_sql = guard_select(
            statement,
            max_rows=probe,
            allowed_tables=self.allowed_tables,
        )

        with self._engine.connect() as conn:
            result = conn.execute(text(safe_sql))
            cols = list(result.keys())
            fetched = [list(r) for r in result.fetchmany(probe)]

        truncated = len(fetched) > self.max_rows
        return QueryResult(columns=cols, rows=fetched[: self.max_rows], truncated=truncated)

    def close(self) -> None:
        """Release pooled connections."""
        self._engine.dispose()
