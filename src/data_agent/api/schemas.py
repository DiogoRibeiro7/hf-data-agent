from __future__ import annotations

from pydantic import BaseModel


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
    args: dict = {}


class ToolResponse(BaseModel):
    result: str
