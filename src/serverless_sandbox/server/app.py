"""Lightweight, stdlib-only HTTP server for running inside sandbox containers.

Uses :class:`http.server.ThreadingHTTPServer` with a custom
:class:`BaseHTTPRequestHandler` subclass that dispatches requests through the
declarative :class:`~serverless_sandbox.server.router.RouteTable` populated by
:mod:`serverless_sandbox.server.routes`.

Typical usage (from a template's ``commands.py``)::

    from serverless_sandbox.server import start
    start(9000)
"""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import routes as _routes  # noqa: F401  (import side-effect: registers routes)
from .registry import CommandRegistry, default_registry
from .router import RouteTable, default_table
from .types import ServerRequest, ServerResponse, SSEResponse

__all__ = [
    "SandboxServer",
    "SandboxRequestHandler",
]

# Auth token — read once at import time so tests can monkeypatch the env var
# before importing.
_TOKEN_ENV_VAR = "SBOX_SERVER_TOKEN"

# HTTP methods that may carry a JSON request body.
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class SandboxRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler that dispatches through a :class:`RouteTable`.

    Attributes:
        server: Bound :class:`SandboxServer` instance (set automatically by
            :mod:`http.server`).  The handler reads ``auth_token``,
            ``registry`` and ``route_table`` back-references from it.
    """

    # Silence per-request log lines in production; tests can override.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress default stderr logging."""

    # ------------------------------------------------------------------ #
    # Auth helper
    # ------------------------------------------------------------------ #

    def _check_auth(self) -> bool:
        """Validate ``X-Access-Token`` if a token is configured.

        Returns:
            ``True`` if the request is authorised; ``False`` if a 401
            response has already been sent.
        """
        token: str | None = getattr(self.server, "auth_token", None)
        if token is None:
            return True  # local mode — no auth required

        request_token = self.headers.get("X-Access-Token")
        if not request_token or not hmac.compare_digest(request_token, token):
            self._send_json(401, {"error": "unauthorized", "type": "AuthError"})
            return False
        return True

    # ------------------------------------------------------------------ #
    # Response helpers
    # ------------------------------------------------------------------ #

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        """Serialise *body* as JSON and send with appropriate headers."""
        payload = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_response(self, response: ServerResponse) -> None:
        """Send a :class:`ServerResponse` (JSON body + optional headers)."""
        payload = json.dumps(response.body, default=str).encode("utf-8")
        self.send_response(response.status)
        if "Content-Type" not in response.headers:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any] | None:
        """Read and parse a JSON request body.

        Returns:
            Parsed dict, or ``None`` if parsing fails (a 400 response will
            have been sent).
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            raw = self.rfile.read(content_length)
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"error": f"Invalid JSON: {exc}", "type": "ValueError"})
            return None

    # ------------------------------------------------------------------ #
    # Unified dispatcher
    # ------------------------------------------------------------------ #

    def _route_table(self) -> RouteTable:
        """Return the bound route table, falling back to the default one."""
        table = getattr(self.server, "route_table", None)
        return table if table is not None else default_table()

    def _dispatch(self, method: str) -> None:
        """Match *method* + path against the route table and invoke the handler."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        table = self._route_table()

        route, path_params = table.match(method, path)
        if route is None:
            self._send_json(404, {"error": f"Not found: {path}", "type": "ValueError"})
            return

        # Auth is enforced unless the route opts out (e.g. /health).
        if route.auth_required and not self._check_auth():
            return

        # Capability-group gate: a disabled group makes the route unavailable.
        if not table.is_group_enabled(route.group):
            self._send_json(404, {
                "error": f"Built-in route {route.name!r} is disabled",
                "type": "ValueError",
            })
            return

        # Read the JSON body for methods that carry one.
        body: dict[str, Any] | None = None
        if method in _BODY_METHODS:
            body = self._read_json_body()
            if body is None:
                return  # 400 already sent

        request = ServerRequest(
            method=method,
            path=path,
            query=parse_qs(parsed.query),
            headers=dict(self.headers),
            body=body,
            path_params=path_params or {},
            context={"registry": getattr(self.server, "registry", None)},
        )

        if route.streaming:
            self._dispatch_streaming(route, request)
            return

        response = route.handler(request)
        self._send_response(response)

    def _dispatch_streaming(self, route: Any, request: ServerRequest) -> None:
        """Invoke a streaming (SSE) handler and flush its events."""
        result = route.handler(request)
        if isinstance(result, SSEResponse):
            self.send_response(result.status)
            for key, value in result.headers.items():
                self.send_header(key, value)
            self.end_headers()
            if result.event_iterator is not None:
                for event in result.event_iterator:
                    chunk = event.encode("utf-8") if isinstance(event, str) else event
                    self.wfile.write(chunk)
                    self.wfile.flush()
        elif isinstance(result, ServerResponse):
            # A streaming route may still choose to return a normal response.
            self._send_response(result)

    # ------------------------------------------------------------------ #
    # Method entry points
    # ------------------------------------------------------------------ #

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET requests."""
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST requests."""
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        """Handle DELETE requests."""
        self._dispatch("DELETE")


class SandboxServer:
    """Lightweight stdlib HTTP server for sandbox containers.

    Args:
        host: Bind address (default ``"0.0.0.0"``).
        registry: Optional :class:`CommandRegistry` (defaults to the module
            singleton).
        route_table: Optional :class:`RouteTable` (defaults to the module
            singleton populated by :mod:`serverless_sandbox.server.routes`).

    Example::

        server = SandboxServer()
        server.serve(port=9000)
    """

    def __init__(
        self,
        host: str = "0.0.0.0",  # noqa: S104
        registry: CommandRegistry | None = None,
        route_table: RouteTable | None = None,
    ) -> None:
        self._host = host
        self.auth_token: str | None = os.environ.get(_TOKEN_ENV_VAR) or None
        self._httpd: ThreadingHTTPServer | None = None
        self._registry: CommandRegistry = registry if registry is not None else default_registry()
        self.route_table: RouteTable = route_table if route_table is not None else default_table()

    def serve(self, port: int = 9000) -> None:
        """Start the server and block until interrupted.

        Args:
            port: TCP port to listen on (default ``9000``).
        """
        self._httpd = ThreadingHTTPServer(
            (self._host, port), SandboxRequestHandler
        )
        # Store back-references so the handler can access auth_token, registry
        # and the route table.
        self._httpd.auth_token = self.auth_token  # type: ignore[attr-defined]
        self._httpd.registry = self._registry  # type: ignore[attr-defined]
        self._httpd.route_table = self.route_table  # type: ignore[attr-defined]
        self._registry.freeze()
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._httpd.server_close()

    def shutdown(self) -> None:
        """Gracefully shut down a running server (thread-safe)."""
        if self._httpd is not None:
            self._httpd.shutdown()


def start(
    port: int = 9000,
    host: str = "0.0.0.0",  # noqa: S104
    registry: CommandRegistry | None = None,
) -> None:
    """Convenience function — create a :class:`SandboxServer` and serve.

    Args:
        port: TCP port (default ``9000``).
        host: Bind address (default ``"0.0.0.0"``).
        registry: Optional :class:`CommandRegistry` (uses the default
            singleton when ``None``).
    """
    server = SandboxServer(host=host, registry=registry)
    server.serve(port=port)
