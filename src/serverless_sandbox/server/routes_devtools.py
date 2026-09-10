"""Developer-tools route handlers — code interpreter and Git inspection.

All routes in this module belong to :data:`CapabilityGroup.DEV_TOOLS`, which
is **disabled by default**.  Callers must explicitly enable it via
``default_table().enable_group(CapabilityGroup.DEV_TOOLS)`` before requests
will be dispatched.

Endpoints:
- ``POST /code/run`` — execute code in Python / Node / Bash
- ``GET  /git/status`` — porcelain ``git status``
- ``GET  /git/diff`` — ``git diff`` with optional ``--staged``
"""

from __future__ import annotations

import subprocess  # noqa: S404
import time
from typing import Any

from .router import CapabilityGroup, default_table
from .types import ServerRequest, ServerResponse

__all__ = [
    "handle_code_run",
    "handle_git_diff",
    "handle_git_status",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_TIMEOUT = 300  # seconds
_DEFAULT_TIMEOUT = 30  # seconds
_MAX_DIFF_BYTES = 1_048_576  # 1 MB

_LANGUAGE_COMMANDS: dict[str, list[str]] = {
    "python": ["python3", "-c"],
    "node": ["node", "-e"],
    "bash": ["bash", "-c"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_query(request: ServerRequest, key: str, default: str = "") -> str:
    """Return the first value for *key* in the query-string, or *default*."""
    values = request.query.get(key, [])
    return values[0] if values else default


def _parse_bool_query(request: ServerRequest, key: str, default: bool = False) -> bool:
    """Parse a boolean query-string parameter."""
    raw = _first_query(request, key, "")
    if not raw:
        return default
    return raw.lower() in {"true", "yes", "1"}


def _validate_git_path(path: str) -> ServerResponse | None:
    """Reject path-traversal attempts (``..``)."""
    if ".." in path.split("/"):
        return ServerResponse.error(
            400,
            "Path traversal ('..') is not allowed",
            error_type="ValueError",
        )
    return None


# ---------------------------------------------------------------------------
# POST /code/run
# ---------------------------------------------------------------------------


def handle_code_run(request: ServerRequest) -> ServerResponse:
    """Execute code in a subprocess and return stdout/stderr/exit_code.

    Expected JSON body::

        {"code": "print('hello')", "language": "python", "timeout": 30}

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` containing ``stdout``, ``stderr``,
        ``exit_code``, ``language``, and ``execution_time_ms``.
    """
    body: dict[str, Any] = request.body or {}

    code = body.get("code")
    if not code or not isinstance(code, str):
        return ServerResponse.error(
            400, "Missing or invalid 'code'", error_type="ValueError",
        )

    language: str = str(body.get("language", "python")).lower()
    if language not in _LANGUAGE_COMMANDS:
        supported = ", ".join(sorted(_LANGUAGE_COMMANDS))
        return ServerResponse.error(
            400,
            f"Unsupported language {language!r}; supported: {supported}",
            error_type="ValueError",
        )

    raw_timeout = body.get("timeout", _DEFAULT_TIMEOUT)
    try:
        timeout = min(int(raw_timeout), _MAX_TIMEOUT)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT
    if timeout <= 0:
        timeout = _DEFAULT_TIMEOUT

    cmd = [*_LANGUAGE_COMMANDS[language], code]

    start_ns = time.monotonic_ns()
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        return ServerResponse.error(
            408,
            f"Code execution timed out after {timeout}s",
            error_type="TimeoutError",
        )
    except FileNotFoundError:
        return ServerResponse.error(
            500,
            f"Runtime not found for language {language!r}",
            error_type="FileNotFoundError",
        )
    except Exception as exc:  # noqa: BLE001
        return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000

    return ServerResponse.ok({
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
        "language": language,
        "execution_time_ms": round(elapsed_ms, 2),
    })


# ---------------------------------------------------------------------------
# GET /git/status
# ---------------------------------------------------------------------------


def _parse_porcelain_status(output: str) -> dict[str, Any]:
    """Parse ``git status --porcelain -b`` output.

    Returns:
        ``{"branch": str, "clean": bool, "files": [{"path": str, "status": str}]}``
    """
    status_map: dict[str, str] = {
        "M": "modified",
        "A": "added",
        "D": "deleted",
        "R": "renamed",
        "?": "untracked",
        "C": "copied",
        "U": "unmerged",
    }

    lines = output.splitlines()
    branch = ""
    files: list[dict[str, str]] = []

    for line in lines:
        if line.startswith("## "):
            # e.g. "## main...origin/main" or "## HEAD (no branch)"
            branch_part = line[3:]
            # Strip tracking info after "..."
            branch = branch_part.split("...")[0] if "..." in branch_part else branch_part
            continue

        if len(line) < 4:
            continue

        # Format: "XY path" where X=index, Y=worktree
        xy = line[:2]
        filepath = line[3:]

        # Use the most significant status character
        status_char = xy[0] if xy[0] != " " else xy[1]
        status_label = status_map.get(status_char, status_char)
        files.append({"path": filepath, "status": status_label})

    return {
        "branch": branch,
        "clean": len(files) == 0,
        "files": files,
    }


def handle_git_status(request: ServerRequest) -> ServerResponse:
    """Return parsed ``git status --porcelain -b`` for a repository.

    Query parameters:
        path: Working directory (default ``"."``).

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``branch``, ``clean``, and ``files``.
    """
    path = _first_query(request, "path", ".")

    err = _validate_git_path(path)
    if err is not None:
        return err

    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", path, "status", "--porcelain", "-b"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except FileNotFoundError:
        return ServerResponse.error(
            500, "git is not installed", error_type="FileNotFoundError",
        )
    except subprocess.TimeoutExpired:
        return ServerResponse.error(
            408, "git status timed out", error_type="TimeoutError",
        )
    except Exception as exc:  # noqa: BLE001
        return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    if proc.returncode != 0:
        return ServerResponse.error(
            400,
            proc.stderr.strip() or "git status failed",
            error_type="GitError",
        )

    result = _parse_porcelain_status(proc.stdout)
    return ServerResponse.ok(result)


# ---------------------------------------------------------------------------
# GET /git/diff
# ---------------------------------------------------------------------------


def _parse_diff_stat(stat_output: str) -> dict[str, int]:
    """Parse ``git diff --stat`` summary line.

    The last line looks like::

        3 files changed, 10 insertions(+), 2 deletions(-)

    Returns:
        ``{"files_changed": int, "insertions": int, "deletions": int}``
    """
    stats: dict[str, int] = {"files_changed": 0, "insertions": 0, "deletions": 0}
    lines = stat_output.strip().splitlines()
    if not lines:
        return stats

    summary = lines[-1]
    import re

    m_files = re.search(r"(\d+)\s+files?\s+changed", summary)
    m_ins = re.search(r"(\d+)\s+insertions?\(\+\)", summary)
    m_del = re.search(r"(\d+)\s+deletions?\(-\)", summary)

    if m_files:
        stats["files_changed"] = int(m_files.group(1))
    if m_ins:
        stats["insertions"] = int(m_ins.group(1))
    if m_del:
        stats["deletions"] = int(m_del.group(1))

    return stats


def handle_git_diff(request: ServerRequest) -> ServerResponse:
    """Return ``git diff`` output with statistics.

    Query parameters:
        path: Working directory (default ``"."``).
        staged: If ``"true"``, use ``git diff --staged`` (default ``"false"``).
        file: Restrict diff to a single file (default ``""``).

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``diff`` (text) and ``stats``.
    """
    path = _first_query(request, "path", ".")
    staged = _parse_bool_query(request, "staged", default=False)
    file_filter = _first_query(request, "file", "")

    err = _validate_git_path(path)
    if err is not None:
        return err

    if file_filter and ".." in file_filter.split("/"):
        return ServerResponse.error(
            400,
            "Path traversal ('..') is not allowed in file parameter",
            error_type="ValueError",
        )

    # Build the diff command
    diff_cmd: list[str] = ["git", "-C", path, "diff"]
    if staged:
        diff_cmd.append("--staged")
    if file_filter:
        diff_cmd.extend(["--", file_filter])

    # Build the stat command
    stat_cmd: list[str] = ["git", "-C", path, "diff", "--stat"]
    if staged:
        stat_cmd.append("--staged")
    if file_filter:
        stat_cmd.extend(["--", file_filter])

    try:
        diff_proc = subprocess.run(  # noqa: S603
            diff_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        stat_proc = subprocess.run(  # noqa: S603
            stat_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except FileNotFoundError:
        return ServerResponse.error(
            500, "git is not installed", error_type="FileNotFoundError",
        )
    except subprocess.TimeoutExpired:
        return ServerResponse.error(
            408, "git diff timed out", error_type="TimeoutError",
        )
    except Exception as exc:  # noqa: BLE001
        return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    if diff_proc.returncode != 0:
        return ServerResponse.error(
            400,
            diff_proc.stderr.strip() or "git diff failed",
            error_type="GitError",
        )

    diff_text = diff_proc.stdout
    # Limit diff output to 1 MB
    if len(diff_text.encode("utf-8", errors="replace")) > _MAX_DIFF_BYTES:
        diff_text = diff_text[:_MAX_DIFF_BYTES] + "\n... (truncated at 1MB)"

    stats = _parse_diff_stat(stat_proc.stdout)

    return ServerResponse.ok({
        "diff": diff_text,
        "stats": stats,
    })


# ---------------------------------------------------------------------------
# Register routes on the default table (import side-effect)
# ---------------------------------------------------------------------------

_table = default_table()
_table.register(
    "POST", "/code/run", handle_code_run,
    group=CapabilityGroup.DEV_TOOLS, name="code_run",
)
_table.register(
    "GET", "/git/status", handle_git_status,
    group=CapabilityGroup.DEV_TOOLS, name="git_status",
)
_table.register(
    "GET", "/git/diff", handle_git_diff,
    group=CapabilityGroup.DEV_TOOLS, name="git_diff",
)
