"""The orchestrator is the single funnel: retrieve, ground, call tools, answer."""

from __future__ import annotations

import json

import pytest

from data_agent.knowledge.ingest import ingest
from data_agent.knowledge.retriever import RetrievedContext
from data_agent.knowledge.sources.base import Document
from data_agent.model.base import CONTEXT_MARKER, Message
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


class ScriptedProvider:
    """Replays canned turns in order, recording what it was shown each time.

    This is how a tool-calling model is simulated without a model: each turn is
    either a JSON tool call or a final answer.
    """

    def __init__(self, *turns: str, default: str = "Final answer."):
        self.turns = list(turns)
        self.default = default
        self.calls: list[list[Message]] = []

    async def generate(self, messages):
        self.calls.append(list(messages))
        return self.turns.pop(0) if self.turns else self.default


def call(tool: str, **args) -> str:
    return json.dumps({"tool": tool, "args": args})


@pytest.fixture
def orchestrator(runtime):
    return Orchestrator(runtime)


def build(settings, provider, **overrides):
    """A runtime wired to a scripted provider, with settings overrides applied."""
    rt = Runtime(settings.model_copy(update=overrides) if overrides else settings)
    rt.model = provider
    return rt


class TestPromptAssembly:
    def test_context_is_injected_into_the_system_message(self, orchestrator):
        contexts = [RetrievedContext(text="revenue runs at 02:00", source="kb", score=0.9)]
        messages = orchestrator._build_messages("when?", contexts)
        assert messages[0].role == "system"
        assert "CONTEXT:" in messages[0].content
        assert "[kb]" in messages[0].content
        assert "revenue runs at 02:00" in messages[0].content

    def test_without_context_no_context_block_is_attached(self, orchestrator):
        messages = orchestrator._build_messages("when?", [])
        assert CONTEXT_MARKER not in messages[0].content

    def test_with_tools_disabled_the_prompt_is_exactly_the_base_instruction(self, settings):
        rt = Runtime(settings.model_copy(update={"enable_tools": False}))
        try:
            messages = Orchestrator(rt)._build_messages("when?", [])
        finally:
            rt.close()
        assert messages[0].content == SYSTEM

    def test_the_tool_catalogue_is_advertised_when_tools_are_enabled(self, orchestrator):
        system = orchestrator._build_messages("when?", [])[0].content
        assert "warehouse_query" in system
        assert "TOOLS:" in system

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
        provider = RecordingProvider()
        rt = build(settings, provider)
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


class TestToolLoop:
    async def test_a_model_that_never_calls_a_tool_answers_directly(self, settings):
        """The single-shot RAG path still exists; it is just the zero-tool case."""
        provider = ScriptedProvider("The DAG runs at 02:00 UTC.")
        rt = build(settings, provider)
        try:
            reply = await Orchestrator(rt).answer("when does it run?")
        finally:
            rt.close()
        assert reply.answer == "The DAG runs at 02:00 UTC."
        assert reply.steps == []
        assert len(provider.calls) == 1

    async def test_one_tool_call_then_an_answer(self, settings):
        provider = ScriptedProvider(
            call("warehouse_query", sql="select region from revenue"),
            "EMEA, AMER and APAC.",
        )
        rt = build(settings, provider)
        try:
            reply = await Orchestrator(rt).answer("which regions?")
        finally:
            rt.close()

        assert reply.answer == "EMEA, AMER and APAC."
        assert len(reply.steps) == 1
        assert reply.steps[0].tool == "warehouse_query"
        assert reply.steps[0].ok
        assert not reply.step_limit_reached

    async def test_the_tool_result_is_fed_back_to_the_model(self, settings):
        provider = ScriptedProvider(
            call("warehouse_query", sql="select region from revenue"),
            "Done.",
        )
        rt = build(settings, provider)
        try:
            await Orchestrator(rt).answer("which regions?")
        finally:
            rt.close()

        second_turn = provider.calls[1]
        observation = second_turn[-1].content
        assert "OBSERVATION from warehouse_query" in observation
        assert "EMEA" in observation  # the real query actually ran

    async def test_the_assistant_turn_is_kept_in_the_transcript(self, settings):
        raw = call("list_dags", dag_id="list")
        provider = ScriptedProvider(raw, "Done.")
        rt = build(settings, provider)
        try:
            await Orchestrator(rt).answer("which dags?")
        finally:
            rt.close()
        roles = [m.role for m in provider.calls[1]]
        assert "assistant" in roles

    async def test_several_tools_run_in_order(self, settings):
        provider = ScriptedProvider(
            call("knowledge_search", query="revenue"),
            call("warehouse_query", sql="select region from revenue"),
            "Combined answer.",
        )
        rt = build(settings, provider)
        try:
            reply = await Orchestrator(rt).answer("tell me everything")
        finally:
            rt.close()
        assert [s.tool for s in reply.steps] == ["knowledge_search", "warehouse_query"]


