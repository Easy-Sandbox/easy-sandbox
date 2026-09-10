"""Tests for serverless_sandbox.server.routes_files — file operation endpoints.

Each test spins up a real ``ThreadingHTTPServer`` on a random free port in a
background thread and uses ``http.client.HTTPConnection`` to hit it directly.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

import serverless_sandbox.server.routes_files  # noqa: F401  (trigger route registration)
from serverless_sandbox.server.app import SandboxRequestHandler
from serverless_sandbox.server.registry import CommandRegistry
from serverless_sandbox.server.router import CapabilityGroup, default_table

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_app.py)
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


@pytest.fixture()
def server_port(tmp_path: Any, monkeypatch: Any) -> Any:
    """Spin up a no-auth server with base_dir set to tmp_path."""
    monkeypatch.setenv("SBOX_SERVER_BASE_DIR", str(tmp_path))
    port = _find_free_port()
    httpd = _start_server(port)
    yield port
    httpd.shutdown()


@pytest.fixture()
def base(tmp_path: Any) -> str:
    """Return the string form of tmp_path for convenience."""
    return str(tmp_path)


# ---------------------------------------------------------------------------
# GET /files/list
# ---------------------------------------------------------------------------


class TestFilesList:
    """GET /files/list — directory listing."""

    def test_list_empty_dir(self, server_port: int, base: str) -> None:
        sub = os.path.join(base, "empty")
        os.makedirs(sub)
        status, body = _request(server_port, "GET", f"/files/list?path={sub}")
        assert status == 200
        assert body["entries"] == []

    def test_list_with_files(self, server_port: int, base: str) -> None:
        sub = os.path.join(base, "data")
        os.makedirs(sub)
        for name in ("a.txt", "b.txt"):
            with open(os.path.join(sub, name), "w") as f:
                f.write("hi")
        status, body = _request(server_port, "GET", f"/files/list?path={sub}")
        assert status == 200
        names = {e["name"] for e in body["entries"]}
        assert names == {"a.txt", "b.txt"}
        for e in body["entries"]:
            assert "size" in e
            assert "modified" in e
            assert e["type"] == "file"

    def test_list_recursive(self, server_port: int, base: str) -> None:
        sub = os.path.join(base, "root")
        child = os.path.join(sub, "child")
        os.makedirs(child)
        with open(os.path.join(sub, "a.txt"), "w") as f:
            f.write("a")
        with open(os.path.join(child, "b.txt"), "w") as f:
            f.write("b")
        status, body = _request(
            server_port, "GET", f"/files/list?path={sub}&recursive=true"
        )
        assert status == 200
        names = {e["name"] for e in body["entries"]}
        assert "a.txt" in names
        assert "b.txt" in names
        assert "child" in names

    def test_list_missing_path(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/files/list")
        assert status == 400

    def test_list_nonexistent_dir(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port, "GET", f"/files/list?path={base}/nonexistent"
        )
        assert status == 404

    def test_list_path_traversal(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port, "GET", f"/files/list?path={base}/../../etc"
        )
        assert status == 400
        assert "Path escapes" in body["error"]


# ---------------------------------------------------------------------------
# GET /files/stat
# ---------------------------------------------------------------------------


class TestFilesStat:
    """GET /files/stat — file/directory information."""

    def test_stat_file(self, server_port: int, base: str) -> None:
        fp = os.path.join(base, "info.txt")
        with open(fp, "w") as f:
            f.write("hello")
        status, body = _request(server_port, "GET", f"/files/stat?path={fp}")
        assert status == 200
        assert body["exists"] is True
        assert body["type"] == "file"
        assert body["name"] == "info.txt"
        assert body["size"] == 5
        assert body["permissions"]  # e.g. "644"
        assert body["modified"]  # ISO string

    def test_stat_directory(self, server_port: int, base: str) -> None:
        dp = os.path.join(base, "mydir")
        os.makedirs(dp)
        status, body = _request(server_port, "GET", f"/files/stat?path={dp}")
        assert status == 200
        assert body["exists"] is True
        assert body["type"] == "directory"

    def test_stat_nonexistent(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port, "GET", f"/files/stat?path={base}/nope.txt"
        )
        assert status == 200
        assert body["exists"] is False

    def test_stat_missing_param(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/files/stat")
        assert status == 400


# ---------------------------------------------------------------------------
# POST /files/mkdir
# ---------------------------------------------------------------------------


class TestFilesMkdir:
    """POST /files/mkdir — create directories."""

    def test_mkdir_simple(self, server_port: int, base: str) -> None:
        dp = os.path.join(base, "newdir")
        status, body = _request(
            server_port, "POST", "/files/mkdir", body={"path": dp}
        )
        assert status == 200
        assert body["created"] is True
        assert os.path.isdir(dp)

    def test_mkdir_nested(self, server_port: int, base: str) -> None:
        dp = os.path.join(base, "a", "b", "c")
        status, body = _request(
            server_port, "POST", "/files/mkdir", body={"path": dp}
        )
        assert status == 200
        assert os.path.isdir(dp)

    def test_mkdir_exist_ok(self, server_port: int, base: str) -> None:
        dp = os.path.join(base, "existing")
        os.makedirs(dp)
        status, body = _request(
            server_port, "POST", "/files/mkdir", body={"path": dp}
        )
        assert status == 200

    def test_mkdir_missing_path(self, server_port: int) -> None:
        status, body = _request(server_port, "POST", "/files/mkdir", body={})
        assert status == 400

    def test_mkdir_path_traversal(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/files/mkdir",
            body={"path": base + "/../../escape"},
        )
        assert status == 400


# ---------------------------------------------------------------------------
# DELETE /files
# ---------------------------------------------------------------------------


class TestFilesDelete:
    """DELETE /files — delete file or directory."""

    def test_delete_file(self, server_port: int, base: str) -> None:
        fp = os.path.join(base, "trash.txt")
        with open(fp, "w") as f:
            f.write("bye")
        status, body = _request(server_port, "DELETE", f"/files?path={fp}")
        assert status == 200
        assert body["deleted"] is True
        assert not os.path.exists(fp)

    def test_delete_directory(self, server_port: int, base: str) -> None:
        dp = os.path.join(base, "rmdir")
        os.makedirs(dp)
        with open(os.path.join(dp, "f.txt"), "w") as f:
            f.write("x")
        status, body = _request(server_port, "DELETE", f"/files?path={dp}")
        assert status == 200
        assert not os.path.exists(dp)

    def test_delete_nonexistent(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port, "DELETE", f"/files?path={base}/ghost"
        )
        assert status == 404

    def test_delete_missing_param(self, server_port: int) -> None:
        status, body = _request(server_port, "DELETE", "/files")
        assert status == 400


# ---------------------------------------------------------------------------
# POST /files/move
# ---------------------------------------------------------------------------


class TestFilesMove:
    """POST /files/move — move/rename files."""

    def test_move_rename(self, server_port: int, base: str) -> None:
        src = os.path.join(base, "old.txt")
        dst = os.path.join(base, "new.txt")
        with open(src, "w") as f:
            f.write("data")
        status, body = _request(
            server_port,
            "POST",
            "/files/move",
            body={"source": src, "destination": dst},
        )
        assert status == 200
        assert not os.path.exists(src)
        assert os.path.exists(dst)

    def test_move_to_subdir(self, server_port: int, base: str) -> None:
        src = os.path.join(base, "file.txt")
        dst_dir = os.path.join(base, "sub")
        dst = os.path.join(dst_dir, "file.txt")
        with open(src, "w") as f:
            f.write("data")
        status, body = _request(
            server_port,
            "POST",
            "/files/move",
            body={"source": src, "destination": dst},
        )
        assert status == 200
        assert os.path.exists(dst)

    def test_move_missing_source(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/files/move",
            body={
                "source": os.path.join(base, "nope"),
                "destination": os.path.join(base, "dst"),
            },
        )
        assert status == 404

    def test_move_missing_params(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/files/move", body={}
        )
        assert status == 400


# ---------------------------------------------------------------------------
# POST /files/search
# ---------------------------------------------------------------------------


class TestFilesSearch:
    """POST /files/search — file search by glob pattern."""

    def test_search_basic(self, server_port: int, base: str) -> None:
        sub = os.path.join(base, "project")
        os.makedirs(sub)
        for name in ("main.py", "utils.py", "readme.md"):
            with open(os.path.join(sub, name), "w") as f:
                f.write("")
        status, body = _request(
            server_port,
            "POST",
            "/files/search",
            body={"path": sub, "pattern": "*.py"},
        )
        assert status == 200
        names = {r["name"] for r in body["results"]}
        assert names == {"main.py", "utils.py"}

    def test_search_nested(self, server_port: int, base: str) -> None:
        sub = os.path.join(base, "proj")
        child = os.path.join(sub, "pkg")
        os.makedirs(child)
        with open(os.path.join(child, "mod.py"), "w") as f:
            f.write("")
        status, body = _request(
            server_port,
            "POST",
            "/files/search",
            body={"path": sub, "pattern": "*.py", "max_depth": 3},
        )
        assert status == 200
        assert len(body["results"]) == 1
        assert body["results"][0]["name"] == "mod.py"

    def test_search_max_results(self, server_port: int, base: str) -> None:
        sub = os.path.join(base, "many")
        os.makedirs(sub)
        for i in range(20):
            with open(os.path.join(sub, f"f{i}.txt"), "w") as f:
                f.write("")
        status, body = _request(
            server_port,
            "POST",
            "/files/search",
            body={"path": sub, "pattern": "*.txt", "max_results": 5},
        )
        assert status == 200
        assert len(body["results"]) == 5

    def test_search_missing_params(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/files/search", body={}
        )
        assert status == 400

    def test_search_nonexistent_dir(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/files/search",
            body={"path": os.path.join(base, "nope"), "pattern": "*"},
        )
        assert status == 404


# ---------------------------------------------------------------------------
# POST /files/upload-stream
# ---------------------------------------------------------------------------


class TestFilesUploadStream:
    """POST /files/upload-stream — base64 file upload."""

    def test_upload_basic(self, server_port: int, base: str) -> None:
        fp = os.path.join(base, "uploaded.txt")
        content = b"Hello upload stream!"
        encoded = base64.b64encode(content).decode()
        status, body = _request(
            server_port,
            "POST",
            "/files/upload-stream",
            body={"path": fp, "content_base64": encoded},
        )
        assert status == 200
        assert body["bytes"] == len(content)
        with open(fp, "rb") as f:
            assert f.read() == content

    def test_upload_creates_parent_dirs(self, server_port: int, base: str) -> None:
        fp = os.path.join(base, "deep", "nested", "file.bin")
        content = b"\x00\x01\x02"
        encoded = base64.b64encode(content).decode()
        status, body = _request(
            server_port,
            "POST",
            "/files/upload-stream",
            body={"path": fp, "content_base64": encoded},
        )
        assert status == 200
        assert os.path.exists(fp)

    def test_upload_bad_base64(self, server_port: int, base: str) -> None:
        fp = os.path.join(base, "bad.txt")
        status, body = _request(
            server_port,
            "POST",
            "/files/upload-stream",
            body={"path": fp, "content_base64": "!!!invalid!!!"},
        )
        assert status == 400

    def test_upload_missing_path(self, server_port: int) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/files/upload-stream",
            body={"content_base64": "aGVsbG8="},
        )
        assert status == 400

    def test_upload_size_limit(
        self, server_port: int, base: str, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("SBOX_MAX_UPLOAD_SIZE", "10")
        fp = os.path.join(base, "big.bin")
        content = b"x" * 100
        encoded = base64.b64encode(content).decode()
        status, body = _request(
            server_port,
            "POST",
            "/files/upload-stream",
            body={"path": fp, "content_base64": encoded},
        )
        assert status == 413

    def test_upload_path_traversal(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/files/upload-stream",
            body={
                "path": base + "/../../etc/evil",
                "content_base64": "aGVsbG8=",
            },
        )
        assert status == 400


# ---------------------------------------------------------------------------
# GET /files/download-stream
# ---------------------------------------------------------------------------


class TestFilesDownloadStream:
    """GET /files/download-stream — base64 file download."""

    def test_download_basic(self, server_port: int, base: str) -> None:
        fp = os.path.join(base, "dl.txt")
        content = b"Download me!"
        with open(fp, "wb") as f:
            f.write(content)
        status, body = _request(
            server_port, "GET", f"/files/download-stream?path={fp}"
        )
        assert status == 200
        assert base64.b64decode(body["content_base64"]) == content
        assert body["bytes"] == len(content)

    def test_download_nonexistent(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port,
            "GET",
            f"/files/download-stream?path={base}/nope.txt",
        )
        assert status == 404

    def test_download_missing_param(self, server_port: int) -> None:
        status, body = _request(server_port, "GET", "/files/download-stream")
        assert status == 400

    def test_download_path_traversal(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port,
            "GET",
            f"/files/download-stream?path={base}/../../etc/passwd",
        )
        assert status == 400


# ---------------------------------------------------------------------------
# POST /files/archive
# ---------------------------------------------------------------------------


class TestFilesArchive:
    """POST /files/archive — archive creation."""

    def _setup_files(self, base: str) -> tuple[str, str]:
        """Create a couple of files and return their paths."""
        f1 = os.path.join(base, "a.txt")
        f2 = os.path.join(base, "b.txt")
        with open(f1, "w") as f:
            f.write("aaa")
        with open(f2, "w") as f:
            f.write("bbb")
        return f1, f2

    def test_archive_tar_gz(self, server_port: int, base: str) -> None:
        f1, f2 = self._setup_files(base)
        status, body = _request(
            server_port,
            "POST",
            "/files/archive",
            body={"paths": [f1, f2], "format": "tar.gz"},
        )
        assert status == 200
        assert body["format"] == "tar.gz"
        assert body["bytes"] > 0
        # Verify it's valid tar.gz
        import io
        import tarfile

        data = base64.b64decode(body["content_base64"])
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            names = tar.getnames()
            assert "a.txt" in names
            assert "b.txt" in names

    def test_archive_zip(self, server_port: int, base: str) -> None:
        f1, f2 = self._setup_files(base)
        status, body = _request(
            server_port,
            "POST",
            "/files/archive",
            body={"paths": [f1, f2], "format": "zip"},
        )
        assert status == 200
        assert body["format"] == "zip"
        # Verify it's valid zip
        import io
        import zipfile

        data = base64.b64decode(body["content_base64"])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert "a.txt" in names
            assert "b.txt" in names

    def test_archive_directory(self, server_port: int, base: str) -> None:
        sub = os.path.join(base, "mydir")
        os.makedirs(sub)
        with open(os.path.join(sub, "inside.txt"), "w") as f:
            f.write("inside")
        status, body = _request(
            server_port,
            "POST",
            "/files/archive",
            body={"paths": [sub], "format": "zip"},
        )
        assert status == 200
        import io
        import zipfile

        data = base64.b64decode(body["content_base64"])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert any("inside.txt" in n for n in names)

    def test_archive_invalid_format(self, server_port: int, base: str) -> None:
        f1, _ = self._setup_files(base)
        status, body = _request(
            server_port,
            "POST",
            "/files/archive",
            body={"paths": [f1], "format": "rar"},
        )
        assert status == 400

    def test_archive_missing_paths(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/files/archive", body={}
        )
        assert status == 400

    def test_archive_nonexistent_file(self, server_port: int, base: str) -> None:
        status, body = _request(
            server_port,
            "POST",
            "/files/archive",
            body={"paths": [os.path.join(base, "ghost.txt")], "format": "zip"},
        )
        assert status == 404

    def test_archive_default_format(self, server_port: int, base: str) -> None:
        f1, _ = self._setup_files(base)
        status, body = _request(
            server_port,
            "POST",
            "/files/archive",
            body={"paths": [f1]},
        )
        assert status == 200
        assert body["format"] == "tar.gz"


# ---------------------------------------------------------------------------
# Upload → Download round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Verify upload-stream + download-stream round-trip."""

    def test_round_trip(self, server_port: int, base: str) -> None:
        fp = os.path.join(base, "round.bin")
        content = os.urandom(256)
        encoded = base64.b64encode(content).decode()

        # Upload
        status, body = _request(
            server_port,
            "POST",
            "/files/upload-stream",
            body={"path": fp, "content_base64": encoded},
        )
        assert status == 200

        # Download
        status, body = _request(
            server_port, "GET", f"/files/download-stream?path={fp}"
        )
        assert status == 200
        assert base64.b64decode(body["content_base64"]) == content
