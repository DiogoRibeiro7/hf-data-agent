"""The bearer gate in front of the remote MCP transport.

Driven as raw ASGI rather than through a client, so these run without the
optional `mcp` extra installed — the middleware is deliberately independent of
the MCP library.
"""

from __future__ import annotations

import json

import pytest

from data_agent.mcp.auth import BearerAuthMiddleware

TOKEN = "mcp-secret"


class SpyApp:
    """Records that it was reached, and what scope reached it."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"reached"})


def http_scope(*headers: tuple[bytes, bytes]) -> dict:
    return {"type": "http", "path": "/mcp", "method": "POST", "headers": list(headers)}


def bearer(token: str) -> tuple[bytes, bytes]:
    return (b"authorization", f"Bearer {token}".encode())


async def drive(middleware, scope) -> list[dict]:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def status_of(sent: list[dict]) -> int | None:
    for message in sent:
        if message["type"] == "http.response.start":
            return message["status"]
    return None


@pytest.fixture
def spy():
    return SpyApp()


@pytest.fixture
def guarded(spy):
    return BearerAuthMiddleware(spy, TOKEN)


class TestConstruction:
    def test_an_empty_token_is_refused(self, spy):
        """A middleware built with no token would authorise everything."""
        with pytest.raises(ValueError, match="non-empty token"):
            BearerAuthMiddleware(spy, "")


class TestAccepted:
    async def test_the_right_token_reaches_the_app(self, guarded, spy):
        sent = await drive(guarded, http_scope(bearer(TOKEN)))
        assert status_of(sent) == 200
        assert len(spy.calls) == 1

    async def test_the_scheme_is_case_insensitive(self, guarded, spy):
        header = (b"authorization", f"bearer {TOKEN}".encode())
        await drive(guarded, http_scope(header))
        assert len(spy.calls) == 1

    async def test_a_capitalised_header_name_is_matched(self, guarded, spy):
        header = (b"Authorization", f"Bearer {TOKEN}".encode())
        await drive(guarded, http_scope(header))
        assert len(spy.calls) == 1


class TestRejected:
    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param((), id="no-header"),
            pytest.param((bearer("wrong"),), id="wrong-token"),
            pytest.param((bearer(""),), id="empty-token"),
            pytest.param(((b"authorization", TOKEN.encode()),), id="no-scheme"),
            pytest.param(((b"authorization", f"Basic {TOKEN}".encode()),), id="wrong-scheme"),
            pytest.param(((b"x-api-key", TOKEN.encode()),), id="wrong-header"),
        ],
    )
    async def test_rejected_with_401(self, guarded, spy, headers):
        sent = await drive(guarded, http_scope(*headers))
        assert status_of(sent) == 401
        assert spy.calls == [], "the request must not reach the transport"

    async def test_the_challenge_header_is_sent(self, guarded):
        sent = await drive(guarded, http_scope())
        start = next(m for m in sent if m["type"] == "http.response.start")
        assert (b"www-authenticate", b"Bearer") in start["headers"]

    async def test_the_body_is_json(self, guarded):
        sent = await drive(guarded, http_scope())
        body = next(m for m in sent if m["type"] == "http.response.body")["body"]
        assert json.loads(body)["detail"]

    async def test_a_token_with_surrounding_space_still_matches(self, guarded, spy):
        header = (b"authorization", f"Bearer  {TOKEN} ".encode())
        await drive(guarded, http_scope(header))
        assert len(spy.calls) == 1


class TestNonHttpScopes:
    async def test_lifespan_passes_through_untouched(self, guarded, spy):
        """The session manager starts in lifespan; gating it would break the
        server rather than protect it."""
        scope = {"type": "lifespan"}
        sent = await drive(guarded, scope)
        assert spy.calls == [scope]
        assert status_of(sent) == 200

    async def test_an_unauthenticated_websocket_is_closed(self, guarded, spy):
        sent = await drive(guarded, {"type": "websocket", "path": "/mcp", "headers": []})
        assert sent == [{"type": "websocket.close", "code": 1008}]
        assert spy.calls == []

    async def test_an_authenticated_websocket_passes(self, guarded, spy):
        scope = {"type": "websocket", "path": "/mcp", "headers": [bearer(TOKEN)]}
        await drive(guarded, scope)
        assert len(spy.calls) == 1
