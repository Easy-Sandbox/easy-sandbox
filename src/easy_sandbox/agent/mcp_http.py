"""MCP Streamable HTTP transport — Starlette ASGI application.

Implements the MCP Streamable HTTP transport (2025-06-18 specification):
- ``POST /mcp``  — JSON-RPC request/response
- ``GET  /mcp``  — returns 405 until SSE server notifications exist
- ``DELETE /mcp`` — Session termination & sandbox cleanup

Reuses the 7 P0 tools defined in :mod:`easy_sandbox.agent.tools` via
:class:`~easy_sandbox.agent.mcp.SandboxMCPServer` and
:class:`~easy_sandbox.agent.mcp.SandboxManager`.

Protocol version: this transport supports ``2025-06-18`` only. Each session's
:class:`~easy_sandbox.agent.mcp.SandboxMCPServer` is created with that
supported-version set, so ``initialize`` negotiates ``2025-06-18`` — consistent
with the version reported by ``GET /health``. The STDIO transport keeps its own
``2024-11-05`` default.

Authentication:
- Client → MCP: ``Authorization: Bearer <token>`` (validated here)
- MCP → Sandbox: ``E2B_API_KEY`` environment variable (forwarded by SandboxManager)

Session affinity requires platform routing based on the
``Mcp-Session-Id`` response header.

Starlette and uvicorn are **optional** dependencies (``mcp`` extra).
A friendly error is raised when the application is created if they are missing.
"""

from __future__ import annotations

import hmac
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from easy_sandbox.utils.logging import get_logger

logger = get_logger("agent.mcp_http")

# ---------------------------------------------------------------------------
# Lazy optional-dependency imports
# ---------------------------------------------------------------------------

_STARLETTE_IMPORT_ERROR: str | None = None

try:
    from starlette.applications import Starlette
    from starlette.requests import Request  # noqa: TC002
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route
except ImportError as _exc:  # pragma: no cover
    _STARLETTE_IMPORT_ERROR = (
        "Starlette is required for MCP HTTP transport but is not installed. "
        "Install it with: pip install 'easy-sandbox[mcp]' "
        "or: pip install starlette uvicorn"
    )

# ---------------------------------------------------------------------------
# MCP protocol constants (Streamable HTTP — 2025-06-18)
# ---------------------------------------------------------------------------

# The only protocol version this transport supports. Passed to each session's
# SandboxMCPServer so initialize negotiates consistently with GET /health.
MCP_PROTOCOL_VERSION = "2025-06-18"
CONTENT_TYPE_JSON = "application/json"

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
SESSION_LIMIT_ERROR = -32000

DEFAULT_SESSION_TTL_SECONDS = 3600.0
DEFAULT_MAX_SESSIONS = 100


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers (shared format with agent/mcp.py)
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


# ---------------------------------------------------------------------------
# Session store — in-process session → SandboxMCPServer mapping
# ---------------------------------------------------------------------------


@dataclass
class _SessionEntry:
    """A server session and its most recent access time."""

    server: Any
    last_access: float


class SessionCapacityError(RuntimeError):
    """Raised when the configured concurrent-session limit is reached."""


