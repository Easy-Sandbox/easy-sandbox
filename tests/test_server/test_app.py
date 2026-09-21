"""Tests for easy_sandbox.server — HTTP server + route handlers.

Each test spins up a real ``ThreadingHTTPServer`` on a random free port in a
background thread and uses ``http.client.HTTPConnection`` to hit it directly.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from easy_sandbox.server.app import SandboxRequestHandler, SandboxServer
from easy_sandbox.server.registry import CommandArg, CommandRegistry
from easy_sandbox.server.router import CapabilityGroup, default_table
from easy_sandbox.server.routes import (
    _resolve_safe_path,
    disable_builtin,
    enable_builtin,
)

# ---------------------------------------------------------------------------
# Helpers
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
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    # Give the server a moment to bind.
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
def _reset_builtins() -> Any:
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


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    """No-op — each test creates its own registry now."""
    yield


@pytest.fixture()
def _test_registry() -> CommandRegistry:
    """Create a fresh CommandRegistry for each test."""
    return CommandRegistry()


@pytest.fixture()
def server_port(_test_registry: CommandRegistry) -> Any:
    """Spin up a no-auth server on a random port and tear it down after."""
    port = _find_free_port()
    httpd = _start_server(port, registry=_test_registry)
    yield port
    httpd.shutdown()


@pytest.fixture()
def test_registry(_test_registry: CommandRegistry) -> CommandRegistry:
    """Expose the test registry so tests can register commands."""
    return _test_registry


@pytest.fixture()
def auth_server_port() -> Any:
    """Spin up a token-protected server on a random port."""
    port = _find_free_port()
    httpd = _start_server(port, auth_token="test-secret-42", registry=CommandRegistry())
    yield port
    httpd.shutdown()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    """GET /health — always 200, no auth required."""

    def test_health_ok(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/health")
        assert status == 200
        assert body == {"status": "ok"}

    def test_health_no_auth_needed(self, auth_server_port: int) -> None:
        """Even with a token configured, /health must pass without a header."""
        status, body = _request(auth_server_port, "GET", "/health")
        assert status == 200
        assert body == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /commands
# ---------------------------------------------------------------------------


class TestListCommands:
    """GET /commands — return the registered command list."""

    def test_empty_registry(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/commands")
        assert status == 200
        assert body == {"commands": []}

    def test_with_registered_command(
        self, server_port: int, test_registry: CommandRegistry
    ) -> None:
        def greet(name: str) -> str:
            return f"hi {name}"

        test_registry.register("greet", greet, args=[
            CommandArg(
                name="name", type="string", required=True, description="Who"
            ),
        ])
        status, body = _request(server_port, "GET", "/commands")
        assert status == 200
        assert len(body["commands"]) == 1
        cmd = body["commands"][0]
        assert cmd["name"] == "greet"
        assert cmd["args"][0]["name"] == "name"
        assert cmd["args"][0]["required"] is True


# ---------------------------------------------------------------------------
# POST /commands/{name}
# ---------------------------------------------------------------------------


class TestRunCommand:
    """POST /commands/{name} — run a registered command."""

    def _register_add(self, registry: CommandRegistry) -> None:
        def add(a: int, b: int) -> int:
            return a + b

        registry.register("add", add, args=[
            CommandArg(name="a", type="integer", required=True),
            CommandArg(name="b", type="integer", required=True),
        ])

    def test_success(self, server_port: int, test_registry: CommandRegistry) -> None:
        self._register_add(test_registry)
        status, body = _request(
            server_port, "POST", "/commands/add", body={"a": 3, "b": 4}
        )
        assert status == 200
        assert body == {"result": 7}

    def test_unknown_command_404(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/commands/nonexistent", body={}
        )
        assert status == 404
        assert "error" in body
        assert body["type"] == "ValueError"

    def test_bad_args_400(self, server_port: int, test_registry: CommandRegistry) -> None:
        self._register_add(test_registry)
        # Missing required arg 'b'
        status, body = _request(
            server_port, "POST", "/commands/add", body={"a": 1}
        )
        assert status == 400
        assert body["type"] == "ValueError"

    def test_execution_error_500(self, server_port: int, test_registry: CommandRegistry) -> None:
        def boom() -> None:
            raise RuntimeError("kaboom")

        test_registry.register("boom", boom, args=[])
        status, body = _request(
            server_port, "POST", "/commands/boom", body={}
        )
        assert status == 500
        assert body["type"] == "RuntimeError"
        assert "kaboom" in body["error"]


# ---------------------------------------------------------------------------
# POST /upload + GET /download  (round-trip)
# ---------------------------------------------------------------------------


class TestUploadDownload:
    """POST /upload and GET /download — file round-trip."""

    def test_round_trip(self, server_port: int, tmp_path: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv("EBX_SERVER_BASE_DIR", str(tmp_path))
        file_path = str(tmp_path / "hello.txt")
        original = b"Hello, sandbox world!"
        encoded = base64.b64encode(original).decode()

        # Upload
        status, body = _request(
            server_port,
            "POST",
            "/upload",
            body={"path": file_path, "content_base64": encoded},
        )
        assert status == 200
        assert body["bytes"] == len(original)

        # Download
        status, body = _request(
            server_port, "GET", f"/download?path={file_path}"
        )
        assert status == 200
        decoded = base64.b64decode(body["content_base64"])
        assert decoded == original

    def test_download_missing_file_404(
        self, server_port: int, tmp_path: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("EBX_SERVER_BASE_DIR", str(tmp_path))
        status, body = _request(
            server_port, "GET", f"/download?path={tmp_path}/nonexistent/file.xyz"
        )
        assert status == 404
        assert body["type"] == "FileNotFoundError"


# ---------------------------------------------------------------------------
# POST /shell
# ---------------------------------------------------------------------------


class TestShell:
    """POST /shell — subprocess execution."""

    def test_echo(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/shell", body={"command": "echo hello"}
        )
        assert status == 200
        assert body["exit_code"] == 0
        assert "hello" in body["stdout"]

    def test_nonzero_exit(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/shell", body={"command": "grep --nonexistent-flag"}
        )
        assert status == 200
        assert body["exit_code"] != 0

    def test_missing_command_400(self, server_port: int) -> None:
        status, body = _request(server_port, "POST", "/shell", body={})
        assert status == 400
        assert body["type"] == "ValueError"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    """Token-based authentication (X-Access-Token header)."""

    def test_missing_token_401(self, auth_server_port: int) -> None:
        status, body = _request(auth_server_port, "GET", "/commands")
        assert status == 401
        assert body["type"] == "AuthError"

    def test_wrong_token_401(self, auth_server_port: int) -> None:
        status, body = _request(
            auth_server_port,
            "GET",
            "/commands",
            headers={"X-Access-Token": "wrong-token"},
        )
        assert status == 401

    def test_correct_token_200(self, auth_server_port: int) -> None:
        status, body = _request(
            auth_server_port,
            "GET",
            "/commands",
            headers={"X-Access-Token": "test-secret-42"},
        )
        assert status == 200
        assert "commands" in body

    def test_post_with_token(self, auth_server_port: int) -> None:
        """POST /shell with correct token succeeds."""
        status, body = _request(
            auth_server_port,
            "POST",
            "/shell",
            body={"command": "echo auth-ok"},
            headers={"X-Access-Token": "test-secret-42"},
        )
        assert status == 200
        assert body["exit_code"] == 0


# ---------------------------------------------------------------------------
# Built-in toggle
# ---------------------------------------------------------------------------


class TestBuiltinToggle:
    """enable_builtin / disable_builtin controls route availability."""

    def test_disable_upload(self, server_port: int) -> None:
        disable_builtin("upload")
        status, body = _request(
            server_port,
            "POST",
            "/upload",
            body={"path": "/tmp/x", "content_base64": "aGVsbG8="},
        )
        assert status == 404

    def test_disable_download(self, server_port: int) -> None:
        disable_builtin("download")
        status, body = _request(
            server_port, "GET", "/download?path=/tmp/x"
        )
        assert status == 404

    def test_disable_shell(self, server_port: int) -> None:
        disable_builtin("shell")
        status, body = _request(
            server_port, "POST", "/shell", body={"command": "echo hi"}
        )
        assert status == 404

    def test_enable_after_disable(self, server_port: int) -> None:
        disable_builtin("shell")
        enable_builtin("shell")
        status, body = _request(
            server_port, "POST", "/shell", body={"command": "echo re-enabled"}
        )
        assert status == 200
        assert body["exit_code"] == 0

    def test_unknown_builtin_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown built-in"):
            enable_builtin("unknown_route")
        with pytest.raises(ValueError, match="Unknown built-in"):
            disable_builtin("unknown_route")


# ---------------------------------------------------------------------------
# SandboxServer class
# ---------------------------------------------------------------------------


class TestSandboxServerClass:
    """SandboxServer initialisation and env-var token reading."""

    def test_default_no_token(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("EBX_SERVER_TOKEN", raising=False)
        srv = SandboxServer()
        assert srv.auth_token is None

    def test_token_from_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("EBX_SERVER_TOKEN", "env-secret")
        srv = SandboxServer()
        assert srv.auth_token == "env-secret"

    def test_empty_token_treated_as_none(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("EBX_SERVER_TOKEN", "")
        srv = SandboxServer()
        assert srv.auth_token is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge-case coverage."""

    def test_not_found_get(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/nonexistent")
        assert status == 404

    def test_not_found_post(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/nonexistent", body={}
        )
        assert status == 404

    def test_upload_bad_base64(self, server_port: int, tmp_path: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv("EBX_SERVER_BASE_DIR", str(tmp_path))
        status, body = _request(
            server_port,
            "POST",
            "/upload",
            body={"path": str(tmp_path / "f"), "content_base64": "!!!"},
        )
        assert status == 400

    def test_upload_missing_path(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/upload",
            body={"content_base64": "aGVsbG8="},
        )
        assert status == 400

    def test_download_missing_path_param(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/download")
        assert status == 400


# ---------------------------------------------------------------------------
# Path traversal security — _resolve_safe_path
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Verify that upload/download reject paths outside base_dir."""

    def test_resolve_safe_path_within_base(self, tmp_path: Any) -> None:
        base = str(tmp_path)
        safe = _resolve_safe_path(str(tmp_path / "sub" / "file.txt"), base_dir=base)
        assert safe.startswith(base)

    def test_resolve_safe_path_dotdot_escape(self, tmp_path: Any) -> None:
        base = str(tmp_path / "sandbox")
        os.makedirs(base, exist_ok=True)
        with pytest.raises(ValueError, match="Path escapes base directory"):
            _resolve_safe_path(base + "/../../../etc/passwd", base_dir=base)

    def test_resolve_safe_path_absolute_outside(self, tmp_path: Any) -> None:
        base = str(tmp_path / "sandbox")
        os.makedirs(base, exist_ok=True)
        with pytest.raises(ValueError, match="Path escapes base directory"):
            _resolve_safe_path("/etc/passwd", base_dir=base)

    def test_upload_path_traversal_rejected(
        self, server_port: int, tmp_path: Any, monkeypatch: Any
    ) -> None:
        base = str(tmp_path / "sandbox")
        os.makedirs(base, exist_ok=True)
        monkeypatch.setenv("EBX_SERVER_BASE_DIR", base)
        payload = base64.b64encode(b"evil").decode()
        status, body = _request(
            server_port,
            "POST",
            "/upload",
            body={"path": base + "/../../etc/shadow", "content_base64": payload},
        )
        assert status == 400
        assert "Path escapes base directory" in body["error"]

    def test_download_path_traversal_rejected(
        self, server_port: int, tmp_path: Any, monkeypatch: Any
    ) -> None:
        base = str(tmp_path / "sandbox")
        os.makedirs(base, exist_ok=True)
        monkeypatch.setenv("EBX_SERVER_BASE_DIR", base)
        status, body = _request(
            server_port, "GET", f"/download?path={base}/../../etc/passwd"
        )
        assert status == 400
        assert "Path escapes base directory" in body["error"]

    def test_upload_within_base_ok(
        self, server_port: int, tmp_path: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("EBX_SERVER_BASE_DIR", str(tmp_path))
        file_path = str(tmp_path / "project" / "file.py")
        payload = base64.b64encode(b"print('hello')").decode()
        status, body = _request(
            server_port,
            "POST",
            "/upload",
            body={"path": file_path, "content_base64": payload},
        )
        assert status == 200
        assert body["bytes"] == len(b"print('hello')")

    def test_env_var_configures_base_dir(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        custom_base = str(tmp_path / "custom")
        os.makedirs(custom_base, exist_ok=True)
        monkeypatch.setenv("EBX_SERVER_BASE_DIR", custom_base)
        safe = _resolve_safe_path(custom_base + "/sub/file.txt")
        assert safe.startswith(custom_base)


# ---------------------------------------------------------------------------
# Shell shlex.split security
# ---------------------------------------------------------------------------


class TestShellSecurity:
    """Verify shell commands use shlex.split (no shell=True)."""

    def test_simple_command(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/shell", body={"command": "echo hello"}
        )
        assert status == 200
        assert body["exit_code"] == 0
        assert "hello" in body["stdout"]

    def test_shell_injection_not_expanded(self, server_port: int) -> None:
        """Shell metacharacters should NOT be interpreted."""
        # With shell=True, $(whoami) would be expanded. With shlex.split + shell=False,
        # the literal string is passed as argument.
        status, body = _request(
            server_port,
            "POST",
            "/shell",
            body={"command": "echo $(whoami)"},
        )
        assert status == 200
        # The literal "$(whoami)" should appear in stdout, not the expanded username
        assert "$(whoami)" in body["stdout"]


# ---------------------------------------------------------------------------
# Auth timing-safe comparison
# ---------------------------------------------------------------------------


class TestAuthTimingSafe:
    """Verify that auth uses hmac.compare_digest."""

    def test_hmac_path_correct_token(self, auth_server_port: int) -> None:
        """Correct token still works with hmac.compare_digest."""
        status, body = _request(
            auth_server_port,
            "GET",
            "/commands",
            headers={"X-Access-Token": "test-secret-42"},
        )
        assert status == 200

    def test_hmac_path_wrong_token(self, auth_server_port: int) -> None:
        """Wrong token is rejected by hmac.compare_digest."""
        status, body = _request(
            auth_server_port,
            "GET",
            "/commands",
            headers={"X-Access-Token": "wrong"},
        )
        assert status == 401

    def test_hmac_path_missing_token(self, auth_server_port: int) -> None:
        """Missing token is rejected."""
        status, body = _request(auth_server_port, "GET", "/commands")
        assert status == 401


# ---------------------------------------------------------------------------
# Hidden commands
# ---------------------------------------------------------------------------


class TestHiddenCommands:
    """Commands registered with ``hidden=True`` are executable but not listed."""

    def test_hidden_command_excluded_from_listing(
        self, server_port: int, test_registry: CommandRegistry
    ) -> None:
        test_registry.register("visible", lambda: "v")
        test_registry.register("secret", lambda: "s", hidden=True)
        status, body = _request(server_port, "GET", "/commands")
        assert status == 200
        names = {c["name"] for c in body["commands"]}
        assert names == {"visible"}

    def test_hidden_command_still_executable(
        self, server_port: int, test_registry: CommandRegistry
    ) -> None:
        test_registry.register("secret", lambda: "executed", hidden=True)
        status, body = _request(server_port, "POST", "/commands/secret", body={})
        assert status == 200
        assert body == {"result": "executed"}
