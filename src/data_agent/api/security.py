"""Bearer-token authentication for the HTTP API.

Auth is off when `DA_API_TOKEN` is empty, because the offline quickstart has to
keep working with no configuration at all. That would leave the service open by
default, so the *bind address* carries the safety instead: `DA_API_HOST` now
defaults to loopback, and `require_safe_binding` refuses to serve a non-loopback
interface without a token. Convenient locally, not silently exposed.

Comparison is constant-time. A token check that short-circuits on the first
wrong byte leaks the token's prefix to anyone who can time the response.
"""

from __future__ import annotations

import ipaddress
import logging
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from data_agent.config import Settings

logger = logging.getLogger(__name__)

#: auto_error=False so a missing header reaches us as None; we want to answer
#: with our own 401 and a WWW-Authenticate challenge, not FastAPI's 403.
_bearer = HTTPBearer(auto_error=False, description="DA_API_TOKEN")

#: Alias so the dependency is declared in the annotation, not the default.
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]

UNAUTHENTICATED = HTTPException(
    status_code=401,
    detail="missing or invalid bearer token",
    headers={"WWW-Authenticate": "Bearer"},
)


class UnsafeBindingError(RuntimeError):
    """Raised when the server would expose an unauthenticated port."""


def token_matches(presented: str | None, expected: str) -> bool:
    """Constant-time token comparison."""
    if not presented:
        return False
    return secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def _settings_of(request: Request) -> Settings:
    """Read settings from the request's runtime, so tests that override the
    runtime dependency also override what auth checks."""
    from data_agent.runtime import get_runtime

    app = request.app
    override = app.dependency_overrides.get(get_runtime)
    runtime = override() if override else get_runtime()
    return runtime.settings


def is_authenticated(request: Request, credentials: BearerCredentials = None) -> bool:
    """True when the caller proved the token, or when auth is switched off."""
    expected = _settings_of(request).api_token
    if not expected:
        return True
    return credentials is not None and token_matches(credentials.credentials, expected)


def require_token(request: Request, credentials: BearerCredentials = None) -> None:
    """Dependency for routes that must never be reachable anonymously."""
    expected = _settings_of(request).api_token
    if not expected:
        return
    if credentials is None or not token_matches(credentials.credentials, expected):
        logger.warning(
            "rejected unauthenticated request",
            extra={"path": request.url.path, "presented_token": credentials is not None},
        )
        raise UNAUTHENTICATED


def is_loopback(host: str) -> bool:
    """True for addresses that are only reachable from this machine."""
    candidate = host.strip()
    if candidate in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        # A hostname we cannot resolve to a literal: assume it is routable.
        return False


def require_safe_binding(settings: Settings) -> None:
    """Refuse to serve a non-loopback interface with no token.

    Raises:
        UnsafeBindingError: unless a token is set, the bind address is
            loopback-only, or the operator explicitly opted in.
    """
    if settings.api_token or settings.allow_unauthenticated:
        return
    if is_loopback(settings.api_host):
        return
    raise UnsafeBindingError(
        f"refusing to bind {settings.api_host} without authentication: this would "
        f"expose /ask and /tool, which can query your warehouse, to anyone who "
        f"can reach the port.\n"
        f"Set DA_API_TOKEN to require a bearer token, bind DA_API_HOST=127.0.0.1 "
        f"for local-only use, or set DA_ALLOW_UNAUTHENTICATED=true if this port is "
        f"already protected by something else (a proxy, a private network)."
    )


def require_safe_mcp_binding(settings: Settings) -> None:
    """Refuse to expose the remote MCP transport on a routable interface.

    Unlike the HTTP API, this transport has **no bearer authentication**.
    FastMCP's built-in auth is an OAuth resource-server model — it wants an
    issuer URL and a resource server URL, not a shared secret — so
    `DA_API_TOKEN` does not protect it and pretending otherwise would be worse
    than saying so. Exposing it therefore has to be a deliberate choice.

    Raises:
        UnsafeBindingError: for a non-loopback bind without an explicit opt-in.
    """
    if settings.allow_unauthenticated or is_loopback(settings.mcp_host):
        return
    raise UnsafeBindingError(
        f"refusing to bind the remote MCP transport to {settings.mcp_host}: it has "
        f"no authentication of its own, and its tools can query your warehouse.\n"
        f"Keep DA_MCP_HOST=127.0.0.1 and reach it through an authenticating proxy, "
        f"or set DA_ALLOW_UNAUTHENTICATED=true if the port is already protected."
    )
