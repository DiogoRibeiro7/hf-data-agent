"""Repo-local shim for the ingestion entrypoint.

The implementation lives in `data_agent.entrypoints.ingest` so that an
installed copy — an Airflow worker, a container — can run it without the
repository checked out. This keeps `python scripts/ingest.py` working.
"""

from __future__ import annotations

import sys

from data_agent.entrypoints.ingest import main

if __name__ == "__main__":
    sys.exit(main())
