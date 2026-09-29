"""Built-in route handlers and dynamic route registry for the sandbox HTTP server.

Provides:
- Health check (``/health``)
- Command listing (``GET /commands``) and execution (``POST /commands/{name}``)
- File upload (``POST /upload``) and download (``GET /download``)
- Shell execution (``POST /shell``)

All built-in routes except ``/health`` and ``/commands`` can be toggled via
:func:`enable_builtin` / :func:`disable_builtin`.
"""

from __future__ import annotations

import base64
import os
import shlex
import subprocess
from typing import Any

from easy_sandbox.utils.coerce import coerce_kwargs as _coerce_kwargs

# Backward-compatible built-in toggle API — now backed by capability groups.
# Re-exported here so existing imports (``from ...routes import enable_builtin``)
# and the historical ``_KNOWN_BUILTINS`` / ``_enabled_builtins`` attributes keep
# working.  See :mod:`easy_sandbox.server._compat`.
from ._compat import (  # noqa: F401  (re-exported for backward compatibility)
    _KNOWN_BUILTINS,
    _enabled_builtins,
    disable_builtin,
    enable_builtin,
    get_enabled_builtins,
    is_builtin_enabled,
)
from .registry import CommandArg, CommandRegistry, default_registry  # noqa: F401
from .router import CapabilityGroup, default_table
from .types import ServerRequest, ServerResponse

__all__ = [
    "enable_builtin",
    "disable_builtin",
    "is_builtin_enabled",
    "get_enabled_builtins",
    "handle_health",
    "handle_list_commands",
    "handle_run_command",
    "handle_upload",
    "handle_download",
    "handle_shell",
]

# ---------------------------------------------------------------------------
# Upload / download size constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
_MAX_UPLOAD_ENV_VAR = "EBX_MAX_UPLOAD_SIZE"


def _max_upload_size() -> int:
    """Return the configured maximum upload size in bytes."""
    raw = os.environ.get(_MAX_UPLOAD_ENV_VAR, "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_MAX_UPLOAD_SIZE


# ---------------------------------------------------------------------------
# Path-safety helper
# ---------------------------------------------------------------------------

_BASE_DIR_ENV_VAR = "EBX_SERVER_BASE_DIR"
_DEFAULT_BASE_DIR = "/home/user"


def _resolve_safe_path(raw_path: str, base_dir: str | None = None) -> str:
    """Resolve *raw_path* and ensure it stays under *base_dir*.

    Args:
        raw_path: The untrusted path provided by the client.
        base_dir: Allowed root directory.  Falls back to the
            ``EBX_SERVER_BASE_DIR`` env-var, then ``/home/user``.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: If the resolved path escapes *base_dir*.
    """
    if base_dir is None:
        base_dir = os.environ.get(_BASE_DIR_ENV_VAR, _DEFAULT_BASE_DIR)

    # Normalise base_dir itself so trailing slashes don't confuse the check.
    base_dir = os.path.realpath(base_dir)

    resolved = os.path.realpath(os.path.normpath(raw_path))

    # The resolved path must be the base dir itself or a child of it.
    if resolved != base_dir and not resolved.startswith(base_dir + os.sep):
        raise ValueError("Path escapes base directory")

    return resolved


# ---------------------------------------------------------------------------
# Route handlers — each returns ``(status_code, response_body_dict)``
# ---------------------------------------------------------------------------


def handle_health() -> tuple[int, dict[str, Any]]:
    """``GET /health`` — always 200."""
    return 200, {"status": "ok"}


def handle_list_commands(
    registry: CommandRegistry | None = None,
) -> tuple[int, dict[str, Any]]:
    """``GET /commands`` — list all registered commands from the sandbox registry.

    Args:
        registry: The :class:`CommandRegistry` to query.  When ``None``,
            the module-level :func:`default_registry` is used.
    """
    if registry is None:
        registry = default_registry()
    commands: list[dict[str, Any]] = []
    for name, cmd in registry.list_visible().items():
        args_list: list[dict[str, Any]] = []
        for arg in cmd.args:
            args_list.append(
                {
                    "name": arg.name,
                    "type": arg.type,
                    "required": arg.required,
                    "default": arg.default,
                    "description": arg.description,
                }
            )
        commands.append({"name": name, "args": args_list, "description": cmd.description})
    return 200, {"commands": commands}


# ---------------------------------------------------------------------------
# Coerce helper — canonical implementation in easy_sandbox.utils.coerce
# ---------------------------------------------------------------------------
# ``_coerce_kwargs`` is imported at the top of this module from
# ``easy_sandbox.utils.coerce.coerce_kwargs``.  The server and declarative
# layers share the same implementation to prevent behavioural drift.


def handle_run_command(
    command_name: str,
    body: dict[str, Any],
    registry: CommandRegistry | None = None,
) -> tuple[int, dict[str, Any]]:
    """``POST /commands/{name}`` — execute a registered command.

    Args:
        command_name: The registered command name extracted from the URL path.
        body: Parsed JSON body containing kwargs for the command.
        registry: The :class:`CommandRegistry` to look up commands from.
            When ``None``, the module-level :func:`default_registry` is used.

    Returns:
        ``(status_code, response_dict)``
    """
    if registry is None:
        registry = default_registry()
    # 1. Lookup
    cmd = registry.get(command_name)
    if cmd is None:
        all_cmds = registry.list_all()
        available = ", ".join(sorted(all_cmds)) or "(none)"
        return 404, {
            "error": f"Unknown command {command_name!r}; available: {available}",
            "type": "ValueError",
        }

    # 2. Coerce / validate kwargs
    try:
        coerced = _coerce_kwargs(cmd.args, body)
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc), "type": type(exc).__name__}

    # 3. Execute the command function directly.
    try:
        result = cmd.fn(**coerced)
    except Exception as exc:
        return 500, {"error": str(exc), "type": type(exc).__name__}

    return 200, {"result": result}


