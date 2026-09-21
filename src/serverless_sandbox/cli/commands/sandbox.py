"""Sandbox lifecycle CLI commands: create, list, info, kill, exec, connect, upload, download."""
from __future__ import annotations

import sys
from typing import Any

import click

from serverless_sandbox.cli.formatters import get_formatter
from serverless_sandbox.cli.main import handle_errors
from serverless_sandbox.cli.output import get_output

# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

@click.command()
@click.argument("description", required=False, default=None)
@click.option("--template", "-T", default=None, help="Sandbox template")
@click.option("--upload", "-u", type=click.Path(exists=True), default=None,
              help="Local file or directory to upload after creation")
@click.option("--timeout", "-t", "cmd_timeout", type=int, default=None, help="Timeout in seconds")
@click.option("--env", "-e", multiple=True, help="传递给 Sandbox 的环境变量，格式 KEY=VALUE")
@click.option("--metadata", "-m", multiple=True, help="元数据键值对，格式 KEY=VALUE")
@click.pass_context
@handle_errors
def create(
    ctx: click.Context,
    description: str | None,
    template: str | None,
    upload: str | None,
    cmd_timeout: int | None,
    env: tuple[str, ...],
    metadata: tuple[str, ...],
) -> None:
    """Create a new sandbox.

    Optionally provide a natural-language DESCRIPTION to auto-select template.
    """
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    # ---- NL inference when description given and --template omitted --------
    effective_template = template or "base"
    if description and not template:
        import os
        from pathlib import Path

        from serverless_sandbox.agent.infer import infer_template as _infer

        # Read LLM config from env vars or ~/.sbox/config.toml
        llm_api_key = os.environ.get("SBOX_LLM_API_KEY")
        llm_model = os.environ.get("SBOX_LLM_MODEL")
        llm_base_url = os.environ.get("SBOX_LLM_BASE_URL")
        if not llm_api_key:
            _cfg_path = Path.home() / ".sbox" / "config.toml"
            if _cfg_path.is_file():
                try:
                    try:
                        import tomllib
                    except ImportError:
                        import tomli as tomllib  # type: ignore[no-redef]
                    with open(_cfg_path, "rb") as _f:
                        _cfg_full = tomllib.load(_f)
                    _cfg_transport = _cfg_full.get("transport", _cfg_full)
                    # LLM 配置从 transport 节读取（与 config set 写入位置一致）
                    llm_api_key = llm_api_key or _cfg_transport.get("llm_api_key")
                    llm_model = llm_model or _cfg_transport.get("llm_model")
                    llm_base_url = llm_base_url or _cfg_transport.get("llm_base_url")
                except Exception:
                    pass

        infer_result = run_sync(_infer(
            description,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
        ))
        effective_template = infer_result.template

        if not fmt.use_json:
            out = get_output(ctx)
            out.info("\u2713 推断结果：")
            out.info(f"    模板: {infer_result.template}")
            out.info(
                f"    CPU: {infer_result.cpu} 核  |  内存: {infer_result.memory} MB"
            )
            out.info(f"    置信度: {infer_result.confidence}")
            out.progress("创建中...")

    # Parse env vars from "KEY=VALUE" format
    envs: dict[str, str] = {}
    for item in env:
        if "=" in item:
            k, v = item.split("=", 1)
            envs[k] = v
        else:
            fmt.print_error(f"Invalid environment variable format: {item!r} (expected KEY=VALUE)")
            sys.exit(2)

    # Parse metadata from "KEY=VALUE" format
    meta: dict[str, str] = {}
    for item in metadata:
        if "=" in item:
            k, v = item.split("=", 1)
            meta[k] = v
        else:
            fmt.print_error(f"Invalid metadata format: {item!r} (expected KEY=VALUE)")
            sys.exit(2)

    # Build create kwargs
    create_kwargs: dict[str, Any] = {"template": effective_template}
    if cmd_timeout is not None:
        create_kwargs["timeout"] = cmd_timeout
    else:
        create_kwargs["timeout"] = ctx.obj.get("timeout", 300)
    if envs:
        create_kwargs["envs"] = envs
    if meta:
        create_kwargs["metadata"] = meta

    async def _create_and_upload() -> Any:
        sbx = await Sandbox.create(**create_kwargs)
        if upload:
            from pathlib import Path

            local = Path(upload)
            remote_base = "/home/user"
            if local.is_file():
                content = local.read_bytes()
                dest = f"{remote_base}/{local.name}"
                await sbx.files.write(dest, content)
                if not fmt.use_json:
                    get_output(ctx).info(f"↑ 已上传 {upload} → {dest}")
            elif local.is_dir():
                count = 0
                for file in local.rglob("*"):
                    if file.is_file():
                        rel = file.relative_to(local)
                        dest = f"{remote_base}/{rel}"
                        await sbx.files.write(dest, file.read_bytes())
                        count += 1
                if not fmt.use_json:
                    get_output(ctx).info(f"↑ 已上传 {count} 个文件 → {remote_base}/")
        return sbx

    sandbox = run_sync(_create_and_upload())

    data = {
        "ID": sandbox.id,
        "Status": sandbox.status.value,
        "Template": sandbox.info.template,
        "URL": sandbox.url,
    }
    if sandbox.info.envd_version:
        data["EnvdVersion"] = sandbox.info.envd_version
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success(f"Sandbox {sandbox.id} created successfully.")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@click.command("list")
@click.option(
    "--status", "-s",
    type=click.Choice(["running", "stopped", "creating", "paused", "error"]),
    default=None,
    help="Filter by status",
)
@click.option("--limit", "-l", type=int, default=20, help="Max results")
@click.pass_context
@handle_errors
def list_cmd(ctx: click.Context, status: str | None, limit: int) -> None:
    """List sandboxes."""
    from serverless_sandbox.models.sandbox import SandboxStatus
    from serverless_sandbox.protocol.sandbox import SandboxProtocol
    from serverless_sandbox.transport.auth import create_auth_provider
    from serverless_sandbox.transport.config import load_config
    from serverless_sandbox.transport.http import HttpClient
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    config = load_config(region=ctx.obj.get("region"))
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)
    proto = SandboxProtocol(http_client)

    sb_status = SandboxStatus(status) if status else None
    sandboxes = run_sync(proto.list(status=sb_status, limit=limit))

    if not sandboxes:
        fmt.print_success("No sandboxes found.")
        return

    headers = ["ID", "Template", "Status", "Region"]
    rows = [
        [sb.sandbox_id, sb.template, sb.status.value, sb.region]
        for sb in sandboxes
    ]
    fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

