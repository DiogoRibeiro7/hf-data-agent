"""Live data platform adapters = the diagram's 'online sync calls'.

Unlike knowledge (pre-processed), these are queried at request time. They are
exposed to the model as MCP tools, so the agent can pull fresh numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]

    def to_markdown(self, limit: int = 20) -> str:
        if not self.rows:
            return "(no rows)"
        head = "| " + " | ".join(self.columns) + " |"
        sep = "| " + " | ".join("---" for _ in self.columns) + " |"
        body = "\n".join(
            "| " + " | ".join(str(c) for c in r) + " |" for r in self.rows[:limit]
        )
        return f"{head}\n{sep}\n{body}"


class DataSource(Protocol):
    name: str

    def query(self, statement: str) -> QueryResult: ...
