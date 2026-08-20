"""Bearer auth and the binding guards.

The guards matter as much as the token check: auth is opt-in, so what actually
prevents an unauthenticated warehouse being published is the refusal to bind a
routable interface without one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from data_agent.api.app import app
from data_agent.api.security import (
    UnsafeBindingError,
    is_loopback,
    require_safe_binding,
    require_safe_mcp_binding,
    token_matches,
)
from data_agent.config import Settings
from data_agent.runtime import Runtime, get_runtime

TOKEN = "s3cret-token"


@pytest.fixture
def secured(settings):
    """A client whose runtime requires a bearer token."""
    runtime = Runtime(settings.model_copy(update={"api_token": TOKEN}))
    app.dependency_overrides[get_runtime] = lambda: runtime
    yield TestClient(app)
    app.dependency_overrides.clear()
    runtime.close()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestTokenComparison:
    def test_the_right_token_matches(self):
        assert token_matches(TOKEN, TOKEN)

    @pytest.mark.parametrize(
        "presented",
        [
            pytest.param("", id="empty"),
            pytest.param(None, id="absent"),
            pytest.param("wrong", id="wrong"),
            pytest.param(TOKEN + "x", id="longer"),
            pytest.param(TOKEN[:-1], id="truncated"),
            pytest.param(TOKEN.upper(), id="case-changed"),
            pytest.param(" " + TOKEN, id="leading-space"),
        ],
    )
    def test_anything_else_does_not(self, presented):
        assert not token_matches(presented, TOKEN)

    def test_non_ascii_tokens_do_not_raise(self):
        # compare_digest rejects non-ASCII str, so the implementation encodes first.
        assert token_matches("señal-✓", "señal-✓")
        assert not token_matches("señal-✓", "other")


class TestProtectedRoutes:
    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("post", "/ask", {"question": "hi"}),
            ("post", "/tool", {"name": "knowledge_search", "args": {"query": "x"}}),
        ],
    )
    def test_no_token_is_rejected(self, secured, method, path, body):
        response = getattr(secured, method)(path, json=body)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    @pytest.mark.parametrize(("method", "path", "body"), [("post", "/ask", {"question": "hi"})])
    def test_a_wrong_token_is_rejected(self, secured, method, path, body):
        response = getattr(secured, method)(path, json=body, headers=auth("nope"))
        assert response.status_code == 401

    def test_the_right_token_is_accepted(self, secured):
        response = secured.post("/ask", json={"question": "hi"}, headers=auth(TOKEN))
        assert response.status_code == 200
        assert response.json()["answer"]

    def test_the_tool_route_works_with_a_token(self, secured):
        response = secured.post(
            "/tool",
            json={"name": "warehouse_query", "args": {"sql": "select * from revenue"}},
            headers=auth(TOKEN),
        )
        assert response.status_code == 200

    def test_a_malformed_authorization_header_is_rejected(self, secured):
        response = secured.post("/ask", json={"question": "hi"}, headers={"Authorization": TOKEN})
        assert response.status_code == 401

    def test_auth_is_checked_before_the_request_body(self, secured):
        """A 401 must not depend on sending a valid payload."""
        assert secured.post("/ask", json={"bad": "body"}).status_code == 401


class TestHealth:
    def test_health_stays_reachable_without_a_token(self, secured):
        """Container probes cannot carry credentials."""
        response = secured.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_detail_is_withheld_from_anonymous_callers(self, secured):
        body = secured.get("/health").json()
        assert "model_id" not in body
        assert "kb_chunks" not in body

    def test_detail_is_returned_with_a_token(self, secured):
        body = secured.get("/health", headers=auth(TOKEN)).json()
        assert body["model_backend"] == "mock"
        assert "kb_chunks" in body


class TestAuthDisabled:
    def test_routes_are_open_when_no_token_is_configured(self, client):
        assert client.post("/ask", json={"question": "hi"}).status_code == 200

    def test_health_is_fully_detailed_when_auth_is_off(self, client):
        assert "kb_chunks" in client.get("/health").json()


class TestLoopbackDetection:
    @pytest.mark.parametrize(
        "host", ["127.0.0.1", "localhost", "::1", "127.0.0.53", " 127.0.0.1 ", ""]
    )
    def test_loopback_addresses(self, host):
        assert is_loopback(host)

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "example.com", "10.0.0.1"])
    def test_routable_addresses(self, host):
        assert not is_loopback(host)


class TestApiBindingGuard:
    def test_loopback_without_a_token_is_allowed(self):
        require_safe_binding(Settings(api_host="127.0.0.1", api_token=""))

    def test_public_bind_without_a_token_is_refused(self):
        with pytest.raises(UnsafeBindingError, match="refusing to bind"):
            require_safe_binding(Settings(api_host="0.0.0.0", api_token=""))

    def test_public_bind_with_a_token_is_allowed(self):
        require_safe_binding(Settings(api_host="0.0.0.0", api_token=TOKEN))

    def test_the_explicit_opt_out_is_honoured(self):
        require_safe_binding(Settings(api_host="0.0.0.0", api_token="", allow_unauthenticated=True))

    def test_the_message_names_the_ways_out(self):
        with pytest.raises(UnsafeBindingError) as excinfo:
            require_safe_binding(Settings(api_host="0.0.0.0"))
        message = str(excinfo.value)
        assert "DA_API_TOKEN" in message
        assert "DA_API_HOST=127.0.0.1" in message
        assert "DA_ALLOW_UNAUTHENTICATED" in message


class TestMcpBindingGuard:
    def test_loopback_is_allowed(self):
        require_safe_mcp_binding(Settings(mcp_host="127.0.0.1"))

    def test_public_bind_is_refused(self):
        with pytest.raises(UnsafeBindingError, match="no authentication of its own"):
            require_safe_mcp_binding(Settings(mcp_host="0.0.0.0"))

    def test_an_api_token_does_not_unlock_it(self):
        """DA_API_TOKEN protects the HTTP API, not the MCP transport. Treating it
        as if it did would be the dangerous kind of convenience."""
        with pytest.raises(UnsafeBindingError):
            require_safe_mcp_binding(Settings(mcp_host="0.0.0.0", api_token=TOKEN))

    def test_the_explicit_opt_out_is_honoured(self):
        require_safe_mcp_binding(Settings(mcp_host="0.0.0.0", allow_unauthenticated=True))


class TestDefaults:
    def test_the_api_binds_loopback_by_default(self):
        assert Settings().api_host == "127.0.0.1"

    def test_mcp_binds_loopback_by_default(self):
        assert Settings().mcp_host == "127.0.0.1"

    def test_auth_is_off_by_default(self):
        assert Settings().api_token == ""

    def test_the_default_configuration_passes_both_guards(self):
        require_safe_binding(Settings())
        require_safe_mcp_binding(Settings())
