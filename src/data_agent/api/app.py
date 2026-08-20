"""AGENT-API: the single funnel every entrypoint hits (UI, MCP, Slack).

Endpoints:
  POST /ask    -> RAG answer from the open HF model
  POST /tool   -> invoke a live data tool directly (warehouse / airflow / kb)
  GET  /health

The service ships without authentication and binds all interfaces by default.
Put it behind an authenticating proxy before exposing it. See SECURITY.md.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from data_agent import __version__
from data_agent.api.schemas import (
    AskRequest,
    AskResponse,
    ContextOut,
    ToolRequest,
    ToolResponse,
    ToolStepOut,
)
from data_agent.api.security import is_authenticated, require_token
from data_agent.datasources.sql_guard import UnsafeSQLError
from data_agent.mcp.tools import TOOLS
from data_agent.observability import configure_logging, new_request_id, request_id_var
from data_agent.orchestrator.agent import Orchestrator
from data_agent.runtime import Runtime, get_runtime

logger = logging.getLogger(__name__)

#: Injected so tests (and embedders) can substitute a runtime via
#: `app.dependency_overrides[get_runtime]`.
RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Build the runtime eagerly, and release its pools and clients on shutdown."""
    rt = get_runtime()
    configure_logging(rt.settings.log_level, rt.settings.log_format)
    logger.info(
        "agent api ready",
        extra={
            "version": __version__,
            "model_backend": rt.settings.model_backend,
            "kb_chunks": len(rt.retriever.store),
        },
    )
    yield
    await get_runtime().aclose()


app = FastAPI(title="HF Data Agent", version=__version__, lifespan=lifespan)
_UI = Path(__file__).resolve().parent.parent / "entrypoints" / "ui" / "index.html"


@app.middleware("http")
async def correlate_requests(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Give every request an id, echo it back, and log how it went."""
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # Logged before the context variable is reset, so this access line carries
        # the same id as the lines emitted while the request was being handled.
        logger.info(
            "request handled",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return response
    finally:
        request_id_var.reset(token)


@app.get("/health")
def health(
    rt: RuntimeDep,
    authenticated: Annotated[bool, Depends(is_authenticated)],
) -> dict[str, Any]:
    """Liveness. Always reachable, because probes cannot carry a token, but the
    detail is withheld from anonymous callers once a token is configured."""
    body: dict[str, Any] = {"status": "ok", "version": __version__}
    if authenticated:
        body |= {
            "model_backend": rt.settings.model_backend,
            "model_id": rt.settings.model_id,
            "kb_chunks": len(rt.retriever.store),
        }
    return body


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_token)])
async def ask(req: AskRequest, rt: RuntimeDep) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(400, "empty question")
    reply = await Orchestrator(rt).answer(req.question)
    return AskResponse(
        answer=reply.answer,
        contexts=[ContextOut(source=c.source, score=c.score, text=c.text) for c in reply.contexts],
        steps=[
            ToolStepOut(tool=s.tool, args=s.args, result=s.result, ok=s.ok) for s in reply.steps
        ],
        step_limit_reached=reply.step_limit_reached,
    )


@app.post("/tool", response_model=ToolResponse, dependencies=[Depends(require_token)])
def tool(req: ToolRequest, rt: RuntimeDep) -> ToolResponse:
    entry = TOOLS.get(req.name)
    if entry is None:
        raise HTTPException(404, f"unknown tool {req.name!r}. available: {sorted(TOOLS)}")
    logger.info("tool invoked", extra={"tool": req.name, "arg_keys": sorted(req.args)})
    try:
        return ToolResponse(result=entry.fn(rt, **req.args))
    except UnsafeSQLError as exc:
        logger.warning("tool rejected unsafe sql", extra={"tool": req.name, "reason": str(exc)})
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
