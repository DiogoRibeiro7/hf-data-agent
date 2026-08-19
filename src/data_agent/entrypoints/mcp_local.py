"""LOCAL AGENT-MCP entrypoint: stdio transport, for desktop MCP clients
(Claude Desktop, IDEs). Run: python -m data_agent.entrypoints.mcp_local"""

from __future__ import annotations

from data_agent.config import get_settings
from data_agent.mcp.server import build_mcp
from data_agent.observability import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    build_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
