"""Tests for transport.ws module."""
from __future__ import annotations

import pytest

from easy_sandbox.transport.config import TransportConfig
from easy_sandbox.transport.ws import WebSocketClient


@pytest.fixture
def ws_config():
    return TransportConfig(
        ws_ping_interval=10.0,
    )


class TestWebSocketClient:
    """Test WebSocketClient construction and properties."""

    def test_construction(self, ws_config):
        ws = WebSocketClient("wss://example.com/ws", config=ws_config)
        assert ws._url == "wss://example.com/ws"
        assert ws._config is ws_config
        assert not ws.is_connected
        assert not ws._closed

    def test_construction_with_extra_headers(self, ws_config):
        headers = {"X-Access-Token": "my-token"}
        ws = WebSocketClient("wss://example.com/ws", config=ws_config, extra_headers=headers)
        assert ws._extra_headers == headers

    def test_is_connected_default_false(self, ws_config):
        ws = WebSocketClient("wss://example.com/ws", config=ws_config)
        assert ws.is_connected is False

    async def test_close_without_connect(self, ws_config):
        ws = WebSocketClient("wss://example.com/ws", config=ws_config)
        await ws.close()
        assert ws._closed is True
        assert ws.is_connected is False

    async def test_close_idempotent(self, ws_config):
        ws = WebSocketClient("wss://example.com/ws", config=ws_config)
        await ws.close()
        await ws.close()  # Should not raise
        assert ws._closed is True

