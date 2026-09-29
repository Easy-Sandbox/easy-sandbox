"""Tests for MCP Streamable HTTP transport (agent/mcp_http.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.agent.mcp_http import (
    MCP_PROTOCOL_VERSION,
    SessionStore,
    _jsonrpc_error,
    _jsonrpc_response,
    _validate_bearer_token,
    create_mcp_app,
)

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


class TestJsonRpcHelpers:
    """Test JSON-RPC response/error builders (HTTP variant)."""

    def test_success_response(self):
        resp = _jsonrpc_response(1, {"tools": []})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"] == {"tools": []}

    def test_error_response(self):
        resp = _jsonrpc_error(2, -32601, "Method not found")
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found"

    def test_error_with_data(self):
        resp = _jsonrpc_error(3, -32603, "Internal error", data={"x": 1})
        assert resp["error"]["data"] == {"x": 1}


# ---------------------------------------------------------------------------
# Bearer token validation
# ---------------------------------------------------------------------------


class TestBearerTokenValidation:
    """Test _validate_bearer_token helper."""

    def test_no_token_required(self):
        req = MagicMock()
        assert _validate_bearer_token(req, None) is True

    def test_valid_token_uses_constant_time_comparison(self):
        req = MagicMock()
        req.headers = {"authorization": "Bearer my-secret-token"}
        with patch(
            "easy_sandbox.agent.mcp_http.hmac.compare_digest",
            return_value=True,
        ) as compare_digest:
            assert _validate_bearer_token(req, "my-secret-token") is True
        compare_digest.assert_called_once_with(b"my-secret-token", b"my-secret-token")

    def test_invalid_token(self):
        req = MagicMock()
        req.headers = {"authorization": "Bearer wrong-token"}
        assert _validate_bearer_token(req, "my-secret-token") is False

    def test_missing_header(self):
        req = MagicMock()
        req.headers = {}
        assert _validate_bearer_token(req, "token") is False

    def test_non_bearer_scheme(self):
        req = MagicMock()
        req.headers = {"authorization": "Basic dXNlcjpwYXNz"}
        assert _validate_bearer_token(req, "token") is False

    @pytest.mark.parametrize("expected_token", ["", "   ", "\n\t"])
    def test_configured_empty_token_fails_closed(self, expected_token):
        req = MagicMock()
        req.headers = {"authorization": "Bearer "}
        assert _validate_bearer_token(req, expected_token) is False


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class TestSessionStore:
    """Test the SessionStore session lifecycle."""

    async def test_create_session(self):
        store = SessionStore(api_key="test-key", template="python-base")
        sid, server = await store.create_session()
        assert isinstance(sid, str)
        assert len(sid) > 0
        assert server is not None
        assert store.get_session(sid) is server

    def test_get_nonexistent_session(self):
        store = SessionStore()
        assert store.get_session("nonexistent") is None

    async def test_destroy_session(self):
        store = SessionStore()
        sid, server = await store.create_session()
        server.shutdown = AsyncMock()
        result = await store.destroy_session(sid)
        assert result is True
        server.shutdown.assert_awaited_once()
        assert store.get_session(sid) is None

    async def test_destroy_nonexistent_session(self):
        store = SessionStore()
        result = await store.destroy_session("nope")
        assert result is False

    async def test_shutdown_all(self):
        store = SessionStore()
        _, s1 = await store.create_session()
        _, s2 = await store.create_session()
        s1.shutdown = AsyncMock()
        s2.shutdown = AsyncMock()
        await store.shutdown_all()
        s1.shutdown.assert_awaited_once()
        s2.shutdown.assert_awaited_once()

    async def test_cleanup_expired_session(self):
        store = SessionStore(session_ttl_seconds=10)
        sid, server = await store.create_session()
        server.shutdown = AsyncMock()
        store._sessions[sid].last_access = 0

        with patch("easy_sandbox.agent.mcp_http.time.monotonic", return_value=11):
            removed = await store.cleanup_expired()

        assert removed == 1
        assert store.get_session(sid) is None
        server.shutdown.assert_awaited_once()

    async def test_session_limit_rejects_new_session(self):
        store = SessionStore(max_sessions=1)
        await store.create_session()

        with pytest.raises(RuntimeError, match="session limit reached"):
            await store.create_session()


# ---------------------------------------------------------------------------
# HTTP protocol version negotiation
# ---------------------------------------------------------------------------


class TestHttpProtocolVersionNegotiation:
    """Sessions created by SessionStore negotiate the HTTP transport version.

    The shared SandboxMCPServer is wired with the HTTP supported-version set
    (2025-06-18), not the STDIO default (2024-11-05).
    """

    async def test_session_server_negotiates_2025_06_18(self):
        store = SessionStore()
        _, server = await store.create_session()
        resp = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            }
        )
        assert resp is not None
        assert resp["result"]["protocolVersion"] == "2025-06-18"
        assert resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

    async def test_session_server_rejects_stdio_version_echo(self):
        """HTTP 会话不回显 STDIO 的 2024-11-05，而是回退到 HTTP 支持版本。"""
        store = SessionStore()
        _, server = await store.create_session()
        resp = await server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            }
        )
        assert resp["result"]["protocolVersion"] == "2025-06-18"


# ---------------------------------------------------------------------------
# ASGI app via Starlette TestClient
# ---------------------------------------------------------------------------

# Starlette may not be installed — skip tests gracefully
starlette_available = True
try:
    from starlette.testclient import TestClient
except ImportError:
    starlette_available = False


@pytest.mark.skipif(not starlette_available, reason="starlette not installed")
class TestMcpHttpApp:
    """Integration tests for the ASGI MCP app using Starlette TestClient."""

    def _make_app(self, auth_token: str | None = None, **kwargs):
        """Create a test app with a controlled configuration."""
        return create_mcp_app(
            auth_token=auth_token,
            api_key="test-key",
            template="test-tpl",
            **kwargs,
        )

    # ---- Health check ----

    def test_health(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["protocol"] == MCP_PROTOCOL_VERSION

    # ---- POST /mcp — initialize ----

    def test_initialize_creates_session(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
        )
        assert resp.status_code == 200
        assert "Mcp-Session-Id" in resp.headers
        body = resp.json()
        assert body["id"] == 1
        # Regression guard for the E2E-found inconsistency: initialize over
        # HTTP must negotiate 2025-06-18, not the shared STDIO constant.
        assert body["result"]["protocolVersion"] == "2025-06-18"

    # ---- Protocol version negotiation (consistent with GET /health) ----

    def test_health_and_initialize_report_same_protocol_version(self):
        """HTTP /health 与 initialize 声明的协议版本必须一致（回归守卫）。"""
        app = self._make_app()
        client = TestClient(app)
        health = client.get("/health")
        assert health.status_code == 200

        init = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
        )
        assert init.status_code == 200
        assert (
            init.json()["result"]["protocolVersion"]
            == health.json()["protocol"]
            == MCP_PROTOCOL_VERSION
        )

    def test_initialize_with_unsupported_version_responds_supported(self):
        """请求不支持的版本 → 按规范返回服务器支持的版本（200，非错误）。"""
        app = self._make_app()
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["protocolVersion"] == "2025-06-18"

    def test_initialize_without_protocol_version_defaults_to_supported(self):
        """请求缺失 protocolVersion → 协商到 HTTP 传输支持的版本。"""
        app = self._make_app()
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["protocolVersion"] == "2025-06-18"

    def test_session_limit_returns_503(self):
        app = self._make_app(max_sessions=1)
        client = TestClient(app)
        first = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        second = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
        )

        assert first.status_code == 200
        assert second.status_code == 503
        assert second.json()["error"]["code"] == -32000

    def test_post_without_session_or_initialize(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        assert resp.status_code == 400
        assert "Mcp-Session-Id" in resp.json()["error"]["message"]

    def test_post_with_invalid_session(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
            headers={"Mcp-Session-Id": "nonexistent-session"},
        )
        assert resp.status_code == 404

    def test_tools_list_after_initialize(self):
        app = self._make_app()
        client = TestClient(app)
        # Initialize
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
        )
        session_id = resp.headers["Mcp-Session-Id"]

        # tools/list
        resp2 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp2.status_code == 200
        tools = resp2.json()["result"]["tools"]
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        assert "create_sandbox" in names
        assert "run_code" in names

    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            ("create_sandbox", {"template": "base"}),
            ("run_code", {"code": "print('ok')"}),
            ("run_command", {"command": "echo ok"}),
            ("read_file", {"path": "/tmp/a"}),
            ("write_file", {"path": "/tmp/a", "content": "ok"}),
            ("list_files", {"path": "/tmp"}),
            ("kill_sandbox", {"sandbox_id": "sbx-1"}),
        ],
    )
    def test_tool_call_is_delegated_over_http(self, tool_name, arguments):
        app = self._make_app()
        client = TestClient(app)
        init_response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session_id = init_response.headers["Mcp-Session-Id"]
        server = app.state.session_store.get_session(session_id)
        expected = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "isError": False,
            },
        }
        server.handle_request = AsyncMock(return_value=expected)
        request_body = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        response = client.post(
            "/mcp",
            json=request_body,
            headers={"Mcp-Session-Id": session_id},
        )

        assert response.status_code == 200
        assert response.json() == expected
        server.handle_request.assert_awaited_once_with(request_body)

    # ---- Notifications ----

    def test_notification_returns_202(self):
        app = self._make_app()
        client = TestClient(app)
        # Initialize first
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
        )
        sid = resp.headers["Mcp-Session-Id"]

        # Send notification (no id)
        resp2 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers={"Mcp-Session-Id": sid},
        )
        assert resp2.status_code == 202

    # ---- Auth ----

    def test_auth_required_post(self):
        app = self._make_app(auth_token="test-token-abc")
        client = TestClient(app)
        # No auth header
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
        )
        assert resp.status_code == 401

    def test_auth_valid_post(self):
        app = self._make_app(auth_token="test-token-abc")
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
            headers={"Authorization": "Bearer test-token-abc"},
        )
        assert resp.status_code == 200
        assert "Mcp-Session-Id" in resp.headers

    def test_auth_wrong_token(self):
        app = self._make_app(auth_token="test-token-abc")
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    def test_empty_configured_token_rejects_request(self):
        app = self._make_app(auth_token="  ")
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401

    # ---- DELETE /mcp ----

    def test_delete_session(self):
        app = self._make_app()
        client = TestClient(app)
        # Initialize
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
        )
        sid = resp.headers["Mcp-Session-Id"]

        # Patch shutdown to avoid real sandbox cleanup
        store = app.state.session_store
        server = store.get_session(sid)
        server.shutdown = AsyncMock()

        # Delete
        resp2 = client.delete(
            "/mcp",
            headers={"Mcp-Session-Id": sid},
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "session_terminated"
        assert store.get_session(sid) is None

    def test_delete_without_session_header(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.delete("/mcp")
        assert resp.status_code == 400

    def test_delete_unknown_session(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.delete(
            "/mcp",
            headers={"Mcp-Session-Id": "no-such-session"},
        )
        assert resp.status_code == 404

    # ---- GET /mcp (Phase 2 stub) ----

    def test_get_returns_501(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.get("/mcp")
        assert resp.status_code == 501

    # ---- Invalid JSON ----

    def test_invalid_json_body(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.post(
            "/mcp",
            content=b"not-json!!!",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize("body", [[], [{"jsonrpc": "2.0", "id": 1, "method": "initialize"}]])
    def test_json_array_returns_invalid_request(self, body):
        app = self._make_app()
        client = TestClient(app)
        resp = client.post("/mcp", json=body)

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32600

    # ---- Auth on DELETE ----

    def test_delete_auth_required(self):
        app = self._make_app(auth_token="sec")
        client = TestClient(app)
        resp = client.delete(
            "/mcp",
            headers={"Mcp-Session-Id": "some-id"},
        )
        assert resp.status_code == 401

    # ---- Auth on GET ----

    def test_get_auth_required(self):
        app = self._make_app(auth_token="sec")
        client = TestClient(app)
        resp = client.get("/mcp")
        assert resp.status_code == 401