@click.command()
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def info(ctx: click.Context, sandbox_id: str) -> None:
    """Get sandbox information."""
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    sandbox = run_sync(Sandbox.connect(sandbox_id))
    sb_info = sandbox.info

    data: dict[str, Any] = {
        "ID": sb_info.sandbox_id,
        "Template": sb_info.template,
        "Status": sb_info.status.value,
        "Region": sb_info.region,
        "Timeout": f"{sb_info.timeout}s",
        "URL": sb_info.envd_url or "N/A",
    }
    if sb_info.envd_version:
        data["EnvdVersion"] = sb_info.envd_version
    if sb_info.started_at:
        data["Started"] = str(sb_info.started_at)
    if sb_info.metadata:
        data["Metadata"] = str(sb_info.metadata)

    fmt.print_dict(data)


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------

@click.command()
@click.argument("sandbox_id", required=False)
@click.option("--all", "kill_all", is_flag=True, help="Kill all running sandboxes")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
@handle_errors
def kill(ctx: click.Context, sandbox_id: str | None, kill_all: bool, yes: bool) -> None:
    """Kill (destroy) a sandbox or all sandboxes."""
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.models.sandbox import SandboxStatus
    from serverless_sandbox.protocol.sandbox import SandboxProtocol
    from serverless_sandbox.transport.auth import create_auth_provider
    from serverless_sandbox.transport.config import load_config
    from serverless_sandbox.transport.http import HttpClient
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    if not kill_all and not sandbox_id:
        fmt.print_error(
            "Either provide a sandbox ID or use --all.",
            suggestion="Usage: sbox kill <sandbox-id> or sbox kill --all",
        )
        sys.exit(2)

    if kill_all:
        config = load_config(region=ctx.obj.get("region"))
        auth = create_auth_provider(
            api_key=config.api_key,
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
        )
        http_client = HttpClient(config, auth)
        proto = SandboxProtocol(http_client)
        sandboxes = run_sync(proto.list(status=SandboxStatus.RUNNING))

        if not sandboxes:
            fmt.print_success("No running sandboxes to kill.")
            return

        if not yes:
            click.confirm(f"Kill all {len(sandboxes)} running sandbox(es)?", abort=True)

        async def _connect_and_kill(sid: str) -> None:
            sbx = await Sandbox.connect(sid)
            await sbx.kill()

        killed = 0
        for sb in sandboxes:
            try:
                run_sync(_connect_and_kill(sb.sandbox_id))
                killed += 1
            except Exception as exc:
                fmt.print_error(f"Failed to kill {sb.sandbox_id}: {exc}")

        fmt.print_success(f"Killed {killed}/{len(sandboxes)} sandbox(es).")
    else:
        if not yes:
            click.confirm(f"Kill sandbox {sandbox_id}?", abort=True)

        async def _connect_and_kill(sid: str) -> None:
            sbx = await Sandbox.connect(sid)
            await sbx.kill()

        run_sync(_connect_and_kill(sandbox_id))

        fmt.print_success(f"Sandbox {sandbox_id} killed.")


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------

