"""Sandbox system, capabilities, and shell-stream CLI commands."""
from __future__ import annotations

import json as json_module
import sys
from typing import Any

import click

from serverless_sandbox.cli.formatters import get_formatter
from serverless_sandbox.cli.main import handle_errors

# ---------------------------------------------------------------------------
# Helper: connect to sandbox
# ---------------------------------------------------------------------------


def _connect_sandbox(sandbox_id: str) -> Any:
    """Connect to a sandbox by ID (sync helper)."""
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    return run_sync(Sandbox.connect(sandbox_id))


# ---------------------------------------------------------------------------
# system info
# ---------------------------------------------------------------------------


@click.command("info")
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def system_info(ctx: click.Context, sandbox_id: str) -> None:
    """Show system information of a sandbox.

    Displays OS, architecture, CPU, memory, disk, and Python version.

    Examples:\n
        sbox sandbox system info abc123
    """
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    script = (
        "python3 -c \""
        "import platform, os, sys, shutil;"
        "u=platform.uname();"
        "d=shutil.disk_usage('/');"
        "print(f'OS: {u.system}');"
        "print(f'Arch: {u.machine}');"
        "print(f'Hostname: {u.node}');"
        "print(f'CPU_Count: {os.cpu_count()}');"
        "print(f'Python: {sys.version.split()[0]}');"
        "print(f'Disk_Total_GB: {round(d.total/(1024**3),2)}');"
        "print(f'Disk_Free_GB: {round(d.free/(1024**3),2)}')"
        "\""
    )
    result = run_sync(sandbox.commands.run(script, timeout=15))

    if result.exit_code != 0:
        # Fallback to simpler command
        result = run_sync(sandbox.commands.run("uname -a", timeout=10))
        if fmt.use_json:
            fmt.print_data({"raw": result.stdout.strip()})
        else:
            click.echo(result.stdout.rstrip())
        return

    data: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if ": " in line:
            key, val = line.split(": ", 1)
            data[key] = val

    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)


# ---------------------------------------------------------------------------
# system env
# ---------------------------------------------------------------------------


@click.command("env")
@click.argument("sandbox_id")
@click.option(
    "--filter", "-f", "env_filter", default="",
    help="Comma-separated variable names to show",
)
@click.pass_context
@handle_errors
def system_env(ctx: click.Context, sandbox_id: str, env_filter: str) -> None:
    """Show environment variables from a sandbox.

    Sensitive variables (containing TOKEN, SECRET, KEY, PASSWORD) are excluded.

    Examples:\n
        sbox sandbox system env abc123\n
        sbox sandbox system env abc123 --filter PATH,HOME,LANG
    """
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    result = run_sync(sandbox.commands.run("env", timeout=10))

    if result.exit_code != 0:
        fmt.print_error("Failed to retrieve environment variables.")
        sys.exit(1)

    # Parse env output
    sensitive_tokens = {"TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL"}
    whitelist: set[str] | None = None
    if env_filter:
        whitelist = {v.strip() for v in env_filter.split(",") if v.strip()}

    variables: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        # Skip sensitive variables
        upper_name = name.upper()
        if any(tok in upper_name for tok in sensitive_tokens):
            continue
        if whitelist is not None and name not in whitelist:
            continue
        variables[name] = value

    if fmt.use_json:
        fmt.print_data({"variables": variables})
    else:
        if not variables:
            fmt.print_success("No matching environment variables found.")
        else:
            for name, value in sorted(variables.items()):
                click.echo(f"{name}={value}")


# ---------------------------------------------------------------------------
# system ports
# ---------------------------------------------------------------------------


@click.command("ports")
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def system_ports(ctx: click.Context, sandbox_id: str) -> None:
    """Show listening TCP ports in a sandbox.

    Examples:\n
        sbox sandbox system ports abc123
    """
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    result = run_sync(sandbox.commands.run(
        "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null || echo 'NO_TOOL'",
        timeout=10,
    ))

    if result.exit_code != 0 or "NO_TOOL" in result.stdout:
        fmt.print_error("Cannot determine listening ports (ss/netstat not available).")
        sys.exit(1)

    if fmt.use_json:
        lines = result.stdout.strip().splitlines()
        fmt.print_data({"raw_output": lines})
    else:
        click.echo(result.stdout.rstrip())


# ---------------------------------------------------------------------------
# system packages
# ---------------------------------------------------------------------------


@click.command("packages")
@click.argument("sandbox_id")
@click.option("--manager", "-m", default="pip",
              type=click.Choice(["pip", "npm"]),
              help="Package manager (default: pip)")
@click.pass_context
@handle_errors
def system_packages(
    ctx: click.Context,
    sandbox_id: str,
    manager: str,
) -> None:
    """List installed packages in a sandbox.

    Examples:\n
        sbox sandbox system packages abc123\n
        sbox sandbox system packages abc123 --manager npm
    """
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    if manager == "pip":
        cmd = "python3 -m pip list --format json 2>/dev/null"
    else:
        cmd = "npm list --json --depth=0 2>/dev/null"

    result = run_sync(sandbox.commands.run(cmd, timeout=30))

    if manager == "pip":
        try:
            packages = json_module.loads(result.stdout)
        except (json_module.JSONDecodeError, ValueError):
            packages = []

        if fmt.use_json:
            fmt.print_data({"manager": manager, "packages": packages})
        else:
            if not packages:
                fmt.print_success("No packages found.")
            else:
                headers = ["Name", "Version"]
                rows = [
                    [p.get("name", ""), p.get("version", "")]
                    for p in packages
                ]
                fmt.print_table(headers, rows)
    else:
        try:
            raw = json_module.loads(result.stdout)
            deps = raw.get("dependencies", {})
            packages_list = [
                {
                    "name": name,
                    "version": info.get("version", "")
                    if isinstance(info, dict)
                    else str(info),
                }
                for name, info in deps.items()
            ]
        except (json_module.JSONDecodeError, ValueError, AttributeError):
            packages_list = []

        if fmt.use_json:
            fmt.print_data({"manager": manager, "packages": packages_list})
        else:
            if not packages_list:
                fmt.print_success("No packages found.")
            else:
                headers = ["Name", "Version"]
                rows = [[p["name"], p["version"]] for p in packages_list]
                fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# system metrics
