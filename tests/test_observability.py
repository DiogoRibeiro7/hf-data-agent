"""Logging setup and request correlation."""

from __future__ import annotations

import json
import logging

import pytest

from data_agent.observability import (
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
    new_request_id,
    request_id_var,
)


@pytest.fixture(autouse=True)
def _restore_root_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    record.__dict__.update(extra)
    return record


class TestJsonFormatter:
    def test_emits_one_parsable_object(self):
        payload = json.loads(JsonFormatter().format(_record(request_id="abc123")))
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["request_id"] == "abc123"

    def test_extra_fields_are_included(self):
        payload = json.loads(JsonFormatter().format(_record(rows=42, truncated=True)))
        assert payload["rows"] == 42
        assert payload["truncated"] is True

    def test_unserialisable_values_do_not_raise(self):
        payload = json.loads(JsonFormatter().format(_record(obj=object())))
        assert "obj" in payload

    def test_exception_info_is_captured(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _record()
            record.exc_info = sys.exc_info()
        assert "boom" in json.loads(JsonFormatter().format(record))["exception"]


class TestRequestId:
    def test_ids_are_unique(self):
        assert new_request_id() != new_request_id()

    def test_filter_stamps_the_current_id(self):
        token = request_id_var.set("req-1")
        try:
            record = _record()
            RequestIdFilter().filter(record)
            assert record.request_id == "req-1"
        finally:
            request_id_var.reset(token)

    def test_default_is_a_placeholder_outside_a_request(self):
        record = _record()
        RequestIdFilter().filter(record)
        assert record.request_id == "-"


class TestConfigureLogging:
    def test_installs_a_single_handler(self):
        configure_logging("DEBUG", "json", force=True)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG

    def test_is_idempotent_without_force(self):
        configure_logging("INFO", "text", force=True)
        configure_logging("ERROR", "json")
        assert logging.getLogger().level == logging.INFO

    def test_json_format_selects_the_json_formatter(self):
        configure_logging("INFO", "json", force=True)
        assert isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)

    def test_text_format_does_not(self):
        configure_logging("INFO", "text", force=True)
        assert not isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)