@click.command("exec")
@click.argument("sandbox_id")
@click.argument("command")
@click.option("--timeout", "-t", "cmd_timeout", type=int, default=60, help="Timeout in seconds")
@click.option("--cwd", default="", help="Working directory (empty = container default)")
@click.pass_context
@handle_errors
def exec_cmd(
    ctx: click.Context,
    sandbox_id: str,
    command: str,
    cmd_timeout: int,
    cwd: str,
) -> None:
    """Execute a command in a sandbox."""
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    async def _connect_and_exec() -> Any:
        sandbox = await Sandbox.connect(sandbox_id)
        return await sandbox.commands.run(command, timeout=cmd_timeout, cwd=cwd)

    result = run_sync(_connect_and_exec())

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

    sys.exit(result.exit_code)


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

@click.command()
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def connect(ctx: click.Context, sandbox_id: str) -> None:
    """Connect to a sandbox interactively (like SSH)."""
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    async def _connect() -> None:
        sandbox = await Sandbox.connect(sandbox_id)
        out = get_output(ctx)
        out.success(f"Connected to sandbox {sandbox_id}")
        out.info("Type 'exit' or Ctrl+D to disconnect")
        out.info("Note: each command runs in an independent process")

        while True:
            try:
                cmd = input(f"sbox:{sandbox_id[:8]}> ")
            except (EOFError, KeyboardInterrupt):
                out.info("\nDisconnected.")
                break

            cmd = cmd.strip()
            if not cmd:
                continue
            if cmd in ("exit", "quit"):
                out.info("Disconnected.")
                break

            try:
                result = await sandbox.commands.run(cmd, timeout=30)
                if result.stdout:
                    click.echo(result.stdout, nl=False)
                if result.stderr:
                    click.echo(result.stderr, nl=False, err=True)
            except Exception as e:
                fmt.print_error(str(e))

    run_sync(_connect())


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

