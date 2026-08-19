"""Deterministic provider used as the default so the whole stack runs with no
GPU, no downloads, and no network. Swap to a real backend via env vars."""
from __future__ import annotations

from collections.abc import Sequence

from data_agent.model.base import Message


class MockProvider:
    async def generate(self, messages: Sequence[Message]) -> str:
        user = next((m for m in reversed(messages) if m.role == "user"), None)
        context = next((m for m in messages if m.role == "system"), None)
        q = user.content.strip() if user else ""
        grounded = "context provided" if (context and "CONTEXT" in context.content) else "no retrieved context"
        return (
            f"[mock-llm] I received your question ({grounded}). "
            f"Set DA_MODEL_BACKEND=transformers|openai_compatible|hf_inference for real answers.\n"
            f"Echo: {q[:280]}"
        )
