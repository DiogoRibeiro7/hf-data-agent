"""The agent's capabilities, defined once. The orchestrator calls these directly;
the MCP server re-exports them so external MCP clients get the same tools."""

from __future__ import annotations

from data_agent.runtime import Runtime


def knowledge_search(rt: Runtime, query: str) -> str:
    """Search the pre-processed company knowledge base (RAG)."""
    hits = rt.retriever.retrieve(query)
    if not hits:
        return "No knowledge-base results. (Has ingestion run?)"
    return "\n\n".join(f"[{h.source} | {h.score:.3f}] {h.text}" for h in hits)


def warehouse_query(rt: Runtime, sql: str) -> str:
    """Run read-only SQL against the data warehouse and return a table."""
    return rt.datasources["warehouse"].query(sql).to_markdown()


def list_dags(rt: Runtime, dag_id: str = "list") -> str:
    """List Airflow DAGs or recent runs for a given dag_id."""
    return rt.datasources["airflow"].query(dag_id).to_markdown()


# name -> (callable, json-schema-ish description) for MCP registration.
TOOLS = {
    "knowledge_search": (knowledge_search, "Search company knowledge base (RAG)."),
    "warehouse_query": (warehouse_query, "Run read-only SQL on the warehouse."),
    "list_dags": (list_dags, "List Airflow DAGs / runs."),
}
