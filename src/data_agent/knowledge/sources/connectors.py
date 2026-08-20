"""SaaS knowledge connectors, re-exported from their own modules.

Each implements the `KnowledgeSource` protocol: a `fetch()` that yields
`Document`s. Ingestion, chunking, embedding and retrieval are source-agnostic,
so a working `fetch()` is all a new source needs.

**None of these has been run against its live API.** Their request shapes follow
the documented APIs and the tests drive real HTTP mocks (Notion, Slack) or a
stand-in service object (Google Docs), so the parsing, pagination and
rate-limit handling are exercised — but no real workspace has been read. Treat
the first real ingest as the test: check the document count, and spot-check the
text of one document, before trusting answers built on it.
"""

from __future__ import annotations

from data_agent.knowledge.sources.gdocs import GoogleDocsSource
from data_agent.knowledge.sources.notion import NotionSource
from data_agent.knowledge.sources.slack import SlackSource

__all__ = ["GoogleDocsSource", "NotionSource", "SlackSource"]
