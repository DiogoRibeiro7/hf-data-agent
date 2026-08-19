"""Hosted path: call the HF Inference Providers chat endpoint. Zero infra, good
for prototyping. Set DA_HF_TOKEN and DA_MODEL_ID."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from data_agent.config import Settings
from data_agent.model.base import Message


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
            json={
                "model": self.settings.model_id,
                "messages": [m.as_dict() for m in messages],
                "max_tokens": self.settings.model_max_new_tokens,
                "temperature": self.settings.model_temperature,
            },
        )
        resp.raise_for_status()
        content: str = resp.json()["choices"][0]["message"]["content"]
        return content.strip()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
