"""Async HTTP client for Platform API and sandbox envd API.

Uses httpx.AsyncClient with HTTP/2 support. A long-lived client is kept for
the Platform API; envd clients are created on demand per sandbox URL.

envd URL 格式: https://49983-{sandbox_id}.{domain}（已实测验证）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

import httpx

from easy_sandbox.models.errors import ConnectionError_, EnvdRpcError
from easy_sandbox.transport.codec import CONNECT_CONTENT_TYPE, ConnectCodec, EnvelopeStreamParser
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from easy_sandbox.transport.auth import AuthProvider, EnvdTokenManager
    from easy_sandbox.transport.config import TransportConfig

logger = get_logger("transport.http")

# Upper bound on bytes read from an envd error response body (defensive —
# an error body is diagnostic text, not data; avoid buffering anything huge).
_MAX_ERROR_BODY_BYTES = 8192

# How much of the error body is kept in the exception / logs.
_ERROR_BODY_TEXT_LIMIT = 500


def _envd_error_detail(envd_error: dict[str, Any] | None) -> str:
    """Extract a human-readable detail string from an envd JSON error body.

    Covers the shapes observed from envd / Connect implementations:
    ``{"error": {"code": ..., "message": ...}}``, ``{"error": "text"}``,
    and flat ``{"code": ..., "message": ...}`` / ``{"message": ...}``.
    Returns ``""`` when nothing readable is found.
    """
    if not isinstance(envd_error, dict):
        return ""
    err = envd_error.get("error")
    if isinstance(err, dict):
        for key in ("message", "msg", "detail", "code"):
            val = err.get(key)
            if isinstance(val, str) and val:
                return val
    elif isinstance(err, str):
        return err
    for key in ("message", "msg", "detail", "code"):
        val = envd_error.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


class HttpClient:
    """Async HTTP client for Platform API and envd API.

    A single long-lived httpx.AsyncClient is used for the Platform API.
    Envd clients are created on demand (different sandboxes may have
    different base URLs) and tracked for proper cleanup.
    """

    def __init__(
        self,
        config: TransportConfig,
        auth: AuthProvider,
    ) -> None:
        self._config = config
        self._auth = auth
        self._codec = ConnectCodec()
        self._platform_client: httpx.AsyncClient | None = None
        self._envd_clients: dict[str, httpx.AsyncClient] = {}

    async def _get_platform_client(self) -> httpx.AsyncClient:
        """Get or create the Platform API client."""
        if self._platform_client is None or self._platform_client.is_closed:
            self._platform_client = httpx.AsyncClient(
                base_url=self._config.api_url,
                http2=self._config.http2,
                timeout=httpx.Timeout(self._config.http_timeout),
                limits=httpx.Limits(
                    max_connections=self._config.max_connections,
                    max_keepalive_connections=self._config.max_keepalive_connections,
                    keepalive_expiry=self._config.keepalive_expiry,
                ),
            )
        return self._platform_client

    def _create_envd_client(self, envd_url: str) -> httpx.AsyncClient:
        """Create (or reuse a cached) envd API client for a sandbox URL."""
        existing = self._envd_clients.get(envd_url)
        if existing is not None and not existing.is_closed:
            return existing
        client = httpx.AsyncClient(
            base_url=envd_url,
            http2=self._config.http2,
            timeout=httpx.Timeout(self._config.http_timeout),
        )
        self._envd_clients[envd_url] = client
        return client

    async def platform_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> httpx.Response:
        """Send a request to the Platform API (REST).

        Automatically injects authentication headers.

        Args:
            request_timeout: Per-request timeout override in seconds.
                When provided, overrides the client-level default
                ``http_timeout`` from :class:`TransportConfig` for this
                single request.  When *None*, the client-level default
                (i.e. ``SANDBOX_HTTP_TIMEOUT`` / ``Config.http_timeout``)
                is used unchanged.
        """
        client = await self._get_platform_client()
        auth_headers = await self._auth.get_headers()

        all_headers = {**auth_headers}
        if headers:
            all_headers.update(headers)

        # Build optional per-request timeout override (mirrors envd_request).
        extra_kwargs: dict[str, Any] = {}
        if request_timeout is not None:
            extra_kwargs["timeout"] = httpx.Timeout(request_timeout)

        logger.debug("Platform %s %s", method, path)
        try:
            response = await client.request(
                method=method,
                url=path,
                json=json,
                params=params,
                headers=all_headers,
                **extra_kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.ConnectError as exc:
            raise ConnectionError_(
                f"Failed to connect to Platform API: {exc}",
                suggestion="Check network connectivity and API base URL.",
            ) from exc
        except httpx.HTTPStatusError:
            # Let higher layers handle specific HTTP errors
            raise

    async def envd_request(
        self,
        envd_url: str,
        rpc_path: str,
        *,
        payload: dict[str, Any] | None = None,
        envd_token: EnvdTokenManager,
        headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a Connect RPC request to the envd API.

        Args:
            envd_url: Base URL of the sandbox envd.
            rpc_path: RPC path (e.g., "/process.Process/Start").
            payload: Request body dict.
            envd_token: Token manager for this sandbox.
            headers: Additional headers.
            request_timeout: Per-request timeout override in seconds.
                When provided, overrides the default ``http_timeout``
                from :class:`TransportConfig` for this single request.
                When *None*, the client-level default is used.

        Returns:
            Decoded response dict.
        """
        client = self._create_envd_client(envd_url)
        auth_headers = envd_token.get_headers()

        all_headers = {
            "Content-Type": CONNECT_CONTENT_TYPE,
            **auth_headers,
        }
        if headers:
            all_headers.update(headers)

        body = self._codec.encode_request(payload or {})

        # Build optional per-request timeout override
        extra_kwargs: dict[str, Any] = {}
        if request_timeout is not None:
            extra_kwargs["timeout"] = httpx.Timeout(request_timeout)

        logger.debug("envd POST %s%s", envd_url, rpc_path)
        try:
            response = await client.post(
                url=rpc_path,
                content=body,
                headers=all_headers,
                **extra_kwargs,
            )
            response.raise_for_status()
            return self._codec.decode_response(response.content)
        except httpx.ConnectError as exc:
            raise ConnectionError_(
                f"Failed to connect to sandbox envd: {exc}",
                suggestion="Check if the sandbox is still running.",
            ) from exc

    async def _raise_envd_rpc_error(
        self,
        response: httpx.Response,
        rpc_path: str,
    ) -> NoReturn:
        """Build and raise an :class:`EnvdRpcError` from an envd error response.

        Reads a *bounded* slice of the error body, parses it as JSON when
        possible (structured propagation for upper layers), and logs the
        details at DEBUG level only — never a default WARNING, and never
        with the full sandbox URL (which embeds the sandbox ID).  The RPC
        path (e.g. ``/process.Process/Start``) is not sensitive and is kept
        for diagnostics.  Task 166.
        """
        raw = b""
        async for chunk in response.aiter_bytes():
            raw += chunk
            if len(raw) >= _MAX_ERROR_BODY_BYTES:
                raw = raw[:_MAX_ERROR_BODY_BYTES]
                break
        body_text = raw.decode("utf-8", errors="replace")[:_ERROR_BODY_TEXT_LIMIT]

        envd_error: dict[str, Any] | None = None
        if raw:
            try:
                parsed = self._codec.decode_response(raw)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                envd_error = parsed

        detail = _envd_error_detail(envd_error) or body_text.strip()
        message = f"envd RPC {rpc_path} failed (HTTP {response.status_code})"
        if detail:
            message = f"{message}: {detail}"

        logger.debug(
            "envd STREAM %s failed (HTTP %s): %s",
            rpc_path,
            response.status_code,
            body_text,
        )
        raise EnvdRpcError(
            message,
            status_code=response.status_code,
            rpc_path=rpc_path,
            envd_error=envd_error,
            body_text=body_text,
        )

    async def envd_stream(
        self,
        envd_url: str,
        rpc_path: str,
        *,
        payload: dict[str, Any] | None = None,
        envd_token: EnvdTokenManager,
        headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a Connect RPC streaming request to the envd API.

        Returns an async iterator of decoded response frames.
        Connect streaming uses binary envelope framing (已实测验证):
          flags (1 byte) + length (4 bytes big-endian) + JSON payload

        The response is consumed incrementally via ``client.stream()`` +
        ``aiter_bytes()`` so frames are yielded as soon as they arrive
        (server-side per-line output is visible line by line).  The full
        response body is never buffered — only a single in-flight frame is
        held in memory.

        NOTE: A fresh httpx client is used for each streaming call to
        avoid HTTP/2 connection-state issues observed with connection
        reuse on some envd versions (cached connections that served
        earlier unary RPCs can return spurious 500 errors on subsequent
        streaming calls).

        Resource cleanup: both the streaming response and the client are
        managed by ``async with``.  They are closed on normal completion,
        on errors, on cancellation (``CancelledError``), and when the
        consumer stops iterating early (``GeneratorExit`` propagated by
        ``aclose()`` / garbage collection of the generator).

        Error responses (HTTP >= 400) raise :class:`EnvdRpcError` — a
        structured :class:`~easy_sandbox.models.errors.SandboxError`
        carrying the parsed envd JSON error body, the status code and the
        RPC path.  No default WARNING is logged for the error body and the
        exception text never contains the full sandbox URL (task 166; the
        CLI/connect-layer friendly mapping is handled separately).

        Args:
            request_timeout: Per-request timeout override in seconds.
                When provided, overrides the default ``http_timeout``
                from :class:`TransportConfig` for this streaming call.
                When *None*, ``self._config.http_timeout`` is used.
        """
        auth_headers = envd_token.get_headers()

        all_headers = {
            "Content-Type": CONNECT_CONTENT_TYPE,
            **auth_headers,
        }
        if headers:
            all_headers.update(headers)

        body = self._codec.encode_request(payload or {})
        effective_timeout = (
            request_timeout if request_timeout is not None else self._config.http_timeout
        )

        logger.debug("envd STREAM %s%s (timeout=%.1fs)", envd_url, rpc_path, effective_timeout)
        try:
            # Use a fresh client per streaming call (see NOTE above) and a
            # true streaming request so frames are decoded incrementally
            # as network chunks arrive.
            async with httpx.AsyncClient(
                http2=self._config.http2,
                timeout=httpx.Timeout(effective_timeout),
            ) as client:
                url = envd_url.rstrip("/") + rpc_path
                async with client.stream(
                    "POST",
                    url=url,
                    content=body,
                    headers=all_headers,
                ) as response:
                    if response.status_code >= 400:
                        # Structured error propagation instead of httpx's
                        # raise_for_status (whose message embeds the full
                        # sandbox URL and an MDN status link).
                        await self._raise_envd_rpc_error(response, rpc_path)

                    parser = EnvelopeStreamParser()
                    async for chunk in response.aiter_bytes():
                        for frame in parser.feed(chunk):
                            yield frame

                    if parser.pending_bytes():
                        logger.warning(
                            "envd STREAM %s ended with %d truncated byte(s); "
                            "incomplete final frame dropped",
                            rpc_path,
                            parser.pending_bytes(),
                        )
        except httpx.ConnectError as exc:
            raise ConnectionError_(
                f"Failed to connect to sandbox envd for streaming: {exc}",
                suggestion="Check if the sandbox is still running.",
            ) from exc

    async def envd_http_request(
        self,
        envd_url: str,
        method: str,
        path: str,
        *,
        envd_token: EnvdTokenManager,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send a plain HTTP request (not Connect RPC) to the envd API.

        Used for file upload/download which use standard HTTP
        rather than Connect protocol (已实测验证).
        """
        client = self._create_envd_client(envd_url)
        auth_headers = envd_token.get_headers()

        all_headers = {**auth_headers}
        if headers:
            all_headers.update(headers)

        logger.debug("envd HTTP %s %s%s", method, envd_url, path)
        try:
            response = await client.request(
                method=method,
                url=path,
                params=params,
                headers=all_headers,
                content=content,
                files=files,
            )
            response.raise_for_status()
            return response
        except httpx.ConnectError as exc:
            raise ConnectionError_(
                f"Failed to connect to sandbox envd: {exc}",
                suggestion="Check if the sandbox is still running.",
            ) from exc

    async def close(self) -> None:
        """Close all HTTP clients and release connections."""
        if self._platform_client and not self._platform_client.is_closed:
            await self._platform_client.aclose()
            self._platform_client = None

        for _url, client in list(self._envd_clients.items()):
            if not client.is_closed:
                await client.aclose()
        self._envd_clients.clear()
        logger.debug("All HTTP clients closed")

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
