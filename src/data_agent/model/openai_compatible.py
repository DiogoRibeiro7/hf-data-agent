"""Talk to a self-hosted HF model served behind an OpenAI-compatible endpoint
(vLLM `--api-server` or HF TGI). This is the recommended production path: serve
the open model once, point many agents at it. See scripts/serve_model.sh.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx

from data_agent.config import Settings
from data_agent.model.base import Message
from data_agent.model.streaming import chat_payload, iter_chat_stream


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
            json=chat_payload(self.settings, messages, stream=False),
        )
        resp.raise_for_status()
        content: str = resp.json()["choices"][0]["message"]["content"]
        return content.strip()

    async def generate_stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Yield answer text as the backend produces it."""
        async with self._client.stream(
            "POST",
            "/chat/completions",
            json=chat_payload(self.settings, messages, stream=True),
        ) as response:
            response.raise_for_status()
            async for chunk in iter_chat_stream(response):
                yield chunk

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
