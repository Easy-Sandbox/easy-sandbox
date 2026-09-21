"""Tests for easy_sandbox.server.routes_devtools — dev-tools endpoints.

Covers:
- POST /code/run  (Python, Node, Bash, timeout, unsupported language, errors)
- GET  /git/status  (clean repo, untracked, modified)
- GET  /git/diff  (unstaged diff, staged diff)
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess  # noqa: S404
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

# Import the devtools routes so they register on the default table.
import easy_sandbox.server.routes_devtools  # noqa: F401
from easy_sandbox.server.app import SandboxRequestHandler
from easy_sandbox.server.registry import CommandRegistry
from easy_sandbox.server.router import CapabilityGroup, default_table

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int) -> ThreadingHTTPServer:
    """Create and start a no-auth server on *port* in a daemon thread."""
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
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    """Send an HTTP request and return ``(status, json_body)``."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
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
def _enable_devtools() -> Any:
    """Enable DEV_TOOLS for every test, then restore default (disabled)."""
    table = default_table()
    table.enable_group(CapabilityGroup.DEV_TOOLS)
    yield
    table.disable_group(CapabilityGroup.DEV_TOOLS)


@pytest.fixture()
def server_port() -> Any:
    """Spin up a no-auth server on a random port and tear it down after."""
    port = _find_free_port()
    httpd = _start_server(port)
    yield port
    httpd.shutdown()


