"""Create a tiny SQLite warehouse so /tool and warehouse_query work out of the box.

    python scripts/seed_warehouse.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path("data/warehouse.db")
ROWS = [
    ("EMEA", "2026-01", 412000),
    ("EMEA", "2026-02", 438500),
    ("AMER", "2026-01", 905300),
    ("AMER", "2026-02", 961200),
    ("APAC", "2026-01", 274100),
    ("APAC", "2026-02", 301800),
]


def main() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS revenue")
    con.execute("CREATE TABLE revenue (region TEXT, month TEXT, revenue_usd INTEGER)")
    con.executemany("INSERT INTO revenue VALUES (?,?,?)", ROWS)
    con.commit()
    con.close()
    print(f"seeded {len(ROWS)} rows -> {DB}")


if __name__ == "__main__":
    main()
