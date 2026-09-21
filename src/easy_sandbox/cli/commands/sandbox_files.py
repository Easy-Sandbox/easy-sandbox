"""Sandbox file-operation CLI commands: list, stat, mkdir, rm, mv, search."""
from __future__ import annotations

import shlex
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
# files list
# ---------------------------------------------------------------------------


@click.command("list")
@click.argument("sandbox_id")
@click.option("--path", "-p", default="/home/user", help="Directory path to list")
@click.option("--recursive", "-r", is_flag=True, help="List recursively")
@click.pass_context
@handle_errors
def files_list(
    ctx: click.Context,
    sandbox_id: str,
    path: str,
    recursive: bool,
) -> None:
    """List directory contents in a sandbox.

    Examples:\n
        ebx sandbox files list abc123\n
        ebx sandbox files list abc123 --path /app --recursive
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    if recursive:
        # Use shell find for recursive listing
        result = run_sync(sandbox.commands.run(
            f"find {shlex.quote(path)} -maxdepth 5 2>/dev/null",
            timeout=30,
        ))
        if fmt.use_json:
            lines = [ln for ln in result.stdout.strip().splitlines() if ln]
            fmt.print_data({"path": path, "entries": lines})
        else:
            if result.stdout.strip():
                click.echo(result.stdout.rstrip())
            else:
                fmt.print_success(f"Directory {path} is empty.")
    else:
        entries = run_sync(sandbox.files.list(path))
        if not entries:
            fmt.print_success(f"Directory {path} is empty.")
            return

        if fmt.use_json:
            fmt.print_data([
                {
                    "name": e.name,
                    "type": e.type.value,
                    "size": e.size,
                }
                for e in entries
            ])
        else:
            headers = ["Name", "Type", "Size"]
            rows = [
                [e.name, e.type.value, str(e.size)]
                for e in entries
            ]
            fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# files stat
# ---------------------------------------------------------------------------


@click.command("stat")
@click.argument("sandbox_id")
@click.option("--path", "-p", required=True, help="File or directory path")
@click.pass_context
@handle_errors
def files_stat(ctx: click.Context, sandbox_id: str, path: str) -> None:
    """Get file or directory information.

    Examples:\n
        ebx sandbox files stat abc123 --path /home/user/app.py
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    info = run_sync(sandbox.files.get_info(path))
    data = {
        "Name": info.name,
        "Path": info.path,
        "Type": info.type.value,
        "Size": str(info.size),
    }
    fmt.print_dict(data)


# ---------------------------------------------------------------------------
# files mkdir
# ---------------------------------------------------------------------------


@click.command("mkdir")
@click.argument("sandbox_id")
@click.option("--path", "-p", required=True, help="Directory path to create")
@click.pass_context
@handle_errors
def files_mkdir(ctx: click.Context, sandbox_id: str, path: str) -> None:
    """Create a directory (including parent directories).

    Examples:\n
        ebx sandbox files mkdir abc123 --path /home/user/myproject/src
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    run_sync(sandbox.files.make_dir(path))
    fmt.print_success(f"Directory created: {path}")


# ---------------------------------------------------------------------------
# files rm
# ---------------------------------------------------------------------------


@click.command("rm")
@click.argument("sandbox_id")
@click.option("--path", "-p", required=True, help="File or directory path to delete")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
@handle_errors
def files_rm(
    ctx: click.Context,
    sandbox_id: str,
    path: str,
    yes: bool,
) -> None:
    """Delete a file or directory in the sandbox.

    Examples:\n
        ebx sandbox files rm abc123 --path /home/user/temp.txt\n
        ebx sandbox files rm abc123 --path /home/user/old_dir -y
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    if not yes:
        click.confirm(f"Delete {path} in sandbox {sandbox_id}?", abort=True)

    sandbox = _connect_sandbox(sandbox_id)
    run_sync(sandbox.files.remove(path))
    fmt.print_success(f"Deleted: {path}")


# ---------------------------------------------------------------------------
# files mv
# ---------------------------------------------------------------------------


@click.command("mv")
@click.argument("sandbox_id")
@click.option("--source", "-s", required=True, help="Source path")
@click.option("--dest", "-d", required=True, help="Destination path")
@click.pass_context
@handle_errors
def files_mv(
    ctx: click.Context,
    sandbox_id: str,
    source: str,
    dest: str,
) -> None:
    """Move or rename a file/directory in the sandbox.

    Examples:\n
        ebx sandbox files mv abc123 --source /home/user/old.py --dest /home/user/new.py
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    run_sync(sandbox.files.move(source, dest))
    fmt.print_success(f"Moved: {source} -> {dest}")


# ---------------------------------------------------------------------------
# files search
# ---------------------------------------------------------------------------


@click.command("search")
@click.argument("sandbox_id")
@click.option("--path", "-p", required=True, help="Directory to search in")
@click.option("--pattern", required=True, help="Glob pattern (e.g. '*.py')")
@click.option("--max-depth", type=int, default=5, help="Max search depth")
@click.pass_context
@handle_errors
def files_search(
    ctx: click.Context,
    sandbox_id: str,
    path: str,
    pattern: str,
    max_depth: int,
) -> None:
    """Search for files matching a glob pattern.

    Examples:\n
        ebx sandbox files search abc123 --path /home/user --pattern "*.py"\n
        ebx sandbox files search abc123 --path /app --pattern "*.log" --max-depth 3
    """
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    cmd = (
        f"find {shlex.quote(path)} -maxdepth {max_depth} "
        f"-name {shlex.quote(pattern)} -type f 2>/dev/null"
    )
    result = run_sync(sandbox.commands.run(cmd, timeout=30))

    lines = [ln for ln in result.stdout.strip().splitlines() if ln]

    if fmt.use_json:
        fmt.print_data({"path": path, "pattern": pattern, "results": lines})
    else:
        if lines:
            for ln in lines:
                click.echo(ln)
            fmt.print_success(f"Found {len(lines)} file(s).")
        else:
            fmt.print_success("No files found matching the pattern.")


# ---------------------------------------------------------------------------
# files group
# ---------------------------------------------------------------------------


@click.group()
@click.pass_context
def files(ctx: click.Context) -> None:
    """File operations in a sandbox (list, stat, mkdir, rm, mv, search)."""
    ctx.ensure_object(dict)


files.add_command(files_list, "list")
files.add_command(files_stat, "stat")
files.add_command(files_mkdir, "mkdir")
files.add_command(files_rm, "rm")
files.add_command(files_mv, "mv")
files.add_command(files_search, "search")

