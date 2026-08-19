"""SLACK AGENT entrypoint. Mentions / DMs -> /ask -> reply in thread.

Install: pip install "hf-data-agent[slack]"
Env: DA_SLACK_BOT_TOKEN, DA_SLACK_SIGNING_SECRET
Run: python -m data_agent.entrypoints.slack_app
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from data_agent.config import get_settings
from data_agent.observability import configure_logging
from data_agent.orchestrator.agent import Orchestrator
from data_agent.runtime import get_runtime


def main() -> None:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = App(token=settings.slack_bot_token, signing_secret=settings.slack_signing_secret)
    orchestrator = Orchestrator(get_runtime())

    @app.event("app_mention")
    def on_mention(event: dict[str, Any], say: Callable[..., Any]) -> None:
        text = event.get("text", "").split(">", 1)[-1].strip()
        reply = asyncio.run(orchestrator.answer(text))
        cites = ", ".join(sorted({c.source for c in reply.contexts}))
        suffix = f"\n\n_sources: {cites}_" if cites else ""
        say(text=reply.answer + suffix, thread_ts=event.get("ts"))

    SocketModeHandler(app, settings.slack_bot_token).start()


if __name__ == "__main__":
    main()
