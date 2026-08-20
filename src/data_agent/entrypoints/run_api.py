"""AGENT-UI / API runner: uvicorn server for the FastAPI app.
Run: python -m data_agent.entrypoints.run_api  (or: data-agent-api)"""

from __future__ import annotations

import logging
import sys

import uvicorn

from data_agent.api.security import UnsafeBindingError, require_safe_binding
from data_agent.config import get_settings
from data_agent.observability import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    s = get_settings()
    configure_logging(s.log_level, s.log_format)
    # Fails fast rather than quietly publishing an unauthenticated warehouse.
    try:
        require_safe_binding(s)
    except UnsafeBindingError as exc:
        # A misconfiguration, not a crash: say so without a traceback.
        logger.error("%s", exc)
        return 2
    logger.info(
        "starting api",
        extra={"host": s.api_host, "port": s.api_port, "auth": bool(s.api_token)},
    )
    uvicorn.run("data_agent.api.app:app", host=s.api_host, port=s.api_port, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
