"""Create a tiny SQLite warehouse so /tool and warehouse_query work out of the box.

python scripts/seed_warehouse.py
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

from data_agent.config import get_settings
from data_agent.observability import configure_logging

logger = logging.getLogger("seed")

DB = Path("data/warehouse.db")
ROWS = [
    ("EMEA", "2026-01", 412000),
    ("EMEA", "2026-02", 438500),
    ("AMER", "2026-01", 905300),
    ("AMER", "2026-02", 961200),
    ("APAC", "2026-01", 274100),
    ("APAC", "2026-02", 301800),
]


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    try:
        con.execute("DROP TABLE IF EXISTS revenue")
        con.execute("CREATE TABLE revenue (region TEXT, month TEXT, revenue_usd INTEGER)")
        con.executemany("INSERT INTO revenue VALUES (?,?,?)", ROWS)
        con.commit()
    finally:
        con.close()

    logger.info("warehouse seeded", extra={"rows": len(ROWS), "path": str(DB)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
