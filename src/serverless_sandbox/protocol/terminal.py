"""PTY terminal protocol — WebSocket bidirectional channel.

Provides interactive terminal access to sandboxes via WebSocket.
Supports terminal resize, input/output streaming.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from serverless_sandbox.transport.auth import EnvdTokenManager
from serverless_sandbox.transport.config import TransportConfig
from serverless_sandbox.transport.ws import WebSocketClient
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("protocol.terminal")


class TerminalSession:
    """Interactive PTY terminal session over WebSocket.

    Provides bidirectional communication with a pseudo-terminal
    in the sandbox.
    """

    def __init__(
        self,
        ws_client: WebSocketClient,
    ) -> None:
        self._ws = ws_client

    @classmethod
    async def create(
        cls,
        envd_url: str,
        envd_token: EnvdTokenManager,
        config: TransportConfig,
        *,
        cols: int = 80,
        rows: int = 24,
        shell: str = "/bin/bash",
    ) -> TerminalSession:
        """Create a new terminal session.

        Establishes WebSocket connection to the sandbox PTY endpoint.
        """
        # Convert HTTP URL to WebSocket URL
        ws_url = envd_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/terminal"

        headers = {
            **envd_token.get_headers(),
        }

        ws_client = WebSocketClient(
            ws_url,
            config=config,
            extra_headers=headers,
        )
        await ws_client.connect()

        session = cls(ws_client)

        # Send initial resize
        await session.resize(cols, rows)

        logger.debug("Terminal session created (%dx%d, shell=%s)", cols, rows, shell)
        return session

    async def send(self, data: str) -> None:
        """Send input to the terminal."""
        await self._ws.send(data)

    async def send_bytes(self, data: bytes) -> None:
        """Send raw bytes to the terminal."""
        await self._ws.send(data)

    async def receive(self, timeout: float | None = None) -> str | bytes:
        """Receive output from the terminal."""
        return await self._ws.receive(timeout=timeout)

    async def output_stream(self) -> AsyncIterator[str | bytes]:
        """Iterate over terminal output."""
        async for msg in self._ws.recv_iter():
            yield msg

    async def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal.

        Sends a JSON control message to resize the PTY.
        """
        control_msg = json.dumps({
            "type": "resize",
            "cols": cols,
            "rows": rows,
        })
        await self._ws.send(control_msg)
        logger.debug("Terminal resized to %dx%d", cols, rows)

    @property
    def is_connected(self) -> bool:
        return self._ws.is_connected

    async def close(self) -> None:
        """Close the terminal session."""
        await self._ws.close()
        logger.debug("Terminal session closed")

    async def __aenter__(self) -> TerminalSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
