"""Tests for MCP Server initialization and request handling."""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from serverless_sandbox.agent.mcp import (
    SandboxMCPServer,
    SandboxManager,
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    _jsonrpc_response,
    _jsonrpc_error,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INTERNAL_ERROR,
)


# ---------------------------------------------------------------------------
# JSON-RPC helper tests
# ---------------------------------------------------------------------------

class TestJsonRpcHelpers:
    """Test JSON-RPC response/error builders."""

    def test_jsonrpc_response(self):
        resp = _jsonrpc_response(1, {"tools": []})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"] == {"tools": []}
        assert "error" not in resp

    def test_jsonrpc_error(self):
        resp = _jsonrpc_error(2, -32601, "Method not found")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 2
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found"

    def test_jsonrpc_error_with_data(self):
        resp = _jsonrpc_error(3, -32603, "Internal error", data={"detail": "boom"})
        assert resp["error"]["data"]["detail"] == "boom"


# ---------------------------------------------------------------------------
# SandboxManager tests
# ---------------------------------------------------------------------------

class TestSandboxManager:
    """Test SandboxManager lifecycle management."""

    def test_init(self):
        mgr = SandboxManager(api_key="test-key", template="python-base")
        assert mgr._api_key == "test-key"
        assert mgr._default_template == "python-base"
        assert mgr._default_sandbox is None

    async def test_create_sandbox(self):
        mgr = SandboxManager(api_key="k")
        mock_sb = AsyncMock()
        mock_sb.id = "sbx-001"
        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.create",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = await mgr.create_sandbox(template="test-tpl")
            assert result.id == "sbx-001"
            assert "sbx-001" in mgr._sandboxes

    async def test_get_sandbox_creates_default(self):
        mgr = SandboxManager(api_key="k")
        mock_sb = AsyncMock()
        mock_sb.id = "sbx-default"
        mgr.create_sandbox = AsyncMock(return_value=mock_sb)

        result = await mgr.get_sandbox(None)
        assert result.id == "sbx-default"
        mgr.create_sandbox.assert_awaited_once()
        # Second call should reuse
        result2 = await mgr.get_sandbox(None)
        assert result2.id == "sbx-default"
        # Still only one create call
        assert mgr.create_sandbox.await_count == 1

    async def test_get_sandbox_by_id_from_cache(self):
        mgr = SandboxManager()
        mock_sb = AsyncMock()
        mock_sb.id = "sbx-123"
        mgr._sandboxes["sbx-123"] = mock_sb

        result = await mgr.get_sandbox("sbx-123")
        assert result is mock_sb

    async def test_kill_sandbox_default(self):
        mgr = SandboxManager()
        mock_sb = AsyncMock()
        mock_sb.id = "sbx-def"
        mock_sb.kill = AsyncMock()
        mgr._default_sandbox = mock_sb
        mgr._sandboxes["sbx-def"] = mock_sb

        await mgr.kill_sandbox(None)
        mock_sb.kill.assert_awaited_once()
        assert mgr._default_sandbox is None
        assert "sbx-def" not in mgr._sandboxes

    async def test_kill_sandbox_by_id(self):
        mgr = SandboxManager()
        mock_sb = AsyncMock()
        mock_sb.id = "sbx-002"
        mock_sb.kill = AsyncMock()
        mgr._sandboxes["sbx-002"] = mock_sb

        await mgr.kill_sandbox("sbx-002")
        mock_sb.kill.assert_awaited_once()
        assert "sbx-002" not in mgr._sandboxes

    async def test_shutdown(self):
        mgr = SandboxManager()
        sb1 = AsyncMock()
        sb1.id = "sb1"
        sb1.kill = AsyncMock()
        sb2 = AsyncMock()
        sb2.id = "sb2"
        sb2.kill = AsyncMock()
        mgr._sandboxes = {"sb1": sb1, "sb2": sb2}
        mgr._default_sandbox = sb1

        await mgr.shutdown()
        sb1.kill.assert_awaited_once()
        sb2.kill.assert_awaited_once()
        assert mgr._default_sandbox is None
        assert len(mgr._sandboxes) == 0


# ---------------------------------------------------------------------------
# SandboxMCPServer tests
# ---------------------------------------------------------------------------

class TestSandboxMCPServer:
    """Test MCP Server request handling."""

    def test_init(self):
        server = SandboxMCPServer(api_key="k", template="t")
        assert not server.initialized
        assert server.manager is not None

    async def test_initialize(self):
        server = SandboxMCPServer()
        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        })
        assert resp is not None
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == SERVER_NAME
        assert result["serverInfo"]["version"] == SERVER_VERSION
        assert "tools" in result["capabilities"]
        assert server.initialized

    async def test_initialized_notification(self):
        server = SandboxMCPServer()
        # Notification (no id)
        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        assert resp is None  # Notifications get no response

    async def test_tools_list(self):
        server = SandboxMCPServer()
        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        assert resp is not None
        tools = resp["result"]["tools"]
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        assert "run_code" in names
        assert "create_sandbox" in names

    async def test_tools_call_unknown_tool(self):
        server = SandboxMCPServer()
        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}},
        })
        assert resp is not None
        result = resp["result"]
        assert result["isError"] is True
        text = json.loads(result["content"][0]["text"])
        assert "Unknown tool" in text["error"]

    async def test_tools_call_success(self):
        server = SandboxMCPServer()
        # Mock the manager's get_sandbox
        mock_sb = AsyncMock()
        mock_sb.id = "sbx-t"
        from serverless_sandbox.models.process import CodeResult
        mock_sb.run_code = AsyncMock(return_value=CodeResult(
            text="ok", stdout="ok\n", stderr="", exit_code=0,
        ))
        server._manager.get_sandbox = AsyncMock(return_value=mock_sb)

        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "run_code",
                "arguments": {"code": "print('ok')"},
            },
        })
        assert resp is not None
        result = resp["result"]
        assert result["isError"] is False
        text = json.loads(result["content"][0]["text"])
        assert text["stdout"] == "ok\n"

    async def test_unknown_method(self):
        server = SandboxMCPServer()
        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "unknown/method",
            "params": {},
        })
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == METHOD_NOT_FOUND

    async def test_ping(self):
        server = SandboxMCPServer()
        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "ping",
            "params": {},
        })
        assert resp is not None
        assert resp["result"] == {}

    async def test_unknown_notification_ignored(self):
        server = SandboxMCPServer()
        # Unknown notification (no id) should be silently ignored
        resp = await server.handle_request({
            "jsonrpc": "2.0",
            "method": "some/unknown/notification",
            "params": {},
        })
        assert resp is None

    async def test_shutdown(self):
        server = SandboxMCPServer()
        server._manager.shutdown = AsyncMock()
        await server.shutdown()
        server._manager.shutdown.assert_awaited_once()
