"""Deterministic provider used as the default so the whole stack runs with no
GPU, no downloads, and no network. Swap to a real backend via env vars."""

from __future__ import annotations

from collections.abc import Sequence

from data_agent.model.base import CONTEXT_MARKER, Message


class MockProvider:
    async def generate(self, messages: Sequence[Message]) -> str:
        user = next((m for m in reversed(messages) if m.role == "user"), None)
        system = next((m for m in messages if m.role == "system"), None)
        q = user.content.strip() if user else ""
        # Match the marker, not the word: the base instruction text mentions
        # "CONTEXT" too, which used to make every turn look grounded.
        has_context = bool(system and CONTEXT_MARKER in system.content)
        grounded = "context provided" if has_context else "no retrieved context"
        return (
            f"[mock-llm] I received your question ({grounded}). "
            f"Set DA_MODEL_BACKEND=transformers|openai_compatible|hf_inference for real answers.\n"
            f"Echo: {q[:280]}"
        )
