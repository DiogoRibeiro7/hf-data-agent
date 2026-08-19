"""LOCAL AGENT-MCP entrypoint: stdio transport, for desktop MCP clients
(Claude Desktop, IDEs). Run: python -m data_agent.entrypoints.mcp_local"""
from __future__ import annotations

from data_agent.mcp.server import build_mcp


def main() -> None:
    build_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
