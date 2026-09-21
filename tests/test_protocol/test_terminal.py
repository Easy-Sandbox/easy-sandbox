"""Tests for protocol.terminal module — PTY WebSocket terminal."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from easy_sandbox.protocol.terminal import TerminalSession
from easy_sandbox.transport.auth import EnvdTokenManager
from easy_sandbox.transport.config import TransportConfig


@pytest.fixture
def mock_ws():
    """Create a mock WebSocketClient."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.receive = AsyncMock(return_value="output data")
    ws.close = AsyncMock()
    ws.connect = AsyncMock()
    type(ws).is_connected = PropertyMock(return_value=True)
    return ws


class TestTerminalSession:
    """Test TerminalSession construction and basic ops."""

    def test_init(self, mock_ws):
        session = TerminalSession(mock_ws)
        assert session._ws is mock_ws

    async def test_send(self, mock_ws):
        session = TerminalSession(mock_ws)
        await session.send("ls\n")
        mock_ws.send.assert_awaited_once_with("ls\n")

    async def test_send_bytes(self, mock_ws):
        session = TerminalSession(mock_ws)
        await session.send_bytes(b"\x03")
        mock_ws.send.assert_awaited_once_with(b"\x03")

    async def test_receive(self, mock_ws):
        session = TerminalSession(mock_ws)
        result = await session.receive(timeout=5.0)
        assert result == "output data"
        mock_ws.receive.assert_awaited_once_with(timeout=5.0)

    async def test_resize_sends_json(self, mock_ws):
        session = TerminalSession(mock_ws)
        await session.resize(120, 40)

        mock_ws.send.assert_awaited_once()
        sent = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed == {"type": "resize", "cols": 120, "rows": 40}

    async def test_close(self, mock_ws):
        session = TerminalSession(mock_ws)
        await session.close()
        mock_ws.close.assert_awaited_once()

    def test_is_connected(self, mock_ws):
        session = TerminalSession(mock_ws)
        assert session.is_connected is True

    async def test_context_manager(self, mock_ws):
        async with TerminalSession(mock_ws) as session:
            await session.send("test")
        mock_ws.close.assert_awaited_once()


class TestTerminalURLConversion:
    """Test URL conversion logic in TerminalSession.create()."""

    async def test_https_to_wss(self):
        """Verify that HTTPS envd_url is converted to WSS."""
        envd_url = "https://envd-sbx-123.example.com"
        envd_token = EnvdTokenManager("tok-123")
        config = TransportConfig(http2=False)

        # Patch WebSocketClient to capture URL
        captured_args: dict = {}

        import easy_sandbox.protocol.terminal as term_mod
        original_ws_class = term_mod.WebSocketClient

        class FakeWS:
            def __init__(self, url, *, config, extra_headers=None):
                captured_args["url"] = url
                captured_args["headers"] = extra_headers
                self._connected = True
                self.is_connected = True

            async def connect(self):
                pass

            async def send(self, data):
                pass

            async def close(self):
                pass

        term_mod.WebSocketClient = FakeWS  # type: ignore
        try:
            session = await TerminalSession.create(envd_url, envd_token, config, cols=80, rows=24)
            assert captured_args["url"] == "wss://envd-sbx-123.example.com/terminal"
            assert "X-Access-Token" in captured_args["headers"]
            assert captured_args["headers"]["X-Access-Token"] == "tok-123"
        finally:
            term_mod.WebSocketClient = original_ws_class  # type: ignore

    async def test_http_to_ws(self):
        """Verify that HTTP envd_url is converted to WS."""
        envd_url = "http://localhost:3000"
        envd_token = EnvdTokenManager("tok-local")
        config = TransportConfig(http2=False)

        captured_args: dict = {}

        import easy_sandbox.protocol.terminal as term_mod
        original_ws_class = term_mod.WebSocketClient

        class FakeWS:
            def __init__(self, url, *, config, extra_headers=None):
                captured_args["url"] = url

            async def connect(self):
                pass

            async def send(self, data):
                pass

            async def close(self):
                pass

        term_mod.WebSocketClient = FakeWS  # type: ignore
        try:
            await TerminalSession.create(envd_url, envd_token, config)
            assert captured_args["url"] == "ws://localhost:3000/terminal"
        finally:
            term_mod.WebSocketClient = original_ws_class  # type: ignore
