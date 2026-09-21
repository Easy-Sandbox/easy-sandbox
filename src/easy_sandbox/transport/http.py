"""Async HTTP client for Platform API and sandbox envd API.

Uses httpx.AsyncClient with HTTP/2 support. A long-lived client is kept for
the Platform API; envd clients are created on demand per sandbox URL.

envd URL 格式: https://49983-{sandbox_id}.{domain}（已实测验证）
"""
from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from easy_sandbox.models.errors import ConnectionError_, NetworkError
from easy_sandbox.transport.auth import AuthProvider, EnvdTokenManager, PLATFORM_AUTH_HEADER
from easy_sandbox.transport.codec import ConnectCodec, CONNECT_CONTENT_TYPE
from easy_sandbox.transport.config import TransportConfig, ENVD_PORT
from easy_sandbox.utils.logging import get_logger

logger = get_logger("transport.http")


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
    ) -> httpx.Response:
        """Send a request to the Platform API (REST).

        Automatically injects authentication headers.
        """
        client = await self._get_platform_client()
        auth_headers = await self._auth.get_headers()

        all_headers = {**auth_headers}
        if headers:
            all_headers.update(headers)

        logger.debug("Platform %s %s", method, path)
        try:
            response = await client.request(
                method=method,
                url=path,
                json=json,
                params=params,
                headers=all_headers,
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
    ) -> dict[str, Any]:
        """Send a Connect RPC request to the envd API.

        Args:
            envd_url: Base URL of the sandbox envd.
            rpc_path: RPC path (e.g., "/process.Process/Start").
            payload: Request body dict.
            envd_token: Token manager for this sandbox.
            headers: Additional headers.

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

        logger.debug("envd POST %s%s", envd_url, rpc_path)
        try:
            response = await client.post(
                url=rpc_path,
                content=body,
                headers=all_headers,
            )
            response.raise_for_status()
            return self._codec.decode_response(response.content)
        except httpx.ConnectError as exc:
            raise ConnectionError_(
                f"Failed to connect to sandbox envd: {exc}",
                suggestion="Check if the sandbox is still running.",
            ) from exc

    async def envd_stream(
        self,
        envd_url: str,
        rpc_path: str,
        *,
        payload: dict[str, Any] | None = None,
        envd_token: EnvdTokenManager,
        headers: dict[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a Connect RPC streaming request to the envd API.

        Returns an async iterator of decoded response frames.
        Connect streaming uses binary envelope framing (已实测验证):
          flags (1 byte) + length (4 bytes big-endian) + JSON payload

        NOTE: A fresh httpx client is used for each streaming call to
        avoid HTTP/2 connection-state issues observed with connection
        reuse on some envd versions (cached connections that served
        earlier unary RPCs can return spurious 500 errors on subsequent
        streaming calls).
        """
        auth_headers = envd_token.get_headers()

        all_headers = {
            "Content-Type": CONNECT_CONTENT_TYPE,
            **auth_headers,
        }
        if headers:
            all_headers.update(headers)

        body = self._codec.encode_request(payload or {})

        logger.debug("envd STREAM %s%s", envd_url, rpc_path)
        try:
            # Use a fresh client per streaming call and a regular POST
            # to read the full response at once.  Reusing the cached
            # envd client can trigger HTTP/2 multiplexing issues where
            # connection state from prior unary RPCs causes the server
            # to return 500 on streaming endpoints.
            async with httpx.AsyncClient(
                http2=self._config.http2,
                timeout=httpx.Timeout(self._config.http_timeout),
            ) as client:
                url = envd_url.rstrip("/") + rpc_path
                response = await client.post(
                    url=url,
                    content=body,
                    headers=all_headers,
                )
                if response.status_code >= 400:
                    # Include response body in the error for better
                    # diagnostics (envd may return useful messages).
                    body_text = response.text[:500]
                    logger.warning(
                        "envd STREAM error %s: %s",
                        response.status_code, body_text,
                    )
                response.raise_for_status()
                raw_bytes = response.content

            # Parse all frames from the binary envelope
            frames = self._codec.parse_streaming_frames(raw_bytes)
            for frame in frames:
                yield frame
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

        for url, client in list(self._envd_clients.items()):
            if not client.is_closed:
                await client.aclose()
        self._envd_clients.clear()
        logger.debug("All HTTP clients closed")

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
