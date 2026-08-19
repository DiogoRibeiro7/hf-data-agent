"""The orchestrator is the single funnel: retrieve, ground, generate."""

from __future__ import annotations

import pytest

from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.retriever import RetrievedContext
from data_agent.knowledge.sources.base import Document
from data_agent.model.base import Message
from data_agent.orchestrator.agent import SYSTEM, AgentReply, Orchestrator
from data_agent.runtime import Runtime


class ListSource:
    name = "test"

    def __init__(self, docs):
        self._docs = docs

    def fetch(self):
        yield from self._docs


class RecordingProvider:
    """Captures the messages it was handed so prompt assembly can be asserted."""

    def __init__(self, reply: str = "canned answer"):
        self.reply = reply
        self.seen: list[Message] = []

    async def generate(self, messages):
        self.seen = list(messages)
        return self.reply


@pytest.fixture
def orchestrator(runtime):
    return Orchestrator(runtime)


class TestPromptAssembly:
    def test_context_is_injected_into_the_system_message(self, orchestrator):
        contexts = [RetrievedContext(text="revenue runs at 02:00", source="kb", score=0.9)]
        messages = orchestrator._build_messages("when?", contexts)
        assert messages[0].role == "system"
        assert "CONTEXT:" in messages[0].content
        assert "[kb]" in messages[0].content
        assert "revenue runs at 02:00" in messages[0].content

    def test_without_context_the_system_prompt_is_left_bare(self, orchestrator):
        messages = orchestrator._build_messages("when?", [])
        assert messages[0].content == SYSTEM

    def test_the_question_is_the_user_message(self, orchestrator):
        messages = orchestrator._build_messages("when?", [])
        assert messages[-1].role == "user"
        assert messages[-1].content == "when?"

    def test_every_context_is_included(self, orchestrator):
        contexts = [
            RetrievedContext(text=f"fact {i}", source=f"src{i}", score=0.5) for i in range(3)
        ]
        system = orchestrator._build_messages("q", contexts)[0].content
        for i in range(3):
            assert f"fact {i}" in system


class TestAnswer:
    async def test_retrieval_feeds_generation(self, settings):
        docs = [Document(id="1", text="Board numbers come from the revenue table.", source="kb")]
        ingest([ListSource(docs)], settings)
        rt = Runtime(settings)
        provider = RecordingProvider()
        rt.model = provider
        try:
            reply = await Orchestrator(rt).answer("where do board numbers come from?")
        finally:
            rt.close()

        assert isinstance(reply, AgentReply)
        assert reply.answer == "canned answer"
        assert reply.contexts
        assert "revenue table" in provider.seen[0].content

    async def test_an_empty_knowledge_base_still_answers(self, runtime):
        reply = await Orchestrator(runtime).answer("anything at all?")
        assert reply.answer
        assert reply.contexts == []

    async def test_the_mock_provider_reports_whether_it_was_grounded(self, settings):
        ingest([ListSource([Document(id="1", text="grounding text", source="kb")])], settings)
        rt = Runtime(settings)
        try:
            reply = await Orchestrator(rt).answer("what grounds this?")
        finally:
            rt.close()
        assert "context provided" in reply.answer
