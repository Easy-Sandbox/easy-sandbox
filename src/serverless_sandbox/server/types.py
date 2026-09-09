"""Stdlib-only request / response types for the sandbox HTTP server.

These lightweight :mod:`dataclasses` types provide a framework-agnostic
abstraction over raw HTTP messages, allowing route handlers to be tested
without spinning up a real server.

All imports are from the Python standard library — no Pydantic, no
third-party packages.
"""

from __future__ import annotations

import dataclasses
from typing import Any

__all__ = [
    "ServerRequest",
    "ServerResponse",
    "SSEResponse",
]


@dataclasses.dataclass
class ServerRequest:
    """Normalised request object parsed from an HTTP request.

    Attributes:
        method: HTTP method (``GET``, ``POST``, etc.) in uppercase.
        path: URL path component (e.g. ``"/commands/greet"``).
        query: Parsed query-string parameters.  Each key maps to a
            *list* of values to handle repeated keys correctly.
        headers: Request headers (single-valued).
        body: Parsed JSON body, or ``None`` if the request has no body
            or the content is not JSON.
        path_params: Path parameters extracted from a ``{param}`` route
            pattern (e.g. ``{"name": "greet"}`` for ``/commands/greet``).
        context: Per-request server context injected by the dispatcher
            (e.g. the active :class:`~serverless_sandbox.server.registry.CommandRegistry`
            under the ``"registry"`` key).
    """

    method: str
    path: str
    query: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    body: dict[str, Any] | None = None
    path_params: dict[str, str] = dataclasses.field(default_factory=dict)
    context: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ServerResponse:
    """Normalised response object returned by route handlers.

    Attributes:
        status: HTTP status code (e.g. ``200``, ``404``).
        body: JSON-serialisable response body.
        headers: Extra response headers to include.
    """

    status: int
    body: dict[str, Any] = dataclasses.field(default_factory=dict)
    headers: dict[str, str] = dataclasses.field(default_factory=dict)

    @classmethod
    def ok(cls, data: dict[str, Any]) -> ServerResponse:
        """Return a ``200 OK`` response wrapping *data*."""
        return cls(status=200, body=data)

    @classmethod
    def error(
        cls,
        status: int,
        message: str,
        error_type: str = "ValueError",
    ) -> ServerResponse:
        """Return an error response with a standardised body.

        Args:
            status: HTTP status code.
            message: Human-readable error message.
            error_type: Exception class name recorded under ``"type"``.

        Returns:
            A :class:`ServerResponse` whose body is
            ``{"error": message, "type": error_type}``.
        """
        return cls(status=status, body={"error": message, "type": error_type})


@dataclasses.dataclass
class SSEResponse:
    """A streaming Server-Sent-Events response.

    Attributes:
        status: HTTP status code (default ``200``).
        headers: Response headers (defaults to an ``text/event-stream``
            content type).
        event_iterator: An iterator yielding SSE event payloads (``str`` or
            ``bytes``) to be flushed to the client one at a time.
    """

    status: int = 200
    headers: dict[str, str] = dataclasses.field(
        default_factory=lambda: {"Content-Type": "text/event-stream"}
    )
    event_iterator: Any = None
