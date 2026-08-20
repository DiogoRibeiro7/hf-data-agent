"""Streaming support for model providers.

`generate_stream` is optional. A provider that does not implement it still works
everywhere: `stream_or_whole` falls back to a single `generate` call and yields
the answer as one chunk, so `/ask/stream` behaves the same for every backend and
only the granularity changes.

The two HTTP backends both speak the OpenAI streaming format, so the decoding
lives here once rather than in each provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable

import httpx

from data_agent.model.base import Message, ModelProvider


@runtime_checkable
class StreamingModelProvider(Protocol):
    """A provider that can emit an answer incrementally."""

    def generate_stream(self, messages: Sequence[Message]) -> AsyncIterator[str]: ...


def supports_streaming(provider: ModelProvider) -> bool:
    return callable(getattr(provider, "generate_stream", None))


async def stream_or_whole(
    provider: ModelProvider,
    messages: Sequence[Message],
) -> AsyncIterator[str]:
    """Stream from `provider` if it can, otherwise yield the whole answer once."""
    if supports_streaming(provider):
        async for chunk in provider.generate_stream(messages):  # type: ignore[attr-defined]
            yield chunk
        return
    yield await provider.generate(messages)


def chat_payload(settings: Any, messages: Sequence[Message], *, stream: bool) -> dict[str, Any]:
    """The request body shared by the OpenAI-compatible and HF router backends."""
    return {
        "model": settings.model_id,
        "messages": [m.as_dict() for m in messages],
        "max_tokens": settings.model_max_new_tokens,
        "temperature": settings.model_temperature,
        "stream": stream,
    }


def decode_sse_delta(line: str) -> str | None:
    """Pull the text out of one `data:` line of an OpenAI-style stream.

    Returns None for keep-alives, comments, the `[DONE]` sentinel, malformed
    JSON, and role-only opening chunks — anything that is not answer text.
    A malformed chunk is skipped rather than raised on: one bad frame should
    not lose an answer that is otherwise arriving fine.
    """
    line = line.strip()
    if not line.startswith("data:"):
        return None

    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None

    try:
        parsed = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None

    for choice in parsed.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        text = delta.get("content")
        if isinstance(text, str) and text:
            return text
    return None


async def iter_chat_stream(response: httpx.Response) -> AsyncIterator[str]:
    """Yield answer text from an OpenAI-style streaming chat response."""
    async for line in response.aiter_lines():
        chunk = decode_sse_delta(line)
        if chunk is not None:
            yield chunk
