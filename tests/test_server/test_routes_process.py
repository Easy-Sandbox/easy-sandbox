"""Tests for serverless_sandbox.server.routes_process — process management endpoints.

Spins up a real server per fixture on a random free port, same pattern as test_app.py.
"""

from __future__ import annotations

import http.client
import json
import socket
import subprocess as _sp  # noqa: S404
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

import serverless_sandbox.server.routes_process as _rp  # noqa: F401
from serverless_sandbox.server.app import SandboxRequestHandler
from serverless_sandbox.server.registry import CommandRegistry
from serverless_sandbox.server.router import CapabilityGroup, default_table
from serverless_sandbox.server.routes_process import (
    _MAX_PROCESSES,
    _process_table,
    _ProcessInfo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int) -> ThreadingHTTPServer:
    registry = CommandRegistry()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), SandboxRequestHandler)
    httpd.auth_token = None  # type: ignore[attr-defined]
    httpd.registry = registry  # type: ignore[attr-defined]
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


def _request_raw(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, str]:
    """Send an HTTP request and return ``(status, raw_body_text)``."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    payload = json.dumps(body).encode() if body is not None else None
    hdrs: dict[str, str] = {"Content-Type": "application/json"}
    conn.request(method, path, body=payload, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read().decode("utf-8", errors="replace")
    status = resp.status
    conn.close()
    return status, raw


def _parse_sse_events(raw: str) -> list[dict[str, Any]]:
    """Parse raw SSE text into a list of ``{event, data}`` dicts."""
    events: list[dict[str, Any]] = []
    current_event: str | None = None
    current_data: str | None = None
    for line in raw.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            current_data = line[len("data: "):]
        elif line == "" and current_event is not None and current_data is not None:
            events.append({"event": current_event, "data": json.loads(current_data)})
            current_event = None
            current_data = None
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_groups() -> Any:
    """Reset capability groups before/after each test."""
    def _reset() -> None:
        table = default_table()
        for group in CapabilityGroup:
            if group == CapabilityGroup.CORE:
                continue
            if group == CapabilityGroup.DEV_TOOLS:
                table.disable_group(group)
            else:
                table.enable_group(group)

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _clean_process_table() -> Any:
    """Clear the module-level process table before and after each test."""
    _process_table.clear()
    yield
    # Cleanup: kill any lingering test processes.
    for info in list(_process_table.values()):
        try:
            info.popen.kill()
            info.popen.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
    _process_table.clear()


@pytest.fixture()
def server_port() -> Any:
    port = _find_free_port()
    httpd = _start_server(port)
    yield port
    httpd.shutdown()


# ---------------------------------------------------------------------------
# POST /shell/stream
# ---------------------------------------------------------------------------


class TestShellStream:
    """POST /shell/stream — SSE streaming shell execution."""

    def test_echo_stream(self, server_port: int) -> None:
        status, raw = _request_raw(
            server_port, "POST", "/shell/stream", body={"command": "echo hello"}
        )
        assert status == 200
        events = _parse_sse_events(raw)
        event_types = [e["event"] for e in events]
        assert "stdout" in event_types
        assert "exit" in event_types
        # Verify stdout content
        stdout_events = [e for e in events if e["event"] == "stdout"]
        assert any("hello" in e["data"]["data"] for e in stdout_events)
        # Verify exit code
        exit_events = [e for e in events if e["event"] == "exit"]
        assert exit_events[-1]["data"]["exit_code"] == 0

    def test_stderr_stream(self, server_port: int) -> None:
        status, raw = _request_raw(
            server_port,
            "POST",
            "/shell/stream",
            body={"command": f"{sys.executable} -c \"import sys; sys.stderr.write('err\\n')\""},
        )
        assert status == 200
        events = _parse_sse_events(raw)
        stderr_events = [e for e in events if e["event"] == "stderr"]
        assert len(stderr_events) >= 1
        assert any("err" in e["data"]["data"] for e in stderr_events)

    def test_nonzero_exit(self, server_port: int) -> None:
        status, raw = _request_raw(
            server_port,
            "POST",
            "/shell/stream",
            body={"command": f"{sys.executable} -c \"raise SystemExit(42)\""},
        )
        assert status == 200
        events = _parse_sse_events(raw)
        exit_events = [e for e in events if e["event"] == "exit"]
        assert exit_events[-1]["data"]["exit_code"] == 42

    def test_missing_command(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/shell/stream", body={}
        )
        assert status == 400
        assert body["type"] == "ValueError"

    def test_multiline_output(self, server_port: int) -> None:
        cmd = f'{sys.executable} -c "print(\'line1\'); print(\'line2\')"'
        status, raw = _request_raw(
            server_port, "POST", "/shell/stream", body={"command": cmd}
        )
        assert status == 200
        events = _parse_sse_events(raw)
        stdout_events = [e for e in events if e["event"] == "stdout"]
        assert len(stdout_events) >= 2


# ---------------------------------------------------------------------------
# POST /process/start
# ---------------------------------------------------------------------------


class TestProcessStart:
    """POST /process/start — background process launch."""

    def test_start_process(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(30)\""},
        )
        assert status == 200
        assert "pid" in body
        assert body["command"] is not None
        assert isinstance(body["pid"], int)

    def test_missing_command(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/process/start", body={}
        )
        assert status == 400
        assert body["type"] == "ValueError"

    def test_process_limit(self, server_port: int) -> None:
        """When _process_table is full, new starts are refused."""
        # Fill the table with dummy entries.
        for i in range(_MAX_PROCESSES):
            dummy = _sp.Popen(  # noqa: S603
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=_sp.PIPE,
                stderr=_sp.PIPE,
            )
            _process_table[100000 + i] = _ProcessInfo(
                pid=100000 + i,
                popen=dummy,
                command="sleep",
                started_at=time.time(),
            )

        status, body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": "echo overflow"},
        )
        assert status == 429
        assert "limit" in body["error"].lower()

        # Cleanup dummies
        for info in list(_process_table.values()):
            try:
                info.popen.kill()
                info.popen.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        _process_table.clear()


# ---------------------------------------------------------------------------
# GET /process/list
# ---------------------------------------------------------------------------


class TestProcessList:
    """GET /process/list — list managed processes."""

    def test_empty_list(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/process/list")
        assert status == 200
        assert body["processes"] == []

    def test_list_after_start(self, server_port: int) -> None:
        # Start a long-running process.
        _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(30)\""},
        )
        status, body = _request(server_port, "GET", "/process/list")
        assert status == 200
        assert len(body["processes"]) == 1
        proc = body["processes"][0]
        assert "pid" in proc
        assert proc["state"] == "running"
        assert "started_at" in proc


# ---------------------------------------------------------------------------
# GET /process/{pid}
# ---------------------------------------------------------------------------


class TestProcessDetail:
    """GET /process/{pid} — single process info."""

    def test_running_process(self, server_port: int) -> None:
        st, start_body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(30)\""},
        )
        pid = start_body["pid"]
        status, body = _request(server_port, "GET", f"/process/{pid}")
        assert status == 200
        assert body["pid"] == pid
        assert body["state"] == "running"
        assert body["exit_code"] is None

    def test_exited_process(self, server_port: int) -> None:
        st, start_body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"print('done')\""},
        )
        pid = start_body["pid"]
        # Wait for the process to exit.
        time.sleep(0.5)
        status, body = _request(server_port, "GET", f"/process/{pid}")
        assert status == 200
        assert body["state"] == "exited"
        assert body["exit_code"] == 0

    def test_not_found(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/process/999999")
        assert status == 404
        assert "not found" in body["error"].lower()

    def test_invalid_pid(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/process/abc")
        assert status == 400
        assert body["type"] == "ValueError"


# ---------------------------------------------------------------------------
# POST /process/{pid}/signal
# ---------------------------------------------------------------------------


class TestProcessSignal:
    """POST /process/{pid}/signal — send signals to managed processes."""

    def test_sigterm(self, server_port: int) -> None:
        st, start_body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(60)\""},
        )
        pid = start_body["pid"]
        status, body = _request(
            server_port,
            "POST",
            f"/process/{pid}/signal",
            body={"signal": 15},
        )
        assert status == 200
        assert body["pid"] == pid
        assert body["signal"] == 15

    def test_disallowed_signal(self, server_port: int) -> None:
        st, start_body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(60)\""},
        )
        pid = start_body["pid"]
        status, body = _request(
            server_port,
            "POST",
            f"/process/{pid}/signal",
            body={"signal": 31},
        )
        assert status == 400
        assert "not allowed" in body["error"].lower()

    def test_missing_signal_field(self, server_port: int) -> None:
        st, start_body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(60)\""},
        )
        pid = start_body["pid"]
        status, body = _request(
            server_port,
            "POST",
            f"/process/{pid}/signal",
            body={},
        )
        assert status == 400

    def test_signal_unknown_pid(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/process/999999/signal",
            body={"signal": 15},
        )
        assert status == 404

    def test_refuse_kill_pid_1(self, server_port: int) -> None:
        """Must refuse to signal PID 1."""
        # We need pid 1 in the table for the route to find it, but the
        # safety check should fire before os.kill.
        # Create a real process to hold the slot.
        dummy = _sp.Popen(  # noqa: S603
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
        )
        _process_table[1] = _ProcessInfo(
            pid=1, popen=dummy, command="init", started_at=time.time(),
        )
        status, body = _request(
            server_port,
            "POST",
            "/process/1/signal",
            body={"signal": 15},
        )
        assert status == 403
        dummy.kill()
        dummy.wait(timeout=2)

    def test_refuse_kill_self(self, server_port: int) -> None:
        """Must refuse to signal own PID."""
        import os as _os

        my_pid = _os.getpid()
        dummy = _sp.Popen(  # noqa: S603
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
        )
        _process_table[my_pid] = _ProcessInfo(
            pid=my_pid, popen=dummy, command="self", started_at=time.time(),
        )
        status, body = _request(
            server_port,
            "POST",
            f"/process/{my_pid}/signal",
            body={"signal": 15},
        )
        assert status == 403
        dummy.kill()
        dummy.wait(timeout=2)

    def test_sigkill(self, server_port: int) -> None:
        st, start_body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(60)\""},
        )
        pid = start_body["pid"]
        status, body = _request(
            server_port,
            "POST",
            f"/process/{pid}/signal",
            body={"signal": 9},
        )
        assert status == 200
        assert body["signal"] == 9


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestProcessLifecycle:
    """Integration test: start → list → detail → signal → verify exit."""

    def test_full_lifecycle(self, server_port: int) -> None:
        # Start
        st, start_body = _request(
            server_port,
            "POST",
            "/process/start",
            body={"command": f"{sys.executable} -c \"import time; time.sleep(60)\""},
        )
        assert st == 200
        pid = start_body["pid"]

        # List
        st, list_body = _request(server_port, "GET", "/process/list")
        assert st == 200
        pids = [p["pid"] for p in list_body["processes"]]
        assert pid in pids

        # Detail — running
        st, detail = _request(server_port, "GET", f"/process/{pid}")
        assert st == 200
        assert detail["state"] == "running"

        # Signal SIGTERM
        st, sig_body = _request(
            server_port,
            "POST",
            f"/process/{pid}/signal",
            body={"signal": 15},
        )
        assert st == 200

        # Wait and verify exited
        time.sleep(0.5)
        st, detail = _request(server_port, "GET", f"/process/{pid}")
        assert st == 200
        assert detail["state"] == "exited"
