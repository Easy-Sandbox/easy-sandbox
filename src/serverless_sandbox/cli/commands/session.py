"""Session lifecycle CLI commands: start, connect, list, stop, info."""
from __future__ import annotations

import sys
from typing import Any

import click

from serverless_sandbox.cli.formatters import get_formatter
from serverless_sandbox.cli.main import handle_errors


# ---------------------------------------------------------------------------
# session group
# ---------------------------------------------------------------------------

@click.group()
@click.pass_context
def session(ctx: click.Context) -> None:
    """Manage named sessions (create, resume, list, stop)."""
    ctx.ensure_object(dict)


# ---------------------------------------------------------------------------
# session start
# ---------------------------------------------------------------------------

@session.command()
@click.argument("name")
@click.option("--template", "-T", default="base", help="Sandbox template")
@click.option("--timeout", "-t", type=int, default=300, help="Timeout in seconds")
@click.option("--env", "-e", multiple=True, help="环境变量，格式 KEY=VALUE")
@click.option("--metadata", "-m", multiple=True, help="元数据键值对，格式 KEY=VALUE")
@click.pass_context
@handle_errors
def start(
    ctx: click.Context,
    name: str,
    template: str,
    timeout: int,
    env: tuple[str, ...],
    metadata: tuple[str, ...],
) -> None:
    """Start a new named session."""
    from serverless_sandbox.api.session_manager import SessionManager
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    envs: dict[str, str] = {}
    for item in env:
        if "=" in item:
            k, v = item.split("=", 1)
            envs[k] = v
        else:
            fmt.print_error(f"Invalid environment variable format: {item!r} (expected KEY=VALUE)")
            sys.exit(2)

    meta: dict[str, str] = {}
    for item in metadata:
        if "=" in item:
            k, v = item.split("=", 1)
            meta[k] = v
        else:
            fmt.print_error(f"Invalid metadata format: {item!r} (expected KEY=VALUE)")
            sys.exit(2)

    mgr = SessionManager()
    sandbox = run_sync(
        mgr.start(name, template, timeout=timeout, metadata=meta or None, envs=envs or None)
    )

    data = {
        "Session": name,
        "SandboxID": sandbox.id,
        "Status": sandbox.status.value,
        "Template": template,
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success(f"Session {name!r} started.")


# ---------------------------------------------------------------------------
# session connect
# ---------------------------------------------------------------------------

@session.command("connect")
@click.argument("name")
@click.pass_context
@handle_errors
def connect_session(ctx: click.Context, name: str) -> None:
    """Reconnect to a named session."""
    from serverless_sandbox.api.session_manager import SessionManager
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    mgr = SessionManager()
    sandbox = run_sync(mgr.connect(name))

    data = {
        "Session": name,
        "SandboxID": sandbox.id,
        "Status": sandbox.status.value,
        "URL": sandbox.url,
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success(f"Reconnected to session {name!r}.")


# ---------------------------------------------------------------------------
# session list
# ---------------------------------------------------------------------------

@session.command("list")
@click.pass_context
@handle_errors
def list_sessions(ctx: click.Context) -> None:
    """List all saved sessions."""
    from serverless_sandbox.api.session_manager import SessionManager
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    mgr = SessionManager()
    sessions = run_sync(mgr.list_sessions())

    if not sessions:
        fmt.print_success("No sessions found.")
        return

    headers = ["Name", "SandboxID", "Template", "Status", "Created"]
    rows = [
        [
            s.name,
            s.sandbox_id or "N/A",
            s.template,
            s.status,
            str(s.created_at or "N/A"),
        ]
        for s in sessions
    ]
    fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# session stop
# ---------------------------------------------------------------------------

@session.command()
@click.argument("name")
@click.option("--keep-alive", is_flag=True, help="Keep sandbox alive, only untrack session")
@click.pass_context
@handle_errors
def stop(ctx: click.Context, name: str, keep_alive: bool) -> None:
    """Stop a named session (kill sandbox by default)."""
    from serverless_sandbox.api.session_manager import SessionManager
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    mgr = SessionManager()
    run_sync(mgr.stop(name, kill=not keep_alive))

    if keep_alive:
        fmt.print_success(f"Session {name!r} untracked (sandbox kept alive).")
    else:
        fmt.print_success(f"Session {name!r} stopped and sandbox killed.")


# ---------------------------------------------------------------------------
# session info
# ---------------------------------------------------------------------------

@session.command("info")
@click.argument("name")
@click.pass_context
@handle_errors
def info_session(ctx: click.Context, name: str) -> None:
    """Show details of a named session."""
    from serverless_sandbox.api.session_manager import SessionManager
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    mgr = SessionManager()
    session_info = run_sync(mgr.get_info(name))

    data: dict[str, Any] = {
        "Name": session_info.name,
        "SandboxID": session_info.sandbox_id or "N/A",
        "Template": session_info.template,
        "Status": session_info.status,
        "Created": str(session_info.created_at or "N/A"),
        "LastConnected": str(session_info.last_connected or "N/A"),
    }
    if session_info.metadata:
        data["Metadata"] = str(session_info.metadata)

    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
