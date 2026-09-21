"""Tests for easy_sandbox.server.routes_pty — PTY WebSocket terminal system.

REST tests follow the same pattern as test_app.py (_find_free_port, _start_server,
_request).  WebSocket tests use ``websockets.connect`` async client.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import platform
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

# PTY is Unix-only.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="PTY not supported on Windows"
)

# Import triggers route registration side-effect.
import easy_sandbox.server.routes_pty  # noqa: F401

from easy_sandbox.server.app import SandboxRequestHandler
from easy_sandbox.server.registry import CommandRegistry
from easy_sandbox.server.router import CapabilityGroup, RouteTable, default_table
from easy_sandbox.server.routes_pty import (
    PtySession,
    PtySessionManager,
    pty_session_manager,
    start_pty_server,
)


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_app.py)
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign one."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(
    port: int,
    *,
    auth_token: str | None = None,
    registry: CommandRegistry | None = None,
) -> ThreadingHTTPServer:
    """Create and start a server on *port* in a daemon thread."""
    if registry is None:
        registry = CommandRegistry()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), SandboxRequestHandler)
    httpd.auth_token = auth_token  # type: ignore[attr-defined]
    httpd.registry = registry  # type: ignore[attr-defined]
    # Use the default route table which has PTY routes registered.
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    return httpd


def _request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Send an HTTP request and return ``(status, json_body)``."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    payload = json.dumps(body).encode() if body is not None else None
    hdrs: dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    conn.request(method, path, body=payload, headers=hdrs)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    status = resp.status
    conn.close()
    return status, data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_groups() -> Any:
    """Ensure TERMINAL group is enabled and reset after each test."""
    table = default_table()
    table.enable_group(CapabilityGroup.TERMINAL)
    yield
    table.enable_group(CapabilityGroup.TERMINAL)


@pytest.fixture(autouse=True)
def _clean_sessions() -> Any:
    """Close all PTY sessions before and after each test."""
    pty_session_manager.close_all()
    yield
    pty_session_manager.close_all()


@pytest.fixture()
def server_port() -> Any:
    """Spin up a no-auth server on a random port and tear it down after."""
    port = _find_free_port()
    httpd = _start_server(port)
    yield port
    httpd.shutdown()


# ---------------------------------------------------------------------------
# PtySession unit tests
# ---------------------------------------------------------------------------


class TestPtySession:
    """Direct tests for PtySession."""

    def test_create_session(self) -> None:
        session = PtySession(shell="/bin/sh", cols=80, rows=24)
        try:
            assert session.is_alive
            assert session.pid > 0
            assert session.cols == 80
            assert session.rows == 24
            assert len(session.id) == 12
        finally:
            session.close()

    def test_write_and_read(self) -> None:
        session = PtySession(shell="/bin/sh")
        try:
            # Wait for shell to start.
            time.sleep(0.3)
            # Drain initial output (prompt, etc.).
            session.read(timeout=0.2)

            session.write(b"echo PTY_TEST_OUTPUT\n")
            time.sleep(0.3)
            output = session.read(timeout=0.5)
            assert b"PTY_TEST_OUTPUT" in output
        finally:
            session.close()

    def test_resize(self) -> None:
        session = PtySession()
        try:
            session.resize(120, 40)
            assert session.cols == 120
            assert session.rows == 40
        finally:
            session.close()

    def test_close_terminates_process(self) -> None:
        session = PtySession()
        pid = session.pid
        assert session.is_alive
        session.close()
        assert not session.is_alive

    def test_to_dict(self) -> None:
        session = PtySession()
        try:
            d = session.to_dict()
            assert "id" in d
            assert "pid" in d
            assert "created_at" in d
            assert "cols" in d
            assert "rows" in d
            assert "alive" in d
            assert d["alive"] is True
        finally:
            session.close()

    def test_send_signal(self) -> None:
        import signal

        session = PtySession()
        try:
            assert session.is_alive
            session.send_signal(signal.SIGTERM)
            time.sleep(0.5)
            # Process may or may not have exited depending on shell behaviour.
        finally:
            session.close()


# ---------------------------------------------------------------------------
# PtySessionManager unit tests
# ---------------------------------------------------------------------------


class TestPtySessionManager:
    """Direct tests for PtySessionManager."""

    def test_create_and_get(self) -> None:
        mgr = PtySessionManager()
        try:
            session = mgr.create(shell="/bin/sh")
            assert mgr.get(session.id) is session
        finally:
            mgr.close_all()

    def test_list_sessions(self) -> None:
        mgr = PtySessionManager()
        try:
            mgr.create(shell="/bin/sh")
            mgr.create(shell="/bin/sh")
            sessions = mgr.list_sessions()
            assert len(sessions) == 2
        finally:
            mgr.close_all()

    def test_close_session(self) -> None:
        mgr = PtySessionManager()
        try:
            session = mgr.create(shell="/bin/sh")
            sid = session.id
            assert mgr.close(sid) is True
            assert mgr.get(sid) is None
            assert mgr.close(sid) is False  # already gone
        finally:
            mgr.close_all()

    def test_session_limit(self) -> None:
        mgr = PtySessionManager()
        mgr.MAX_SESSIONS = 3
        try:
            mgr.create(shell="/bin/sh")
            mgr.create(shell="/bin/sh")
            mgr.create(shell="/bin/sh")
            with pytest.raises(RuntimeError, match="Session limit"):
                mgr.create(shell="/bin/sh")
        finally:
            mgr.close_all()

    def test_close_all(self) -> None:
        mgr = PtySessionManager()
        try:
            mgr.create(shell="/bin/sh")
            mgr.create(shell="/bin/sh")
            mgr.close_all()
            assert mgr.list_sessions() == []
        finally:
            mgr.close_all()

    def test_cleanup_idle(self) -> None:
        mgr = PtySessionManager()
        mgr.IDLE_TIMEOUT = 0  # expire immediately
        try:
            mgr.create(shell="/bin/sh")
            time.sleep(0.1)
            cleaned = mgr.cleanup_idle()
            assert cleaned == 1
            assert mgr.list_sessions() == []
        finally:
            mgr.close_all()


# ---------------------------------------------------------------------------
# REST API tests
# ---------------------------------------------------------------------------


class TestPtyRestApi:
    """REST API for PTY session management."""

    def test_create_session(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/pty/sessions",
            body={"shell": "/bin/sh", "cols": 100, "rows": 30},
        )
        assert status == 200
        assert "session_id" in body
        assert "ws_url" in body
        assert "pid" in body
        assert body["pid"] > 0

    def test_create_session_defaults(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/pty/sessions", body={}
        )
        assert status == 200
        assert "session_id" in body

    def test_list_sessions(self, server_port: int) -> None:
        # Create two sessions.
        _request(server_port, "POST", "/pty/sessions", body={"shell": "/bin/sh"})
        _request(server_port, "POST", "/pty/sessions", body={"shell": "/bin/sh"})

        status, body = _request(server_port, "GET", "/pty/sessions")
        assert status == 200
        assert len(body["sessions"]) == 2

    def test_delete_session(self, server_port: int) -> None:
        _, create_body = _request(
            server_port, "POST", "/pty/sessions", body={"shell": "/bin/sh"}
        )
        sid = create_body["session_id"]

        status, body = _request(
            server_port, "DELETE", f"/pty/sessions/{sid}"
        )
        assert status == 200
        assert body["status"] == "closed"

        # Verify it's gone.
        status, body = _request(server_port, "GET", "/pty/sessions")
        assert status == 200
        assert all(s["id"] != sid for s in body["sessions"])

    def test_delete_nonexistent_session(self, server_port: int) -> None:
        status, body = _request(
            server_port, "DELETE", "/pty/sessions/nonexistent"
        )
        assert status == 404

    def test_session_limit_429(self, server_port: int) -> None:
        """Exceeding MAX_SESSIONS returns 429."""
        original = pty_session_manager.MAX_SESSIONS
        pty_session_manager.MAX_SESSIONS = 2
        try:
            _request(server_port, "POST", "/pty/sessions", body={"shell": "/bin/sh"})
            _request(server_port, "POST", "/pty/sessions", body={"shell": "/bin/sh"})
            status, body = _request(
                server_port, "POST", "/pty/sessions", body={"shell": "/bin/sh"}
            )
            assert status == 429
            assert "Session limit" in body["error"]
        finally:
            pty_session_manager.MAX_SESSIONS = original

    def test_terminal_group_disabled(self, server_port: int) -> None:
        """When TERMINAL group is disabled, PTY routes return 404."""
        table = default_table()
        table.disable_group(CapabilityGroup.TERMINAL)
        try:
            status, body = _request(
                server_port, "POST", "/pty/sessions", body={}
            )
            assert status == 404
        finally:
            table.enable_group(CapabilityGroup.TERMINAL)


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------


class TestPtyWebSocket:
    """WebSocket interactive PTY tests."""

    @pytest.fixture()
    def ws_port(self) -> Any:
        """Start a PTY WebSocket server on a random port."""
        port = _find_free_port()
        loop: asyncio.AbstractEventLoop | None = None
        ready = threading.Event()
        # We'll create the asyncio.Event *inside* the loop.
        stop_holder: list[asyncio.Event] = []

        def _run() -> None:
            nonlocal loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            stop = asyncio.Event()
            stop_holder.append(stop)
            loop.run_until_complete(
                start_pty_server("127.0.0.1", port, stop_event=stop, ready_event=ready)
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        ready.wait(timeout=5)  # wait for WS server to be listening
        yield port
        if loop is not None and stop_holder:
            loop.call_soon_threadsafe(stop_holder[0].set)
        t.join(timeout=3)

    @pytest.mark.asyncio
    async def test_connect_and_receive_started_event(self, ws_port: int) -> None:
        import websockets

        # Create a session first.
        session = pty_session_manager.create(shell="/bin/sh")
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{ws_port}/pty?session_id={session.id}",
                open_timeout=5,
            ) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                assert msg["type"] == "event"
                assert msg["event"] == "started"
                assert msg["session_id"] == session.id
        finally:
            pty_session_manager.close(session.id)

    @pytest.mark.asyncio
    async def test_input_output(self, ws_port: int) -> None:
        import websockets

        session = pty_session_manager.create(shell="/bin/sh")
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{ws_port}/pty?session_id={session.id}",
                open_timeout=5,
            ) as ws:
                # Read the started event.
                await asyncio.wait_for(ws.recv(), timeout=5)

                # Drain any initial prompt output.
                try:
                    while True:
                        await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

                # Send a command.
                await ws.send(json.dumps({
                    "type": "input",
                    "data": "echo WS_PTY_MARKER\n",
                }))

                # Collect output until we see the marker.
                collected = ""
                for _ in range(30):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        msg = json.loads(raw)
                        if msg["type"] == "output":
                            collected += msg["data"]
                            if "WS_PTY_MARKER" in collected:
                                break
                    except asyncio.TimeoutError:
                        break

                assert "WS_PTY_MARKER" in collected
        finally:
            pty_session_manager.close(session.id)

    @pytest.mark.asyncio
    async def test_resize(self, ws_port: int) -> None:
        import websockets

        session = pty_session_manager.create(shell="/bin/sh")
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{ws_port}/pty?session_id={session.id}",
                open_timeout=5,
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=5)

                await ws.send(json.dumps({
                    "type": "resize",
                    "cols": 200,
                    "rows": 50,
                }))
                # Give it a moment to process.
                await asyncio.sleep(0.2)

                assert session.cols == 200
                assert session.rows == 50
        finally:
            pty_session_manager.close(session.id)

    @pytest.mark.asyncio
    async def test_missing_session_id(self, ws_port: int) -> None:
        import websockets

        with pytest.raises(websockets.exceptions.ConnectionClosed):
            async with websockets.connect(
                f"ws://127.0.0.1:{ws_port}/pty",
                open_timeout=5,
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=5)

    @pytest.mark.asyncio
    async def test_unknown_session_id(self, ws_port: int) -> None:
        import websockets

        with pytest.raises(websockets.exceptions.ConnectionClosed):
            async with websockets.connect(
                f"ws://127.0.0.1:{ws_port}/pty?session_id=nonexistent",
                open_timeout=5,
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=5)
