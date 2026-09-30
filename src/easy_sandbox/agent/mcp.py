"""Easy Sandbox MCP Server。

将沙箱能力暴露为 MCP Tools，支持 Cursor / Claude Desktop / VS Code 等 IDE 集成。

传输方式：STDIO（本地 IDE 集成）。

实现：自包含的最小 JSON-RPC 2.0 over STDIO 处理器，
无需外部 ``mcp`` SDK 依赖。当 ``mcp`` 包可用时可平滑迁移。

MCP 协议版本协商：本模块默认支持 STDIO 传输版本 ``2024-11-05``；
Streamable HTTP 传输（:mod:`easy_sandbox.agent.mcp_http`）通过
``supported_protocol_versions`` 构造参数声明 ``2025-06-18``。
``initialize`` 回显受支持的请求版本；请求缺失或不支持时，
回退到传输的首选（第一个）支持版本。
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

from easy_sandbox.agent.tools import (
    TOOL_SCHEMA_MAP,
    TOOL_SCHEMAS,
    dispatch_tool,
)
from easy_sandbox.utils.logging import get_logger

logger = get_logger("agent.mcp")

# MCP protocol version supported by the STDIO transport — the default for
# SandboxMCPServer. Other transports (e.g. Streamable HTTP in mcp_http.py)
# declare their own version via the ``supported_protocol_versions`` argument.
MCP_PROTOCOL_VERSION = "2024-11-05"

# A single tools/call (for example write_file of a source file) is one JSON
# line. The asyncio default of 64 KiB kills the process on a longer line.
_STDIO_READ_LIMIT = 8 * 1024 * 1024

SERVER_NAME = "easy-sandbox"
SERVER_VERSION = "0.2.0"


# ---------------------------------------------------------------------------
# Sandbox Manager — manages sandbox lifecycle for MCP sessions
# ---------------------------------------------------------------------------


class SandboxManager:
    """Manage sandbox instances for an MCP session.

    The default sandbox is the one omitted ``sandbox_id`` arguments use:

    - The first such call lazily creates it with this manager's template.
    - ``create_sandbox`` makes the new sandbox the default, so the usual
      agent sequence (create, then write / run / kill without an id) stays
      on that sandbox. Earlier sandboxes stay alive until killed or the
      session ends.
    - An explicit ``sandbox_id`` addresses that sandbox and does not change
      the default.
    - Concurrent callers share one lazy create.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        template: str = "base",
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._domain = domain
        self._default_template = template
        self._default_sandbox: Any = None  # Sandbox instance
        self._sandboxes: dict[str, Any] = {}  # sandbox_id -> Sandbox
        self._lifetimes: dict[str, int] = {}  # sandbox_id -> timeout seconds
        self._state_lock = asyncio.Lock()
        self._default_lock = asyncio.Lock()

    def _connect_kwargs(self, **extra: Any) -> dict[str, Any]:
        """Build SDK kwargs shared by create, connect, and kill."""
        kwargs = dict(extra)
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_url:
            kwargs["api_url"] = self._api_url
        if self._domain:
            kwargs["domain"] = self._domain
        return kwargs

    async def _refresh_lifetime(self, sandbox: Any) -> None:
        """Best-effort extend of the sandbox TTL before a tool uses it.

        ``Sandbox.set_timeout`` posts the platform timeout endpoint that has
        been verified against the service. A refresh failure is logged and
        the tool call continues; the tool's own error is what the agent sees
        if the sandbox is already gone.
        """
        setter = getattr(sandbox, "set_timeout", None)
        if setter is None:
            return
        sandbox_id = getattr(sandbox, "id", "")
        timeout = self._lifetimes.get(sandbox_id, 300)
        try:
            result = setter(int(timeout))
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                await result
        except Exception:
            logger.warning(
                "Could not extend sandbox %s lifetime",
                sandbox_id or "?",
                exc_info=True,
            )

    async def create_sandbox(
        self,
        template: str | None = None,
        timeout: int = 300,
        envs: dict[str, str] | None = None,
    ) -> Any:
        """Create a sandbox and make it the session default."""
        from easy_sandbox.api.sandbox import Sandbox

        kwargs = self._connect_kwargs(
            template=template or self._default_template,
            timeout=timeout,
            envs=envs or {},
        )
        sandbox = await Sandbox.create(**kwargs)
        async with self._state_lock:
            self._sandboxes[sandbox.id] = sandbox
            self._lifetimes[sandbox.id] = timeout
            self._default_sandbox = sandbox
        logger.info("Created sandbox: %s", sandbox.id)
        return sandbox

    async def get_sandbox(self, sandbox_id: str | None = None) -> Any:
        """Get a sandbox by ID, or create/return the default sandbox."""
        if sandbox_id:
            async with self._state_lock:
                cached = self._sandboxes.get(sandbox_id)
            if cached is not None:
                await self._refresh_lifetime(cached)
                return cached
            from easy_sandbox.api.sandbox import Sandbox

            sb = await Sandbox.connect(**self._connect_kwargs(sandbox_id=sandbox_id))
            async with self._state_lock:
                self._sandboxes[sb.id] = sb
                self._lifetimes.setdefault(sb.id, 300)
            await self._refresh_lifetime(sb)
            return sb

        # One lazy create even when two tool calls arrive together.
        async with self._default_lock:
            if self._default_sandbox is None:
                created = await self.create_sandbox()
                if self._default_sandbox is None:
                    self._default_sandbox = created
                logger.info("Auto-created default sandbox: %s", self._default_sandbox.id)
            sandbox = self._default_sandbox
        await self._refresh_lifetime(sandbox)
        return sandbox

    async def kill_sandbox(self, sandbox_id: str | None = None) -> str | None:
        """Kill a sandbox by ID, or the default sandbox.

        Returns:
            The killed sandbox id, or ``None`` when there was no default
            sandbox to kill.
        """
        if sandbox_id:
            async with self._state_lock:
                sb = self._sandboxes.pop(sandbox_id, None)
                self._lifetimes.pop(sandbox_id, None)
                if self._default_sandbox is not None and self._default_sandbox.id == sandbox_id:
                    self._default_sandbox = None
            if sb is not None:
                await sb.kill()
                logger.info("Killed sandbox: %s", sandbox_id)
                return sandbox_id
            from easy_sandbox.api.sandbox import Sandbox

            kwargs: dict[str, Any] = {"sandbox_id": sandbox_id}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._api_url:
                kwargs["api_url"] = self._api_url
            await Sandbox.kill_by_id(**kwargs)
            return sandbox_id

        async with self._state_lock:
            sb = self._default_sandbox
            self._default_sandbox = None
            if sb is not None:
                self._sandboxes.pop(sb.id, None)
                self._lifetimes.pop(sb.id, None)
        if sb is None:
            return None
        sid = sb.id
        await sb.kill()
        logger.info("Killed default sandbox: %s", sid)
        return str(sid)

    async def shutdown(self) -> None:
        """Kill all sandboxes."""
        async with self._state_lock:
            items = list(self._sandboxes.items())
            self._sandboxes.clear()
            self._lifetimes.clear()
            self._default_sandbox = None
        for sid, sb in items:
            try:
                await sb.kill()
                logger.info("Shutdown: killed sandbox %s", sid)
            except Exception:
                logger.warning("Failed to kill sandbox %s during shutdown", sid, exc_info=True)


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


