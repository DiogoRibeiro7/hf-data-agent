"""Slack knowledge source.

One Document per **thread**, not per message. A Slack answer is almost always
spread across a reply chain, and indexing messages individually would chop the
question away from the answer — the retrieval would then surface a fragment that
reads as authoritative and is missing its own context.

Uses the Web API through `httpx`, so no dependency beyond the core install and
the request handling is exercisable against a mock transport. The `slack` extra
is only needed for the *bot* entrypoint, not for ingestion.

**Not verified against the live Slack API.** Request shapes follow the
documented API and the tests drive real HTTP mocks, but this has not read a
genuine workspace. The bot token needs `channels:history` (and `groups:history`
for private channels) plus `users:read` if you want author names resolved.

    export DA_SLACK_INGEST_TOKEN=xoxb-...
    export DA_SLACK_INGEST_CHANNELS=C0123ABC,C0456DEF
    python scripts/ingest.py data/seed --slack
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx

from data_agent.knowledge.sources._http import ConnectorError, request_json
from data_agent.knowledge.sources.base import Document

logger = logging.getLogger(__name__)

API_ROOT = "https://slack.com/api"
PAGE_SIZE = 200


def _check(payload: dict[str, Any], call: str) -> dict[str, Any]:
    """Slack answers 200 OK with `ok: false`, so status codes are not enough."""
    if not payload.get("ok", False):
        raise ConnectorError(f"slack {call} failed: {payload.get('error', 'unknown error')}")
    return payload


class SlackSource:
    """Yields one Document per thread across the configured channels."""

    name = "slack"

    def __init__(
        self,
        bot_token: str,
        channel_ids: list[str],
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not bot_token:
            raise ValueError("SlackSource requires a bot token")
        self.channel_ids = [c for c in channel_ids if c]
        self._client = client or httpx.Client(
            base_url=API_ROOT,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=timeout,
        )

    # ------------------------------------------------------------------ api --
    def fetch(self) -> Iterator[Document]:
        for channel in self.channel_ids:
            for parent in self._history(channel):
                document = self._thread_document(channel, parent)
                if document is not None:
                    yield document

    # -------------------------------------------------------------- helpers --
    def _paginate(self, call: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            query = {**params, "limit": PAGE_SIZE}
            if cursor:
                query["cursor"] = cursor
            payload = _check(request_json(self._client, "GET", f"/{call}", params=query), call)
            yield from payload.get("messages", [])
            cursor = (payload.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                return

    def _history(self, channel: str) -> Iterator[dict[str, Any]]:
        for message in self._paginate("conversations.history", {"channel": channel}):
            # A reply surfaced at top level is skipped: it arrives again as part
            # of its own thread, and indexing it twice would double-count it.
            if message.get("thread_ts") and message.get("thread_ts") != message.get("ts"):
                continue
            if message.get("subtype") in {"channel_join", "channel_leave"}:
                continue
            yield message

    def _thread_document(self, channel: str, parent: dict[str, Any]) -> Document | None:
        ts = parent.get("ts")
        if not ts:
            return None

        messages = (
            list(self._paginate("conversations.replies", {"channel": channel, "ts": ts}))
            if parent.get("thread_ts")
            else [parent]
        )
        lines = [text for text in (m.get("text", "").strip() for m in messages) if text]
        if not lines:
            return None

        return Document(
            id=f"{channel}:{ts}",
            text="\n\n".join(lines),
            source=f"{self.name}:{channel}",
            metadata={
                "channel": channel,
                "thread_ts": ts,
                "messages": len(lines),
                "permalink": parent.get("permalink", ""),
            },
        )

    def close(self) -> None:
        self._client.close()
