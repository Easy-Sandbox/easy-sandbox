"""WebSocket client for PTY terminal and bidirectional channels.

WebSocket disconnection typically means the sandbox has been terminated.
Reconnection is the caller's responsibility — this client provides only
basic connect / disconnect / send / receive functionality.

Heartbeat (ping/pong) is handled natively by the ``websockets`` library
via the ``ping_interval`` parameter; no extra SDK wrapper is needed.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from easy_sandbox.models.errors import ConnectionError_
from easy_sandbox.transport.config import TransportConfig
from easy_sandbox.utils.logging import get_logger

logger = get_logger("transport.ws")

# Lightweight alias — a lost connection is still a ConnectionError_.
ConnectionLostError = ConnectionError_

try:
    import websockets
    import websockets.client

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


class WebSocketClient:
    """Async WebSocket client with native heartbeat.

    Used for PTY terminal connections and other bidirectional channels.
    Auto-reconnect has been intentionally removed: a WebSocket disconnection
    usually signals that the sandbox has been terminated, so reconnection
    decisions belong to the higher-level caller.
    """

    def __init__(
        self,
        url: str,
        *,
        config: TransportConfig,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not HAS_WEBSOCKETS:
            raise ImportError("websockets package is required: pip install websockets")

        self._url = url
        self._config = config
        self._extra_headers = extra_headers or {}
        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._connected = False
        self._closed = False

    async def connect(self) -> None:
        """Establish WebSocket connection.

        Heartbeat is delegated to the websockets library's built-in
        ``ping_interval`` / ``ping_timeout`` parameters.
        """
        try:
            self._ws = await websockets.client.connect(
                self._url,
                additional_headers=self._extra_headers,
                ping_interval=self._config.ws_ping_interval,
                ping_timeout=self._config.ws_ping_interval * 2,
                close_timeout=10,
            )
            self._connected = True
            self._closed = False
            logger.debug("WebSocket connected to %s", self._url)
        except Exception as exc:
            raise ConnectionError_(
                f"Failed to establish WebSocket connection: {exc}",
                suggestion="Check WebSocket URL and network connectivity.",
            ) from exc

    async def send(self, data: str | bytes) -> None:
        """Send a message over the WebSocket."""
        if not self._connected or self._ws is None:
            raise ConnectionLostError("WebSocket is not connected")
        try:
            await self._ws.send(data)
        except Exception as exc:
            self._connected = False
            raise ConnectionLostError(f"Failed to send WebSocket message: {exc}") from exc

    async def receive(self, timeout: float | None = None) -> str | bytes:
        """Receive the next message from the WebSocket.

        Args:
            timeout: Max seconds to wait. None = wait forever.

        Returns:
            The received message.

        Raises:
            ConnectionLostError: If connection is lost while waiting.
            asyncio.TimeoutError: If timeout expires.
        """
        if not self._connected or self._ws is None:
            raise ConnectionLostError("WebSocket is not connected")
        try:
            return await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            self._connected = False
            raise ConnectionLostError(f"WebSocket receive error: {exc}") from exc

    async def recv_iter(self) -> AsyncIterator[str | bytes]:
        """Iterate over received messages until the connection closes."""
        if self._ws is None:
            raise ConnectionLostError("WebSocket is not connected")
        try:
            async for message in self._ws:
                if self._closed:
                    break
                yield message
        except Exception as exc:
            if not self._closed:
                self._connected = False
                raise ConnectionLostError(f"WebSocket connection lost: {exc}") from exc

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._closed = True
        self._connected = False

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.debug("WebSocket closed")

    async def __aenter__(self) -> WebSocketClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
