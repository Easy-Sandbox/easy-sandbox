"""Container-side HTTP server — stdlib-only, zero external dependencies.

Quick start (inside a sandbox template's ``commands.py``)::

    from easy_sandbox.server import start
    start(9000)

Or for more control::

    from easy_sandbox.server import SandboxServer, enable_builtin

    enable_builtin("upload")
    enable_builtin("download")

    server = SandboxServer(host="0.0.0.0")
    server.serve(port=9000)
"""

from __future__ import annotations

from .app import SandboxServer, start
from .registry import CommandArg, CommandRegistry, RegisteredCommand, default_registry
from .router import CapabilityGroup, RouteInfo, RouteTable, default_table
from .routes import (
    disable_builtin,
    enable_builtin,
    get_enabled_builtins,
    is_builtin_enabled,
)
from .routes_pty import (
    PtySession,
    PtySessionManager,
    pty_session_manager,
    start_pty_server,
)
from .types import ServerRequest, ServerResponse, SSEResponse

__all__ = [
    "SandboxServer",
    "start",
    "enable_builtin",
    "disable_builtin",
    "is_builtin_enabled",
    "get_enabled_builtins",
    "CommandArg",
    "CommandRegistry",
    "RegisteredCommand",
    "default_registry",
    "ServerRequest",
    "ServerResponse",
    "SSEResponse",
    "RouteTable",
    "RouteInfo",
    "CapabilityGroup",
    "default_table",
    "PtySession",
    "PtySessionManager",
    "pty_session_manager",
    "start_pty_server",
]