# ---------------------------------------------------------------------------


@click.command("metrics")
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def system_metrics(ctx: click.Context, sandbox_id: str) -> None:
    """Show resource usage metrics of a sandbox.

    Displays CPU load, memory usage, and disk usage.

    Examples:\n
        sbox sandbox system metrics abc123
    """
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    script = (
        "python3 -c \""
        "import os, shutil, json;"
        "try:\\n"
        "  load1, load5, load15 = os.getloadavg()\\n"
        "except OSError:\\n"
        "  load1 = load5 = load15 = 0.0\\n"
        "d = shutil.disk_usage('/')\\n"
        "print(json.dumps({"
        "'cpu_load_1m': round(load1,2),"
        "'cpu_load_5m': round(load5,2),"
        "'cpu_load_15m': round(load15,2),"
        "'disk_total_gb': round(d.total/(1024**3),2),"
        "'disk_used_gb': round(d.used/(1024**3),2),"
        "'disk_free_gb': round(d.free/(1024**3),2)"
        "}))"
        "\""
    )
    result = run_sync(sandbox.commands.run(script, timeout=15))

    if result.exit_code != 0:
        # Fallback: raw uptime + df
        result = run_sync(sandbox.commands.run(
            "uptime 2>/dev/null; echo '---'; df -h / 2>/dev/null",
            timeout=10,
        ))
        if fmt.use_json:
            fmt.print_data({"raw": result.stdout.strip()})
        else:
            click.echo(result.stdout.rstrip())
        return

    try:
        data = json_module.loads(result.stdout.strip())
    except (json_module.JSONDecodeError, ValueError):
        click.echo(result.stdout.rstrip())
        return

    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict({k: str(v) for k, v in data.items()})


# ---------------------------------------------------------------------------
# capabilities (top-level sandbox subcommand, not under system)
# ---------------------------------------------------------------------------


@click.command("capabilities")
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def capabilities(ctx: click.Context, sandbox_id: str) -> None:
    """Show supported capability groups of a sandbox.

    Examples:\n
        sbox sandbox capabilities abc123
    """
    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    caps = sorted(sandbox.capabilities)

    if fmt.use_json:
        fmt.print_data({"capabilities": caps})
    else:
        if not caps:
            fmt.print_success("No capabilities declared.")
        else:
            click.echo("Capabilities:")
            for cap in caps:
                click.echo(f"  - {cap}")


# ---------------------------------------------------------------------------
# shell-stream
# ---------------------------------------------------------------------------


@click.command("shell-stream")
@click.argument("sandbox_id")
@click.option(
    "--command", "-c", "cmd", required=True,
    help="Command to execute with streaming output",
)
@click.option("--timeout", "-t", "cmd_timeout", type=int, default=300, help="Timeout in seconds")
@click.option("--cwd", default="", help="Working directory")
@click.pass_context
@handle_errors
def shell_stream(
    ctx: click.Context,
    sandbox_id: str,
    cmd: str,
    cmd_timeout: int,
    cwd: str,
) -> None:
    """Execute a command with real-time streaming output.

    Unlike 'exec', output is printed line-by-line as it arrives.

    Examples:\n
        sbox sandbox shell-stream abc123 --command "pip install numpy"\n
        sbox sandbox shell-stream abc123 -c "make build" --cwd /app
    """
    from serverless_sandbox.models.process import ProcessChunkType
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    sandbox = _connect_sandbox(sandbox_id)

    exit_code = 0

    async def _stream() -> int:
        nonlocal exit_code
        async for chunk in sandbox.commands.stream(
            cmd, timeout=cmd_timeout, cwd=cwd,
        ):
            if chunk.type == ProcessChunkType.STDOUT:
                if chunk.data:
                    click.echo(chunk.data, nl=False)
            elif chunk.type == ProcessChunkType.STDERR:
                if chunk.data:
                    click.echo(chunk.data, err=True, nl=False)
            elif chunk.type == ProcessChunkType.EXIT:
                exit_code = chunk.exit_code or 0
        return exit_code

    code = run_sync(_stream())

    if fmt.use_json:
        fmt.print_data({"exit_code": code})

    sys.exit(code)


# ---------------------------------------------------------------------------
# system group
# ---------------------------------------------------------------------------


@click.group()
@click.pass_context
def system(ctx: click.Context) -> None:
    """System information for a sandbox (info, env, ports, packages, metrics)."""
    ctx.ensure_object(dict)


system.add_command(system_info, "info")
system.add_command(system_env, "env")
system.add_command(system_ports, "ports")
system.add_command(system_packages, "packages")
system.add_command(system_metrics, "metrics")
