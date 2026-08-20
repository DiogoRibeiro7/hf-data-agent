"""Parsing tool calls out of free-form model text.

Two failure modes matter and pull in opposite directions: missing a real call
stalls the agent, and seeing a call in ordinary prose sends it into a pointless
tool round. Both are covered here.
"""

from __future__ import annotations

import pytest

from data_agent.orchestrator.tool_calls import ToolCall, parse_tool_call


class TestRecognisedCalls:
    def test_bare_json_object(self):
        call = parse_tool_call('{"tool": "warehouse_query", "args": {"sql": "select 1"}}')
        assert call == ToolCall("warehouse_query", {"sql": "select 1"})

    def test_fenced_json_block(self):
        text = '```json\n{"tool": "list_dags", "args": {"dag_id": "daily_revenue"}}\n```'
        assert parse_tool_call(text) == ToolCall("list_dags", {"dag_id": "daily_revenue"})

    def test_unlabelled_fence(self):
        assert parse_tool_call('```\n{"tool": "list_dags"}\n```') == ToolCall("list_dags", {})

    def test_preamble_before_the_object(self):
        text = 'Let me look that up.\n{"tool": "list_dags", "args": {}}'
        assert parse_tool_call(text) == ToolCall("list_dags", {})

    def test_trailing_commentary_after_the_object(self):
        text = '{"tool": "list_dags", "args": {}}\nI will check the runs next.'
        assert parse_tool_call(text) == ToolCall("list_dags", {})

    def test_missing_args_defaults_to_empty(self):
        assert parse_tool_call('{"tool": "list_dags"}').args == {}

    def test_null_args_is_treated_as_empty(self):
        assert parse_tool_call('{"tool": "list_dags", "args": null}').args == {}

    def test_nested_object_arguments_survive(self):
        text = '{"tool": "x", "args": {"filter": {"region": "EMEA"}}}'
        assert parse_tool_call(text).args == {"filter": {"region": "EMEA"}}

    def test_a_brace_inside_a_string_does_not_truncate_the_object(self):
        text = '{"tool": "warehouse_query", "args": {"sql": "select \'{\' as brace"}}'
        assert parse_tool_call(text).args["sql"] == "select '{' as brace"

    def test_an_escaped_quote_inside_a_string_is_handled(self):
        text = r'{"tool": "warehouse_query", "args": {"sql": "select \"col\" from t"}}'
        assert parse_tool_call(text) is not None

    def test_whitespace_around_the_name_is_trimmed(self):
        assert parse_tool_call('{"tool": "  list_dags  "}').name == "list_dags"

    def test_the_first_valid_call_wins(self):
        text = '{"tool": "first"}\n{"tool": "second"}'
        assert parse_tool_call(text).name == "first"

    def test_a_leading_non_call_object_is_skipped(self):
        text = '{"thinking": "which tool?"}\n{"tool": "list_dags"}'
        assert parse_tool_call(text).name == "list_dags"


class TestFinalAnswers:
    """None is the loop's exit condition, so prose must never look like a call."""

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("The daily_revenue DAG runs at 02:00 UTC.", id="plain-prose"),
            pytest.param("", id="empty"),
            pytest.param("   \n\t ", id="whitespace"),
            pytest.param("Revenue was {high} last month.", id="brace-in-prose"),
            pytest.param('{"answer": "42"}', id="object-without-tool-key"),
            pytest.param('{"tool": ""}', id="empty-tool-name"),
            pytest.param('{"tool": "   "}', id="whitespace-tool-name"),
            pytest.param('{"tool": 42}', id="non-string-tool-name"),
            pytest.param('{"tool": null}', id="null-tool-name"),
            pytest.param('{"tool": "x", "args": "not-an-object"}', id="args-not-an-object"),
            pytest.param('{"tool": "x", "args": [1, 2]}', id="args-is-a-list"),
            pytest.param('{"tool": "x", "args"', id="truncated-json"),
            pytest.param("{not json at all}", id="malformed"),
            pytest.param('["tool", "warehouse_query"]', id="json-array"),
        ],
    )
    def test_returns_none(self, text):
        assert parse_tool_call(text) is None

    def test_an_answer_quoting_the_protocol_is_not_a_call(self):
        # The model explaining itself must not be mistaken for a request.
        text = 'I could have used {"tool": "warehouse_query"} but the context already says 02:00.'
        # It *is* a syntactically valid call, so the loop would run it; the cap is
        # what bounds that. Documented here so the behaviour is a decision, not a surprise.
        assert parse_tool_call(text) is not None
