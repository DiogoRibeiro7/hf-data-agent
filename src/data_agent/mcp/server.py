"""AGENT-MCP: exposes the agent + its data tools over the Model Context Protocol.

Same FastMCP instance is launched as a LOCAL entrypoint (stdio) or REMOTE
entrypoint (HTTP/SSE) — see entrypoints/mcp_local.py and mcp_remote.py.

Install: pip install "hf-data-agent[mcp]"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from data_agent.orchestrator.agent import Orchestrator
from data_agent.runtime import get_runtime

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def build_mcp() -> FastMCP:
    from mcp.server.fastmcp import FastMCP

    rt = get_runtime()
    mcp = FastMCP(
        "hf-data-agent",
        host=rt.settings.mcp_host,
        port=rt.settings.mcp_port,
    )

    @mcp.tool()
    async def ask(question: str) -> str:
        """Ask the data agent a question (RAG over company knowledge)."""
        reply = await Orchestrator(rt).answer(question)
        return reply.answer

    @mcp.tool()
    def knowledge_search(query: str) -> str:
        """Search the pre-processed company knowledge base."""
        from data_agent.mcp.tools import knowledge_search as fn

        return fn(rt, query)

    @mcp.tool()
    def warehouse_query(sql: str) -> str:
        """Run read-only SQL against the data warehouse."""
        from data_agent.mcp.tools import warehouse_query as fn

        return fn(rt, sql)

    @mcp.tool()
    def list_dags(dag_id: str = "list") -> str:
        """List Airflow DAGs or recent runs for a dag_id."""
        from data_agent.mcp.tools import list_dags as fn

        return fn(rt, dag_id)

    return mcp
