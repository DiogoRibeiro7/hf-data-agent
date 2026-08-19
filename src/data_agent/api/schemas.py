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


class AskResponse(BaseModel):
    answer: str
    contexts: list[ContextOut]


class ToolRequest(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    result: str
