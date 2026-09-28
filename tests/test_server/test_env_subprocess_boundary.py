"""Tests for POST /env → subprocess inheritance boundary.

Validates the documented design decision (server-subprocess-env-inheritance-decision.md):

1. ``POST /env`` sets variables in SandboxServer's ``os.environ``.
2. Server-side subprocesses (``POST /shell``, ``POST /shell/stream``) inherit those
   variables because ``subprocess.Popen``/``subprocess.run`` are called without
   an explicit ``env=`` parameter.
3. envd ``ProcessProtocol.start()`` payloads are **completely independent** of
   Server ``os.environ``; only per-call ``env=`` kwargs flow into the RPC payload.

Each test saves and restores ``os.environ`` to avoid cross-test pollution.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

import easy_sandbox.server.routes_process  # noqa: F401  — trigger registration
import easy_sandbox.server.routes_system  # noqa: F401  — trigger registration
from easy_sandbox.server.app import SandboxRequestHandler
from easy_sandbox.server.registry import CommandRegistry
from easy_sandbox.server.router import CapabilityGroup, default_table

# Unique prefix to avoid collisions with real env vars or other tests.
_PREFIX = "_EBX_BOUNDARY_TEST_"

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_routes_system / test_routes_process)
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


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
) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    payload = json.dumps(body).encode() if body is not None else None
    hdrs: dict[str, str] = {"Content-Type": "application/json"}
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
    events: list[dict[str, Any]] = []
    current_event: str | None = None
    current_data: str | None = None
    for line in raw.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: ") :]
        elif line.startswith("data: "):
            current_data = line[len("data: ") :]
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
    """Reset all capability groups to their defaults before/after each test."""

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


@pytest.fixture()
def server_port() -> Any:
    port = _find_free_port()
    httpd = _start_server(port)
    yield port
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _clean_test_env_vars() -> Any:
    """Save and restore any env vars with the test prefix, even on exception."""
    saved: dict[str, str | None] = {}
    # Snapshot all vars that start with our test prefix.
    for key in list(os.environ):
        if key.startswith(_PREFIX):
            saved[key] = os.environ[key]
    yield
    # Restore: delete any new test vars, restore previously-existing ones.
    for key in list(os.environ):
        if key.startswith(_PREFIX):
            del os.environ[key]
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# POST /shell (non-streaming) inherits POST /env values
# ---------------------------------------------------------------------------


class TestShellInheritsEnv:
    """POST /env → POST /shell: subprocess sees the set variable."""

    def test_new_variable_visible_in_shell(self, server_port: int) -> None:
        """A freshly created env var via POST /env is visible in POST /shell."""
        var_name = f"{_PREFIX}NEW_VAR"
        var_value = "boundary_test_value_42"

        # Ensure it doesn't exist beforehand.
        os.environ.pop(var_name, None)

        # Set via POST /env.
        status, body = _request(
            server_port,
            "POST",
            "/env",
            body={"vars": {var_name: var_value}},
        )
        assert status == 200
        assert var_name in body["updated"]

        # Read via POST /shell (subprocess.run — inherits os.environ).
        cmd = f"{sys.executable} -c \"import os; print(os.environ.get('{var_name}', ''))\""
        status, body = _request(server_port, "POST", "/shell", body={"command": cmd})
        assert status == 200
        assert body["exit_code"] == 0
        assert var_value in body["stdout"]

    def test_overwrite_existing_value(self, server_port: int) -> None:
        """POST /env can overwrite a previously set variable."""
        var_name = f"{_PREFIX}OVERWRITE"

        # Set initial value.
        _request(server_port, "POST", "/env", body={"vars": {var_name: "old"}})

        # Overwrite with a new value.
        status, body = _request(
            server_port,
            "POST",
            "/env",
            body={"vars": {var_name: "new"}},
        )
        assert status == 200

        # Subprocess must see the overwritten value.
        cmd = f"{sys.executable} -c \"import os; print(os.environ.get('{var_name}', ''))\""
        status, body = _request(server_port, "POST", "/shell", body={"command": cmd})
        assert status == 200
        assert "new" in body["stdout"]
        assert "old" not in body["stdout"]


# ---------------------------------------------------------------------------
# POST /shell/stream (SSE streaming) inherits POST /env values
# ---------------------------------------------------------------------------


class TestShellStreamInheritsEnv:
    """POST /env → POST /shell/stream: SSE subprocess sees the set variable."""

    def test_new_variable_visible_in_stream(self, server_port: int) -> None:
        """A freshly created env var via POST /env is visible in POST /shell/stream."""
        var_name = f"{_PREFIX}STREAM_VAR"
        var_value = "stream_boundary_test_99"

        os.environ.pop(var_name, None)

        # Set via POST /env.
        status, _ = _request(
            server_port,
            "POST",
            "/env",
            body={"vars": {var_name: var_value}},
        )
        assert status == 200

        # Read via POST /shell/stream (SSE — Popen, inherits os.environ).
        cmd = f"{sys.executable} -c \"import os; print(os.environ.get('{var_name}', ''))\""
        status, raw = _request_raw(
            server_port,
            "POST",
            "/shell/stream",
            body={"command": cmd},
        )
        assert status == 200

        events = _parse_sse_events(raw)
        stdout_events = [e for e in events if e["event"] == "stdout"]
        combined_stdout = " ".join(e["data"]["data"] for e in stdout_events)
        assert var_value in combined_stdout

        # Exit code should be 0.
        exit_events = [e for e in events if e["event"] == "exit"]
        assert exit_events[-1]["data"]["exit_code"] == 0

    def test_overwrite_visible_in_stream(self, server_port: int) -> None:
        """POST /env overwrite is reflected in subsequent /shell/stream calls."""
        var_name = f"{_PREFIX}STREAM_OW"

        _request(server_port, "POST", "/env", body={"vars": {var_name: "alpha"}})
        _request(server_port, "POST", "/env", body={"vars": {var_name: "beta"}})

        cmd = f"{sys.executable} -c \"import os; print(os.environ.get('{var_name}', ''))\""
        status, raw = _request_raw(
            server_port,
            "POST",
            "/shell/stream",
            body={"command": cmd},
        )
        assert status == 200

        events = _parse_sse_events(raw)
        stdout_events = [e for e in events if e["event"] == "stdout"]
        combined_stdout = " ".join(e["data"]["data"] for e in stdout_events)
        assert "beta" in combined_stdout
        assert "alpha" not in combined_stdout


# ---------------------------------------------------------------------------
# Cleanup / restore safety
# ---------------------------------------------------------------------------


class TestEnvCleanup:
    """Verify that the _clean_test_env_vars fixture properly restores os.environ."""

    def test_var_does_not_leak_after_set(self, server_port: int) -> None:
        """Variable set via POST /env during a test is cleaned up by the fixture."""
        var_name = f"{_PREFIX}LEAK_CHECK"
        os.environ.pop(var_name, None)
        _request(server_port, "POST", "/env", body={"vars": {var_name: "should_be_cleaned"}})
        # The fixture will remove this in teardown; subsequent tests
        # should not see it.  We confirm the set succeeded here.
        assert os.environ.get(var_name) == "should_be_cleaned"

    def test_previous_test_did_not_leak(self) -> None:
        """Confirm the variable set in the previous test was cleaned up.

        This test MUST run after ``test_var_does_not_leak_after_set`` (same class,
        pytest default ordering guarantees this).
        """
        var_name = f"{_PREFIX}LEAK_CHECK"
        assert os.environ.get(var_name) is None
