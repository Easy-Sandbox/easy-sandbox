"""Tests for protocol.filesystem module — envd filesystem operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from easy_sandbox.models.filesystem import FileInfo, FileType, WatchEvent, WatchEventType
from easy_sandbox.protocol.filesystem import (
    FilesystemProtocol,
    _name_from_path,
    _parse_file_info,
    _parse_watch_event,
)
from easy_sandbox.transport.auth import EnvdTokenManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
        info = _parse_file_info(
            {
                "name": "test.py",
                "path": "/app/test.py",
                "size": 1024,
            }
        )
        assert info.name == "test.py"
        assert info.path == "/app/test.py"
        assert info.type == FileType.FILE
        assert info.size == 1024

    def test_parse_directory_is_dir_flag(self):
        info = _parse_file_info(
            {
                "name": "src",
                "path": "/app/src",
                "isDir": True,
                "size": 0,
            }
        )
        assert info.type == FileType.DIRECTORY

    def test_parse_directory_type_field(self):
        info = _parse_file_info(
            {
                "name": "docs",
                "path": "/app/docs",
                "type": "directory",
                "size": 0,
            }
        )
        assert info.type == FileType.DIRECTORY

    def test_parse_defaults(self):
        """Empty dict → all defaults (no path to fallback for name)."""
        info = _parse_file_info({})
        assert info.name == ""
        assert info.path == ""
        assert info.type == FileType.FILE
        assert info.size == 0

    # --- name fallback from path ---

    def test_name_fallback_unix_path(self):
        """Missing name → derived from Unix path."""
        info = _parse_file_info({"path": "/app/test.py", "size": 10})
        assert info.name == "test.py"

    def test_name_fallback_empty_string(self):
        """Explicit empty-string name → derived from path."""
        info = _parse_file_info({"name": "", "path": "/var/log/app.log"})
        assert info.name == "app.log"

    def test_name_fallback_trailing_slash(self):
        """Trailing slash is stripped before extracting segment."""
        info = _parse_file_info({"path": "/app/src/", "isDir": True})
        assert info.name == "src"

    def test_name_fallback_root_path(self):
        """Root path '/' has no valid segment → name stays empty."""
        info = _parse_file_info({"path": "/"})
        assert info.name == ""

    def test_name_fallback_relative_path(self):
        """Relative path without leading slash."""
        info = _parse_file_info({"path": "relative/path.txt"})
        assert info.name == "path.txt"

    def test_name_fallback_bare_filename(self):
        """Path is a bare filename (no separators)."""
        info = _parse_file_info({"path": "notes.md"})
        assert info.name == "notes.md"

    def test_name_fallback_windows_path(self):
        """Windows-style backslash path."""
        info = _parse_file_info({"path": "C:\\Users\\test\\file.txt"})
        assert info.name == "file.txt"

    def test_name_fallback_windows_trailing_backslash(self):
        """Windows path with trailing backslash."""
        info = _parse_file_info({"path": "C:\\Users\\docs\\", "isDir": True})
        assert info.name == "docs"

    def test_name_explicit_preserved(self):
        """Explicit non-empty name from server is always preserved."""
        info = _parse_file_info({"name": "custom.txt", "path": "/app/other.txt"})
        assert info.name == "custom.txt"

    def test_name_fallback_double_slash(self):
        """Multiple trailing slashes handled."""
        info = _parse_file_info({"path": "/app/dir//"})
        assert info.name == "dir"

    def test_name_fallback_mixed_separators(self):
        """Mixed / and \\ separators."""
        info = _parse_file_info({"path": "C:\\project/src/main.py"})
        assert info.name == "main.py"

    # --- type detection (OR logic) ---

    def test_type_isdir_true_only(self):
        info = _parse_file_info({"name": "d", "path": "/d", "isDir": True})
        assert info.type == FileType.DIRECTORY

    def test_type_type_directory_only(self):
        info = _parse_file_info({"name": "d", "path": "/d", "type": "directory"})
        assert info.type == FileType.DIRECTORY

    def test_type_isdir_false_and_type_directory(self):
        """isDir=False + type='directory' → trust type field (OR logic)."""
        info = _parse_file_info({"name": "d", "path": "/d", "isDir": False, "type": "directory"})
        assert info.type == FileType.DIRECTORY

    def test_type_isdir_false_no_type(self):
        info = _parse_file_info({"name": "f", "path": "/f", "isDir": False})
        assert info.type == FileType.FILE

    def test_type_no_signals(self):
        info = _parse_file_info({"name": "f", "path": "/f"})
        assert info.type == FileType.FILE


# =============================================================================
# Tests for _name_from_path (standalone helper)
# =============================================================================


class TestNameFromPath:
    """Test _name_from_path edge cases."""

    def test_empty(self):
        assert _name_from_path("") == ""

    def test_root(self):
        assert _name_from_path("/") == ""

    def test_double_root(self):
        assert _name_from_path("//") == ""

    def test_backslash_root(self):
        assert _name_from_path("\\") == ""

    def test_unix_abs(self):
        assert _name_from_path("/usr/local/bin") == "bin"

    def test_unix_trailing(self):
        assert _name_from_path("/usr/local/bin/") == "bin"

    def test_windows(self):
        assert _name_from_path("C:\\Windows\\System32") == "System32"

    def test_windows_trailing(self):
        assert _name_from_path("C:\\Windows\\") == "Windows"

    def test_bare_name(self):
        assert _name_from_path("file.txt") == "file.txt"

    def test_relative(self):
        assert _name_from_path("a/b/c") == "c"

    def test_mixed_sep(self):
        assert _name_from_path("a\\b/c") == "c"

    def test_drive_only(self):
        """'C:\\' stripped to 'C:' which is returned as the name."""
        assert _name_from_path("C:\\") == "C:"


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
        event = _parse_watch_event(
            {
                "type": "renamed",
                "path": "/app/new_name.py",
                "oldPath": "/app/old_name.py",
            }
        )
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
        mock_http = _make_mock_http(
            envd_request_return={
                "entries": [
                    {"name": "file.txt", "path": "/file.txt", "size": 100},
                    {"name": "dir", "path": "/dir", "isDir": True, "size": 0},
                ],
            }
        )
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
        mock_http = _make_mock_http(
            envd_request_return={
                "name": "file.py",
                "path": "/app/file.py",
                "size": 100,
            }
        )
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
        mock_http = _make_mock_http(
            envd_request_return={
                "name": "app.py",
                "path": "/app/app.py",
                "size": 2048,
            }
        )
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
        resp._content = "你好世界".encode()
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
            envd_url,
            envd_token,
            old_path="/app/a.txt",
            new_path="/app/b.txt",
        )

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload == {"source": "/app/a.txt", "destination": "/app/b.txt"}


class TestWatchDir:
    """Test FilesystemProtocol.watch_dir()."""

    async def test_returns_stream_reader(self, envd_url, envd_token):
        mock_http = _make_mock_http(
            stream_frames=[
                {"type": "created", "path": "/app/new.py"},
                {"type": "modified", "path": "/app/new.py"},
            ]
        )
        proto = FilesystemProtocol(mock_http)
        reader = await proto.watch_dir(envd_url, envd_token, path="/app")

        events: list[WatchEvent] = []
        async for event in reader:
            events.append(event)

        assert len(events) == 2
        assert events[0].type == WatchEventType.CREATED
        assert events[1].type == WatchEventType.MODIFIED