def handle_upload(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """``POST /upload`` — write base64-encoded content to the local filesystem.

    Expected *body*::

        {"path": "/some/file.txt", "content_base64": "<base64>"}

    Returns:
        ``(status_code, response_dict)``
    """
    path = body.get("path")
    content_b64 = body.get("content_base64")
    if not path or not isinstance(path, str):
        return 400, {"error": "Missing or invalid 'path'", "type": "ValueError"}
    if not content_b64 or not isinstance(content_b64, str):
        return 400, {
            "error": "Missing or invalid 'content_base64'",
            "type": "ValueError",
        }

    try:
        data = base64.b64decode(content_b64, validate=True)
    except Exception as exc:
        return 400, {"error": f"Invalid base64: {exc}", "type": "ValueError"}

    # Enforce upload size limit (consistent with routes_files.py).
    max_size = _max_upload_size()
    if len(data) > max_size:
        return 413, {
            "error": f"File size {len(data)} exceeds limit {max_size}",
            "type": "ValueError",
        }

    # Path-traversal guard
    try:
        safe_path = _resolve_safe_path(path)
    except ValueError as exc:
        return 400, {"error": str(exc), "type": "ValueError"}

    try:
        os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
        with open(safe_path, "wb") as f:
            f.write(data)
    except Exception as exc:
        return 500, {"error": str(exc), "type": type(exc).__name__}

    return 200, {"path": safe_path, "bytes": len(data)}


def handle_download(path: str) -> tuple[int, dict[str, Any]]:
    """``GET /download?path=...`` — read a file and return base64-encoded content.

    Args:
        path: Filesystem path to read.

    Returns:
        ``(status_code, response_dict)``
    """
    if not path:
        return 400, {"error": "Missing 'path' query parameter", "type": "ValueError"}

    # Path-traversal guard
    try:
        safe_path = _resolve_safe_path(path)
    except ValueError as exc:
        return 400, {"error": str(exc), "type": "ValueError"}

    if not os.path.isfile(safe_path):
        return 404, {
            "error": f"File not found: {safe_path}",
            "type": "FileNotFoundError",
        }

    # Enforce download size limit.
    try:
        file_size = os.path.getsize(safe_path)
    except OSError as exc:
        return 500, {"error": str(exc), "type": type(exc).__name__}
    max_size = _max_upload_size()  # reuse same configurable limit
    if file_size > max_size:
        return 413, {
            "error": f"File size {file_size} exceeds download limit {max_size}",
            "type": "ValueError",
        }

    try:
        with open(safe_path, "rb") as f:
            data = f.read()
    except Exception as exc:
        return 500, {"error": str(exc), "type": type(exc).__name__}

    return 200, {
        "path": safe_path,
        "content_base64": base64.b64encode(data).decode("ascii"),
    }


def handle_shell(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """``POST /shell`` — execute a shell command via subprocess.

    Expected *body*::

        {"command": "ls -la /tmp"}

    Returns:
        ``(status_code, response_dict)``
    """
    command = body.get("command")
    if not command or not isinstance(command, str):
        return 400, {"error": "Missing or invalid 'command'", "type": "ValueError"}

    try:
        proc = subprocess.run(
            shlex.split(command),
            shell=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return 500, {
            "error": "Command timed out after 300s",
            "type": "TimeoutError",
        }
    except Exception as exc:
        return 500, {"error": str(exc), "type": type(exc).__name__}

    return 200, {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
    }


# ---------------------------------------------------------------------------
# Route-table adapters
# ---------------------------------------------------------------------------
#
# Each wrapper adapts a legacy ``handle_*`` function (which returns a
# ``(status, body)`` tuple) to the uniform route signature
# ``(request: ServerRequest) -> ServerResponse`` expected by the dispatcher.
# The active :class:`CommandRegistry` is injected by ``app.py`` under
# ``request.context["registry"]``.


def _handle_health_wrapped(request: ServerRequest) -> ServerResponse:
    """Adapt :func:`handle_health` to the route signature."""
    status, body = handle_health()
    return ServerResponse(status=status, body=body)


def _handle_commands_wrapped(request: ServerRequest) -> ServerResponse:
    """Adapt :func:`handle_list_commands` (``GET /commands``)."""
    registry = request.context.get("registry")
    status, body = handle_list_commands(registry)
    return ServerResponse(status=status, body=body)


def _handle_run_command_wrapped(request: ServerRequest) -> ServerResponse:
    """Adapt :func:`handle_run_command` (``POST /commands/{name}``)."""
    command_name = request.path_params.get("name", "")
    body = request.body or {}
    registry = request.context.get("registry")
    status, resp = handle_run_command(command_name, body, registry)
    return ServerResponse(status=status, body=resp)


def _handle_upload_wrapped(request: ServerRequest) -> ServerResponse:
    """Adapt :func:`handle_upload` (``POST /upload``)."""
    status, resp = handle_upload(request.body or {})
    return ServerResponse(status=status, body=resp)


def _handle_download_wrapped(request: ServerRequest) -> ServerResponse:
    """Adapt :func:`handle_download` (``GET /download?path=...``)."""
    file_path = request.query.get("path", [""])[0]
    status, body = handle_download(file_path)
    return ServerResponse(status=status, body=body)


def _handle_shell_wrapped(request: ServerRequest) -> ServerResponse:
    """Adapt :func:`handle_shell` (``POST /shell``)."""
    status, resp = handle_shell(request.body or {})
    return ServerResponse(status=status, body=resp)


# ---------------------------------------------------------------------------
# Register the built-in routes on the default table (import side-effect)
# ---------------------------------------------------------------------------

_table = default_table()
_table.register(
    "GET",
    "/health",
    _handle_health_wrapped,
    group=CapabilityGroup.CORE,
    auth_required=False,
    name="health",
)
_table.register(
    "GET",
    "/commands",
    _handle_commands_wrapped,
    group=CapabilityGroup.COMMANDS,
    name="list_commands",
)
_table.register(
    "POST",
    "/commands/{name}",
    _handle_run_command_wrapped,
    group=CapabilityGroup.COMMANDS,
    name="run_command",
)
_table.register(
    "POST",
    "/upload",
    _handle_upload_wrapped,
    group=CapabilityGroup.FILE_OPS,
    name="upload",
)
_table.register(
    "GET",
    "/download",
    _handle_download_wrapped,
    group=CapabilityGroup.FILE_OPS,
    name="download",
)
_table.register(
    "POST",
    "/shell",
    _handle_shell_wrapped,
    group=CapabilityGroup.PROCESS,
    name="shell",
)
