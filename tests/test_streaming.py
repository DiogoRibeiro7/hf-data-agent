"""Streaming: SSE decoding, the prose/tool-call decision, and /ask/stream.

The load-bearing behaviour is that a tool-call turn never reaches the client as
text. Streaming raw model output would put the JSON protocol into the answer.
"""

from __future__ import annotations

import json

import httpx
import pytest

from data_agent.api.app import app
from data_agent.config import Settings
from data_agent.model.base import Message
from data_agent.model.mock_provider import MockProvider
from data_agent.model.openai_compatible import OpenAICompatibleProvider
from data_agent.model.streaming import (
    decode_sse_delta,
    stream_or_whole,
    supports_streaming,
)
from data_agent.orchestrator.agent import (
    DeltaEvent,
    DoneEvent,
    Orchestrator,
    StepEvent,
    _Turn,
)
from data_agent.runtime import Runtime, get_runtime

MESSAGES = [Message("user", "how much revenue?")]


def tool_call(tool: str, **args) -> str:
    return json.dumps({"tool": tool, "args": args})


class Chunked:
    """Emits a scripted turn in fixed-size pieces."""

    def __init__(self, *turns: str, size: int = 5):
        self.turns = list(turns)
        self.size = size

    def _next(self) -> str:
        return self.turns.pop(0) if self.turns else "Final answer."

    async def generate(self, messages):
        return self._next()

    async def generate_stream(self, messages):
        text = self._next()
        for i in range(0, len(text), self.size):
            yield text[i : i + self.size]


class NoStreaming:
    """A provider from before streaming existed."""

    async def generate(self, messages):
        return "whole answer"


class TestDecodeSse:
    def test_extracts_delta_content(self):
        line = 'data: {"choices":[{"delta":{"content":"Hello"}}]}'
        assert decode_sse_delta(line) == "Hello"

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("data: [DONE]", id="done-sentinel"),
            pytest.param("data:", id="empty-data"),
            pytest.param(": keep-alive", id="comment"),
            pytest.param("", id="blank"),
            pytest.param("event: message", id="event-line"),
            pytest.param("data: {not json}", id="malformed-json"),
            pytest.param('data: {"choices":[{"delta":{}}]}', id="empty-delta"),
            pytest.param('data: {"choices":[{"delta":{"role":"assistant"}}]}', id="role-only"),
            pytest.param('data: {"choices":[]}', id="no-choices"),
            pytest.param('data: {"choices":[{"delta":{"content":""}}]}', id="empty-content"),
            pytest.param("data: [1,2,3]", id="json-array"),
        ],
    )
    def test_non_text_frames_yield_nothing(self, line):
        assert decode_sse_delta(line) is None

    def test_a_malformed_frame_does_not_raise(self):
        """One bad frame must not lose an answer that is otherwise arriving."""
        assert decode_sse_delta('data: {"choices":') is None


