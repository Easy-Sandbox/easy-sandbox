"""File-operation route handlers for the sandbox HTTP server.

Provides endpoints for directory listing, file stat, mkdir, delete, move,
search, streaming upload/download, and archive creation.  All routes are
registered on the module-level default :class:`RouteTable` at import time
(side-effect) under :data:`CapabilityGroup.FILE_OPS`.
"""

from __future__ import annotations

import base64
import fnmatch
import io
import os
import shutil
import tarfile
import threading
import zipfile
from datetime import datetime, timezone
from typing import Any

from .router import CapabilityGroup, default_table
from .routes import _resolve_safe_path
from .types import ServerRequest, ServerResponse

__all__: list[str] = []

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ENTRIES = 1000
_DEFAULT_MAX_DEPTH = 3
_SEARCH_MAX_DEPTH = 5
_SEARCH_MAX_RESULTS = 100
_SEARCH_TIMEOUT_SECONDS = 10
_CHUNK_SIZE = 64 * 1024  # 64 KB
_DEFAULT_MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
_MAX_UPLOAD_ENV_VAR = "SBOX_MAX_UPLOAD_SIZE"
_ARCHIVE_MAX_SIZE = 100 * 1024 * 1024  # 100 MB
_ARCHIVE_MAX_FILES = 10_000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_mtime(ts: float) -> str:
    """Convert a POSIX timestamp to an ISO 8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _max_upload_size() -> int:
    """Return the configured maximum upload size in bytes."""
    raw = os.environ.get(_MAX_UPLOAD_ENV_VAR, "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_MAX_UPLOAD_SIZE


def _entry_type(path: str) -> str:
    """Return ``'file'``, ``'directory'``, or ``'symlink'``."""
    if os.path.islink(path):
        return "symlink"
    if os.path.isdir(path):
        return "directory"
    return "file"


# ---------------------------------------------------------------------------
# GET /files/list
# ---------------------------------------------------------------------------


def _handle_files_list(request: ServerRequest) -> ServerResponse:
    """List directory contents, optionally recursive."""
    raw_path = request.query.get("path", [""])[0]
    if not raw_path:
        return ServerResponse.error(400, "Missing 'path' query parameter", "ValueError")

    recursive_str = request.query.get("recursive", ["false"])[0].lower()
    recursive = recursive_str in {"true", "yes", "1"}

    try:
        max_entries = int(request.query.get("max_entries", [str(_DEFAULT_MAX_ENTRIES)])[0])
    except ValueError:
        max_entries = _DEFAULT_MAX_ENTRIES

    max_entries = min(max_entries, _DEFAULT_MAX_ENTRIES)

    try:
        safe_path = _resolve_safe_path(raw_path)
    except ValueError as exc:
        return ServerResponse.error(400, str(exc), "ValueError")

    if not os.path.isdir(safe_path):
        return ServerResponse.error(404, f"Directory not found: {raw_path}", "FileNotFoundError")

    base_dir = os.environ.get("SBOX_SERVER_BASE_DIR", "/home/user")
    base_dir = os.path.realpath(base_dir)

    entries: list[dict[str, Any]] = []

    def _scan(dir_path: str, depth: int) -> None:
        if len(entries) >= max_entries:
            return
        try:
            with os.scandir(dir_path) as it:
                for entry in it:
                    if len(entries) >= max_entries:
                        return
                    # Don't follow symlinks that point outside base_dir
                    if entry.is_symlink():
                        real = os.path.realpath(entry.path)
                        if not real.startswith(base_dir + os.sep) and real != base_dir:
                            continue
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append({
                        "name": entry.name,
                        "type": "directory" if entry.is_dir(follow_symlinks=False) else "file",
                        "size": stat.st_size,
                        "modified": _iso_mtime(stat.st_mtime),
                    })
                    is_subdir = entry.is_dir(follow_symlinks=False)
                    if recursive and is_subdir and depth < _DEFAULT_MAX_DEPTH:
                        _scan(entry.path, depth + 1)
        except PermissionError:
            pass

    _scan(safe_path, 1)
    return ServerResponse.ok({"entries": entries})


# ---------------------------------------------------------------------------
# GET /files/stat
# ---------------------------------------------------------------------------


def _handle_files_stat(request: ServerRequest) -> ServerResponse:
    """Return stat information for a single file or directory."""
    raw_path = request.query.get("path", [""])[0]
    if not raw_path:
        return ServerResponse.error(400, "Missing 'path' query parameter", "ValueError")

    try:
        safe_path = _resolve_safe_path(raw_path)
    except ValueError as exc:
        return ServerResponse.error(400, str(exc), "ValueError")

    exists = os.path.exists(safe_path)
    if not exists:
        return ServerResponse.ok({
            "name": os.path.basename(safe_path),
            "path": safe_path,
            "type": "unknown",
            "size": 0,
            "permissions": "",
            "modified": "",
            "exists": False,
        })

    try:
        st = os.stat(safe_path, follow_symlinks=False)
    except OSError as exc:
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    return ServerResponse.ok({
        "name": os.path.basename(safe_path),
        "path": safe_path,
        "type": _entry_type(safe_path),
        "size": st.st_size,
        "permissions": oct(st.st_mode)[-3:],
        "modified": _iso_mtime(st.st_mtime),
        "exists": True,
    })


# ---------------------------------------------------------------------------
# POST /files/mkdir
# ---------------------------------------------------------------------------


def _handle_files_mkdir(request: ServerRequest) -> ServerResponse:
    """Create a directory (with parents)."""
    body = request.body or {}
    raw_path = body.get("path", "")
    if not raw_path or not isinstance(raw_path, str):
        return ServerResponse.error(400, "Missing or invalid 'path'", "ValueError")

    try:
        safe_path = _resolve_safe_path(raw_path)
    except ValueError as exc:
        return ServerResponse.error(400, str(exc), "ValueError")

    try:
        os.makedirs(safe_path, exist_ok=True)
    except OSError as exc:
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    return ServerResponse.ok({"path": safe_path, "created": True})


# ---------------------------------------------------------------------------
# DELETE /files
# ---------------------------------------------------------------------------


def _handle_files_delete(request: ServerRequest) -> ServerResponse:
    """Delete a file or directory."""
    raw_path = request.query.get("path", [""])[0]
    if not raw_path:
        return ServerResponse.error(400, "Missing 'path' query parameter", "ValueError")

    try:
        safe_path = _resolve_safe_path(raw_path)
    except ValueError as exc:
        return ServerResponse.error(400, str(exc), "ValueError")

    if not os.path.exists(safe_path):
        return ServerResponse.error(404, f"Path not found: {raw_path}", "FileNotFoundError")

    try:
        if os.path.isdir(safe_path):
            shutil.rmtree(safe_path)
        else:
            os.remove(safe_path)
    except OSError as exc:
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    return ServerResponse.ok({"path": safe_path, "deleted": True})


# ---------------------------------------------------------------------------
# POST /files/move
# ---------------------------------------------------------------------------


def _handle_files_move(request: ServerRequest) -> ServerResponse:
    """Move or rename a file/directory."""
    body = request.body or {}
    source = body.get("source", "")
    destination = body.get("destination", "")

    if not source or not isinstance(source, str):
        return ServerResponse.error(400, "Missing or invalid 'source'", "ValueError")
    if not destination or not isinstance(destination, str):
        return ServerResponse.error(400, "Missing or invalid 'destination'", "ValueError")

    try:
        safe_src = _resolve_safe_path(source)
    except ValueError as exc:
        return ServerResponse.error(400, f"source: {exc}", "ValueError")

    try:
        safe_dst = _resolve_safe_path(destination)
    except ValueError as exc:
        return ServerResponse.error(400, f"destination: {exc}", "ValueError")

    if not os.path.exists(safe_src):
        return ServerResponse.error(404, f"Source not found: {source}", "FileNotFoundError")

    try:
        # Ensure destination parent exists
        os.makedirs(os.path.dirname(safe_dst) or ".", exist_ok=True)
        shutil.move(safe_src, safe_dst)
    except OSError as exc:
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    return ServerResponse.ok({"source": safe_src, "destination": safe_dst})


# ---------------------------------------------------------------------------
# POST /files/search
# ---------------------------------------------------------------------------


def _handle_files_search(request: ServerRequest) -> ServerResponse:
    """Search for files matching a glob pattern."""
    body = request.body or {}
    raw_path = body.get("path", "")
    pattern = body.get("pattern", "")

    if not raw_path or not isinstance(raw_path, str):
        return ServerResponse.error(400, "Missing or invalid 'path'", "ValueError")
    if not pattern or not isinstance(pattern, str):
        return ServerResponse.error(400, "Missing or invalid 'pattern'", "ValueError")

    try:
        max_depth = int(body.get("max_depth", _SEARCH_MAX_DEPTH))
        max_results = int(body.get("max_results", _SEARCH_MAX_RESULTS))
    except (ValueError, TypeError):
        return ServerResponse.error(
            400,
            "Invalid 'max_depth' or 'max_results': must be integers",
            "ValueError",
        )

    try:
        safe_path = _resolve_safe_path(raw_path)
    except ValueError as exc:
        return ServerResponse.error(400, str(exc), "ValueError")

    if not os.path.isdir(safe_path):
        return ServerResponse.error(404, f"Directory not found: {raw_path}", "FileNotFoundError")

    results: list[dict[str, str]] = []
    timed_out = False
    cancelled = threading.Event()

    # Use a timer thread for timeout (works in any thread, unlike SIGALRM)
    timer = threading.Timer(_SEARCH_TIMEOUT_SECONDS, cancelled.set)
    timer.start()

    try:
        for dirpath, dirnames, filenames in os.walk(safe_path):
            if cancelled.is_set():
                timed_out = True
                break
            rel_depth = dirpath[len(safe_path):].count(os.sep)
            if rel_depth >= max_depth:
                dirnames.clear()
                continue
            for name in filenames:
                if cancelled.is_set():
                    timed_out = True
                    break
                if fnmatch.fnmatch(name, pattern):
                    full = os.path.join(dirpath, name)
                    results.append({
                        "name": name,
                        "path": full,
                    })
                    if len(results) >= max_results:
                        break
            if len(results) >= max_results or timed_out:
                break
    finally:
        timer.cancel()

    return ServerResponse.ok({
        "results": results,
        "timed_out": timed_out,
    })


# ---------------------------------------------------------------------------
# POST /files/upload-stream
# ---------------------------------------------------------------------------


def _handle_files_upload_stream(request: ServerRequest) -> ServerResponse:
    """Upload a file via base64-encoded content with chunked decoding."""
    body = request.body or {}
    raw_path = body.get("path", "")
    content_b64 = body.get("content_base64", "")

    if not raw_path or not isinstance(raw_path, str):
        return ServerResponse.error(400, "Missing or invalid 'path'", "ValueError")
    if not content_b64 or not isinstance(content_b64, str):
        return ServerResponse.error(400, "Missing or invalid 'content_base64'", "ValueError")

    try:
        safe_path = _resolve_safe_path(raw_path)
    except ValueError as exc:
        return ServerResponse.error(400, str(exc), "ValueError")

    # Decode the full base64 first to validate, then write in chunks
    try:
        data = base64.b64decode(content_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        return ServerResponse.error(400, f"Invalid base64: {exc}", "ValueError")

    max_size = _max_upload_size()
    if len(data) > max_size:
        return ServerResponse.error(
            413,
            f"File size {len(data)} exceeds limit {max_size}",
            "ValueError",
        )

    try:
        os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
        with open(safe_path, "wb") as f:
            offset = 0
            while offset < len(data):
                chunk = data[offset : offset + _CHUNK_SIZE]
                f.write(chunk)
                offset += _CHUNK_SIZE
    except OSError as exc:
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    return ServerResponse.ok({"path": safe_path, "bytes": len(data)})


# ---------------------------------------------------------------------------
# GET /files/download-stream
# ---------------------------------------------------------------------------


def _handle_files_download_stream(request: ServerRequest) -> ServerResponse:
    """Download a file, reading in chunks and returning base64."""
    raw_path = request.query.get("path", [""])[0]
    if not raw_path:
        return ServerResponse.error(400, "Missing 'path' query parameter", "ValueError")

    try:
        safe_path = _resolve_safe_path(raw_path)
    except ValueError as exc:
        return ServerResponse.error(400, str(exc), "ValueError")

    if not os.path.isfile(safe_path):
        return ServerResponse.error(
            404, f"File not found: {raw_path}", "FileNotFoundError"
        )

    try:
        buf = io.BytesIO()
        with open(safe_path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK_SIZE)
                if not chunk:
                    break
                buf.write(chunk)
        file_data = buf.getvalue()
    except OSError as exc:
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    return ServerResponse.ok({
        "path": safe_path,
        "content_base64": base64.b64encode(file_data).decode("ascii"),
        "bytes": len(file_data),
    })


# ---------------------------------------------------------------------------
# POST /files/archive
# ---------------------------------------------------------------------------


def _handle_files_archive(request: ServerRequest) -> ServerResponse:
    """Create an archive (tar.gz or zip) from a list of paths."""
    body = request.body or {}
    paths = body.get("paths")
    fmt = body.get("format", "tar.gz")

    if not paths or not isinstance(paths, list):
        return ServerResponse.error(400, "Missing or invalid 'paths'", "ValueError")
    if fmt not in {"tar.gz", "zip"}:
        return ServerResponse.error(400, f"Unsupported format: {fmt}", "ValueError")

    safe_paths: list[str] = []
    for raw in paths:
        if not isinstance(raw, str):
            return ServerResponse.error(400, "All paths must be strings", "ValueError")
        try:
            safe_paths.append(_resolve_safe_path(raw))
        except ValueError as exc:
            return ServerResponse.error(400, str(exc), "ValueError")

    # Validate all paths exist
    for sp in safe_paths:
        if not os.path.exists(sp):
            return ServerResponse.error(404, f"Path not found: {sp}", "FileNotFoundError")

    # Count files and check limits
    total_files = 0
    for sp in safe_paths:
        if os.path.isfile(sp):
            total_files += 1
        elif os.path.isdir(sp):
            for _dirpath, _dirnames, filenames in os.walk(sp):
                total_files += len(filenames)
                if total_files > _ARCHIVE_MAX_FILES:
                    return ServerResponse.error(
                        400,
                        f"Too many files ({total_files}+), limit is {_ARCHIVE_MAX_FILES}",
                        "ValueError",
                    )

    buf = io.BytesIO()
    try:
        if fmt == "tar.gz":
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for sp in safe_paths:
                    tar.add(sp, arcname=os.path.basename(sp))
        else:
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for sp in safe_paths:
                    if os.path.isfile(sp):
                        zf.write(sp, os.path.basename(sp))
                    elif os.path.isdir(sp):
                        base_name = os.path.basename(sp)
                        for dirpath, _dirnames, filenames in os.walk(sp):
                            for fname in filenames:
                                full = os.path.join(dirpath, fname)
                                arcname = os.path.join(
                                    base_name, os.path.relpath(full, sp)
                                )
                                zf.write(full, arcname)
    except OSError as exc:
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    archive_data = buf.getvalue()
    if len(archive_data) > _ARCHIVE_MAX_SIZE:
        return ServerResponse.error(
            413,
            f"Archive size {len(archive_data)} exceeds limit {_ARCHIVE_MAX_SIZE}",
            "ValueError",
        )

    return ServerResponse.ok({
        "content_base64": base64.b64encode(archive_data).decode("ascii"),
        "format": fmt,
        "bytes": len(archive_data),
    })


# ---------------------------------------------------------------------------
# Route registration (import side-effect)
# ---------------------------------------------------------------------------

_table = default_table()

_table.register(
    "GET", "/files/list", _handle_files_list,
    group=CapabilityGroup.FILE_OPS, name="files_list",
)
_table.register(
    "GET", "/files/stat", _handle_files_stat,
    group=CapabilityGroup.FILE_OPS, name="files_stat",
)
_table.register(
    "POST", "/files/mkdir", _handle_files_mkdir,
    group=CapabilityGroup.FILE_OPS, name="files_mkdir",
)
_table.register(
    "DELETE", "/files", _handle_files_delete,
    group=CapabilityGroup.FILE_OPS, name="files_delete",
)
_table.register(
    "POST", "/files/move", _handle_files_move,
    group=CapabilityGroup.FILE_OPS, name="files_move",
)
_table.register(
    "POST", "/files/search", _handle_files_search,
    group=CapabilityGroup.FILE_OPS, name="files_search",
)
_table.register(
    "POST", "/files/upload-stream", _handle_files_upload_stream,
    group=CapabilityGroup.FILE_OPS, name="files_upload_stream",
)
_table.register(
    "GET", "/files/download-stream", _handle_files_download_stream,
    group=CapabilityGroup.FILE_OPS, name="files_download_stream",
)
_table.register(
    "POST", "/files/archive", _handle_files_archive,
    group=CapabilityGroup.FILE_OPS, name="files_archive",
)
