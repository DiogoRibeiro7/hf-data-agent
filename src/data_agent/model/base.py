"""Model provider abstraction.

The diagram's MODEL box is a hard dependency boundary: the orchestrator only
knows about `ModelProvider.generate`. Swap GPT-5.2 for any open HF model by
changing DA_MODEL_BACKEND / DA_MODEL_ID — nothing else moves.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from data_agent.config import Settings


@dataclass(frozen=True)
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class ModelProvider(Protocol):
    async def generate(self, messages: Sequence[Message]) -> str: ...


def build_provider(settings: Settings) -> ModelProvider:
    """Factory: pick a concrete provider from settings."""
    backend = settings.model_backend
    if backend == "mock":
        from data_agent.model.mock_provider import MockProvider

        return MockProvider()
    if backend == "transformers":
        from data_agent.model.transformers_provider import TransformersProvider

        return TransformersProvider(settings)
    if backend == "openai_compatible":
        from data_agent.model.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings)
    if backend == "hf_inference":
        from data_agent.model.hf_inference import HFInferenceProvider

        return HFInferenceProvider(settings)
    raise ValueError(f"Unknown model backend: {backend!r}")