class TestToolLoopRecovery:
    """A bad tool call must come back as an observation, not kill the request."""

    async def test_an_unknown_tool_is_reported_back(self, settings):
        provider = ScriptedProvider(call("teleport"), "Sorry, I cannot do that.")
        rt = build(settings, provider)
        try:
            reply = await Orchestrator(rt).answer("teleport me")
        finally:
            rt.close()

        assert reply.answer == "Sorry, I cannot do that."
        assert not reply.steps[0].ok
        assert "unknown tool" in reply.steps[0].result
        assert "ERROR from teleport" in provider.calls[1][-1].content

    async def test_a_missing_required_argument_is_reported_back(self, settings):
        provider = ScriptedProvider(call("warehouse_query"), "I need the SQL.")
        rt = build(settings, provider)
        try:
            reply = await Orchestrator(rt).answer("query something")
        finally:
            rt.close()
        assert not reply.steps[0].ok
        assert "missing required argument" in reply.steps[0].result

    async def test_rejected_sql_becomes_an_observation_not_an_exception(self, settings):
        """The guard raising must not take the whole request down — the model
        gets told why and can correct itself."""
        provider = ScriptedProvider(
            call("warehouse_query", sql="DROP TABLE revenue"),
            call("warehouse_query", sql="select region from revenue"),
            "Recovered.",
        )
        rt = build(settings, provider)
        try:
            reply = await Orchestrator(rt).answer("clear the table")
        finally:
            rt.close()

        assert reply.answer == "Recovered."
        assert not reply.steps[0].ok
        assert "UnsafeSQLError" in reply.steps[0].result
        assert reply.steps[1].ok

    async def test_an_optional_argument_may_be_omitted(self, settings):
        provider = ScriptedProvider(call("list_dags"), "Done.")

        class FakeAirflow:
            name = "airflow"

            def query(self, statement):
                from data_agent.datasources.base import QueryResult

                return QueryResult(columns=["dag_id"], rows=[[statement]])

        rt = build(settings, provider)
        rt.datasources["airflow"] = FakeAirflow()
        try:
            reply = await Orchestrator(rt).answer("which dags?")
        finally:
            rt.close()
        assert reply.steps[0].ok
        assert "list" in reply.steps[0].result  # the default was applied


class TestToolLoopBounds:
    async def test_the_step_budget_is_enforced(self, settings):
        """A model stuck in a tool loop must be stopped, not followed."""
        provider = ScriptedProvider(default=call("knowledge_search", query="again"))
        rt = build(settings, provider, max_tool_steps=3)
        try:
            reply = await Orchestrator(rt).answer("loop forever")
        finally:
            rt.close()

        assert len(reply.steps) == 3
        assert reply.step_limit_reached

    async def test_a_final_answer_is_forced_after_the_budget(self, settings):
        provider = ScriptedProvider(
            call("knowledge_search", query="a"),
            call("knowledge_search", query="b"),
            "Concluding without more tools.",
        )
        rt = build(settings, provider, max_tool_steps=2)
        try:
            reply = await Orchestrator(rt).answer("dig")
        finally:
            rt.close()

        assert reply.answer == "Concluding without more tools."
        assert reply.step_limit_reached
        assert "maximum number of tool calls" in provider.calls[-1][-1].content

    async def test_zero_steps_disables_tool_use_without_disabling_the_agent(self, settings):
        provider = ScriptedProvider(default="Answer without tools.")
        rt = build(settings, provider, max_tool_steps=0)
        try:
            reply = await Orchestrator(rt).answer("anything")
        finally:
            rt.close()
        assert reply.steps == []
        assert reply.answer == "Answer without tools."

    async def test_tools_can_be_switched_off_entirely(self, settings):
        provider = ScriptedProvider(default=call("warehouse_query", sql="select 1"))
        rt = build(settings, provider, enable_tools=False)
        try:
            reply = await Orchestrator(rt).answer("anything")
        finally:
            rt.close()

        # The JSON is returned verbatim: with tools off it is just text.
        assert reply.steps == []
        assert len(provider.calls) == 1

    async def test_a_long_observation_is_truncated(self, settings):
        class Chatty:
            name = "airflow"

            def query(self, statement):
                from data_agent.datasources.base import QueryResult

                return QueryResult(columns=["x"], rows=[["y" * 200] for _ in range(50)])

        provider = ScriptedProvider(call("list_dags", dag_id="list"), "Done.")
        rt = build(settings, provider, tool_result_max_chars=100)
        rt.datasources["airflow"] = Chatty()
        try:
            reply = await Orchestrator(rt).answer("dags?")
        finally:
            rt.close()

        assert "result truncated" in reply.steps[0].result
        assert len(reply.steps[0].result) < 200
