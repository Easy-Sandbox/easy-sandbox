"""Sandbox lifecycle CLI commands: create, list, info, kill, exec, connect, upload, download."""

from __future__ import annotations

import os
import sys
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors
from easy_sandbox.cli.output import get_output

# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

# Minimum HTTP timeout (seconds) for the sandbox-create call.  Cold starts
# routinely exceed the 30s transport default — even when the user has
# configured a custom http_timeout in ~/.ebx/config.toml, we enforce this
# floor so that a small configured value doesn't silently kill create.
_CREATE_REQUEST_TIMEOUT_FLOOR = 120.0


@click.command()
@click.argument("description", required=False, default=None)
@click.option("--template", "-T", default=None, help="Sandbox template")
@click.option(
    "--upload",
    "-u",
    type=click.Path(exists=True),
    default=None,
    help="Local file or directory to upload after creation",
)
@click.option("--timeout", "-t", "cmd_timeout", type=int, default=None, help="Timeout in seconds")
@click.option(
    "--request-timeout",
    type=float,
    default=None,
    help="HTTP request timeout in seconds for the create call "
    "(floor: 120s for cold starts, or your configured http_timeout if larger). "
    "Increase for very slow sandbox creation.",
)
@click.option(
    "--env",
    "-e",
    multiple=True,
    help="Environment variable for the sandbox, format KEY=VALUE (repeatable)",
)
@click.option(
    "--metadata", "-m", multiple=True, help="Metadata key-value pair, format KEY=VALUE (repeatable)"
)
@click.option("-v", "--verbose", "verbose_flag", is_flag=True, help="Verbose output (DEBUG level)")
@click.pass_context
@handle_errors
def create(
    ctx: click.Context,
    description: str | None,
    template: str | None,
    upload: str | None,
    cmd_timeout: int | None,
    request_timeout: float | None,
    env: tuple[str, ...],
    metadata: tuple[str, ...],
    verbose_flag: bool,
) -> None:
    """Create a new sandbox.

    Optionally provide a natural-language DESCRIPTION to auto-select template.
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    if verbose_flag:
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)

    fmt = get_formatter(ctx)

    # ---- NL inference when description given and --template omitted --------
    effective_template = template or "base"
    if description and not template:
        import os
        from pathlib import Path

        from easy_sandbox.agent.infer import infer_template as _infer

        # Read LLM config from env vars or ~/.ebx/config.toml
        llm_api_key = os.environ.get("EBX_LLM_API_KEY")
        llm_model = os.environ.get("EBX_LLM_MODEL")
        llm_base_url = os.environ.get("EBX_LLM_BASE_URL")
        if not llm_api_key:
            _cfg_path = Path.home() / ".ebx" / "config.toml"
            if _cfg_path.is_file():
                try:
                    try:
                        import tomllib  # type: ignore[import-not-found]
                    except ImportError:
                        import tomli as tomllib
                    with open(_cfg_path, "rb") as _f:
                        _cfg_full = tomllib.load(_f)
                    _cfg_transport = _cfg_full.get("transport", _cfg_full)
                    # LLM config read from transport section (consistent with config set)
                    llm_api_key = llm_api_key or _cfg_transport.get("llm_api_key")
                    llm_model = llm_model or _cfg_transport.get("llm_model")
                    llm_base_url = llm_base_url or _cfg_transport.get("llm_base_url")
                except Exception:
                    pass

        infer_result = run_sync(
            _infer(
                description,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
            )
        )
        effective_template = infer_result.template

        if not fmt.use_json:
            out = get_output(ctx)
            out.info("\u2713 Inference result:")
            out.info(f"    Template: {infer_result.template}")
            out.info(f"    CPU: {infer_result.cpu} cores  |  Memory: {infer_result.memory} MB")
            out.info(f"    Confidence: {infer_result.confidence}")
            if not out.use_rich_spinner:
                # The spinner below already announces creation in TTY mode;
                # only print the plain progress line in degraded modes.
                out.progress("Creating...")

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

    # HTTP timeout for the create call: sandbox creation (cold start) is
    # known to be slow, so we always enforce a floor of 120s.  If the user
    # configured a *larger* http_timeout (e.g. 300s) that is respected;
    # if they configured a *smaller* value (e.g. 30s) or left the default,
    # we bump to the floor.  --request-timeout always wins when provided.
    if request_timeout is not None:
        create_kwargs["request_timeout"] = request_timeout
    else:
        from easy_sandbox.transport.config import load_config as _load_cfg

        configured = _load_cfg().http_timeout
        create_kwargs["request_timeout"] = max(configured, _CREATE_REQUEST_TIMEOUT_FLOOR)

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
                    get_output(ctx).info(f"↑ Uploaded {upload} → {dest}")
            elif local.is_dir():
                count = 0
                for file in local.rglob("*"):
                    if file.is_file():
                        rel = file.relative_to(local)
                        dest = f"{remote_base}/{rel}"
                        await sbx.files.write(dest, file.read_bytes())
                        count += 1
                if not fmt.use_json:
                    get_output(ctx).info(f"↑ Uploaded {count} file(s) → {remote_base}/")
        return sbx

    out = get_output(ctx)
    with out.spinner("Creating sandbox"):
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
    "--status",
    "-s",
    type=click.Choice(["running", "stopped", "creating", "paused", "error"]),
    default=None,
    help="Filter by status",
)
@click.option("--limit", "-l", type=int, default=20, help="Max results")
@click.pass_context
@handle_errors
def list_cmd(ctx: click.Context, status: str | None, limit: int) -> None:
    """List sandboxes."""
    from easy_sandbox.models.sandbox import SandboxStatus
    from easy_sandbox.protocol.sandbox import SandboxProtocol
    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.utils.async_bridge import run_sync

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
    rows = [[sb.sandbox_id, sb.template, sb.status.value, sb.region] for sb in sandboxes]
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
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

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
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.models.sandbox import SandboxStatus
    from easy_sandbox.protocol.sandbox import SandboxProtocol
    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    if not kill_all and not sandbox_id:
        fmt.print_error(
            "Either provide a sandbox ID or use --all.",
            suggestion="Usage: ebx kill <sandbox-id> or ebx kill --all",
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
            if not sys.stdin.isatty():
                raise click.UsageError(
                    "Confirmation required for killing all sandboxes. "
                    "Use --yes/-y to skip in non-interactive mode."
                )
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

        run_sync(_connect_and_kill(sandbox_id))  # type: ignore[arg-type]

        fmt.print_success(f"Sandbox {sandbox_id} killed.")


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------


@click.command("exec")
@click.argument("sandbox_id")
@click.argument("command")
@click.option("--timeout", "-t", "cmd_timeout", type=int, default=60, help="Timeout in seconds")
@click.option("--cwd", default="", help="Working directory (empty = container default)")
@click.option("-v", "--verbose", "verbose_flag", is_flag=True, help="Verbose output (DEBUG level)")
@click.pass_context
@handle_errors
def exec_cmd(
    ctx: click.Context,
    sandbox_id: str,
    command: str,
    cmd_timeout: int,
    cwd: str,
    verbose_flag: bool,
) -> None:
    """Execute a command in a sandbox."""
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    if verbose_flag:
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)

    fmt = get_formatter(ctx)

    async def _connect_and_exec() -> Any:
        sandbox = await Sandbox.connect(sandbox_id)
        return await sandbox.commands.run(command, timeout=cmd_timeout, cwd=cwd)

    result = run_sync(_connect_and_exec())

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

    sys.exit(result.exit_code)


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


@click.command()
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def connect(ctx: click.Context, sandbox_id: str) -> None:
    """Connect to a sandbox interactively (like SSH).

    Each command has a 30-second timeout.
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    async def _connect() -> None:
        sandbox = await Sandbox.connect(sandbox_id)
        out = get_output(ctx)
        out.success(f"Connected to sandbox {sandbox_id}")
        out.info("Type 'exit' or Ctrl+D to disconnect")
        out.info("Note: each command runs in an independent process")

        while True:
            try:
                cmd = input(f"ebx:{sandbox_id[:8]}> ")
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
                # Hardcoded 30s timeout for interactive commands to prevent
                # indefinite hangs; long-running tasks should use 'ebx exec'
                # with an explicit --timeout instead.
                result = await sandbox.commands.run(cmd, timeout=30)
                if result.stdout:  # type: ignore[union-attr]
                    click.echo(result.stdout, nl=False)  # type: ignore[union-attr]
                if result.stderr:  # type: ignore[union-attr]
                    click.echo(result.stderr, nl=False, err=True)  # type: ignore[union-attr]
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
        ebx upload abc123 ./script.py /app/script.py\n
        ebx upload abc123 ./data/ /app/data/
    """
    from pathlib import Path

    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    async def _connect_and_upload() -> str:
        sandbox = await Sandbox.connect(sandbox_id)
        local = Path(local_path)

        if local.is_file():
            content = local.read_bytes()
            await sandbox.files.write(remote_path, content)
            return f"Uploaded {local_path} -> {remote_path}"
        if local.is_dir():
            count = 0
            for file in local.rglob("*"):
                if file.is_file():
                    rel = file.relative_to(local)
                    dest = f"{remote_path.rstrip('/')}/{rel}"
                    content = file.read_bytes()
                    await sandbox.files.write(dest, content)
                    count += 1
            return f"Uploaded {count} files from {local_path} -> {remote_path}"
        return ""

    # Upload can take a while for directories — show a spinner in TTY mode.
    # The success message is printed after the spinner stops so output
    # never interleaves with the animation.
    with out.spinner(f"Uploading {local_path}"):
        message = run_sync(_connect_and_upload())
    if message:
        fmt.print_success(message)


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
        ebx download abc123 /app/result.csv ./result.csv\n
        ebx download abc123 /app/output.log .
    """
    from pathlib import Path

    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

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
    Legacy:  ebx run <id> <cmd> --arg key=value
    New:     ebx run <id> <cmd> --key value

    When the command comes from @sandbox.register, typed options
    (--x, --y, ...) are derived automatically from the function signature.

    Examples:\n
        ebx run abc123 dev\n
        ebx run abc123 test --arg file=tests/\n
        ebx run abc123 demo --x 1 --y hello
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

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
        from easy_sandbox.models.errors import CommandNotFoundError

        sandbox = await Sandbox.connect(sandbox_id)

        # server_port is a reserved kwarg controlling mechanism-B routing;
        # it is never forwarded as a command argument.
        port = 9000
        if "server_port" in kwargs:
            try:
                port = int(kwargs.pop("server_port"))
            except ValueError:
                fmt.print_error("server_port must be an integer")
                sys.exit(2)

        # sandbox.custom() resolves template commands (A) then falls back to
        # the in-sandbox SandboxServer registry (B), returning a unified
        # CommandResult.  This preserves the historic `ebx run` A→B routing.
        try:
            result = await sandbox.custom(command_name, server_port=port, **kwargs)
        except CommandNotFoundError as exc:
            fmt.print_error(str(exc))
            sys.exit(2)
        except ValueError as exc:
            fmt.print_error(str(exc))
            sys.exit(2)

        if result.source == "server":
            # Mechanism B: print the function's JSON return value.
            if fmt.use_json:
                fmt.print_data({"result": result.value})
            else:
                click.echo(result.value)
            sys.exit(0 if result.success else 1)

        # Mechanism A: print process stdout/stderr like the old template path.
        _print_process_result(fmt, result)
        sys.exit(result.exit_code)

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

    **Opt-in behaviour**  (security hardening):

    Discovery is gated behind an explicit opt-in to prevent accidental
    code-execution when the CLI is invoked from an untrusted directory.
    At least one of the following conditions must hold:

    * The ``EBX_DISCOVER_COMMANDS`` environment variable is set to a truthy
      value (``1``, ``true``, ``yes``).
    * A ``.ebx`` marker file or directory exists in the current working
      directory, indicating a trusted Easy-Sandbox project root.

    When neither condition is satisfied the function returns immediately
    without scanning.

    SECURITY NOTE
    -------------
    Matched Python files are *executed* during ``importlib`` loading.
    Only enable discovery in project directories whose ``.py`` files you
    trust.  The scan is limited to top-level files in ``cwd`` (no
    recursive descent) and only files whose names are valid Python
    identifiers are considered.
    """
    import importlib.util
    import logging
    import re
    from pathlib import Path

    _log = logging.getLogger(__name__)

    # ---- Opt-in gate -------------------------------------------------------
    _truthy = frozenset({"1", "true", "yes"})
    env_flag = os.environ.get("EBX_DISCOVER_COMMANDS", "").strip().lower()
    cwd = Path.cwd()
    marker_exists = (cwd / ".ebx").exists()

    if env_flag not in _truthy and not marker_exists:
        _log.debug(
            "Skipping command discovery: set EBX_DISCOVER_COMMANDS=1 "
            "or create a .ebx marker in the project root to enable."
        )
        return

    # ---- Safe filename filter -----------------------------------------------
    safe_stem = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    for py_file in sorted(cwd.glob("*.py")):
        if not safe_stem.match(py_file.stem):
            _log.debug("Skipping %s: stem is not a valid Python identifier", py_file.name)
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            if "sandbox.register" not in text:
                continue
            module_name = f"_ebx_discover_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001
            _log.debug("Failed to import %s during command discovery", py_file.name, exc_info=True)
            continue


# ---------------------------------------------------------------------------
# sandbox group (ebx sandbox list/info/kill/...)
# ---------------------------------------------------------------------------


@click.group()
@click.pass_context
def sandbox(ctx: click.Context) -> None:
    """Manage sandboxes.

    Subcommands: create, list, info, kill, exec, connect, upload, download, run,
    files, process, system.
    """
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
from easy_sandbox.cli.commands.sandbox_files import files  # noqa: E402
from easy_sandbox.cli.commands.sandbox_process import process  # noqa: E402
from easy_sandbox.cli.commands.sandbox_system import (  # noqa: E402
    capabilities,
    shell_stream,
    system,
)

sandbox.add_command(files, "files")
sandbox.add_command(process, "process")
sandbox.add_command(system, "system")
sandbox.add_command(capabilities, "capabilities")
sandbox.add_command(shell_stream, "shell-stream")