def _install_stop_signals(loop: asyncio.AbstractEventLoop) -> None:
    """Turn SIGINT and SIGTERM into cancellation so shutdown still runs.

    ``ebx mcp stop`` sends SIGTERM. Cancelling the read loop lets ``run``
    reach its ``finally`` block and kill the session's sandboxes.
    """
    if sys.platform == "win32":
        return

    def _request_stop() -> None:
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            return


def _line_exceeds_limit(exc: BaseException) -> bool:
    """True when ``StreamReader.readline`` rejected an overlong line."""
    return type(exc).__name__ in {"LimitOverrunError", "ValueError"} and "limit" in str(exc).lower()


async def _discard_overlong_line(reader: asyncio.StreamReader) -> None:
    """Drop the line that exceeded the read limit and keep any following bytes.

    ``readline`` leaves the oversized line in the internal buffer. The buffer
    is not part of the public stream API; clearing through the newline is what
    lets the server keep reading the next message instead of exiting.
    """
    buffer = reader._buffer  # type: ignore[attr-defined]
    newline = buffer.find(b"\n")
    if newline >= 0:
        del buffer[: newline + 1]
        return
    buffer.clear()
    while True:
        chunk = await reader.read(64 * 1024)
        if not chunk:
            return
        newline = chunk.find(b"\n")
        if newline >= 0:
            rest = chunk[newline + 1 :]
            if rest:
                buffer.extend(rest)
            return


# ---------------------------------------------------------------------------
# SandboxMCPServer
# ---------------------------------------------------------------------------


