"""Tests for protocol.filesystem module — envd filesystem operations."""
from __future__ import annotations

import base64
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from serverless_sandbox.models.filesystem import FileInfo, FileType, WatchEvent, WatchEventType
from serverless_sandbox.protocol.filesystem import (
    FilesystemProtocol,
    _parse_file_info,
    _parse_watch_event,
)
from serverless_sandbox.transport.auth import EnvdTokenManager


@pytest.fixture
def envd_token():
    return EnvdTokenManager("test-envd-token")


@pytest.fixture
def envd_url():
    return "https://envd-sbx-123.example.com"


def _make_mock_http(
    envd_request_return: dict[str, Any] | None = None,
    stream_frames: list[dict[str, Any]] | None = None,
    envd_http_response: httpx.Response | None = None,
) -> MagicMock:
    """Create a mock HttpClient."""
    mock = MagicMock()
    if envd_request_return is not None:
        mock.envd_request = AsyncMock(return_value=envd_request_return)
    else:
        mock.envd_request = AsyncMock(return_value={})

    if envd_http_response is not None:
        mock.envd_http_request = AsyncMock(return_value=envd_http_response)
    else:
        # Default: return a 200 response with empty content
        default_resp = httpx.Response(200, request=httpx.Request("GET", "https://fake"))
        default_resp._content = b""
        mock.envd_http_request = AsyncMock(return_value=default_resp)

    if stream_frames is not None:
        async def fake_envd_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            for frame in stream_frames:
                yield frame

        mock.envd_stream = fake_envd_stream
    else:
        async def empty_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            return
            yield

        mock.envd_stream = empty_stream

    return mock


# =============================================================================
# Tests for _parse_file_info
# =============================================================================


class TestParseFileInfo:
    """Test _parse_file_info helper."""

    def test_parse_file(self):
        info = _parse_file_info({
            "name": "test.py",
            "path": "/app/test.py",
            "size": 1024,
        })
        assert info.name == "test.py"
        assert info.path == "/app/test.py"
        assert info.type == FileType.FILE
        assert info.size == 1024

    def test_parse_directory_is_dir_flag(self):
        info = _parse_file_info({
            "name": "src",
            "path": "/app/src",
            "isDir": True,
            "size": 0,
        })
        assert info.type == FileType.DIRECTORY

    def test_parse_directory_type_field(self):
        info = _parse_file_info({
            "name": "docs",
            "path": "/app/docs",
            "type": "directory",
            "size": 0,
        })
        assert info.type == FileType.DIRECTORY

    def test_parse_defaults(self):
        info = _parse_file_info({})
        assert info.name == ""
        assert info.path == ""
        assert info.type == FileType.FILE
        assert info.size == 0


# =============================================================================
# Tests for _parse_watch_event
# =============================================================================


class TestParseWatchEvent:
    """Test _parse_watch_event helper."""

    def test_created_event(self):
        event = _parse_watch_event({"type": "created", "path": "/app/new.py"})
        assert event.type == WatchEventType.CREATED
        assert event.path == "/app/new.py"

    def test_modified_event(self):
        event = _parse_watch_event({"type": "modified", "path": "/app/mod.py"})
        assert event.type == WatchEventType.MODIFIED

    def test_deleted_event(self):
        event = _parse_watch_event({"type": "deleted", "path": "/app/old.py"})
        assert event.type == WatchEventType.DELETED

    def test_renamed_event(self):
        event = _parse_watch_event({
            "type": "renamed",
            "path": "/app/new_name.py",
            "oldPath": "/app/old_name.py",
        })
        assert event.type == WatchEventType.RENAMED
        assert event.old_path == "/app/old_name.py"

    def test_short_form_event_types(self):
        assert _parse_watch_event({"type": "create", "path": ""}).type == WatchEventType.CREATED
        assert _parse_watch_event({"type": "modify", "path": ""}).type == WatchEventType.MODIFIED
        assert _parse_watch_event({"type": "delete", "path": ""}).type == WatchEventType.DELETED
        assert _parse_watch_event({"type": "rename", "path": ""}).type == WatchEventType.RENAMED

    def test_result_wrapper(self):
        event = _parse_watch_event({"result": {"type": "created", "path": "/app/x"}})
        assert event.type == WatchEventType.CREATED
        assert event.path == "/app/x"

    def test_unknown_type_defaults_to_modified(self):
        event = _parse_watch_event({"type": "unknown", "path": "/app/x"})
        assert event.type == WatchEventType.MODIFIED


# =============================================================================
# Tests for FilesystemProtocol
# =============================================================================


class TestListDir:
    """Test FilesystemProtocol.list_dir()."""

    async def test_parses_entries(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "entries": [
                {"name": "file.txt", "path": "/file.txt", "size": 100},
                {"name": "dir", "path": "/dir", "isDir": True, "size": 0},
            ],
        })
        proto = FilesystemProtocol(mock_http)
        result = await proto.list_dir(envd_url, envd_token, path="/")

        assert len(result) == 2
        assert result[0].name == "file.txt"
        assert result[0].type == FileType.FILE
        assert result[1].name == "dir"
        assert result[1].type == FileType.DIRECTORY

    async def test_empty_directory(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={"entries": []})
        proto = FilesystemProtocol(mock_http)
        result = await proto.list_dir(envd_url, envd_token, path="/empty")
        assert result == []


