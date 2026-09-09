"""Server 端到端测试 — 在本地启动真实 HTTP Server 进行测试。

Tests the full HTTP server including:
- Health checks
- Custom command registration and execution
- Shell command execution
- File upload / download with path traversal protection
- Token-based authentication
- Registry freeze semantics
"""
from __future__ import annotations

import base64
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from serverless_sandbox.server import SandboxServer, CommandRegistry, CommandArg
from serverless_sandbox.server.routes import (
    disable_builtin,
    enable_builtin,
    _enabled_builtins,
    _KNOWN_BUILTINS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_request(
    url: str,
    *,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Send an HTTP request and return ``(status_code, json_body)``."""
    body_bytes: bytes | None = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body_bytes, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _reset_builtins():
    """Ensure the module-level enabled-builtins set is restored after each test."""
    original = set(_enabled_builtins)
    yield
    _enabled_builtins.clear()
    _enabled_builtins.update(original)


@pytest.fixture()
def server_with_commands(_reset_builtins, tmp_path):
    """Start a SandboxServer with custom commands and return ``(base_url, registry)``."""
    registry = CommandRegistry()

    def greet(name: str) -> str:
        return f"Hello, {name}!"

    def add(a: int, b: int) -> int:
        return a + b

    def no_args() -> str:
        return "ok"

    registry.register(
        "greet",
        greet,
        args=[CommandArg(name="name", type="string", required=True)],
        description="Greet someone",
    )
    registry.register(
        "add",
        add,
        args=[
            CommandArg(name="a", type="integer", required=True),
            CommandArg(name="b", type="integer", required=True),
        ],
    )
    registry.register("no_args", no_args)

    port = _free_port()
    server = SandboxServer(host="127.0.0.1", registry=registry)

    # Enable all builtins
    for name in _KNOWN_BUILTINS:
        enable_builtin(name)

    # Set base dir for upload / download path safety
    os.environ["SBOX_SERVER_BASE_DIR"] = str(tmp_path)

    t = threading.Thread(target=server.serve, kwargs={"port": port}, daemon=True)
    t.start()

    # Wait until the server is reachable
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            _http_request(f"{base_url}/health")
            break
        except Exception:
            time.sleep(0.05)
    else:
        pytest.fail("Server did not start within 2 seconds")

    yield base_url, registry, tmp_path

    server.shutdown()
    os.environ.pop("SBOX_SERVER_BASE_DIR", None)


# ---------------------------------------------------------------------------
# Test 1: Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """GET /health returns status=ok, no auth required."""

    def test_health_returns_ok(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(f"{base_url}/health")
        assert status == 200
        assert body == {"status": "ok"}


# ---------------------------------------------------------------------------
# Test 2: Custom command registration and execution
# ---------------------------------------------------------------------------


class TestCustomCommands:
    """GET /commands and POST /commands/{name}."""

    def test_list_commands(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(f"{base_url}/commands")
        assert status == 200
        names = {cmd["name"] for cmd in body["commands"]}
        assert {"greet", "add", "no_args"} == names

    def test_run_command_greet(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/commands/greet",
            method="POST",
            data={"name": "World"},
        )
        assert status == 200
        assert body["result"] == "Hello, World!"

    def test_run_command_add_with_type_coercion(self, server_with_commands):
        """String '42' should be coerced to int."""
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/commands/add",
            method="POST",
            data={"a": "42", "b": 8},
        )
        assert status == 200
        assert body["result"] == 50

    def test_run_command_no_args(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/commands/no_args",
            method="POST",
            data={},
        )
        assert status == 200
        assert body["result"] == "ok"

    def test_missing_required_argument_returns_400(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/commands/greet",
            method="POST",
            data={},
        )
        assert status == 400
        assert "name" in body["error"].lower()

    def test_unknown_command_returns_404(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/commands/nonexistent",
            method="POST",
            data={},
        )
        assert status == 404
        assert "nonexistent" in body["error"]


# ---------------------------------------------------------------------------
# Test 3: Shell execution
# ---------------------------------------------------------------------------


class TestShellExecution:
    """POST /shell."""

    def test_shell_echo(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/shell",
            method="POST",
            data={"command": "echo hello"},
        )
        assert status == 200
        assert body["stdout"].strip() == "hello"
        assert body["exit_code"] == 0

    def test_shell_nonexistent_path(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/shell",
            method="POST",
            data={"command": "ls /nonexistent_path_that_does_not_exist_xyz"},
        )
        assert status == 200
        assert body["exit_code"] != 0
        assert body["stderr"]  # should contain error text

    def test_shell_disabled_returns_404(self, server_with_commands):
        base_url, _, _ = server_with_commands
        disable_builtin("shell")
        status, body = _http_request(
            f"{base_url}/shell",
            method="POST",
            data={"command": "echo hi"},
        )
        assert status == 404
        assert "disabled" in body["error"].lower()
        # Re-enable for other tests
        enable_builtin("shell")


# ---------------------------------------------------------------------------
# Test 4: File upload / download
# ---------------------------------------------------------------------------


class TestFileUploadDownload:
    """POST /upload and GET /download."""

    def test_upload_and_download_roundtrip(self, server_with_commands):
        base_url, _, tmp_path = server_with_commands
        content = b"Hello, sandbox file system!"
        content_b64 = base64.b64encode(content).decode("ascii")
        file_path = str(tmp_path / "test_file.txt")

        # Upload
        status, body = _http_request(
            f"{base_url}/upload",
            method="POST",
            data={"path": file_path, "content_base64": content_b64},
        )
        assert status == 200
        assert body["bytes"] == len(content)

        # Download
        status, body = _http_request(
            f"{base_url}/download?path={urllib.request.quote(file_path)}",
        )
        assert status == 200
        downloaded = base64.b64decode(body["content_base64"])
        assert downloaded == content

    def test_path_traversal_upload_returns_400(self, server_with_commands):
        base_url, _, tmp_path = server_with_commands
        content_b64 = base64.b64encode(b"hack").decode("ascii")
        # Try to escape the base dir
        evil_path = str(tmp_path / ".." / ".." / "etc" / "passwd")

        status, body = _http_request(
            f"{base_url}/upload",
            method="POST",
            data={"path": evil_path, "content_base64": content_b64},
        )
        assert status == 400
        assert "escapes" in body["error"].lower() or "path" in body["error"].lower()

    def test_path_traversal_download_returns_400(self, server_with_commands):
        base_url, _, tmp_path = server_with_commands
        evil_path = str(tmp_path / ".." / ".." / "etc" / "passwd")

        status, body = _http_request(
            f"{base_url}/download?path={urllib.request.quote(evil_path)}",
        )
        assert status == 400

    def test_upload_disabled_returns_404(self, server_with_commands):
        base_url, _, tmp_path = server_with_commands
        disable_builtin("upload")
        content_b64 = base64.b64encode(b"data").decode("ascii")
        file_path = str(tmp_path / "nope.txt")

        status, body = _http_request(
            f"{base_url}/upload",
            method="POST",
            data={"path": file_path, "content_base64": content_b64},
        )
        assert status == 404
        enable_builtin("upload")

    def test_download_disabled_returns_404(self, server_with_commands):
        base_url, _, tmp_path = server_with_commands
        disable_builtin("download")

        status, body = _http_request(
            f"{base_url}/download?path=/some/file",
        )
        assert status == 404
        enable_builtin("download")


# ---------------------------------------------------------------------------
# Test 5: Authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    """Token-based auth via SBOX_SERVER_TOKEN."""

    def test_auth_required_when_token_set(self, _reset_builtins, tmp_path):
        """Requests without a token return 401 when SBOX_SERVER_TOKEN is set."""
        token = "test-secret-token-12345"
        os.environ["SBOX_SERVER_TOKEN"] = token
        os.environ["SBOX_SERVER_BASE_DIR"] = str(tmp_path)

        registry = CommandRegistry()
        registry.register("ping", lambda: "pong")

        port = _free_port()
        server = SandboxServer(host="127.0.0.1", registry=registry)
        t = threading.Thread(target=server.serve, kwargs={"port": port}, daemon=True)
        t.start()

        base_url = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                _http_request(f"{base_url}/health")
                break
            except Exception:
                time.sleep(0.05)

        try:
            # /health should NOT require auth
            status, body = _http_request(f"{base_url}/health")
            assert status == 200
            assert body["status"] == "ok"

            # /commands without token → 401
            status, body = _http_request(f"{base_url}/commands")
            assert status == 401
            assert "unauthorized" in body["error"].lower()

            # /commands with wrong token → 401
            status, body = _http_request(
                f"{base_url}/commands",
                headers={"X-Access-Token": "wrong-token"},
            )
            assert status == 401

            # /commands with correct token → 200
            status, body = _http_request(
                f"{base_url}/commands",
                headers={"X-Access-Token": token},
            )
            assert status == 200

            # POST /commands/ping with correct token → 200
            status, body = _http_request(
                f"{base_url}/commands/ping",
                method="POST",
                data={},
                headers={"X-Access-Token": token},
            )
            assert status == 200
            assert body["result"] == "pong"
        finally:
            server.shutdown()
            os.environ.pop("SBOX_SERVER_TOKEN", None)
            os.environ.pop("SBOX_SERVER_BASE_DIR", None)


# ---------------------------------------------------------------------------
# Test 6: Registry freeze
# ---------------------------------------------------------------------------


class TestRegistryFreeze:
    """Verify that the registry is frozen after server starts."""

    def test_registry_frozen_after_serve(self, server_with_commands):
        _, registry, _ = server_with_commands
        assert registry._frozen is True
        with pytest.raises(RuntimeError, match="frozen"):
            registry.register("new_cmd", lambda: None)

    def test_unfrozen_registry_allows_register(self):
        """A fresh registry should accept registrations before freeze."""
        reg = CommandRegistry()
        reg.register("test", lambda: 42)
        assert "test" in reg
        reg.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            reg.register("another", lambda: 0)


# ---------------------------------------------------------------------------
# Test 7: 404 for unknown routes
# ---------------------------------------------------------------------------


class TestUnknownRoutes:
    """Unknown paths return 404."""

    def test_get_unknown_path(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(f"{base_url}/unknown/path")
        assert status == 404

    def test_post_unknown_path(self, server_with_commands):
        base_url, _, _ = server_with_commands
        status, body = _http_request(
            f"{base_url}/unknown",
            method="POST",
            data={},
        )
        assert status == 404
