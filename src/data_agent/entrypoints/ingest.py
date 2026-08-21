"""Offline ingestion entrypoint = the diagram's "pre-processed offline" arrow.

Lives in the package rather than in scripts/ so that anything which installs
hf-data-agent can run it — an Airflow worker has the wheel, not the repo.

    data-agent-ingest data/seed
    python -m data_agent.entrypoints.ingest data/seed --notion --slack
    python scripts/ingest.py data/seed          # same thing, from a checkout

SaaS connectors are opt-in per run and read their credentials from the
environment (see .env.example). None of them has been verified against its live
API — check the reported document count on the first real run.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from data_agent.config import Settings, get_settings
from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.sources.base import KnowledgeSource
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
    parser.add_argument("--no-filesystem", action="store_true", help="skip the local directory")
    parser.add_argument("--notion", action="store_true", help="also ingest Notion databases")
    parser.add_argument("--slack", action="store_true", help="also ingest Slack channels")
    parser.add_argument("--gdocs", action="store_true", help="also ingest a Google Drive folder")
    return parser.parse_args(argv)


def build_sources(args: argparse.Namespace, settings: Settings) -> list[KnowledgeSource]:
    """Assemble the requested sources, failing loudly on missing credentials.

    A connector that quietly does nothing because a token is unset is worse than
    one that refuses: the ingest reports success and the knowledge base is
    missing a whole source.
    """
    sources: list[KnowledgeSource] = []

    if not args.no_filesystem:
        sources.append(FilesystemSource(str(args.root)))

    if args.notion:
        from data_agent.knowledge.sources.notion import NotionSource

        if not settings.notion_databases:
            raise SystemExit("--notion needs DA_NOTION_DATABASE_IDS")
        sources.append(NotionSource(settings.notion_token, settings.notion_databases))

    if args.slack:
        from data_agent.knowledge.sources.slack import SlackSource

        if not settings.slack_channels:
            raise SystemExit("--slack needs DA_SLACK_INGEST_CHANNELS")
        sources.append(SlackSource(settings.slack_ingest_token, settings.slack_channels))

    if args.gdocs:
        from data_agent.knowledge.sources.gdocs import GoogleDocsSource

        sources.append(
            GoogleDocsSource(
                settings.gdocs_credentials,
                settings.gdocs_folder_id,
                recursive=settings.gdocs_recursive,
            )
        )

    return sources


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    root = Path(args.root)
    if not args.no_filesystem and not root.is_dir():
        logger.error("not a directory: %s", root)
        return 1

    try:
        sources = build_sources(args, settings)
    except (SystemExit, ValueError) as exc:
        logger.error("%s", exc)
        return 2

    if not sources:
        logger.error("no sources selected")
        return 2

    store = ingest(sources, settings, rebuild=not args.append)
    logger.info(
        "ingestion complete",
        extra={
            "chunks": len(store),
            "sources": [s.name for s in sources],
            "store": settings.vector_store_path,
            "mode": "append" if args.append else "rebuild",
        },
    )
    return 0


def run_or_raise(argv: list[str] | None = None) -> None:
    """Run ingestion, raising on failure.

    Schedulers signal task failure with an exception, not an exit code. Keeping
    this here rather than in the DAG file means the failure semantics are
    covered by the test suite instead of living in a file that cannot be
    imported without Airflow installed.

    Raises:
        RuntimeError: if ingestion reported a non-zero exit code.
    """
    exit_code = main(argv)
    if exit_code != 0:
        raise RuntimeError(f"ingestion failed with exit code {exit_code}")


if __name__ == "__main__":
    sys.exit(main())
