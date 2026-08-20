"""Hosted path: call the HF Inference Providers chat endpoint. Zero infra, good
for prototyping. Set DA_HF_TOKEN and DA_MODEL_ID."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx

from data_agent.config import Settings
from data_agent.model.base import Message
from data_agent.model.streaming import chat_payload, iter_chat_stream


class HFInferenceProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url="https://router.huggingface.co/v1",
            headers={"Authorization": f"Bearer {settings.hf_token}"},
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
