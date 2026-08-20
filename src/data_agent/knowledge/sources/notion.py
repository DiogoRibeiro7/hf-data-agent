"""Notion knowledge source.

Uses the REST API through `httpx` rather than `notion-client`, so the connector
needs no dependency beyond the core install and its request handling can be
exercised against a mock transport.

**Not verified against the live Notion API.** The request shapes follow the
documented API and the tests drive real HTTP mocks, but nobody has pointed this
at a genuine workspace. Treat the first real run as the actual test: check the
document count and spot-check one page's text.

    export DA_NOTION_TOKEN=secret_...
    export DA_NOTION_DATABASE_IDS=abc123,def456
    python scripts/ingest.py data/seed --notion
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx

from data_agent.knowledge.sources._http import plain_text, request_json
from data_agent.knowledge.sources.base import Document

logger = logging.getLogger(__name__)

API_ROOT = "https://api.notion.com/v1"
#: Notion pins behaviour to a dated version; changing this can change responses.
API_VERSION = "2022-06-28"
PAGE_SIZE = 100
#: Nested toggles and columns can recurse; stop before a cycle costs an ingest.
MAX_BLOCK_DEPTH = 3

#: Block types whose rich_text is prose worth indexing. Others (images, files,
#: dividers) carry no text, and code blocks are included because runbooks put
#: commands in them.
_TEXT_BLOCKS = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "quote",
        "callout",
        "code",
    }
)


class NotionSource:
    """Yields one Document per page across the configured databases."""

    name = "notion"

    def __init__(
        self,
        token: str,
        database_ids: list[str],
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not token:
            raise ValueError("NotionSource requires an integration token")
        self.database_ids = [d for d in database_ids if d]
        self._client = client or httpx.Client(
            base_url=API_ROOT,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": API_VERSION,
            },
            timeout=timeout,
        )

    # ------------------------------------------------------------------ api --
    def fetch(self) -> Iterator[Document]:
        for database_id in self.database_ids:
            for page in self._pages(database_id):
                document = self._document(page, database_id)
                if document is not None:
                    yield document

    # -------------------------------------------------------------- helpers --
    def _pages(self, database_id: str) -> Iterator[dict[str, Any]]:
        """Every page in a database, following the cursor to the end."""
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": PAGE_SIZE}
            if cursor:
                body["start_cursor"] = cursor
            payload = request_json(
                self._client, "POST", f"/databases/{database_id}/query", json=body
            )
            yield from payload.get("results", [])
            if not payload.get("has_more"):
                return
            cursor = payload.get("next_cursor")
            if not cursor:
                return

    def _document(self, page: dict[str, Any], database_id: str) -> Document | None:
        page_id = page.get("id")
        if not page_id:
            return None

        title = self._title(page)
        body = "\n".join(self._block_text(page_id, depth=0))
        text = f"{title}\n\n{body}".strip() if title else body.strip()
        if not text:
            logger.debug("skipping empty notion page", extra={"page_id": page_id})
            return None

        return Document(
            id=page_id,
            text=text,
            source=f"{self.name}:{title or page_id}",
            metadata={
                "page_id": page_id,
                "database_id": database_id,
                "url": page.get("url", ""),
                "last_edited_time": page.get("last_edited_time", ""),
            },
        )

    @staticmethod
    def _title(page: dict[str, Any]) -> str:
        """The page's title property, whatever it happens to be called."""
        for prop in (page.get("properties") or {}).values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                return plain_text(prop.get("title")).strip()
        return ""

    def _block_text(self, block_id: str, *, depth: int) -> Iterator[str]:
        """Flatten a block subtree to lines of text."""
        if depth > MAX_BLOCK_DEPTH:
            return

        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": PAGE_SIZE}
            if cursor:
                params["start_cursor"] = cursor
            payload = request_json(
                self._client, "GET", f"/blocks/{block_id}/children", params=params
            )

            for block in payload.get("results", []):
                kind = block.get("type", "")
                if kind in _TEXT_BLOCKS:
                    line = plain_text((block.get(kind) or {}).get("rich_text"))
                    if line.strip():
                        yield line
                if block.get("has_children") and block.get("id"):
                    yield from self._block_text(block["id"], depth=depth + 1)

            if not payload.get("has_more"):
                return
            cursor = payload.get("next_cursor")
            if not cursor:
                return

    def close(self) -> None:
        self._client.close()
