"""Talk to a self-hosted HF model served behind an OpenAI-compatible endpoint
(vLLM `--api-server` or HF TGI). This is the recommended production path: serve
the open model once, point many agents at it. See scripts/serve_model.sh.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from data_agent.config import Settings
from data_agent.model.base import Message


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.model_base_url,
            headers={"Authorization": f"Bearer {settings.model_api_key}"},
            timeout=120.0,
        )

    async def generate(self, messages: Sequence[Message]) -> str:
        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": self.settings.model_id,
                "messages": [m.as_dict() for m in messages],
                "max_tokens": self.settings.model_max_new_tokens,
                "temperature": self.settings.model_temperature,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
