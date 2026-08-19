"""The warehouse adapter must apply the read-only guard, not merely document it."""

from __future__ import annotations

import sqlite3

import pytest

from data_agent.datasources.sql_guard import UnsafeSQLError
from data_agent.datasources.warehouse import WarehouseSource


@pytest.fixture
def warehouse(warehouse_path):
    source = WarehouseSource(f"sqlite:///{warehouse_path}")
    yield source
    source.close()


def test_select_returns_rows_and_columns(warehouse):
    result = warehouse.query("SELECT region, revenue_usd FROM revenue ORDER BY region")
    assert result.columns == ["region", "revenue_usd"]
    assert result.rows[0][0] == "AMER"


def test_destructive_sql_is_rejected_before_execution(warehouse, warehouse_path):
    with pytest.raises(UnsafeSQLError):
        warehouse.query("DROP TABLE revenue")

    # The regression this guards: the statement used to reach the engine and the
    # table was gone, even though the call raised on the way out.
    con = sqlite3.connect(warehouse_path)
    try:
        listing = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in listing}
        remaining = con.execute("SELECT count(*) FROM revenue").fetchone()[0]
    finally:
        con.close()
    assert "revenue" in tables
    assert remaining == 3


def test_delete_does_not_reach_the_engine(warehouse, warehouse_path):
    with pytest.raises(UnsafeSQLError):
        warehouse.query("DELETE FROM revenue")
    con = sqlite3.connect(warehouse_path)
    try:
        assert con.execute("SELECT count(*) FROM revenue").fetchone()[0] == 3
    finally:
        con.close()


def test_row_cap_truncates_and_says_so(warehouse_path):
    source = WarehouseSource(f"sqlite:///{warehouse_path}", max_rows=2)
    try:
        result = source.query("SELECT * FROM revenue")
        assert len(result.rows) == 2
        assert result.truncated
        assert "truncated" in result.to_markdown()
    finally:
        source.close()


def test_table_allow_list_is_enforced(warehouse_path):
    source = WarehouseSource(
        f"sqlite:///{warehouse_path}", allowed_tables=frozenset({"other_table"})
    )
    try:
        with pytest.raises(UnsafeSQLError, match="revenue"):
            source.query("SELECT * FROM revenue")
    finally:
        source.close()


def test_empty_result_renders_a_placeholder(warehouse):
    result = warehouse.query("SELECT * FROM revenue WHERE region = 'NOWHERE'")
    assert result.to_markdown() == "(no rows)"
