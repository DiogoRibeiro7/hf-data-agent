"""Deterministic provider used as the default so the whole stack runs with no
GPU, no downloads, and no network. Swap to a real backend via env vars."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

from data_agent.model.base import CONTEXT_MARKER, Message

#: Split on words but keep their trailing space, so chunks rejoin exactly.
_WORDS = re.compile(r"\S+\s*")


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

    async def generate_stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Emit the same answer a word at a time.

        The default backend streams too, so `/ask/stream` can be exercised
        offline and the concatenated chunks are byte-identical to `generate`.
        """
        for word in _WORDS.findall(await self.generate(messages)):
            yield word