@pytest.fixture()
def git_repo(tmp_path: Any) -> Any:
    """Create a minimal git repository in *tmp_path* and return its path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(  # noqa: S603, S607
        ["git", "init"], cwd=str(repo), capture_output=True, check=True, env=env,
    )
    # Create an initial file and commit
    (repo / "hello.txt").write_text("hello\n")
    subprocess.run(  # noqa: S603, S607
        ["git", "add", "."], cwd=str(repo), capture_output=True, check=True, env=env,
    )
    subprocess.run(  # noqa: S603, S607
        ["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True, env=env,
    )
    yield str(repo)


# ---------------------------------------------------------------------------
# POST /code/run
# ---------------------------------------------------------------------------


class TestCodeRun:
    """POST /code/run — code execution via subprocess."""

    def test_python_hello(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"code": "print('hello')", "language": "python"},
        )
        assert status == 200
        assert body["stdout"] == "hello\n"
        assert body["exit_code"] == 0
        assert body["language"] == "python"
        assert "execution_time_ms" in body

    def test_node_hello(self, server_port: int) -> None:
        if shutil.which("node") is None:
            pytest.skip("node not available")
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"code": "console.log('hi')", "language": "node"},
        )
        assert status == 200
        assert body["stdout"] == "hi\n"
        assert body["exit_code"] == 0

    def test_bash_echo(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"code": "echo test", "language": "bash"},
        )
        assert status == 200
        assert body["stdout"] == "test\n"
        assert body["exit_code"] == 0

    def test_timeout(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={
                "code": "import time; time.sleep(100)",
                "language": "python",
                "timeout": 2,
            },
            timeout=30,
        )
        assert status == 408
        assert "timed out" in body["error"]
        assert body["type"] == "TimeoutError"

    def test_unsupported_language(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"code": "puts 'hi'", "language": "ruby"},
        )
        assert status == 400
        assert "Unsupported language" in body["error"]

    def test_execution_error(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"code": "raise ValueError('boom')", "language": "python"},
        )
        assert status == 200
        assert body["exit_code"] != 0
        assert "boom" in body["stderr"]

    def test_missing_code(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"language": "python"},
        )
        assert status == 400
        assert "code" in body["error"].lower()

    def test_default_language_is_python(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"code": "print(42)"},
        )
        assert status == 200
        assert body["stdout"] == "42\n"
        assert body["language"] == "python"


# ---------------------------------------------------------------------------
# GET /git/status
# ---------------------------------------------------------------------------


class TestGitStatus:
    """GET /git/status — porcelain git status."""

    def test_clean_repo(self, server_port: int, git_repo: str) -> None:
        status, body = _request(
            server_port, "GET", f"/git/status?path={git_repo}",
        )
        assert status == 200
        assert body["clean"] is True
        assert body["files"] == []
        assert body["branch"]  # should have a branch name

    def test_untracked_file(self, server_port: int, git_repo: str) -> None:
        # Create a new untracked file
        with open(os.path.join(git_repo, "new.txt"), "w") as f:
            f.write("new content\n")

        status, body = _request(
            server_port, "GET", f"/git/status?path={git_repo}",
        )
        assert status == 200
        assert body["clean"] is False
        paths = [f["path"] for f in body["files"]]
        assert "new.txt" in paths
        statuses = {f["path"]: f["status"] for f in body["files"]}
        assert statuses["new.txt"] == "untracked"

    def test_modified_file(self, server_port: int, git_repo: str) -> None:
        # Modify an already-committed file
        with open(os.path.join(git_repo, "hello.txt"), "w") as f:
            f.write("modified\n")

        status, body = _request(
            server_port, "GET", f"/git/status?path={git_repo}",
        )
        assert status == 200
        assert body["clean"] is False
        statuses = {f["path"]: f["status"] for f in body["files"]}
        assert statuses["hello.txt"] == "modified"

    def test_path_traversal_rejected(self, server_port: int) -> None:
        status, body = _request(
            server_port, "GET", "/git/status?path=../../etc",
        )
        assert status == 400
        assert "traversal" in body["error"].lower()

    def test_invalid_repo(self, server_port: int, tmp_path: Any) -> None:
        """Pointing at a non-git directory should return an error."""
        status, body = _request(
            server_port, "GET", f"/git/status?path={tmp_path}",
        )
        assert status == 400
        assert body["type"] == "GitError"


# ---------------------------------------------------------------------------
# GET /git/diff
# ---------------------------------------------------------------------------


class TestGitDiff:
    """GET /git/diff — git diff with stats."""

    def test_unstaged_diff(self, server_port: int, git_repo: str) -> None:
        # Modify a committed file (unstaged change)
        with open(os.path.join(git_repo, "hello.txt"), "w") as f:
            f.write("changed content\n")

        status, body = _request(
            server_port, "GET", f"/git/diff?path={git_repo}",
        )
        assert status == 200
        assert "changed content" in body["diff"]
        assert body["stats"]["files_changed"] >= 1

    def test_staged_diff(self, server_port: int, git_repo: str) -> None:
        # Modify and stage a file
        with open(os.path.join(git_repo, "hello.txt"), "w") as f:
            f.write("staged change\n")
        subprocess.run(  # noqa: S603, S607
            ["git", "-C", git_repo, "add", "hello.txt"],
            capture_output=True, check=True,
        )

        status, body = _request(
            server_port, "GET", f"/git/diff?path={git_repo}&staged=true",
        )
        assert status == 200
        assert "staged change" in body["diff"]
        assert body["stats"]["files_changed"] >= 1

    def test_clean_repo_empty_diff(self, server_port: int, git_repo: str) -> None:
        status, body = _request(
            server_port, "GET", f"/git/diff?path={git_repo}",
        )
        assert status == 200
        assert body["diff"] == ""
        assert body["stats"]["files_changed"] == 0

    def test_file_filter(self, server_port: int, git_repo: str) -> None:
        # Create two modified files, filter by one
        with open(os.path.join(git_repo, "hello.txt"), "w") as f:
            f.write("change a\n")
        with open(os.path.join(git_repo, "other.txt"), "w") as f:
            f.write("change b\n")
        subprocess.run(  # noqa: S603, S607
            ["git", "-C", git_repo, "add", "other.txt"],
            capture_output=True, check=True,
        )

        status, body = _request(
            server_port, "GET", f"/git/diff?path={git_repo}&file=hello.txt",
        )
        assert status == 200
        assert "change a" in body["diff"]
        # other.txt changes should NOT appear (it's staged, not in unstaged diff)
        assert "change b" not in body["diff"]

    def test_path_traversal_rejected(self, server_port: int) -> None:
        status, body = _request(
            server_port, "GET", "/git/diff?path=../../etc",
        )
        assert status == 400
        assert "traversal" in body["error"].lower()


# ---------------------------------------------------------------------------
# DEV_TOOLS disabled by default
# ---------------------------------------------------------------------------


class TestDevToolsDisabledByDefault:
    """When DEV_TOOLS is not explicitly enabled, endpoints should 404."""

    @pytest.fixture(autouse=True)
    def _disable_devtools(self) -> Any:
        """Override the module-level autouse fixture to disable DEV_TOOLS."""
        table = default_table()
        table.disable_group(CapabilityGroup.DEV_TOOLS)
        yield
        # Re-enable so the autouse fixture teardown doesn't double-disable
        table.enable_group(CapabilityGroup.DEV_TOOLS)

    def test_code_run_404(self, server_port: int) -> None:
        status, _body = _request(
            server_port,
            "POST",
            "/code/run",
            body={"code": "print(1)"},
        )
        assert status == 404

    def test_git_status_404(self, server_port: int) -> None:
        status, _body = _request(server_port, "GET", "/git/status")
        assert status == 404

    def test_git_diff_404(self, server_port: int) -> None:
        status, _body = _request(server_port, "GET", "/git/diff")
        assert status == 404
