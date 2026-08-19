"""AGENT-UI / API runner: uvicorn server for the FastAPI app.
Run: python -m data_agent.entrypoints.run_api  (or: data-agent-api)"""

from __future__ import annotations

import uvicorn

from data_agent.config import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run("data_agent.api.app:app", host=s.api_host, port=s.api_port, reload=False)


if __name__ == "__main__":
    main()
