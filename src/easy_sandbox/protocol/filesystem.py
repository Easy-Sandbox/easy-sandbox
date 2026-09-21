"""envd API protocol — filesystem operations (Connect protocol + HTTP file API).

Connect RPC endpoints（已实测验证）:
- /filesystem.Filesystem/Stat — Get file/dir info
- /filesystem.Filesystem/MakeDir — Create directory
- /filesystem.Filesystem/ListDir — List directory contents
- /filesystem.Filesystem/Remove — Remove file/directory
- /filesystem.Filesystem/Move — Move/rename file
- /filesystem.Filesystem/WatchDir (streaming) — Watch for changes

HTTP file API（非 Connect RPC，已实测验证）:
- POST /files?path={path}&username=user (multipart) — Upload file → 201
- GET /files?path={path}&username=user — Download file → 200
"""
from __future__ import annotations

import base64
from typing import Any

from easy_sandbox.models.filesystem import FileInfo, FileType, WatchEvent, WatchEventType
from easy_sandbox.models.errors import FileOperationError, FileNotFoundError_
from easy_sandbox.transport.auth import EnvdTokenManager
from easy_sandbox.transport.codec import ConnectCodec
from easy_sandbox.transport.http import HttpClient
from easy_sandbox.transport.streaming import StreamReader
from easy_sandbox.utils.logging import get_logger

logger = get_logger("protocol.filesystem")

_codec = ConnectCodec()

# RPC paths（已实测验证）
_STAT = _codec.build_rpc_path("filesystem", "Filesystem", "Stat")
_MAKE_DIR = _codec.build_rpc_path("filesystem", "Filesystem", "MakeDir")
_LIST_DIR = _codec.build_rpc_path("filesystem", "Filesystem", "ListDir")
_REMOVE = _codec.build_rpc_path("filesystem", "Filesystem", "Remove")
_MOVE = _codec.build_rpc_path("filesystem", "Filesystem", "Move")
_WATCH_DIR = _codec.build_rpc_path("filesystem", "Filesystem", "WatchDir")


def _parse_file_info(data: dict[str, Any]) -> FileInfo:
    """Parse a file info dict from the API response."""
    file_type = FileType.DIRECTORY if data.get("isDir", data.get("type") == "directory") else FileType.FILE
    return FileInfo(
        name=data.get("name", ""),
        path=data.get("path", ""),
        type=file_type,
        size=data.get("size", 0),
    )


def _parse_watch_event(frame: dict[str, Any]) -> WatchEvent:
    """Parse a streaming watch event frame."""
    data = frame.get("result", frame)
    event_type_str = data.get("type", data.get("eventType", "modified"))

    type_map = {
        "created": WatchEventType.CREATED,
        "modified": WatchEventType.MODIFIED,
        "deleted": WatchEventType.DELETED,
        "renamed": WatchEventType.RENAMED,
        "create": WatchEventType.CREATED,
        "modify": WatchEventType.MODIFIED,
        "delete": WatchEventType.DELETED,
        "rename": WatchEventType.RENAMED,
    }
    event_type = type_map.get(event_type_str, WatchEventType.MODIFIED)

    return WatchEvent(
        type=event_type,
        path=data.get("path", ""),
        old_path=data.get("oldPath"),
    )


