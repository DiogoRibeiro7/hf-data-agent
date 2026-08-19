"""The agent's capabilities, defined once. The orchestrator calls these directly;
the MCP server re-exports them so external MCP clients get the same tools."""

from __future__ import annotations

import logging
import time

from data_agent.runtime import Runtime

logger = logging.getLogger(__name__)


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


# name -> (callable, human-readable description) for MCP registration.
TOOLS = {
    "knowledge_search": (knowledge_search, "Search company knowledge base (RAG)."),
    "warehouse_query": (warehouse_query, "Run read-only SQL on the warehouse."),
    "list_dags": (list_dags, "List Airflow DAGs / runs."),
}