class TestExists:
    """Test FilesystemProtocol.exists() — now via stat()."""

    async def test_exists_true(self, envd_url, envd_token):
        """exists() returns True when stat() succeeds."""
        mock_http = _make_mock_http(envd_request_return={
            "name": "file.py", "path": "/app/file.py", "size": 100,
        })
        proto = FilesystemProtocol(mock_http)
        assert await proto.exists(envd_url, envd_token, path="/app/file.py") is True

    async def test_exists_false(self, envd_url, envd_token):
        """exists() returns False when stat() raises an exception."""
        mock_http = _make_mock_http()
        mock_http.envd_request.side_effect = Exception("not found")
        proto = FilesystemProtocol(mock_http)
        assert await proto.exists(envd_url, envd_token, path="/nonexistent") is False


class TestGetInfo:
    """Test FilesystemProtocol.get_info()."""

    async def test_get_file_info(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "name": "app.py",
            "path": "/app/app.py",
            "size": 2048,
        })
        proto = FilesystemProtocol(mock_http)
        info = await proto.get_info(envd_url, envd_token, path="/app/app.py")

        assert isinstance(info, FileInfo)
        assert info.name == "app.py"
        assert info.size == 2048


class TestRead:
    """Test FilesystemProtocol.read() — now uses HTTP file API (download_file)."""

    async def test_returns_bytes(self, envd_url, envd_token):
        resp = httpx.Response(200, request=httpx.Request("GET", "https://fake"))
        resp._content = b"hello world"
        mock_http = _make_mock_http(envd_http_response=resp)
        proto = FilesystemProtocol(mock_http)
        result = await proto.read(envd_url, envd_token, path="/app/test.txt")
        assert result == b"hello world"

    async def test_binary_content(self, envd_url, envd_token):
        resp = httpx.Response(200, request=httpx.Request("GET", "https://fake"))
        resp._content = b"\x00\x01\x02"
        mock_http = _make_mock_http(envd_http_response=resp)
        proto = FilesystemProtocol(mock_http)
        result = await proto.read(envd_url, envd_token, path="/app/bin")
        assert result == b"\x00\x01\x02"


class TestReadText:
    """Test FilesystemProtocol.read_text() — delegates to read() then decodes."""

    async def test_returns_string(self, envd_url, envd_token):
        resp = httpx.Response(200, request=httpx.Request("GET", "https://fake"))
        resp._content = "你好世界".encode("utf-8")
        mock_http = _make_mock_http(envd_http_response=resp)
        proto = FilesystemProtocol(mock_http)
        result = await proto.read_text(envd_url, envd_token, path="/app/test.txt")
        assert result == "你好世界"


class TestWrite:
    """Test FilesystemProtocol.write() — now uses HTTP file API (upload_file)."""

    async def test_writes_string(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = FilesystemProtocol(mock_http)
        await proto.write(envd_url, envd_token, path="/app/out.txt", content="hello")

        mock_http.envd_http_request.assert_awaited_once()
        call_args = mock_http.envd_http_request.call_args
        assert call_args[0][2] == "/files"  # path
        assert call_args[1]["params"]["path"] == "/app/out.txt"

    async def test_writes_bytes(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = FilesystemProtocol(mock_http)
        await proto.write(envd_url, envd_token, path="/app/bin", content=b"\x00\x01\x02")

        mock_http.envd_http_request.assert_awaited_once()


class TestMakeDir:
    """Test FilesystemProtocol.make_dir()."""

    async def test_sends_path(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = FilesystemProtocol(mock_http)
        await proto.make_dir(envd_url, envd_token, path="/app/new_dir")

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload == {"path": "/app/new_dir"}


class TestRemove:
    """Test FilesystemProtocol.remove()."""

    async def test_sends_path(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = FilesystemProtocol(mock_http)
        await proto.remove(envd_url, envd_token, path="/app/old.txt")

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload == {"path": "/app/old.txt"}


class TestRename:
    """Test FilesystemProtocol.rename() — delegates to move() with source/destination."""

    async def test_sends_old_and_new_paths(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = FilesystemProtocol(mock_http)
        await proto.rename(
            envd_url, envd_token,
            old_path="/app/a.txt",
            new_path="/app/b.txt",
        )

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload == {"source": "/app/a.txt", "destination": "/app/b.txt"}


class TestWatchDir:
    """Test FilesystemProtocol.watch_dir()."""

    async def test_returns_stream_reader(self, envd_url, envd_token):
        mock_http = _make_mock_http(stream_frames=[
            {"type": "created", "path": "/app/new.py"},
            {"type": "modified", "path": "/app/new.py"},
        ])
        proto = FilesystemProtocol(mock_http)
        reader = await proto.watch_dir(envd_url, envd_token, path="/app")

        events: list[WatchEvent] = []
        async for event in reader:
            events.append(event)

        assert len(events) == 2
        assert events[0].type == WatchEventType.CREATED
        assert events[1].type == WatchEventType.MODIFIED