class FilesystemProtocol:
    """Typed wrapper for envd filesystem operations (Connect protocol + HTTP file API).

    Connect RPC 用于目录操作；HTTP API 用于文件上传/下载（已实测验证）。
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    # --- Connect RPC methods（已实测验证）---

    async def stat(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
    ) -> FileInfo:
        """Get info about a file or directory.

        POST envd_url + /filesystem.Filesystem/Stat（已实测验证）
        """
        response = await self._http.envd_request(
            envd_url, _STAT,
            payload={"path": path},
            envd_token=envd_token,
        )
        data = response.get("result", response)
        return _parse_file_info(data)

    async def list_dir(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str = "/",
    ) -> list[FileInfo]:
        """List directory contents.

        POST envd_url + /filesystem.Filesystem/ListDir（已实测验证）
        """
        response = await self._http.envd_request(
            envd_url, _LIST_DIR,
            payload={"path": path},
            envd_token=envd_token,
        )

        entries = response.get("entries", response.get("result", {}).get("entries", []))
        return [_parse_file_info(entry) for entry in entries]

    async def make_dir(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
    ) -> None:
        """Create a directory (and parents).

        POST envd_url + /filesystem.Filesystem/MakeDir（已实测验证）
        """
        await self._http.envd_request(
            envd_url, _MAKE_DIR,
            payload={"path": path},
            envd_token=envd_token,
        )

    async def remove(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
    ) -> None:
        """Remove a file or directory.

        POST envd_url + /filesystem.Filesystem/Remove（已实测验证）
        """
        await self._http.envd_request(
            envd_url, _REMOVE,
            payload={"path": path},
            envd_token=envd_token,
        )

    async def move(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        source: str,
        destination: str,
    ) -> None:
        """Move/rename a file or directory.

        POST envd_url + /filesystem.Filesystem/Move（已实测验证）
        """
        await self._http.envd_request(
            envd_url, _MOVE,
            payload={"source": source, "destination": destination},
            envd_token=envd_token,
        )

    async def watch_dir(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
    ) -> StreamReader[WatchEvent]:
        """Watch a directory for changes (streaming).

        POST envd_url + /filesystem.Filesystem/WatchDir (Connect streaming, 已实测验证)
        """
        raw_stream = self._http.envd_stream(
            envd_url, _WATCH_DIR,
            payload={"path": path},
            envd_token=envd_token,
        )
        return StreamReader(raw_stream, _parse_watch_event)

    # --- HTTP file API（非 Connect RPC，已实测验证）---

    async def upload_file(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
        content: bytes,
        username: str = "user",
    ) -> None:
        """Upload a file via HTTP multipart POST.

        POST envd_url/files?path={path}&username=user → 201（已实测验证）
        """
        await self._http.envd_http_request(
            envd_url,
            "POST",
            "/files",
            envd_token=envd_token,
            params={"path": path, "username": username},
            files={"file": ("file", content)},
        )

    async def download_file(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
        username: str = "user",
    ) -> bytes:
        """Download a file via HTTP GET.

        GET envd_url/files?path={path}&username=user → 200（已实测验证）
        """
        response = await self._http.envd_http_request(
            envd_url,
            "GET",
            "/files",
            envd_token=envd_token,
            params={"path": path, "username": username},
        )
        return response.content

    # --- convenience wrappers ---

    async def exists(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
    ) -> bool:
        """Check if a file or directory exists (via Stat)."""
        try:
            await self.stat(envd_url, envd_token, path=path)
            return True
        except Exception:
            return False

    async def get_info(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
    ) -> FileInfo:
        """Alias for stat(). Kept for backward compatibility."""
        return await self.stat(envd_url, envd_token, path=path)

    async def read(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
    ) -> bytes:
        """Read file content via HTTP download API."""
        return await self.download_file(envd_url, envd_token, path=path)

    async def read_text(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
        encoding: str = "utf-8",
    ) -> str:
        """Read file content as text."""
        raw = await self.read(envd_url, envd_token, path=path)
        return raw.decode(encoding)

    async def write(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        path: str,
        content: str | bytes,
    ) -> None:
        """Write content to a file via HTTP upload API."""
        if isinstance(content, str):
            raw_bytes = content.encode("utf-8")
        else:
            raw_bytes = content
        await self.upload_file(envd_url, envd_token, path=path, content=raw_bytes)

    async def rename(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        old_path: str,
        new_path: str,
    ) -> None:
        """Deprecated: use move(). Kept for backward compatibility."""
        await self.move(envd_url, envd_token, source=old_path, destination=new_path)
