"""Easy Sandbox MCP Server。

将沙箱能力暴露为 MCP Tools，支持 Cursor / Claude Desktop / VS Code 等 IDE 集成。

传输方式：STDIO（本地 IDE 集成）。

实现：自包含的最小 JSON-RPC 2.0 over STDIO 处理器，
无需外部 ``mcp`` SDK 依赖。当 ``mcp`` 包可用时可平滑迁移。

MCP 协议版本: 2024-11-05
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from easy_sandbox.agent.tools import (
    TOOL_SCHEMAS,
    TOOL_SCHEMA_MAP,
    dispatch_tool,
)
from easy_sandbox.utils.logging import get_logger

logger = get_logger("agent.mcp")

# MCP protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"

SERVER_NAME = "easy-sandbox"
SERVER_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Sandbox Manager — manages sandbox lifecycle for MCP sessions
# ---------------------------------------------------------------------------

class SandboxManager:
    """Manage sandbox instances for an MCP session.

    Implements the "default sandbox" concept:
    - First tool call without sandbox_id → auto-create default sandbox
    - Subsequent calls without sandbox_id → reuse default sandbox
    - Explicit sandbox_id → use/store that specific sandbox
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        template: str = "code-interpreter-v1",
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._domain = domain
        self._default_template = template
        self._default_sandbox: Any = None  # Sandbox instance
        self._sandboxes: dict[str, Any] = {}  # sandbox_id -> Sandbox

    async def create_sandbox(
        self,
        template: str | None = None,
        timeout: int = 300,
        envs: dict[str, str] | None = None,
    ) -> Any:
        """Create a new sandbox."""
        from easy_sandbox.api.sandbox import Sandbox

        kwargs: dict[str, Any] = {
            "template": template or self._default_template,
            "timeout": timeout,
            "envs": envs or {},
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_url:
            kwargs["api_url"] = self._api_url
        if self._domain:
            kwargs["domain"] = self._domain

        sandbox = await Sandbox.create(**kwargs)
        self._sandboxes[sandbox.id] = sandbox
        logger.info("Created sandbox: %s", sandbox.id)
        return sandbox

    async def get_sandbox(self, sandbox_id: str | None = None) -> Any:
        """Get a sandbox by ID, or create/return default sandbox."""
        if sandbox_id:
            sb = self._sandboxes.get(sandbox_id)
            if sb is not None:
                return sb
            # Try to connect to existing sandbox
            from easy_sandbox.api.sandbox import Sandbox

            kwargs: dict[str, Any] = {"sandbox_id": sandbox_id}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._api_url:
                kwargs["api_url"] = self._api_url
            if self._domain:
                kwargs["domain"] = self._domain
            sb = await Sandbox.connect(**kwargs)
            self._sandboxes[sb.id] = sb
            return sb

        # Default sandbox — lazy create
        if self._default_sandbox is None:
            self._default_sandbox = await self.create_sandbox()
            logger.info("Auto-created default sandbox: %s", self._default_sandbox.id)
        return self._default_sandbox

    async def kill_sandbox(self, sandbox_id: str | None = None) -> None:
        """Kill a sandbox by ID, or kill default sandbox."""
        if sandbox_id:
            sb = self._sandboxes.pop(sandbox_id, None)
            if sb:
                await sb.kill()
                if self._default_sandbox and self._default_sandbox.id == sandbox_id:
                    self._default_sandbox = None
                logger.info("Killed sandbox: %s", sandbox_id)
                return
            # Kill by ID without having a local reference
            from easy_sandbox.api.sandbox import Sandbox

            kwargs: dict[str, Any] = {"sandbox_id": sandbox_id}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._api_url:
                kwargs["api_url"] = self._api_url
            await Sandbox.kill_by_id(**kwargs)
            return

        # Kill default
        if self._default_sandbox:
            sid = self._default_sandbox.id
            await self._default_sandbox.kill()
            self._sandboxes.pop(sid, None)
            self._default_sandbox = None
            logger.info("Killed default sandbox: %s", sid)

    async def shutdown(self) -> None:
        """Kill all sandboxes."""
        for sid in list(self._sandboxes.keys()):
            try:
                sb = self._sandboxes.pop(sid)
                await sb.kill()
                logger.info("Shutdown: killed sandbox %s", sid)
            except Exception:
                logger.warning("Failed to kill sandbox %s during shutdown", sid, exc_info=True)
        self._default_sandbox = None


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers
# ---------------------------------------------------------------------------

def _jsonrpc_response(id_: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response."""
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _jsonrpc_error(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


# JSON-RPC standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# SandboxMCPServer
# ---------------------------------------------------------------------------

class SandboxMCPServer:
    """沙箱 MCP Server — 自包含 JSON-RPC 2.0 over STDIO 实现。

    支持 MCP 协议的 initialize / tools/list / tools/call 方法。
    当 ``mcp`` SDK 可用时可平滑替换传输层。
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        template: str = "code-interpreter-v1",
    ) -> None:
        self._manager = SandboxManager(
            api_key=api_key,
            api_url=api_url,
            domain=domain,
            template=template,
        )
        self._initialized = False

    @property
    def manager(self) -> SandboxManager:
        """Expose sandbox manager for testing."""
        return self._manager

    @property
    def initialized(self) -> bool:
        """Whether the server has received an initialize request."""
        return self._initialized

    # ---- MCP method handlers ----

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle MCP initialize request."""
        self._initialized = True
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        }

    async def _handle_initialized(self, params: dict[str, Any]) -> None:
        """Handle MCP initialized notification (no response needed)."""
        logger.info("MCP client confirmed initialization")
        return None

    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request — return all available tools."""
        return {"tools": TOOL_SCHEMAS}

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request — dispatch to tool handler."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name not in TOOL_SCHEMA_MAP:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"error": f"Unknown tool: {tool_name}"}),
                    }
                ],
                "isError": True,
            }

        result = await dispatch_tool(tool_name, arguments, self._manager)

        is_error = "error" in result
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str),
                }
            ],
            "isError": is_error,
        }

    async def _handle_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ping request."""
        return {}

    # ---- Method dispatch ----

    _METHOD_MAP: dict[str, str] = {
        "initialize": "_handle_initialize",
        "notifications/initialized": "_handle_initialized",
        "tools/list": "_handle_tools_list",
        "tools/call": "_handle_tools_call",
        "ping": "_handle_ping",
    }

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process a single JSON-RPC request and return a response (or None for notifications)."""
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")  # None for notifications

        handler_name = self._METHOD_MAP.get(method)
        if handler_name is None:
            if req_id is not None:
                return _jsonrpc_error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")
            return None  # Unknown notification — silently ignore

        handler = getattr(self, handler_name)
        try:
            result = await handler(params)
        except Exception as exc:
            logger.error("Error handling %s: %s", method, exc, exc_info=True)
            if req_id is not None:
                return _jsonrpc_error(req_id, INTERNAL_ERROR, str(exc))
            return None

        # Notifications don't get responses
        if req_id is None:
            return None
        return _jsonrpc_response(req_id, result)

    # ---- STDIO transport ----

    async def run(self) -> None:
        """Run MCP Server over STDIO transport.

        Reads JSON-RPC messages from stdin (newline-delimited),
        writes responses to stdout.
        """
        logger.info("Starting MCP Server (STDIO mode)")

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        # Use stdout for writing
        transport, _ = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.BaseProtocol, sys.stdout,
        )

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break  # EOF

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    request = json.loads(line_str)
                except json.JSONDecodeError as exc:
                    resp = _jsonrpc_error(None, PARSE_ERROR, f"Parse error: {exc}")
                    transport.write((json.dumps(resp) + "\n").encode("utf-8"))
                    continue

                response = await self.handle_request(request)
                if response is not None:
                    transport.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown the server and clean up sandboxes."""
        logger.info("Shutting down MCP Server")
        await self._manager.shutdown()


# ---------------------------------------------------------------------------
# Module-level entry point for ``python -m easy_sandbox.agent.mcp``
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for running MCP server directly."""
    import os

    api_key = os.environ.get("E2B_API_KEY") or os.environ.get("SANDBOX_API_KEY")
    api_url = os.environ.get("E2B_API_URL") or os.environ.get("SANDBOX_API_BASE_URL")
    domain = os.environ.get("E2B_DOMAIN")
    template = os.environ.get("SANDBOX_TEMPLATE", "code-interpreter-v1")

    server = SandboxMCPServer(
        api_key=api_key,
        api_url=api_url,
        domain=domain,
        template=template,
    )
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
