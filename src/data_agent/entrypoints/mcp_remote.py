"""REMOTE AGENT-MCP entrypoint: streamable-HTTP transport, for networked MCP
clients. Run: python -m data_agent.entrypoints.mcp_remote

The transport is served through uvicorn here rather than through the library's
own `run()`, so that a bearer gate can be wrapped around the ASGI app. See
mcp/auth.py for why authentication is not delegated to the MCP library.
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from data_agent.api.security import UnsafeBindingError, require_safe_mcp_binding
from data_agent.config import get_settings
from data_agent.mcp.auth import BearerAuthMiddleware
from data_agent.mcp.server import build_mcp
from data_agent.observability import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    try:
        require_safe_mcp_binding(settings)
    except UnsafeBindingError as exc:
        logger.error("%s", exc)
        return 2

    app = build_mcp().streamable_http_app()
    if settings.api_token:
        app = BearerAuthMiddleware(app, settings.api_token)

    logger.info(
        "starting remote mcp",
        extra={
            "host": settings.mcp_host,
            "port": settings.mcp_port,
            "auth": bool(settings.api_token),
        },
    )
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
