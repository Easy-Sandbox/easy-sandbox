"""Process management and streaming shell endpoints.

Provides:
- Streaming shell execution via SSE (``POST /shell/stream``)
- Background process start (``POST /process/start``)
- Process listing (``GET /process/list``)
- Process detail (``GET /process/{pid}``)
- Signal delivery (``POST /process/{pid}/signal``)

All routes are registered under :data:`CapabilityGroup.PROCESS`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shlex
import subprocess  # noqa: S404
import threading
import time
from typing import Any

from .router import CapabilityGroup, default_table
from .types import ServerRequest, ServerResponse, SSEResponse

__all__: list[str] = []

# ---------------------------------------------------------------------------
# Internal process bookkeeping
# ---------------------------------------------------------------------------

_MAX_PROCESSES = 100

_ALLOWED_SIGNALS: frozenset[int] = frozenset({2, 9, 15, 18, 20})


@dataclasses.dataclass
class _ProcessInfo:
    """Metadata about a background process managed by the server."""

    pid: int
    popen: subprocess.Popen[bytes]
    command: str
    started_at: float


_process_table: dict[int, _ProcessInfo] = {}
_process_lock = threading.Lock()


def _poll_process(info: _ProcessInfo) -> str:
    """Return ``"running"`` or ``"exited"`` after polling the process."""
    if info.popen.poll() is None:
        return "running"
    return "exited"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_shell_stream(request: ServerRequest) -> SSEResponse | ServerResponse:
    """``POST /shell/stream`` — execute a command and stream output via SSE."""
    body = request.body or {}
    command = body.get("command")
    if not command or not isinstance(command, str):
        return ServerResponse.error(400, "Missing or invalid 'command'", "ValueError")

    raw_timeout = body.get("timeout", 300)
    try:
        timeout: int | float = float(raw_timeout)
    except (ValueError, TypeError):
        timeout = 300.0
    if timeout <= 0:
        timeout = 300.0
    cwd: str = body.get("cwd", "") or None  # type: ignore[assignment]

    try:
        args = shlex.split(command)
    except ValueError as exc:
        return ServerResponse.error(400, f"Invalid command: {exc}", "ValueError")

    def event_gen() -> Any:  # noqa: ANN401
        try:
            proc = subprocess.Popen(  # noqa: S603
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                shell=False,
            )
        except Exception as exc:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
            return

        start = time.monotonic()

        # Read stdout
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                if time.monotonic() - start > timeout:
                    proc.kill()
                    yield f"event: error\ndata: {json.dumps({'error': 'timeout'})}\n\n"
                    proc.wait()
                    yield f"event: exit\ndata: {json.dumps({'exit_code': proc.returncode})}\n\n"
                    return
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                yield f"event: stdout\ndata: {json.dumps({'data': line})}\n\n"

        # Read stderr
        if proc.stderr is not None:
            for raw_line in proc.stderr:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                yield f"event: stderr\ndata: {json.dumps({'data': line})}\n\n"

        proc.wait()
        yield f"event: exit\ndata: {json.dumps({'exit_code': proc.returncode})}\n\n"

    return SSEResponse(event_iterator=event_gen())


def _handle_process_start(request: ServerRequest) -> ServerResponse:
    """``POST /process/start`` — start a background process."""
    body = request.body or {}
    command = body.get("command")
    if not command or not isinstance(command, str):
        return ServerResponse.error(400, "Missing or invalid 'command'", "ValueError")

    with _process_lock:
        if len(_process_table) >= _MAX_PROCESSES:
            return ServerResponse.error(
                429,
                f"Process limit reached ({_MAX_PROCESSES})",
                "ResourceError",
            )

    cwd: str | None = body.get("cwd", "") or None

    try:
        args = shlex.split(command)
    except ValueError as exc:
        return ServerResponse.error(400, f"Invalid command: {exc}", "ValueError")

    try:
        proc = subprocess.Popen(  # noqa: S603
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            shell=False,
        )
    except Exception as exc:  # noqa: BLE001
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    info = _ProcessInfo(
        pid=proc.pid,
        popen=proc,
        command=command,
        started_at=time.time(),
    )
    with _process_lock:
        _process_table[proc.pid] = info

    return ServerResponse.ok({"pid": proc.pid, "command": command})


def _handle_process_list(request: ServerRequest) -> ServerResponse:
    """``GET /process/list`` — list managed background processes."""
    processes: list[dict[str, Any]] = []
    with _process_lock:
        # Clean up exited processes while holding the lock.
        exited = [pid for pid, info in _process_table.items() if info.popen.poll() is not None]
        for pid in exited:
            _process_table.pop(pid, None)
        snapshot = list(_process_table.values())
    for info in snapshot:
        state = _poll_process(info)
        processes.append({
            "pid": info.pid,
            "command": info.command,
            "state": state,
            "started_at": info.started_at,
        })
    return ServerResponse.ok({"processes": processes})


def _handle_process_detail(request: ServerRequest) -> ServerResponse:
    """``GET /process/{pid}`` — get details of a single managed process."""
    raw_pid = request.path_params.get("pid", "")
    try:
        pid = int(raw_pid)
    except (ValueError, TypeError):
        return ServerResponse.error(400, f"Invalid pid: {raw_pid!r}", "ValueError")

    with _process_lock:
        info = _process_table.get(pid)
    if info is None:
        return ServerResponse.error(404, f"Process {pid} not found", "NotFoundError")

    state = _poll_process(info)
    result: dict[str, Any] = {
        "pid": info.pid,
        "command": info.command,
        "state": state,
        "started_at": info.started_at,
    }
    if state == "exited":
        result["exit_code"] = info.popen.returncode
    else:
        result["exit_code"] = None
    return ServerResponse.ok(result)


def _handle_process_signal(request: ServerRequest) -> ServerResponse:
    """``POST /process/{pid}/signal`` — send a signal to a managed process."""
    raw_pid = request.path_params.get("pid", "")
    try:
        pid = int(raw_pid)
    except (ValueError, TypeError):
        return ServerResponse.error(400, f"Invalid pid: {raw_pid!r}", "ValueError")

    body = request.body or {}
    sig = body.get("signal")
    if sig is None:
        return ServerResponse.error(400, "Missing 'signal' in body", "ValueError")

    try:
        sig = int(sig)
    except (ValueError, TypeError):
        return ServerResponse.error(400, f"Invalid signal value: {sig!r}", "ValueError")

    if sig not in _ALLOWED_SIGNALS:
        return ServerResponse.error(
            400,
            f"Signal {sig} not allowed; permitted: {sorted(_ALLOWED_SIGNALS)}",
            "ValueError",
        )

    # Safety: refuse to kill PID 1 or own process.
    if pid == 1 or pid == os.getpid():
        return ServerResponse.error(
            403, f"Refusing to signal pid {pid}", "PermissionError"
        )

    with _process_lock:
        info = _process_table.get(pid)
    if info is None:
        return ServerResponse.error(404, f"Process {pid} not found", "NotFoundError")

    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return ServerResponse.error(404, f"Process {pid} not found (os)", "NotFoundError")
    except PermissionError as exc:
        return ServerResponse.error(403, str(exc), "PermissionError")
    except Exception as exc:  # noqa: BLE001
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    return ServerResponse.ok({"pid": pid, "signal": sig})


# ---------------------------------------------------------------------------
# Route registration (import side-effect)
# ---------------------------------------------------------------------------

_table = default_table()
_table.register(
    "POST", "/shell/stream", _handle_shell_stream,
    group=CapabilityGroup.PROCESS, streaming=True, name="shell_stream",
)
_table.register(
    "POST", "/process/start", _handle_process_start,
    group=CapabilityGroup.PROCESS, name="process_start",
)
_table.register(
    "GET", "/process/list", _handle_process_list,
    group=CapabilityGroup.PROCESS, name="process_list",
)
_table.register(
    "GET", "/process/{pid}", _handle_process_detail,
    group=CapabilityGroup.PROCESS, name="process_detail",
)
_table.register(
    "POST", "/process/{pid}/signal", _handle_process_signal,
    group=CapabilityGroup.PROCESS, name="process_signal",
)
