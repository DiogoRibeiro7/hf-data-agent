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
        with pytest.raises(UnsafeBindingError, match="without authentication"):
            require_safe_mcp_binding(Settings(mcp_host="0.0.0.0"))

    def test_a_token_unlocks_it(self):
        """The mcp_remote entrypoint wraps the transport in BearerAuthMiddleware,
        so DA_API_TOKEN really does protect it — see test_mcp_auth.py."""
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


class TestErrorDisclosure:
    """CodeQL flagged both of these once the repository went public."""

    def test_an_internal_failure_does_not_return_the_exception_text(self, client, runtime):
        """A 500 body reaches the caller; an exception message can carry a DSN
        fragment, a filesystem path, or the statement that failed."""

        class Exploding:
            name = "warehouse"

            def query(self, statement):
                raise RuntimeError("connection to postgres://user:pw@host failed")

        runtime.datasources["warehouse"] = Exploding()
        response = client.post(
            "/tool", json={"name": "warehouse_query", "args": {"sql": "select 1"}}
        )
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "postgres://" not in detail
        assert "RuntimeError" not in detail
        assert "request" in detail  # the correlation id is offered instead

    def test_a_rejected_statement_still_explains_itself(self, client):
        """400s describe the caller's own mistake, so they stay informative."""
        response = client.post(
            "/tool", json={"name": "warehouse_query", "args": {"sql": "DROP TABLE revenue"}}
        )
        assert response.status_code == 400
        assert "read-only" in response.json()["detail"].lower()


class TestLogInjection:
    def test_control_characters_are_stripped_before_logging(self):
        from data_agent.observability import scrub

        forged = "warehouse_query" + chr(10) + "INFO: transfer approved"
        assert chr(10) not in scrub(forged)

    def test_an_oversized_value_is_truncated(self):
        from data_agent.observability import scrub

        assert len(scrub("x" * 5000)) == 200

    def test_an_unknown_tool_name_never_reaches_a_log_record(self, client, caplog):
        """A crafted name is rejected by the registry lookup before anything is
        logged, so the caller's string has no path into a log line at all."""
        import logging

        forged = "nope" + chr(10) + "WARNING: fake entry"
        with caplog.at_level(logging.INFO, logger="data_agent.api.app"):
            assert client.post("/tool", json={"name": forged, "args": {}}).status_code == 404
        for record in caplog.records:
            assert forged not in str(record.__dict__.get("tool", ""))
            assert chr(10) not in str(record.__dict__.get("tool", ""))

    def test_a_known_tool_is_logged_under_its_registry_name(self, client, caplog):
        """The logged value comes from the ToolSpec, not from the request."""
        import logging

        with caplog.at_level(logging.INFO, logger="data_agent.api.app"):
            client.post("/tool", json={"name": "warehouse_query", "args": {"sql": "select 1"}})
        logged = [r.__dict__.get("tool") for r in caplog.records if "tool" in r.__dict__]
        assert "warehouse_query" in logged

    def test_invented_argument_names_are_counted_not_echoed(self, client, caplog):
        """Argument names are reported by intersecting with the tool's declared
        parameters, so a crafted key is counted rather than written to the log."""
        import logging

        crafted = "sql" + chr(10) + "forged"
        with caplog.at_level(logging.INFO, logger="data_agent.api.app"):
            client.post("/tool", json={"name": "warehouse_query", "args": {crafted: "x"}})
        invoked = [r for r in caplog.records if r.getMessage() == "tool invoked"]
        assert invoked
        for record in invoked:
            assert crafted not in str(record.__dict__.get("args", []))
            assert record.__dict__["unexpected_args"] == 1

    def test_declared_argument_names_are_reported(self, client, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="data_agent.api.app"):
            client.post("/tool", json={"name": "warehouse_query", "args": {"sql": "select 1"}})
        invoked = [r for r in caplog.records if r.getMessage() == "tool invoked"]
        assert invoked
        assert invoked[0].__dict__["args"] == ["sql"]
        assert invoked[0].__dict__["unexpected_args"] == 0
