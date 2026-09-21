"""PTY WebSocket terminal system — REST management API and interactive terminal.

Provides:

- **REST management** (registered on the HTTP :class:`RouteTable`, group
  :data:`CapabilityGroup.TERMINAL`):

  ======  =======================  ================================
  Method  Path                     Description
  ======  =======================  ================================
  POST    ``/pty/sessions``        Create a new PTY session
  GET     ``/pty/sessions``        List active sessions
  DELETE  ``/pty/sessions/{id}``   Close and destroy a session
  ======  =======================  ================================

- **WebSocket interactive terminal** served on a dedicated port (default
  ``9001``).  Each connection is associated with a PTY session created via the
  REST API.  The protocol uses JSON messages:

  Client → Server::

      {"type": "input",  "data": "ls\\n"}
      {"type": "resize", "cols": 120, "rows": 40}
      {"type": "signal", "signal": "SIGINT"}

  Server → Client::

      {"type": "output", "data": "..."}
      {"type": "event",  "event": "started"|"exited", ...}

.. note::

   The ``pty`` module is only available on Unix.  On other platforms the
   module can still be imported but session creation will raise
   :class:`OSError`.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import json
import logging
import os
import pty
import select
import signal
import struct
import subprocess  # noqa: S404
import termios
import threading
import time
import uuid
from typing import Any

from .router import CapabilityGroup, default_table
from .types import ServerRequest, ServerResponse

__all__ = [
    "PtySession",
    "PtySessionManager",
    "pty_session_manager",
    "pty_ws_handler",
    "start_pty_server",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PtySession
# ---------------------------------------------------------------------------


class PtySession:
    """Encapsulate a single PTY session (pseudo-terminal + child process).

    Args:
        shell: Path to the shell executable (default ``"/bin/bash"``).
        cols: Initial terminal width in columns.
        rows: Initial terminal height in rows.
        env: Extra environment variables merged into the child's environ.
    """

    def __init__(
        self,
        shell: str = "/bin/bash",
        cols: int = 80,
        rows: int = 24,
        env: dict[str, str] | None = None,
    ) -> None:
        self.id: str = uuid.uuid4().hex[:12]
        self.created_at: float = time.time()
        self.last_activity: float = self.created_at
        self._cols = cols
        self._rows = rows

        # Create the pseudo-terminal pair.
        master_fd, slave_fd = pty.openpty()
        self._master_fd: int = master_fd

        # Set initial terminal size.
        self._set_winsize(slave_fd, rows, cols)

        # Build child environment.
        child_env = os.environ.copy()
        child_env["TERM"] = "xterm-256color"
        if env:
            child_env.update(env)

        # Spawn the shell process with stdin/stdout/stderr on the slave PTY.
        self._process = subprocess.Popen(  # noqa: S603
            [shell],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,  # noqa: PLW1509
            env=child_env,
            close_fds=True,
        )
        # The parent no longer needs the slave fd.
        os.close(slave_fd)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _set_winsize(fd: int, rows: int, cols: int) -> None:
        """Set the terminal window size on file descriptor *fd*."""
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    # -- public API -------------------------------------------------------

    def read(self, timeout: float = 0.1) -> bytes:
        """Non-blocking read from the PTY master.

        Returns:
            Data read from the PTY, or ``b""`` if nothing was available within
            *timeout* seconds.
        """
        try:
            rlist, _, _ = select.select([self._master_fd], [], [], timeout)
        except (ValueError, OSError):
            return b""
        if rlist:
            try:
                return os.read(self._master_fd, 4096)
            except OSError:
                return b""
        return b""

    def write(self, data: bytes) -> None:
        """Write *data* to the PTY master (i.e. send input to the shell)."""
        self.last_activity = time.time()
        try:
            os.write(self._master_fd, data)
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal to *cols* × *rows*."""
        self._cols = cols
        self._rows = rows
        self.last_activity = time.time()
        try:
            self._set_winsize(self._master_fd, rows, cols)
        except OSError:
            pass

    def send_signal(self, sig: int) -> None:
        """Send signal *sig* to the shell process group."""
        self.last_activity = time.time()
        try:
            os.killpg(os.getpgid(self._process.pid), sig)
        except (OSError, ProcessLookupError):
            pass

    def close(self) -> None:
        """Close the session, terminate the shell process, and free the fd."""
        try:
            self._process.terminate()
        except OSError:
            pass
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                self._process.kill()
                self._process.wait(timeout=1)
            except OSError:
                pass
        try:
            os.close(self._master_fd)
        except OSError:
            pass

    @property
    def is_alive(self) -> bool:
        """Return whether the shell process is still running."""
        return self._process.poll() is None

    @property
    def pid(self) -> int:
        """Return the PID of the shell process."""
        return self._process.pid

    @property
    def cols(self) -> int:
        """Current terminal width."""
        return self._cols

    @property
    def rows(self) -> int:
        """Current terminal height."""
        return self._rows

    def to_dict(self) -> dict[str, Any]:
        """Serialise session metadata to a JSON-friendly dict."""
        return {
            "id": self.id,
            "pid": self.pid,
            "created_at": self.created_at,
            "cols": self._cols,
            "rows": self._rows,
            "alive": self.is_alive,
        }