class SessionStore:
    """Manage bounded, expiring MCP sessions.

    In FC, requests carrying the same ``Mcp-Session-Id`` must be routed to
    the same instance. Idle sessions are expired and the total number of
    in-process sessions is capped to prevent unbounded resource growth.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        template: str = "base",
        session_ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self._api_key = api_key
        self._api_url = api_url
        self._domain = domain
        self._template = template
        self._session_ttl_seconds = session_ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, _SessionEntry] = {}

    async def create_session(self) -> tuple[str, Any]:
        """Create a session after removing expired entries.

        Returns:
            Tuple of (session_id, SandboxMCPServer).

        Raises:
            SessionCapacityError: If the active-session limit is reached.
        """
        from easy_sandbox.agent.mcp import SandboxMCPServer

        await self.cleanup_expired()
        if len(self._sessions) >= self._max_sessions:
            raise SessionCapacityError(f"MCP session limit reached ({self._max_sessions})")

        session_id = str(uuid.uuid4())
        server = SandboxMCPServer(
            api_key=self._api_key,
            api_url=self._api_url,
            domain=self._domain,
            template=self._template,
            # Streamable HTTP transport supports only 2025-06-18 — the same
            # version GET /health reports. Keeps initialize negotiation
            # consistent with the transport declaration.
            supported_protocol_versions=(MCP_PROTOCOL_VERSION,),
        )
        self._sessions[session_id] = _SessionEntry(
            server=server,
            last_access=time.monotonic(),
        )
        logger.info("Created MCP session: %s", session_id)
        return session_id, server

    def get_session(self, session_id: str) -> Any | None:
        """Look up an existing session and refresh its idle timestamp.

        Returns:
            SandboxMCPServer if found, else None.
        """
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        entry.last_access = time.monotonic()
        return entry.server

    async def destroy_session(self, session_id: str) -> bool:
        """Destroy a session and shut down its sandboxes.

        Returns:
            True if the session existed and was cleaned up.
        """
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return False
        await entry.server.shutdown()
        logger.info("Destroyed MCP session: %s", session_id)
        return True

    async def cleanup_expired(self) -> int:
        """Destroy idle sessions whose TTL has elapsed.

        Returns:
            Number of expired sessions removed.
        """
        now = time.monotonic()
        expired_ids = [
            session_id
            for session_id, entry in self._sessions.items()
            if now - entry.last_access >= self._session_ttl_seconds
        ]
        for session_id in expired_ids:
            await self.destroy_session(session_id)
        return len(expired_ids)

    async def shutdown_all(self) -> None:
        """Destroy every session (used on process exit)."""
        for session_id in list(self._sessions):
            await self.destroy_session(session_id)


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------


class MCPAuthConfigError(RuntimeError):
    """The remote MCP server was started without a usable Bearer token."""


def require_auth_token(value: str | None) -> str:
    """Return a non-empty Bearer token or refuse to start.

    A missing token used to mean "authentication disabled". That is acceptable
    on a loopback STDIO or HTTP process the operator started themselves. A
    function deployed for remote clients must not boot in that mode.

    Args:
        value: ``EBX_MCP_AUTH_TOKEN`` or an equivalent setting.

    Returns:
        The stripped token.

    Raises:
        MCPAuthConfigError: When the token is missing or only whitespace.
    """
    token = (value or "").strip()
    if not token:
        raise MCPAuthConfigError(
            "EBX_MCP_AUTH_TOKEN is empty. Refusing to start a remote MCP "
            "server with client authentication disabled."
        )
    return token


def _validate_bearer_token(request: Any, expected_token: str | None) -> bool:
    """Check ``Authorization: Bearer <token>`` header.

    Args:
        request: Starlette Request object.
        expected_token: The expected token value. If *None*, auth is disabled.

    Returns:
        True if the request is authorized.
    """
    if expected_token is None:
        return True  # authentication explicitly disabled

    normalized_expected = expected_token.strip()
    if not normalized_expected:
        return False  # configured-but-empty tokens fail closed

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    supplied_token = auth_header[7:].strip()
    return hmac.compare_digest(
        supplied_token.encode("utf-8"),
        normalized_expected.encode("utf-8"),
    )


def _origin_allowed(request: Any, allowed_origins: frozenset[str]) -> bool:
    """Allow missing Origin, localhost, and an explicit allow-list.

    Browsers always send Origin. A remote MCP endpoint with authentication
    disabled must still reject a page on another host (DNS rebinding).
    Non-browser clients omit Origin and are allowed.
    """
    origin = request.headers.get("origin")
    if not origin:
        return True
    if origin in allowed_origins:
        return True
    host = (urlparse(origin).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _reject_origin() -> JSONResponse:
    """403 used when the Origin header is present and not allowed."""
    return JSONResponse({"error": "Origin is not allowed"}, status_code=403)


# ---------------------------------------------------------------------------
# ASGI application factory
# ---------------------------------------------------------------------------


def create_mcp_app(
    auth_token: str | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    template: str = "base",
    session_ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
    max_sessions: int = DEFAULT_MAX_SESSIONS,
    allowed_origins: frozenset[str] | set[str] | None = None,
) -> Starlette:
    """Create the MCP Streamable HTTP Starlette application.

    Args:
        auth_token: Bearer token for client authentication.
            If *None*, authentication is disabled.
        api_key: ``E2B_API_KEY`` for MCP → Sandbox backend auth.
        api_url: Override for the sandbox API URL.
        domain: Override for the sandbox domain.
        template: Default sandbox template.
        session_ttl_seconds: Idle time before a session is cleaned up.
        max_sessions: Maximum concurrent sessions in this process.
        allowed_origins: Extra ``Origin`` values to accept. Localhost is
            always accepted. A missing Origin is accepted.

    Returns:
        A Starlette ASGI application.

    Raises:
        RuntimeError: If Starlette is not installed.
    """
    if _STARLETTE_IMPORT_ERROR is not None:
        raise RuntimeError(_STARLETTE_IMPORT_ERROR)

    origins = frozenset(allowed_origins or ())

    store = SessionStore(
        api_key=api_key,
        api_url=api_url,
        domain=domain,
        template=template,
        session_ttl_seconds=session_ttl_seconds,
        max_sessions=max_sessions,
    )

    # ---- POST /mcp ----
    async def handle_post(request: Request) -> Response:
        """Handle JSON-RPC requests from MCP clients."""
        if not _origin_allowed(request, origins):
            return _reject_origin()
        # Auth check
        if not _validate_bearer_token(request, auth_token):
            return JSONResponse(
                _jsonrpc_error(None, -32001, "Unauthorized"),
                status_code=401,
            )

        # Parse body
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                _jsonrpc_error(None, PARSE_ERROR, "Invalid JSON"),
                status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                _jsonrpc_error(None, INVALID_REQUEST, "Request must be a JSON object"),
                status_code=400,
            )

        await store.cleanup_expired()

        # Resolve or create session
        session_id = request.headers.get("mcp-session-id")
        method = body.get("method", "")

        if session_id:
            server = store.get_session(session_id)
            if server is None:
                return JSONResponse(
                    _jsonrpc_error(
                        body.get("id"),
                        INVALID_REQUEST,
                        f"Unknown session: {session_id}",
                    ),
                    status_code=404,
                )
        else:
            # Only 'initialize' may create a new session
            if method == "initialize":
                try:
                    session_id, server = await store.create_session()
                except SessionCapacityError as exc:
                    return JSONResponse(
                        _jsonrpc_error(body.get("id"), SESSION_LIMIT_ERROR, str(exc)),
                        status_code=503,
                    )
            else:
                return JSONResponse(
                    _jsonrpc_error(
                        body.get("id"),
                        INVALID_REQUEST,
                        "Missing Mcp-Session-Id header. Send an 'initialize' request first.",
                    ),
                    status_code=400,
                )

        # Dispatch to the shared MCP logic
        response_body = await server.handle_request(body)

        resp = Response(status_code=202) if response_body is None else JSONResponse(response_body)

        # Attach session header
        if session_id:
            resp.headers["Mcp-Session-Id"] = session_id

        return resp

    # ---- GET /mcp (SSE not implemented; 405 per the Streamable HTTP spec) ----
    async def handle_get(request: Request) -> Response:
        """Reject SSE until server-initiated notifications exist.

        The Streamable HTTP spec says a server that does not offer an SSE
        stream responds with 405 Method Not Allowed, not 501.
        """
        if not _origin_allowed(request, origins):
            return _reject_origin()
        if not _validate_bearer_token(request, auth_token):
            return JSONResponse(
                _jsonrpc_error(None, -32001, "Unauthorized"),
                status_code=401,
            )
        return JSONResponse(
            {"error": "SSE server notifications are not implemented. Use POST /mcp."},
            status_code=405,
            headers={"Allow": "POST, DELETE"},
        )

    # ---- DELETE /mcp ----
    async def handle_delete(request: Request) -> Response:
        """Terminate an MCP session and clean up sandboxes."""
        if not _origin_allowed(request, origins):
            return _reject_origin()
        if not _validate_bearer_token(request, auth_token):
            return JSONResponse(
                _jsonrpc_error(None, -32001, "Unauthorized"),
                status_code=401,
            )

        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            return JSONResponse(
                {"error": "Missing Mcp-Session-Id header"},
                status_code=400,
            )

        destroyed = await store.destroy_session(session_id)
        if not destroyed:
            return JSONResponse(
                {"error": f"Unknown session: {session_id}"},
                status_code=404,
            )
        return JSONResponse({"status": "session_terminated"})

    # ---- Health check ----
    async def handle_health(request: Request) -> Response:
        """Simple health check for FC / load balancer probes."""
        return JSONResponse({"status": "ok", "protocol": MCP_PROTOCOL_VERSION})

    # ---- Lifecycle events ----
    @asynccontextmanager
    async def _lifespan(app_instance: Any) -> AsyncIterator[None]:
        """ASGI lifespan — clean up all sessions on shutdown."""
        yield
        await store.shutdown_all()

    app = Starlette(
        routes=[
            Route("/mcp", handle_post, methods=["POST"]),
            Route("/mcp", handle_get, methods=["GET"]),
            Route("/mcp", handle_delete, methods=["DELETE"]),
            Route("/health", handle_health, methods=["GET"]),
        ],
        lifespan=_lifespan,
    )

    # Expose store for testing
    app.state.session_store = store

    return app


# ---------------------------------------------------------------------------
# Convenience: default ASGI app (read config from env)
# ---------------------------------------------------------------------------


def _create_default_app() -> Starlette:
    """Create a default app reading configuration from environment variables.

    Environment variables:
    - ``EBX_MCP_AUTH_TOKEN`` — Bearer token for client auth (optional)
    - ``E2B_API_KEY`` / ``SANDBOX_API_KEY`` — Sandbox backend API key
    - ``E2B_API_URL`` / ``SANDBOX_API_BASE_URL`` — API URL override
    - ``E2B_DOMAIN`` — Domain override
    - ``SANDBOX_TEMPLATE`` / ``EBX_TEMPLATE`` — Default template
    """
    raw_origins = os.environ.get("EBX_MCP_ALLOWED_ORIGINS", "")
    allowed_origins = frozenset(part.strip() for part in raw_origins.split(",") if part.strip())
    return create_mcp_app(
        auth_token=os.environ.get("EBX_MCP_AUTH_TOKEN"),
        api_key=os.environ.get("E2B_API_KEY") or os.environ.get("SANDBOX_API_KEY"),
        api_url=os.environ.get("E2B_API_URL") or os.environ.get("SANDBOX_API_BASE_URL"),
        domain=os.environ.get("E2B_DOMAIN"),
        template=os.environ.get("SANDBOX_TEMPLATE") or os.environ.get("EBX_TEMPLATE", "base"),
        allowed_origins=allowed_origins,
    )


# Module-level ASGI entry point for ``uvicorn easy_sandbox.agent.mcp_http:asgi_app``
# Lazily created on first access to avoid import-time side effects.
_cached_app: Starlette | None = None


def get_asgi_app() -> Starlette:
    """Return the module-level ASGI app (lazily created).

    This is the recommended entry point for uvicorn / FC runtime:

    .. code-block:: bash

        uvicorn easy_sandbox.agent.mcp_http:asgi_app --host 0.0.0.0 --port 9000
    """
    global _cached_app
    if _cached_app is None:
        _cached_app = _create_default_app()
    return _cached_app


class _LazyApp:
    """ASGI app proxy that lazily creates the real app on first call."""

    def __init__(self) -> None:
        self._app: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._app is None:
            self._app = get_asgi_app()
        await self._app(scope, receive, send)


# This is the module-level ASGI entry point.
asgi_app: Any = _LazyApp()