class TestProviderStreaming:
    def test_the_mock_provider_streams(self):
        assert supports_streaming(MockProvider())

    def test_a_provider_without_streaming_is_detected(self):
        assert not supports_streaming(NoStreaming())

    async def test_chunks_rejoin_into_the_whole_answer(self):
        provider = MockProvider()
        whole = await provider.generate(MESSAGES)
        streamed = "".join([c async for c in provider.generate_stream(MESSAGES)])
        assert streamed == whole

    async def test_the_fallback_yields_the_whole_answer_once(self):
        chunks = [c async for c in stream_or_whole(NoStreaming(), MESSAGES)]
        assert chunks == ["whole answer"]

    async def test_the_http_backend_streams_over_sse(self):
        body = (
            'data: {"choices":[{"delta":{"content":"AMER "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"booked "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"$1.8m"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, text=body)

        provider = OpenAICompatibleProvider(Settings(model_backend="openai_compatible"))
        provider._client = httpx.AsyncClient(
            base_url="http://model/v1", transport=httpx.MockTransport(handler)
        )
        try:
            chunks = [c async for c in provider.generate_stream(MESSAGES)]
        finally:
            await provider.aclose()

        assert chunks == ["AMER ", "booked ", "$1.8m"]
        assert captured["body"]["stream"] is True


class TestTurnBuffer:
    def test_prose_is_forwarded_immediately(self):
        turn = _Turn()
        assert turn.add("The revenue") == "The revenue"
        assert turn.add(" is high") == " is high"
        assert turn.is_prose

    def test_json_is_withheld(self):
        turn = _Turn()
        assert turn.add('{"tool"') is None
        assert turn.add(': "x"}') is None
        assert turn.is_prose is False

    def test_a_fenced_block_is_withheld(self):
        turn = _Turn()
        assert turn.add("```json") is None
        assert turn.is_prose is False

    def test_leading_whitespace_does_not_decide(self):
        turn = _Turn()
        assert turn.add("  ") is None
        assert turn.is_prose is None
        assert turn.add("{") is None
        assert turn.is_prose is False

    def test_buffered_prose_is_released_on_the_deciding_chunk(self):
        turn = _Turn()
        assert turn.add("  ") is None
        assert turn.add("Hi") == "  Hi"

    def test_withheld_returns_the_text_only_for_a_suspected_call(self):
        prose, call = _Turn(), _Turn()
        prose.add("Hello")
        call.add("{oops")
        assert prose.withheld() is None
        assert call.withheld() == "{oops"

    def test_text_accumulates_everything(self):
        turn = _Turn()
        turn.add("a")
        turn.add("b")
        assert turn.text == "ab"


class TestAnswerStream:
    async def _events(self, settings, *turns, **overrides):
        runtime = Runtime(settings.model_copy(update=overrides) if overrides else settings)
        runtime.model = Chunked(*turns)
        try:
            return [event async for event in Orchestrator(runtime).answer_stream("q")]
        finally:
            runtime.close()

    def _text(self, events) -> str:
        return "".join(e.text for e in events if isinstance(e, DeltaEvent))

    async def test_prose_arrives_in_pieces(self, settings):
        events = await self._events(settings, "The DAG runs at 02:00 UTC.")
        deltas = [e for e in events if isinstance(e, DeltaEvent)]
        assert len(deltas) > 1
        assert self._text(events) == "The DAG runs at 02:00 UTC."

    async def test_exactly_one_done_event_arrives_last(self, settings):
        events = await self._events(settings, "Answer.")
        assert isinstance(events[-1], DoneEvent)
        assert sum(isinstance(e, DoneEvent) for e in events) == 1

    async def test_the_done_event_matches_the_streamed_text(self, settings):
        events = await self._events(settings, "Answer text.")
        assert events[-1].reply.answer == self._text(events)

    async def test_a_tool_call_never_reaches_the_client_as_text(self, settings):
        """The regression this guards: streaming raw turns would emit the JSON
        protocol into the answer."""
        events = await self._events(
            settings,
            tool_call("warehouse_query", sql="select region from revenue"),
            "EMEA and AMER.",
        )
        assert "tool" not in self._text(events)
        assert "{" not in self._text(events)
        assert self._text(events) == "EMEA and AMER."

    async def test_a_step_event_is_emitted_for_the_tool(self, settings):
        events = await self._events(
            settings,
            tool_call("warehouse_query", sql="select region from revenue"),
            "Done.",
        )
        steps = [e for e in events if isinstance(e, StepEvent)]
        assert [s.step.tool for s in steps] == ["warehouse_query"]
        assert steps[0].step.ok

    async def test_the_step_precedes_the_answer(self, settings):
        events = await self._events(
            settings, tool_call("warehouse_query", sql="select region from revenue"), "Done."
        )
        kinds = [type(e).__name__ for e in events]
        assert kinds.index("StepEvent") < kinds.index("DeltaEvent")

    async def test_text_withheld_as_json_but_not_a_call_is_released(self, settings):
        """A turn opening with '{' that is not a tool call must still be shown,
        or the answer would silently vanish."""
        events = await self._events(settings, "{this is not a tool call}")
        assert self._text(events) == "{this is not a tool call}"
        assert events[-1].reply.answer == "{this is not a tool call}"

    async def test_a_failing_tool_still_streams_an_answer(self, settings):
        events = await self._events(
            settings, tool_call("warehouse_query", sql="DROP TABLE revenue"), "I cannot do that."
        )
        step = next(e for e in events if isinstance(e, StepEvent))
        assert not step.step.ok
        assert self._text(events) == "I cannot do that."

    async def test_tools_disabled_streams_a_single_turn(self, settings):
        events = await self._events(settings, "Straight answer.", enable_tools=False)
        assert not any(isinstance(e, StepEvent) for e in events)
        assert self._text(events) == "Straight answer."

    async def test_the_step_budget_is_reported(self, settings):
        call = tool_call("knowledge_search", query="again")
        events = await self._events(settings, call, call, "forced", max_tool_steps=2)
        assert events[-1].reply.step_limit_reached
        assert len(events[-1].reply.steps) == 2


class TestAskStreamEndpoint:
    def frames(self, body: str) -> list[tuple[str, dict]]:
        out = []
        for block in body.strip().split("\n\n"):
            lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
            if "event" in lines and "data" in lines:
                out.append((lines["event"], json.loads(lines["data"])))
        return out

    def test_the_response_is_an_event_stream(self, client):
        response = client.post("/ask/stream", json={"question": "hi"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    def test_delta_frames_then_one_done(self, client):
        frames = self.frames(client.post("/ask/stream", json={"question": "hi"}).text)
        kinds = [name for name, _ in frames]
        assert kinds.count("done") == 1
        assert kinds[-1] == "done"
        assert "delta" in kinds

    def test_the_concatenated_deltas_equal_the_final_answer(self, client):
        frames = self.frames(client.post("/ask/stream", json={"question": "hi"}).text)
        streamed = "".join(d["text"] for name, d in frames if name == "delta")
        done = next(d for name, d in frames if name == "done")
        assert streamed == done["answer"]

    def test_the_done_frame_carries_the_ask_body(self, client):
        frames = self.frames(client.post("/ask/stream", json={"question": "hi"}).text)
        done = next(d for name, d in frames if name == "done")
        assert set(done) == {"answer", "contexts", "steps", "step_limit_reached"}

    @pytest.mark.parametrize("question", ["", "   "])
    def test_a_blank_question_is_rejected_before_streaming(self, client, question):
        assert client.post("/ask/stream", json={"question": question}).status_code == 400

    def test_a_failure_is_reported_in_band(self, runtime):
        """Once the response has begun the status cannot change, so the error has
        to travel as a frame rather than as a 500."""

        class Exploding:
            async def generate(self, messages):
                raise RuntimeError("backend on fire")

        runtime.model = Exploding()
        app.dependency_overrides[get_runtime] = lambda: runtime
        try:
            from fastapi.testclient import TestClient

            response = TestClient(app).post("/ask/stream", json={"question": "hi"})
            frames = self.frames(response.text)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert ("error", frames[-1][1]) == (frames[-1][0], frames[-1][1])
        assert "backend on fire" in frames[-1][1]["detail"]