@click.command()
@click.argument("sandbox_id")
@click.argument("local_path", type=click.Path(exists=True))
@click.argument("remote_path")
@click.pass_context
@handle_errors
def upload(ctx: click.Context, sandbox_id: str, local_path: str, remote_path: str) -> None:
    """Upload a local file or directory to the sandbox.

    Examples:\n
        sbox upload abc123 ./script.py /app/script.py\n
        sbox upload abc123 ./data/ /app/data/
    """
    from pathlib import Path

    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    async def _connect_and_upload() -> None:
        sandbox = await Sandbox.connect(sandbox_id)
        local = Path(local_path)

        if local.is_file():
            content = local.read_bytes()
            await sandbox.files.write(remote_path, content)
            fmt.print_success(f"Uploaded {local_path} -> {remote_path}")
        elif local.is_dir():
            count = 0
            for file in local.rglob("*"):
                if file.is_file():
                    rel = file.relative_to(local)
                    dest = f"{remote_path.rstrip('/')}/{rel}"
                    content = file.read_bytes()
                    await sandbox.files.write(dest, content)
                    count += 1
            fmt.print_success(f"Uploaded {count} files from {local_path} -> {remote_path}")

    run_sync(_connect_and_upload())


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

@click.command()
@click.argument("sandbox_id")
@click.argument("remote_path")
@click.argument("local_path", type=click.Path())
@click.pass_context
@handle_errors
def download(ctx: click.Context, sandbox_id: str, remote_path: str, local_path: str) -> None:
    """Download a file from the sandbox to local.

    Examples:\n
        sbox download abc123 /app/result.csv ./result.csv\n
        sbox download abc123 /app/output.log .
    """
    from pathlib import Path

    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    async def _connect_and_download() -> bytes:
        sandbox = await Sandbox.connect(sandbox_id)
        return await sandbox.files.read_bytes(remote_path)

    content = run_sync(_connect_and_download())

    local = Path(local_path)
    if local.is_dir():
        filename = remote_path.rsplit("/", 1)[-1]
        local = local / filename

    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(content)
    fmt.print_success(f"Downloaded {remote_path} -> {local}")


# ---------------------------------------------------------------------------
# run (custom command)
# ---------------------------------------------------------------------------

