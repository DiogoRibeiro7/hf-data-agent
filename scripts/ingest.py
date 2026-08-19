"""Offline ingestion CLI. Rebuilds the vector store from the filesystem source
(and any connectors you enable). Run on a schedule (cron / Airflow).

    python scripts/ingest.py data/seed
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from data_agent.config import get_settings
from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.sources.filesystem import FilesystemSource
from data_agent.observability import configure_logging

logger = logging.getLogger("ingest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default="data/seed",
        help="directory to ingest (default: data/seed)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="add to the existing store instead of rebuilding it (may duplicate chunks)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    root = Path(args.root)
    if not root.is_dir():
        logger.error("not a directory: %s", root)
        return 1

    sources = [FilesystemSource(str(root))]
    # Enable SaaS connectors here once credentials are wired, e.g.:
    #   from data_agent.knowledge.sources.connectors import NotionSource
    #   sources.append(NotionSource(token=..., database_ids=[...]))
    store = ingest(sources, settings, rebuild=not args.append)
    logger.info(
        "ingestion complete",
        extra={
            "chunks": len(store),
            "root": str(root),
            "store": settings.vector_store_path,
            "mode": "append" if args.append else "rebuild",
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
