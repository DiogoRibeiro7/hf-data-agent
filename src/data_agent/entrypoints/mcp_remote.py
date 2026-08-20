"""REMOTE AGENT-MCP entrypoint: streamable-HTTP transport, for networked MCP
clients. Run: python -m data_agent.entrypoints.mcp_remote"""

from __future__ import annotations

import logging
import sys

from data_agent.api.security import UnsafeBindingError, require_safe_mcp_binding
from data_agent.config import get_settings
from data_agent.mcp.server import build_mcp
from data_agent.observability import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    # This transport carries no auth of its own; refuse to publish it silently.
    try:
        require_safe_mcp_binding(settings)
    except UnsafeBindingError as exc:
        logger.error("%s", exc)
        return 2
    # streamable-http is the modern remote transport; "sse" also available.
    build_mcp().run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    sys.exit(main())