# ---------------------------------------------------------------------------
# PtySessionManager
# ---------------------------------------------------------------------------


class PtySessionManager:
    """Manage all PTY sessions with an upper-bound and idle-timeout policy.

    Attributes:
        MAX_SESSIONS: Maximum number of concurrent sessions.
        IDLE_TIMEOUT: Seconds of inactivity after which a session is reaped.
    """

    MAX_SESSIONS: int = 10
    IDLE_TIMEOUT: int = 1800  # 30 minutes

    def __init__(self) -> None:
        self._sessions: dict[str, PtySession] = {}
        self._lock = threading.Lock()

    def create(
        self,
        shell: str = "/bin/bash",
        cols: int = 80,
        rows: int = 24,
        env: dict[str, str] | None = None,
    ) -> PtySession:
        """Create a new PTY session.

        Raises:
            RuntimeError: If the session limit has been reached.
        """
        with self._lock:
            # Reap dead sessions first.
            self._reap_dead()
            if len(self._sessions) >= self.MAX_SESSIONS:
                raise RuntimeError(
                    f"Session limit reached ({self.MAX_SESSIONS})"
                )
            session = PtySession(shell=shell, cols=cols, rows=rows, env=env)
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str) -> PtySession | None:
        """Return the session with *session_id*, or ``None``."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return a list of metadata dicts for all active sessions."""
        with self._lock:
            self._reap_dead()
            return [s.to_dict() for s in self._sessions.values()]

    def close(self, session_id: str) -> bool:
        """Close and remove the session.  Return ``True`` if it existed."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()
            return True
        return False

    def cleanup_idle(self) -> int:
        """Close sessions idle longer than :attr:`IDLE_TIMEOUT`.

        Returns:
            Number of sessions cleaned up.
        """
        now = time.time()
        to_close: list[str] = []
        with self._lock:
            for sid, sess in self._sessions.items():
                if now - sess.last_activity > self.IDLE_TIMEOUT:
                    to_close.append(sid)
            for sid in to_close:
                sess = self._sessions.pop(sid, None)
                if sess is not None:
                    sess.close()
        return len(to_close)

    def close_all(self) -> None:
        """Close every open session (used during server shutdown)."""
        with self._lock:
            for sess in self._sessions.values():
                sess.close()
            self._sessions.clear()

    # -- internals --------------------------------------------------------

    def _reap_dead(self) -> None:
        """Remove sessions whose shell process has exited (caller holds lock)."""
        dead = [sid for sid, s in self._sessions.items() if not s.is_alive]
        for sid in dead:
            sess = self._sessions.pop(sid, None)
            if sess is not None:
                sess.close()


# Module-level singleton.
pty_session_manager = PtySessionManager()


# ---------------------------------------------------------------------------
# REST handlers (registered on the HTTP RouteTable)
# ---------------------------------------------------------------------------


def _handle_create_session(request: ServerRequest) -> ServerResponse:
    """``POST /pty/sessions`` — create a new PTY session."""
    body = request.body or {}
    shell: str = body.get("shell", "/bin/bash")
    try:
        cols: int = int(body.get("cols", 80))
        rows: int = int(body.get("rows", 24))
    except (ValueError, TypeError):
        return ServerResponse.error(
            400,
            "Invalid 'cols' or 'rows': must be integers",
            "ValueError",
        )
    env: dict[str, str] | None = body.get("env")

    try:
        session = pty_session_manager.create(
            shell=shell, cols=cols, rows=rows, env=env,
        )
    except RuntimeError as exc:
        return ServerResponse.error(429, str(exc), "RuntimeError")
    except OSError as exc:
        return ServerResponse.error(500, str(exc), "OSError")

    # Construct ws_url — the WebSocket server runs on a separate port.
    try:
        pty_port = int(os.environ.get("EBX_PTY_PORT", "9001"))
    except (ValueError, TypeError):
        pty_port = 9001
    ws_url = f"ws://localhost:{pty_port}/pty?session_id={session.id}"

    return ServerResponse.ok({
        "session_id": session.id,
        "ws_url": ws_url,
        "pid": session.pid,
    })


def _handle_list_sessions(request: ServerRequest) -> ServerResponse:
    """``GET /pty/sessions`` — list active PTY sessions."""
    sessions = pty_session_manager.list_sessions()
    return ServerResponse.ok({"sessions": sessions})


def _handle_delete_session(request: ServerRequest) -> ServerResponse:
    """``DELETE /pty/sessions/{id}`` — close and destroy a PTY session."""
    session_id = request.path_params.get("id", "")
    if not session_id:
        return ServerResponse.error(400, "Missing session id", "ValueError")

    removed = pty_session_manager.close(session_id)
    if not removed:
        return ServerResponse.error(
            404, f"Session not found: {session_id}", "ValueError",
        )
    return ServerResponse.ok({"status": "closed", "session_id": session_id})


# ---------------------------------------------------------------------------
# Register REST routes on the default table (import side-effect)
# ---------------------------------------------------------------------------

_table = default_table()
_table.register(
    "POST", "/pty/sessions", _handle_create_session,
    group=CapabilityGroup.TERMINAL, name="pty_create_session",
)
_table.register(
    "GET", "/pty/sessions", _handle_list_sessions,
    group=CapabilityGroup.TERMINAL, name="pty_list_sessions",
)
_table.register(
    "DELETE", "/pty/sessions/{id}", _handle_delete_session,
    group=CapabilityGroup.TERMINAL, name="pty_delete_session",
)


# ---------------------------------------------------------------------------
# WebSocket PTY handler
# ---------------------------------------------------------------------------

_SIGNAL_MAP: dict[str, int] = {
    "SIGINT": signal.SIGINT,
    "SIGTERM": signal.SIGTERM,
    "SIGKILL": signal.SIGKILL,
    "SIGHUP": signal.SIGHUP,
    "SIGQUIT": signal.SIGQUIT,
}


async def pty_ws_handler(websocket: Any) -> None:
    """WebSocket handler for interactive PTY I/O.

    The client must connect to ``ws://<host>:<port>/pty?session_id=<id>``.
    """
    import websockets  # noqa: F811

    # Extract session_id from the request path / query.
    raw_path: str = websocket.request.path if hasattr(websocket, "request") else getattr(websocket, "path", "")
    session_id = _extract_query_param(raw_path, "session_id")

    if not session_id:
        await websocket.close(1008, "Missing session_id parameter")
        return

    session = pty_session_manager.get(session_id)
    if session is None:
        await websocket.close(1008, f"Unknown session: {session_id}")
        return

    # Notify the client that the session is connected.
    await websocket.send(json.dumps({
        "type": "event",
        "event": "started",
        "session_id": session.id,
        "pid": session.pid,
    }))

    # Launch a background task that reads PTY output and forwards to WS.
    read_task = asyncio.ensure_future(_pty_read_loop(websocket, session))

    try:
        async for raw_msg in websocket:
            try:
                if isinstance(raw_msg, bytes):
                    raw_msg = raw_msg.decode("utf-8")
                msg = json.loads(raw_msg) if isinstance(raw_msg, str) else raw_msg
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                continue

            msg_type = msg.get("type")
            if msg_type == "input":
                data = msg.get("data", "")
                if isinstance(data, str):
                    data = data.encode("utf-8")
                session.write(data)
            elif msg_type == "resize":
                try:
                    cols = int(msg.get("cols", session.cols))
                    rows = int(msg.get("rows", session.rows))
                except (ValueError, TypeError):
                    continue
                session.resize(cols, rows)
            elif msg_type == "signal":
                sig_name = msg.get("signal", "SIGINT")
                sig = _SIGNAL_MAP.get(sig_name)
                if sig is None:
                    continue
                session.send_signal(sig)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        read_task.cancel()
        try:
            await read_task
        except asyncio.CancelledError:
            pass

        # Send an exited event if the process has ended.
        if not session.is_alive:
            try:
                await websocket.send(json.dumps({
                    "type": "event",
                    "event": "exited",
                    "session_id": session.id,
                }))
            except Exception:  # noqa: BLE001
                pass


async def _pty_read_loop(websocket: Any, session: PtySession) -> None:
    """Continuously read PTY output and send to the WebSocket client."""
    loop = asyncio.get_event_loop()
    while True:
        try:
            data = await loop.run_in_executor(None, session.read, 0.1)
            if data:
                await websocket.send(json.dumps({
                    "type": "output",
                    "data": data.decode("utf-8", errors="replace"),
                }))
            else:
                await asyncio.sleep(0.05)

            # If the shell process has exited, send a final event.
            if not session.is_alive:
                # Drain remaining output.
                remaining = await loop.run_in_executor(None, session.read, 0.1)
                if remaining:
                    await websocket.send(json.dumps({
                        "type": "output",
                        "data": remaining.decode("utf-8", errors="replace"),
                    }))
                await websocket.send(json.dumps({
                    "type": "event",
                    "event": "exited",
                    "session_id": session.id,
                }))
                break
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            break


# ---------------------------------------------------------------------------
# WebSocket server entry point
# ---------------------------------------------------------------------------


async def start_pty_server(
    host: str = "0.0.0.0",  # noqa: S104
    port: int = 9001,
    stop_event: asyncio.Event | None = None,
    ready_event: threading.Event | None = None,
) -> None:
    """Start the PTY WebSocket server.

    Args:
        host: Bind address.
        port: TCP port.
        stop_event: If provided, the server will stop when this event is set.
            Otherwise it will run forever.  Must be created in the same event
            loop that runs this coroutine.
        ready_event: A :class:`threading.Event` set once the server is
            listening — useful for tests to avoid race conditions.
    """
    import websockets

    async with websockets.serve(pty_ws_handler, host, port):
        if ready_event is not None:
            ready_event.set()
        if stop_event is not None:
            await stop_event.wait()
        else:
            await asyncio.Future()  # run forever


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_query_param(path: str, param: str) -> str | None:
    """Extract a single query parameter from a raw URL path string."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(path)
    values = parse_qs(parsed.query).get(param, [])
    return values[0] if values else None