@click.command(
    "run",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.argument("sandbox_id")
@click.argument("command_name")
@click.option(
    "--arg",
    "-a",
    "args",
    multiple=True,
    help="Command argument as key=value (repeatable, legacy style)",
)
@click.pass_context
@handle_errors
def run_cmd(
    ctx: click.Context,
    sandbox_id: str,
    command_name: str,
    args: tuple[str, ...],
) -> None:
    """Run a named custom command or registered command.

    Supports two argument styles:

    \b
    Legacy:  sbox run <id> <cmd> --arg key=value
    New:     sbox run <id> <cmd> --key value

    When the command comes from @sandbox.register, typed options
    (--x, --y, ...) are derived automatically from the function signature.

    Examples:\n
        sbox run abc123 dev\n
        sbox run abc123 test --arg file=tests/\n
        sbox run abc123 demo --x 1 --y hello
    """
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    # -- Parse arguments --------------------------------------------------
    kwargs: dict[str, str] = {}

    # Legacy --arg key=value
    for item in args:
        if "=" in item:
            k, v = item.split("=", 1)
            kwargs[k] = v
        else:
            fmt.print_error(
                f"Invalid argument format: {item!r} (expected key=value)",
            )
            sys.exit(2)

    # New-style --key value from extra args
    kwargs.update(_parse_extra_args(ctx.args, fmt))

    # -- Connect and dispatch ----------------------------------------------
    async def _connect_and_run() -> None:
        sandbox = await Sandbox.connect(sandbox_id)

        # Try Sandbox.run() (template custom commands) first.
        # On ValueError("Unknown custom command ...") fall through to registry.
        try:
            result = await sandbox.run(command_name, **kwargs)
            _print_process_result(fmt, result)
            sys.exit(result.exit_code)
            return
        except ValueError as exc:
            if "Unknown custom command" not in str(exc):
                raise
            # Not a template custom command — fall through to registry

        # Try @sandbox.register registry
        from serverless_sandbox.declarative.decorator import (
            sandbox as _sb,
        )

        if command_name not in _sb._registry:
            # Attempt project-level discovery (import *.py in cwd)
            _discover_registered_commands()

        if command_name in _sb._registry:
            port = int(kwargs.pop("server_port", "9000"))
            result = await sandbox.run_command(
                command_name, server_port=port, **kwargs
            )
            if fmt.use_json:
                fmt.print_data({"result": result})
            else:
                click.echo(result)
            sys.exit(0)
            return

        # Neither custom command nor registered
        fmt.print_error(
            f"Unknown command {command_name!r}. "
            f"Not found in sandbox custom commands or local @sandbox.register registry.",
        )
        sys.exit(2)

    run_sync(_connect_and_run())


# ---------------------------------------------------------------------------
# run_cmd helpers
# ---------------------------------------------------------------------------


def _parse_extra_args(
    extra: list[str],
    fmt: Any,
) -> dict[str, str]:
    """Parse Click extra-args (``--key value`` pairs) into a dict."""
    kwargs: dict[str, str] = {}
    i = 0
    while i < len(extra):
        arg = extra[i]
        if arg.startswith("--"):
            key = arg[2:]
            if not key:
                fmt.print_error("Empty option name: '--'")
                sys.exit(2)
            # Next token is the value unless it's another option
            if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
                kwargs[key] = extra[i + 1]
                i += 2
            else:
                # Treat as boolean flag
                kwargs[key] = "true"
                i += 1
        else:
            fmt.print_error(f"Unexpected positional argument: {arg!r}")
            sys.exit(2)
    return kwargs


def _print_process_result(fmt: Any, result: Any) -> None:
    """Print a :class:`ProcessResult` using *fmt*."""
    if fmt.use_json:
        fmt.print_data(
            {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
            }
        )
    else:
        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.stderr:
            click.echo(result.stderr, err=True, nl=False)


def _discover_registered_commands() -> None:
    """Best-effort: scan ``*.py`` in *cwd* for ``@sandbox.register``.

    Files containing the literal ``sandbox.register`` are imported so that
    registrations are triggered on the module-level ``sandbox`` singleton.
    Failures are silently ignored.
    """
    import importlib.util
    from pathlib import Path

    cwd = Path.cwd()
    for py_file in sorted(cwd.glob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            if "sandbox.register" not in text:
                continue
            module_name = f"_sbox_discover_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(
                module_name, py_file
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            continue


# ---------------------------------------------------------------------------
# sandbox group (sbox sandbox list/info/kill/...)
# ---------------------------------------------------------------------------


@click.group()
@click.pass_context
def sandbox(ctx: click.Context) -> None:
    """Manage sandboxes (create, list, info, kill, exec, connect, upload, download, run, files, process, system)."""
    ctx.ensure_object(dict)


sandbox.add_command(create)
sandbox.add_command(list_cmd, "list")
sandbox.add_command(info)
sandbox.add_command(kill)
sandbox.add_command(exec_cmd, "exec")
sandbox.add_command(connect)
sandbox.add_command(upload)
sandbox.add_command(download)
sandbox.add_command(run_cmd, "run")

# Sub-groups for extended server capabilities
from serverless_sandbox.cli.commands.sandbox_files import files  # noqa: E402
from serverless_sandbox.cli.commands.sandbox_process import process  # noqa: E402
from serverless_sandbox.cli.commands.sandbox_system import (
    capabilities,
    shell_stream,
    system,
)  # noqa: E402

sandbox.add_command(files, "files")
sandbox.add_command(process, "process")
sandbox.add_command(system, "system")
sandbox.add_command(capabilities, "capabilities")
sandbox.add_command(shell_stream, "shell-stream")
