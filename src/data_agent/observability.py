"""Logging setup and request correlation.

One agent request fans out across an entrypoint, the orchestrator, the model
provider and one or more datasources. Without a correlation id those lines are
impossible to reassemble in a shared log, so a request id is generated at the
edge, carried in a context variable, and stamped onto every record.

Set `DA_LOG_FORMAT=json` to emit one JSON object per line for log shipping;
the default is human-readable text.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any

#: Correlation id for the request currently being handled.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_CONFIGURED = False

# Attributes LogRecord always carries; anything else was passed via `extra`.
_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


#: Control characters that would let untrusted text forge extra log lines.
_CONTROL = re.compile("[" + chr(0) + "-" + chr(31) + chr(127) + "]")


def scrub(value: object, limit: int = 200) -> str:
    """Make an untrusted value safe to put in a log record.

    The JSON formatter escapes newlines on its own, but the default text
    formatter does not: a tool name containing a newline would otherwise write
    what looks like a second, forged log entry.
    """
    return _CONTROL.sub(" ", str(value))[:limit]


def new_request_id() -> str:
    """A short, unique id for one inbound request."""
    return uuid.uuid4().hex[:12]


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, including whatever was passed via `extra`."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _STANDARD_ATTRS and k != "request_id"
        }
        payload.update(extras)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "text", *, force: bool = False) -> None:
    """Install the root handler. Idempotent unless `force` is set.

    Called by every entrypoint. Importing the library does not configure
    logging — that decision belongs to the application, not the library.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    _CONFIGURED = True
