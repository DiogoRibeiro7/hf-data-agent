"""AGENT-API: the single funnel every entrypoint hits (UI, MCP, Slack).

Endpoints:
  POST /ask    -> RAG answer from the open HF model
  POST /tool   -> invoke a live data tool directly (warehouse / airflow / kb)
  GET  /health

The service ships without authentication and binds all interfaces by default.
Put it behind an authenticating proxy before exposing it. See SECURITY.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from data_agent import __version__
from data_agent.api.schemas import (
    AskRequest,
    AskResponse,
    ContextOut,
    ToolRequest,
    ToolResponse,
)
from data_agent.datasources.sql_guard import UnsafeSQLError
from data_agent.mcp.tools import TOOLS
from data_agent.orchestrator.agent import Orchestrator
from data_agent.runtime import get_runtime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Build the runtime eagerly, and release its pools and clients on shutdown."""
    get_runtime()
    yield
    await get_runtime().aclose()


app = FastAPI(title="HF Data Agent", version=__version__, lifespan=lifespan)
_UI = Path(__file__).resolve().parent.parent / "entrypoints" / "ui" / "index.html"


@app.get("/health")
def health() -> dict:
    rt = get_runtime()
    return {
        "status": "ok",
        "version": __version__,
        "model_backend": rt.settings.model_backend,
        "model_id": rt.settings.model_id,
        "kb_chunks": len(rt.retriever.store),
    }


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(400, "empty question")
    reply = await Orchestrator(get_runtime()).answer(req.question)
    return AskResponse(
        answer=reply.answer,
        contexts=[ContextOut(source=c.source, score=c.score, text=c.text) for c in reply.contexts],
    )


@app.post("/tool", response_model=ToolResponse)
def tool(req: ToolRequest) -> ToolResponse:
    entry = TOOLS.get(req.name)
    if entry is None:
        raise HTTPException(404, f"unknown tool {req.name!r}. available: {sorted(TOOLS)}")
    fn, _ = entry
    try:
        return ToolResponse(result=fn(get_runtime(), **req.args))
    except UnsafeSQLError as exc:
        # The caller sent a statement the read-only guard rejected: their fault, not ours.
        raise HTTPException(400, str(exc)) from exc
    except TypeError as exc:
        # Wrong or missing arguments for this tool.
        raise HTTPException(400, f"bad arguments for tool {req.name!r}: {exc}") from exc
    except Exception as exc:  # surface adapter errors to the caller
        raise HTTPException(500, str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return _UI.read_text(encoding="utf-8") if _UI.exists() else "<h1>HF Data Agent</h1>"
