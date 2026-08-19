"""REMOTE AGENT-MCP entrypoint: streamable-HTTP transport, for networked MCP
clients. Run: python -m data_agent.entrypoints.mcp_remote"""

from __future__ import annotations

from data_agent.config import get_settings
from data_agent.mcp.server import build_mcp
from data_agent.observability import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    # streamable-http is the modern remote transport; "sse" also available.
    build_mcp().run(transport="streamable-http")


if __name__ == "__main__":
    main()
