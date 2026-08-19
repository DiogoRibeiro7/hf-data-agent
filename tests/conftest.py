"""Shared fixtures. Everything here stays on the offline defaults: the mock model
provider, the hashing embedder, and a throwaway SQLite file per test."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data_agent.config import Settings
from data_agent.runtime import Runtime

REVENUE_ROWS = [
    ("EMEA", "2026-01", 412000),
    ("EMEA", "2026-02", 438500),
    ("AMER", "2026-01", 905300),
]


@pytest.fixture
def warehouse_path(tmp_path: Path) -> Path:
    """A SQLite file holding a small `revenue` table."""
    db = tmp_path / "warehouse.db"
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE revenue (region TEXT, month TEXT, revenue_usd INTEGER)")
        con.executemany("INSERT INTO revenue VALUES (?,?,?)", REVENUE_ROWS)
        con.commit()
    finally:
        con.close()
    return db


@pytest.fixture
def settings(tmp_path: Path, warehouse_path: Path) -> Settings:
    return Settings(
        model_backend="mock",
        embedder_backend="hashing",
        vector_store_path=str(tmp_path / "vector_store.json"),
        warehouse_dsn=f"sqlite:///{warehouse_path}",
    )


@pytest.fixture
def runtime(settings: Settings):
    rt = Runtime(settings)
    yield rt
    rt.close()
