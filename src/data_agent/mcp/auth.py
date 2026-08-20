"""Bearer authentication for the remote MCP transport.

The MCP server library does support authentication, but only as an OAuth
resource server: supplying a `token_verifier` without `AuthSettings` — an issuer
URL and a resource server URL — is rejected outright. This project authenticates
with a single shared secret (`DA_API_TOKEN`), so adopting that model would mean
inventing an issuer and advertising OAuth discovery metadata for an
authorization server that does not exist.

The transport is a plain ASGI application, so the gate goes in front of it
instead. Same token, same constant-time comparison, and the same 401 shape as
the HTTP API.

`lifespan` scopes pass through untouched: the session manager starts there, and
gating it would break the server rather than protect it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from data_agent.api.security import token_matches

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_BODY = json.dumps({"detail": "missing or invalid bearer token"}).encode()


class BearerAuthMiddleware:
    """Require `Authorization: Bearer <token>` on every request to `app`."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        if not token:
            raise ValueError("BearerAuthMiddleware requires a non-empty token")
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")

        # Startup and shutdown are not requests and carry no credentials.
        if kind == "lifespan":
            await self.app(scope, receive, send)
            return

        if self._authorised(scope):
            await self.app(scope, receive, send)
            return

        logger.warning(
            "rejected unauthenticated mcp request",
            extra={"path": scope.get("path", "?"), "scope_type": kind},
        )
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await self._deny(send)

    def _authorised(self, scope: Scope) -> bool:
        for name, value in scope.get("headers", []):
            if name.lower() != b"authorization":
                continue
            scheme, _, presented = value.decode("latin-1").partition(" ")
            if scheme.lower() != "bearer":
                return False
            return token_matches(presented.strip(), self.token)
        return False

    async def _deny(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _BODY})
