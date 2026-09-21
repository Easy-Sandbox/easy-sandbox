"""Tests for easy_sandbox.server.routes_system — system endpoints.

Each test spins up a real ``ThreadingHTTPServer`` on a random free port in a
background thread and uses ``http.client.HTTPConnection`` to hit it directly.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

import easy_sandbox.server.routes_system  # noqa: F401  # trigger registration
from easy_sandbox.server.app import SandboxRequestHandler
from easy_sandbox.server.registry import CommandRegistry
from easy_sandbox.server.router import CapabilityGroup, default_table

# ---------------------------------------------------------------------------
# Helpers (mirrors test_app.py)
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign one."""
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
    """Spin up a no-auth server on a random port and tear it down after."""
    port = _find_free_port()
    httpd = _start_server(port)
    yield port
    httpd.shutdown()


# ---------------------------------------------------------------------------
# GET /capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    """GET /capabilities — list all capability groups and status."""

    def test_returns_all_groups(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/capabilities")
        assert status == 200
        groups = body["groups"]
        # All 7 CapabilityGroup members must be present.
        expected = {g.value for g in CapabilityGroup}
        assert set(groups.keys()) == expected

    def test_core_always_true(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/capabilities")
        assert body["groups"]["core"] is True

    def test_disable_reflects_in_capabilities(self, server_port: int) -> None:
        table = default_table()
        table.disable_group(CapabilityGroup.COMMANDS)
        status, body = _request(server_port, "GET", "/capabilities")
        assert status == 200
        assert body["groups"]["commands"] is False

    def test_no_auth_required(self) -> None:
        """Verify /capabilities is registered with auth_required=False."""
        port = _find_free_port()
        httpd = _start_server(port, auth_token="test-placeholder-token")
        try:
            status, body = _request(port, "GET", "/capabilities")
            assert status == 200
            assert "groups" in body
        finally:
            httpd.shutdown()


# ---------------------------------------------------------------------------
# GET /system/info
# ---------------------------------------------------------------------------


class TestSystemInfo:
    """GET /system/info — OS / CPU / memory / disk / Python info."""

    def test_returns_expected_fields(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/system/info")
        assert status == 200
        for key in (
            "os", "arch", "cpu_count", "memory_total_mb",
            "memory_available_mb", "disk_total_gb", "disk_free_gb",
            "python_version", "hostname",
        ):
            assert key in body, f"Missing key: {key}"

    def test_cpu_count_positive(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/system/info")
        assert body["cpu_count"] > 0

    def test_python_version_format(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/system/info")
        # Should look like "3.x.y"
        parts = body["python_version"].split(".")
        assert len(parts) >= 2
        assert int(parts[0]) >= 3


# ---------------------------------------------------------------------------
# GET /env
# ---------------------------------------------------------------------------


class TestEnvGet:
    """GET /env — filtered environment variable listing."""

    def test_returns_variables(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/env")
        assert status == 200
        assert "variables" in body
        assert isinstance(body["variables"], dict)

    def test_filter_whitelist(self, server_port: int, monkeypatch: Any) -> None:
        monkeypatch.setenv("MY_TEST_VAR_A", "aaa")
        monkeypatch.setenv("MY_TEST_VAR_B", "bbb")
        status, body = _request(
            server_port, "GET", "/env?filter=MY_TEST_VAR_A"
        )
        assert status == 200
        assert "MY_TEST_VAR_A" in body["variables"]
        assert "MY_TEST_VAR_B" not in body["variables"]

    def test_blacklist_filters_sensitive(
        self, server_port: int, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("MY_SECRET_VALUE", "s3cret")
        monkeypatch.setenv("DB_PASSWORD_MAIN", "hunter2")
        monkeypatch.setenv("SAFE_VARIABLE", "ok")
        status, body = _request(server_port, "GET", "/env")
        assert status == 200
        assert "MY_SECRET_VALUE" not in body["variables"]
        assert "DB_PASSWORD_MAIN" not in body["variables"]
        assert "SAFE_VARIABLE" in body["variables"]

    def test_blacklist_token_key_credential(
        self, server_port: int, monkeypatch: Any
    ) -> None:
        """All blacklist tokens: TOKEN, SECRET, KEY, PASSWORD, CREDENTIAL."""
        monkeypatch.setenv("API_TOKEN_X", "t")
        monkeypatch.setenv("AUTH_KEY_ID", "k")
        monkeypatch.setenv("USER_CREDENTIAL_FILE", "c")
        status, body = _request(server_port, "GET", "/env")
        assert "API_TOKEN_X" not in body["variables"]
        assert "AUTH_KEY_ID" not in body["variables"]
        assert "USER_CREDENTIAL_FILE" not in body["variables"]


# ---------------------------------------------------------------------------
# POST /env
# ---------------------------------------------------------------------------


class TestEnvSet:
    """POST /env — set environment variables."""

    def test_set_variables(self, server_port: int, monkeypatch: Any) -> None:
        # Ensure cleanup
        monkeypatch.delenv("CUSTOM_VAR_1", raising=False)
        monkeypatch.delenv("CUSTOM_VAR_2", raising=False)
        status, body = _request(
            server_port,
            "POST",
            "/env",
            body={"vars": {"CUSTOM_VAR_1": "hello", "CUSTOM_VAR_2": "world"}},
        )
        assert status == 200
        assert sorted(body["updated"]) == ["CUSTOM_VAR_1", "CUSTOM_VAR_2"]
        assert os.environ.get("CUSTOM_VAR_1") == "hello"
        assert os.environ.get("CUSTOM_VAR_2") == "world"

    def test_protected_variable_rejected(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/env",
            body={"vars": {"PATH": "/evil"}},
        )
        assert status == 403
        assert "PATH" in body["error"]

    def test_protected_ebx_token_rejected(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/env",
            body={"vars": {"EBX_SERVER_TOKEN": "hacked"}},
        )
        assert status == 403

    def test_invalid_vars_type(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/env",
            body={"vars": "not-a-dict"},
        )
        assert status == 400


# ---------------------------------------------------------------------------
# GET /ports
# ---------------------------------------------------------------------------


class TestPorts:
    """GET /ports — listening port enumeration."""

    def test_returns_listening_list(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/ports")
        assert status == 200
        assert "listening" in body
        assert isinstance(body["listening"], list)

    def test_entries_have_expected_keys(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/ports")
        assert status == 200
        for entry in body["listening"]:
            assert "port" in entry
            assert "protocol" in entry
            assert "address" in entry
            assert "pid" in entry


# ---------------------------------------------------------------------------
# GET /packages
# ---------------------------------------------------------------------------


class TestPackages:
    """GET /packages — installed package listing."""

    def test_pip_returns_structure(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/packages?manager=pip")
        assert status == 200
        assert body["manager"] == "pip"
        assert isinstance(body["packages"], list)
        # pytest itself should be in the list
        names = {p["name"].lower() for p in body["packages"]}
        assert "pytest" in names

    def test_pip_default_manager(self, server_port: int) -> None:
        """When no manager is specified, pip is used by default."""
        status, body = _request(server_port, "GET", "/packages")
        assert status == 200
        assert body["manager"] == "pip"

    def test_unsupported_manager(self, server_port: int) -> None:
        status, body = _request(
            server_port, "GET", "/packages?manager=cargo"
        )
        assert status == 400
        assert "Unsupported" in body["error"]

    def test_package_entry_has_name_version(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/packages?manager=pip")
        assert status == 200
        if body["packages"]:
            pkg = body["packages"][0]
            assert "name" in pkg
            assert "version" in pkg


# ---------------------------------------------------------------------------
# GET /system/metrics
# ---------------------------------------------------------------------------


class TestSystemMetrics:
    """GET /system/metrics — resource-usage metrics."""

    def test_returns_expected_fields(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/system/metrics")
        assert status == 200
        for key in (
            "cpu_load_1m", "cpu_load_5m", "cpu_load_15m",
            "memory_used_mb", "memory_total_mb", "memory_percent",
            "disk_used_gb", "disk_total_gb", "disk_percent",
            "uptime_seconds",
        ):
            assert key in body, f"Missing key: {key}"

    def test_uptime_positive(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/system/metrics")
        assert body["uptime_seconds"] >= 0

    def test_disk_percent_range(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/system/metrics")
        assert 0 <= body["disk_percent"] <= 100
