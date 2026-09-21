"""Sandbox process-management CLI commands: list, start, info, signal."""
from __future__ import annotations

import sys
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors

# ---------------------------------------------------------------------------
# Helper: connect to sandbox
# ---------------------------------------------------------------------------


def _connect_sandbox(sandbox_id: str) -> Any:
    """Connect to a sandbox by ID (sync helper)."""
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    return run_sync(Sandbox.connect(sandbox_id))


# ---------------------------------------------------------------------------
# process list
# ---------------------------------------------------------------------------


@click.command("list")
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def process_list(ctx: click.Context, sandbox_id: str) -> None:
    """List running processes in a sandbox.

    Examples:\n
        ebx sandbox process list abc123
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    processes = run_sync(sandbox.commands.list())

    if not processes:
        fmt.print_success("No processes found.")
        return

    if fmt.use_json:
        fmt.print_data([
            {"pid": p.pid, "command": p.command, "status": p.status}
            for p in processes
        ])
    else:
        headers = ["PID", "Command", "Status"]
        rows = [
            [str(p.pid), p.command, p.status]
            for p in processes
        ]
        fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# process start
# ---------------------------------------------------------------------------


@click.command("start")
@click.argument("sandbox_id")
@click.option("--command", "-c", "cmd", required=True, help="Command to run in background")
@click.option("--timeout", "-t", "cmd_timeout", type=int, default=300, help="Timeout in seconds")
@click.option("--cwd", default="", help="Working directory")
@click.pass_context
@handle_errors
def process_start(
    ctx: click.Context,
    sandbox_id: str,
    cmd: str,
    cmd_timeout: int,
    cwd: str,
) -> None:
    """Start a background process in a sandbox.

    The process runs asynchronously; output is collected and displayed.

    Examples:\n
        ebx sandbox process start abc123 --command "python app.py"\n
        ebx sandbox process start abc123 -c "node server.js" --cwd /app
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    result = run_sync(sandbox.commands.run(cmd, timeout=cmd_timeout, cwd=cwd))

    if fmt.use_json:
        fmt.print_data({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "execution_time": result.execution_time,
        })
    else:
        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.stderr:
            click.echo(result.stderr, err=True, nl=False)
        if result.exit_code == 0:
            fmt.print_success("Process completed successfully.")
        else:
            fmt.print_error(f"Process exited with code {result.exit_code}.")

    sys.exit(result.exit_code)


# ---------------------------------------------------------------------------
# process info
# ---------------------------------------------------------------------------


@click.command("info")
@click.argument("sandbox_id")
@click.argument("pid", type=int)
@click.pass_context
@handle_errors
def process_info(ctx: click.Context, sandbox_id: str, pid: int) -> None:
    """Get details of a process by PID.

    Uses ps to query process information from the sandbox.

    Examples:\n
        ebx sandbox process info abc123 1234
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    # Use ps for process info
    result = run_sync(sandbox.commands.run(
        f"ps -p {pid} -o pid=,ppid=,user=,stat=,rss=,etime=,comm= 2>/dev/null",
        timeout=10,
    ))

    if result.exit_code != 0 or not result.stdout.strip():
        fmt.print_error(f"Process {pid} not found or not accessible.")
        sys.exit(1)

    lines = result.stdout.strip().splitlines()
    if not lines:
        fmt.print_error(f"Process {pid} not found.")
        sys.exit(1)

    # Parse ps output
    parts = lines[0].split(None, 6)
    data: dict[str, Any] = {"PID": str(pid)}
    labels = ["PPID", "User", "State", "RSS(KB)", "Elapsed", "Command"]
    for i, label in enumerate(labels):
        if i + 1 < len(parts):
            data[label] = parts[i + 1]

    fmt.print_dict(data)


# ---------------------------------------------------------------------------
# process signal
# ---------------------------------------------------------------------------


@click.command("signal")
@click.argument("sandbox_id")
@click.argument("pid", type=int)
@click.option(
    "--signal", "-s", "sig", type=int, default=15,
    help="Signal number (default: 15/SIGTERM)",
)
@click.pass_context
@handle_errors
def process_signal(
    ctx: click.Context,
    sandbox_id: str,
    pid: int,
    sig: int,
) -> None:
    """Send a signal to a process in the sandbox.

    Common signals: 15 (SIGTERM), 9 (SIGKILL), 2 (SIGINT).

    Examples:\n
        ebx sandbox process signal abc123 1234\n
        ebx sandbox process signal abc123 1234 --signal 9
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    run_sync(sandbox.commands.send_signal(pid, sig))
    fmt.print_success(f"Signal {sig} sent to process {pid}.")


# ---------------------------------------------------------------------------
# process group
# ---------------------------------------------------------------------------


@click.group()
@click.pass_context
def process(ctx: click.Context) -> None:
    """Process management in a sandbox (list, start, info, signal)."""
    ctx.ensure_object(dict)


process.add_command(process_list, "list")
process.add_command(process_start, "start")
process.add_command(process_info, "info")
process.add_command(process_signal, "signal")