class SandboxMCPServer:
    """沙箱 MCP Server — 自包含 JSON-RPC 2.0 over STDIO 实现。

    支持 MCP 协议的 initialize / tools/list / tools/call 方法。
    当 ``mcp`` SDK 可用时可平滑替换传输层。

    协议版本按 transport 协商：默认支持 STDIO 的 ``2024-11-05``；
    其他 transport 通过 ``supported_protocol_versions`` 声明自己的版本集，
    首个条目为缺失/不支持请求时的回退版本。
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        template: str = "base",
        supported_protocol_versions: Sequence[str] | None = None,
    ) -> None:
        self._manager = SandboxManager(
            api_key=api_key,
            api_url=api_url,
            domain=domain,
            template=template,
        )
        self._initialized = False
        if supported_protocol_versions is None:
            versions: tuple[str, ...] = (MCP_PROTOCOL_VERSION,)
        else:
            versions = tuple(supported_protocol_versions)
        if not versions:
            raise ValueError("supported_protocol_versions must contain at least one version")
        self._supported_protocol_versions = versions

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
        """Handle MCP initialize request with per-transport version negotiation.

        Echoes the client-requested ``protocolVersion`` when this transport
        supports it. Otherwise — the request is missing ``protocolVersion``
        or asks for an unsupported version — respond with the preferred
        (first) supported version, per the MCP version negotiation rule that
        the server replies with another protocol version it supports (the
        client may then disconnect if it cannot accept it).
        """
        self._initialized = True
        requested = params.get("protocolVersion")
        if isinstance(requested, str) and requested in self._supported_protocol_versions:
            negotiated = requested
        else:
            negotiated = self._supported_protocol_versions[0]
            logger.debug(
                "MCP initialize: requested protocolVersion %r is missing or unsupported; "
                "negotiating to preferred version %s",
                requested,
                negotiated,
            )
        return {
            "protocolVersion": negotiated,
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
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"error": "Tool arguments must be an object"}),
                    }
                ],
                "isError": True,
            }

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

        exit_code = result.get("exit_code")
        is_error = "error" in result or (isinstance(exit_code, int) and exit_code != 0)
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

    async def handle_request(self, request: Any) -> dict[str, Any] | None:
        """Process one JSON-RPC object and return its response.

        Non-object JSON values and JSON-RPC batches are rejected because this
        minimal server intentionally supports one request object per message.
        """
        if not isinstance(request, dict):
            return _jsonrpc_error(None, INVALID_REQUEST, "Request must be a JSON object")

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")  # None for notifications
        if params is None:
            params = {}
        if not isinstance(params, dict):
            if req_id is not None:
                return _jsonrpc_error(req_id, INVALID_PARAMS, "params must be a JSON object")
            return None

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

        Reads newline-delimited JSON-RPC from stdin and writes responses to
        stdout. ``ping`` and other methods are answered while a ``tools/call``
        is still running; tool calls themselves stay serialized so two tools
        do not share one sandbox at the same time. A line over the read limit
        is rejected and the process keeps serving the next message.
        """
        logger.info("Starting MCP Server (STDIO mode)")
        loop = asyncio.get_running_loop()
        _install_stop_signals(loop)

        reader = asyncio.StreamReader(limit=_STDIO_READ_LIMIT)
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        transport, _ = await loop.connect_write_pipe(
            asyncio.BaseProtocol,
            sys.stdout,
        )
        write_lock = asyncio.Lock()
        tool_lock = asyncio.Lock()
        pending: set[asyncio.Task[None]] = set()

        async def _write(payload: dict[str, Any]) -> None:
            encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            async with write_lock:
                transport.write(encoded)

        async def _serve(request: Any) -> None:
            method = request.get("method") if isinstance(request, dict) else None
            try:
                if method == "tools/call":
                    async with tool_lock:
                        response = await self.handle_request(request)
                else:
                    response = await self.handle_request(request)
            except Exception as exc:
                req_id = request.get("id") if isinstance(request, dict) else None
                logger.error("STDIO dispatch failed: %s", exc, exc_info=True)
                response = _jsonrpc_error(req_id, INTERNAL_ERROR, str(exc))
            if response is not None:
                await _write(response)

        try:
            while True:
                try:
                    line = await reader.readline()
                except (asyncio.CancelledError, KeyboardInterrupt):
                    raise
                except Exception as exc:
                    if not _line_exceeds_limit(exc):
                        raise
                    await _discard_overlong_line(reader)
                    await _write(
                        _jsonrpc_error(
                            None,
                            INVALID_REQUEST,
                            "Message exceeds the STDIO size limit",
                        )
                    )
                    continue
                if not line:
                    break  # EOF

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    request = json.loads(line_str)
                except json.JSONDecodeError as exc:
                    await _write(_jsonrpc_error(None, PARSE_ERROR, f"Parse error: {exc}"))
                    continue

                task = asyncio.create_task(_serve(request))
                pending.add(task)
                task.add_done_callback(pending.discard)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            for task in list(pending):
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
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
    template = os.environ.get("SANDBOX_TEMPLATE") or os.environ.get("EBX_TEMPLATE") or "base"

    server = SandboxMCPServer(
        api_key=api_key,
        api_url=api_url,
        domain=domain,
        template=template,
    )
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
