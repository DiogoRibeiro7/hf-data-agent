"""Shared JSON-over-HTTP plumbing for the SaaS knowledge connectors.

Ingestion is an offline batch job, so these are deliberately synchronous: a
generator that yields Documents is easier to reason about than an async one, and
nothing here is on the request path.

Two behaviours are worth stating because they are what usually breaks a
connector in production rather than in a demo:

* **Pagination is followed to the end.** A connector that silently reads only
  the first page produces a knowledge base that looks fine and is missing most
  of the corpus.
* **429 is retried, with the server's own `Retry-After`.** Notion and Slack both
  rate limit aggressively on backfills.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: Give up after this many consecutive rate-limit responses for one request.
MAX_RETRIES = 5
#: Cap a server-supplied Retry-After, so a bad header cannot stall ingestion.
MAX_BACKOFF_SECONDS = 60.0


class ConnectorError(RuntimeError):
    """A knowledge source could not be read."""


def retry_after_seconds(response: httpx.Response, default: float = 1.0) -> float:
    """Seconds to wait before retrying, from the response's own header."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return default
    try:
        return min(max(float(raw), 0.0), MAX_BACKOFF_SECONDS)
    except ValueError:
        return default


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    sleep: Any = time.sleep,
    **kwargs: Any,
) -> dict[str, Any]:
    """One JSON request, retrying while the server says it is rate limited.

    Args:
        sleep: injected so tests do not actually wait.

    Raises:
        ConnectorError: on a non-2xx response, or once retries are exhausted.
    """
    for attempt in range(MAX_RETRIES):
        response = client.request(method, url, **kwargs)
        if response.status_code == 429:
            pause = retry_after_seconds(response)
            logger.warning(
                "rate limited; backing off",
                extra={"url": url, "attempt": attempt + 1, "sleep_s": pause},
            )
            sleep(pause)
            continue
        if response.status_code >= 400:
            raise ConnectorError(
                f"{method} {url} failed with {response.status_code}: {response.text[:300]}"
            )
        payload: dict[str, Any] = response.json()
        return payload

    raise ConnectorError(f"{method} {url} still rate limited after {MAX_RETRIES} attempts")


def plain_text(rich_text: list[dict[str, Any]] | None) -> str:
    """Flatten a Notion-style rich-text array to plain text."""
    if not rich_text:
        return ""
    return "".join(str(span.get("plain_text", "")) for span in rich_text)
