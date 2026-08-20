from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str
    entrypoint: str = "api"  # ui | slack | mcp_local | mcp_remote | api


class ContextOut(BaseModel):
    source: str
    score: float
    text: str


class ToolStepOut(BaseModel):
    """One tool execution from the agent's loop, in the order it happened."""

    tool: str
    args: dict[str, Any]
    result: str
    ok: bool


class AskResponse(BaseModel):
    answer: str
    contexts: list[ContextOut]
    #: Empty when the model answered without reaching for a tool.
    steps: list[ToolStepOut] = Field(default_factory=list)
    #: True when the loop hit DA_MAX_TOOL_STEPS and was forced to conclude.
    step_limit_reached: bool = False


class ToolRequest(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    result: str
