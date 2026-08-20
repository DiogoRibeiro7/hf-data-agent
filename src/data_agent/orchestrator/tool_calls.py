"""The text protocol the tool-calling loop speaks.

Open-weights models vary wildly in whether they support native function calling,
so the agent uses a plain-text contract that any instruct model can follow: emit
a single JSON object with a `tool` key, and nothing else.

Real models do not follow that cleanly. They wrap the object in ``` fences, add
a sentence of preamble, or emit prose that merely contains a brace. The parser
here is deliberately forgiving about packaging and strict about shape: it scans
for balanced JSON objects and accepts the first one that actually looks like a
tool call, so a stray brace in an answer does not get mistaken for one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

__all__ = ["ToolCall", "parse_tool_call"]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


def _json_candidates(text: str) -> list[str]:
    """Every balanced ``{...}`` run in `text`, outermost first.

    Braces inside JSON string literals are skipped, so a query like
    ``{"sql": "select '{' "}`` does not truncate the candidate.
    """
    candidates: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : i + 1])
    return candidates


def parse_tool_call(text: str) -> ToolCall | None:
    """Extract a tool call from a model turn, or None if it is a final answer.

    Returning None is the loop's exit condition, so this must not report a tool
    call for ordinary prose. A candidate qualifies only when it is a JSON object
    whose `tool` is a non-empty string and whose `args`, if present, is an
    object.
    """
    if not text:
        return None

    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue

        name = parsed.get("tool")
        if not isinstance(name, str) or not name.strip():
            continue

        args = parsed.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            continue
        if any(not isinstance(key, str) for key in args):
            continue

        return ToolCall(name=name.strip(), args=args)

    return None
