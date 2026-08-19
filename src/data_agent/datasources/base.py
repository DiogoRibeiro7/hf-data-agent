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
    #: True when the source held more rows than it was willing to return.
    truncated: bool = False

    def to_markdown(self, limit: int = 20) -> str:
        if not self.rows:
            return "(no rows)"
        head = "| " + " | ".join(self.columns) + " |"
        sep = "| " + " | ".join("---" for _ in self.columns) + " |"
        body = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in self.rows[:limit])
        table = f"{head}\n{sep}\n{body}"
        if self.truncated or len(self.rows) > limit:
            table += f"\n\n_showing {min(limit, len(self.rows))} row(s); result truncated._"
        return table


class DataSource(Protocol):
    name: str

    def query(self, statement: str) -> QueryResult: ...
