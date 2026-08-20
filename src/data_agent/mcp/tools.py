"""The agent's capabilities, defined once. The orchestrator calls these directly;
the MCP server re-exports them so external MCP clients get the same tools.

Each tool carries enough metadata to be described to a model, so the tool-calling
loop and the MCP server advertise the same surface without a second definition.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from data_agent.runtime import Runtime

logger = logging.getLogger(__name__)

#: Tools take the runtime plus keyword arguments and return rendered text.
ToolFn = Callable[..., str]


@dataclass(frozen=True)
class ToolSpec:
    """One capability, described well enough for a model to invoke it."""

    name: str
    fn: ToolFn
    description: str
    #: argument name -> what it means, in the words the model will read.
    parameters: Mapping[str, str] = field(default_factory=dict)
    #: arguments that must be supplied; the rest have defaults.
    required: tuple[str, ...] = ()

    def signature(self) -> str:
        """A one-line rendering used in the prompt's tool catalogue."""
        args = ", ".join(
            f"{name}{'' if name in self.required else '?'}" for name in self.parameters
        )
        return f"{self.name}({args})"


def knowledge_search(rt: Runtime, query: str) -> str:
    """Search the pre-processed company knowledge base (RAG)."""
    hits = rt.retriever.retrieve(query)
    logger.debug("knowledge_search", extra={"hits": len(hits)})
    if not hits:
        return "No knowledge-base results. (Has ingestion run?)"
    return "\n\n".join(f"[{h.source} | {h.score:.3f}] {h.text}" for h in hits)


def warehouse_query(rt: Runtime, sql: str) -> str:
    """Run read-only SQL against the data warehouse and return a table.

    The statement is validated by `datasources.sql_guard` before execution;
    anything that is not a single read-only query raises `UnsafeSQLError`.
    """
    started = time.perf_counter()
    result = rt.datasources["warehouse"].query(sql)
    logger.info(
        "warehouse_query",
        extra={
            "rows": len(result.rows),
            "truncated": result.truncated,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return result.to_markdown()


def list_dags(rt: Runtime, dag_id: str = "list") -> str:
    """List Airflow DAGs or recent runs for a given dag_id."""
    return rt.datasources["airflow"].query(dag_id).to_markdown()


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="knowledge_search",
            fn=knowledge_search,
            description=(
                "Search the company knowledge base (runbooks, wikis, design docs). "
                "Use for policy, ownership, process and 'how does X work' questions."
            ),
            parameters={"query": "Natural-language search phrase."},
            required=("query",),
        ),
        ToolSpec(
            name="warehouse_query",
            fn=warehouse_query,
            description=(
                "Run one read-only SQL SELECT against the data warehouse and get a "
                "table back. Use for actual numbers. Writes and DDL are rejected."
            ),
            parameters={"sql": "A single read-only SELECT (or WITH ... SELECT) statement."},
            required=("sql",),
        ),
        ToolSpec(
            name="list_dags",
            fn=list_dags,
            description=(
                "List Airflow DAGs, or the recent runs of one DAG. Use for pipeline "
                "status and freshness questions."
            ),
            parameters={"dag_id": "A dag_id, or 'list' for all DAGs. Defaults to 'list'."},
        ),
    )
}
