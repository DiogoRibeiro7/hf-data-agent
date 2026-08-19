"""Provider abstraction: the factory, the offline mock, and the two HTTP backends.

The HTTP backends are exercised against httpx MockTransport so the request shape
is asserted without a network call or a model download.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import httpx
import pytest

from data_agent.config import Settings
from data_agent.model.base import Message, build_provider
from data_agent.model.hf_inference import HFInferenceProvider
from data_agent.model.mock_provider import MockProvider
from data_agent.model.openai_compatible import OpenAICompatibleProvider

MESSAGES = [Message("system", "CONTEXT: revenue"), Message("user", "how much revenue?")]


def _chat_response(content: str = "  spaced answer  ") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class TestMessage:
    def test_serialises_to_the_chat_wire_format(self):
        assert Message("user", "hi").as_dict() == {"role": "user", "content": "hi"}

    def test_is_immutable(self):
        with pytest.raises(FrozenInstanceError):
            Message("user", "hi").content = "changed"


class TestFactory:
    def test_mock_is_the_default(self):
        assert isinstance(build_provider(Settings()), MockProvider)

    def test_openai_compatible_is_selected_by_name(self):
        provider = build_provider(Settings(model_backend="openai_compatible"))
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_hf_inference_is_selected_by_name(self):
        provider = build_provider(Settings(model_backend="hf_inference"))
        assert isinstance(provider, HFInferenceProvider)

    def test_an_unknown_backend_fails_loudly(self):
        settings = Settings()
        object.__setattr__(settings, "model_backend", "telepathy")
        with pytest.raises(ValueError, match="Unknown model backend"):
            build_provider(settings)


class TestMockProvider:
    async def test_reports_when_context_was_supplied(self):
        assert "context provided" in await MockProvider().generate(MESSAGES)

    async def test_reports_when_context_was_absent(self):
        out = await MockProvider().generate([Message("user", "hi")])
        assert "no retrieved context" in out

    async def test_echoes_the_question(self):
        assert "how much revenue?" in await MockProvider().generate(MESSAGES)

    async def test_survives_an_empty_message_list(self):
        assert await MockProvider().generate([])


class TestOpenAICompatibleProvider:
    async def test_posts_the_configured_model_and_messages(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = httpx.Request("POST", request.url, content=request.content).content
            captured["auth"] = request.headers.get("authorization")
            return _chat_response()

        settings = Settings(model_backend="openai_compatible", model_id="Qwen/Qwen2.5-7B-Instruct")
        provider = OpenAICompatibleProvider(settings)
        provider._client = httpx.AsyncClient(
            base_url=settings.model_base_url,
            headers={"Authorization": f"Bearer {settings.model_api_key}"},
            transport=httpx.MockTransport(handler),
        )
        try:
            answer = await provider.generate(MESSAGES)
        finally:
            await provider.aclose()

        assert answer == "spaced answer"  # whitespace is stripped
        assert captured["url"].endswith("/chat/completions")
        assert b"Qwen/Qwen2.5-7B-Instruct" in captured["body"]
        assert captured["auth"].startswith("Bearer ")

    async def test_http_errors_are_raised(self):
        provider = OpenAICompatibleProvider(Settings(model_backend="openai_compatible"))
        provider._client = httpx.AsyncClient(
            base_url="http://model/v1",
            transport=httpx.MockTransport(lambda r: httpx.Response(503, text="overloaded")),
        )
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await provider.generate(MESSAGES)
        finally:
            await provider.aclose()


class TestHFInferenceProvider:
    async def test_calls_the_router_with_the_token(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["host"] = request.url.host
            captured["auth"] = request.headers.get("authorization")
            return _chat_response("hosted answer")

        settings = Settings(model_backend="hf_inference", hf_token="hf_test_token")
        provider = HFInferenceProvider(settings)
        provider._client = httpx.AsyncClient(
            base_url="https://router.huggingface.co/v1",
            headers={"Authorization": f"Bearer {settings.hf_token}"},
            transport=httpx.MockTransport(handler),
        )
        try:
            assert await provider.generate(MESSAGES) == "hosted answer"
        finally:
            await provider.aclose()

        assert captured["host"] == "router.huggingface.co"
        assert captured["auth"] == "Bearer hf_test_token"
