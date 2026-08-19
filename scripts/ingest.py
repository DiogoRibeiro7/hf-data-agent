"""Offline ingestion CLI. Builds the vector store from the filesystem source
(and any connectors you enable). Run on a schedule (cron / Airflow).

    python scripts/ingest.py data/seed
"""

from __future__ import annotations

import sys

from data_agent.config import get_settings
from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.sources.filesystem import FilesystemSource


def main(root: str) -> None:
    settings = get_settings()
    sources = [FilesystemSource(root)]
    # Enable SaaS connectors here once credentials are wired, e.g.:
    #   from data_agent.knowledge.sources.connectors import NotionSource
    #   sources.append(NotionSource(token=..., database_ids=[...]))
    store = ingest(sources, settings)
    print(f"ingested {len(store)} chunks -> {settings.vector_store_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/seed")
