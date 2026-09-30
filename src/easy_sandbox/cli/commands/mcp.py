"""MCP Server CLI commands: install, start, status, deploy."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors
from easy_sandbox.cli.region import region_option, resolve_region

# ---------------------------------------------------------------------------
# IDE config paths
# ---------------------------------------------------------------------------


def _get_cursor_config_path() -> Path:
    """Get the Cursor MCP config file path."""
    return Path.home() / ".cursor" / "mcp.json"


def _get_claude_config_path() -> Path:
    """Get the Claude Desktop config file path."""
    system = platform.system()
    if system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"


def _get_vscode_config_path() -> Path:
    """Get the VS Code workspace MCP config path.

    VS Code reads ``.vscode/mcp.json`` with a top-level ``servers`` object.
    This file is workspace-scoped, so the installer does not copy the API key
    into it.
    """
    return Path.cwd() / ".vscode" / "mcp.json"


_IDE_CONFIG_MAP = {
    "cursor": _get_cursor_config_path,
    "claude": _get_claude_config_path,
    "vscode": _get_vscode_config_path,
}


def _read_api_key() -> str | None:
    """Read the sandbox API key with the same order the SDK uses.

    Process environment, then ``./.env``, then ``~/.ebx/.env``, then a
    legacy ``api_key`` in ``~/.ebx/config.toml``. ``E2B_API_KEY`` beats
    ``SANDBOX_API_KEY`` inside each layer.
    """
    from easy_sandbox.transport.config import load_config, reset_config

    reset_config()
    return load_config().api_key


def _resolve_mcp_launch() -> tuple[str, list[str]]:
    """Return a command the IDE can execute without relying on a login PATH.

    Prefer the ``ebx`` next to the current interpreter, then ``ebx`` on PATH,
    then ``python -m easy_sandbox.cli.main``.
    """
    sibling_name = "ebx.exe" if os.name == "nt" else "ebx"
    sibling = Path(sys.executable).with_name(sibling_name)
    if sibling.is_file():
        return str(sibling), ["mcp", "start"]
    found = shutil.which("ebx")
    if found:
        return found, ["mcp", "start"]
    return sys.executable, ["-m", "easy_sandbox.cli.main", "mcp", "start"]


def _build_mcp_server_config() -> dict[str, Any]:
    """Build the MCP server configuration block."""
    api_key = _read_api_key() or ""
    env_block: dict[str, str] = {}
    if api_key:
        env_block["E2B_API_KEY"] = api_key

    api_url = os.environ.get("E2B_API_URL") or os.environ.get("SANDBOX_API_BASE_URL")
    if api_url:
        env_block["E2B_API_URL"] = api_url

    region = os.environ.get("SANDBOX_REGION")
    if region:
        env_block["SANDBOX_REGION"] = region

    command, args = _resolve_mcp_launch()
    config: dict[str, Any] = {
        "command": command,
        "args": args,
    }
    if env_block:
        config["env"] = env_block
    return config


def _read_json_object(config_path: Path) -> dict[str, Any]:
    """Load a JSON object, refusing to continue when the file is not strict JSON."""
    if not config_path.is_file():
        return {}
    try:
        loaded = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        click.echo(
            f"Error: {config_path} is not strict JSON ({exc}). "
            "Refusing to overwrite it. Remove comments or trailing commas, "
            "or add the easy-sandbox entry by hand.",
            err=True,
        )
        raise SystemExit(1) from exc
    except OSError as exc:
        click.echo(f"Error: could not read {config_path}: {exc}", err=True)
        raise SystemExit(1) from exc
    if not isinstance(loaded, dict):
        click.echo(f"Error: {config_path} must contain a JSON object.", err=True)
        raise SystemExit(1)
    return loaded


# ---------------------------------------------------------------------------
# MCP command group
# ---------------------------------------------------------------------------


@click.group()
def mcp() -> None:
    """Configure and run Easy Sandbox as an MCP server.

    Use local STDIO transport for IDE integrations, or generate a Streamable
    HTTP deployment artifact for manual deployment to Alibaba Cloud FC.

    \b
    Examples:
      ebx mcp install --target cursor
      ebx mcp start
      ebx mcp start --http --background
      ebx mcp stop
      ebx mcp deploy --generate-token --output-dir ./mcp-artifact

    \b
    Related commands:
      ebx config set sandbox_api_key VALUE  Configure sandbox authentication
      ebx mcp status                Inspect local MCP configuration
      ebx mcp stop                  Stop the local MCP server
    """


@mcp.command()
@click.option(
    "--target",
    type=click.Choice(["cursor", "claude", "vscode"]),
    required=True,
    help="Target IDE for MCP installation.",
)
@click.pass_context
@handle_errors
def install(ctx: click.Context, target: str) -> None:
    """Install MCP Server configuration to a target IDE.

    Generates the correct MCP config and merges it into the selected IDE's
    configuration file. Supported targets are cursor, claude, and vscode.

    \b
    Examples:
      ebx mcp install --target cursor
      ebx mcp install --target claude
      ebx mcp install --target vscode

    \b
    Related commands:
      ebx mcp status  Verify installed IDE configurations
      ebx mcp start   Run the configured STDIO server
      ebx config get sandbox_api_key
    """
    fmt = get_formatter(ctx)

    path_fn = _IDE_CONFIG_MAP[target]
    config_path = path_fn()

    existing = _read_json_object(config_path)

    # Build server config
    server_config = _build_mcp_server_config()

    # Merge based on IDE type
    if target == "vscode":
        # Workspace file: do not copy the API key into a path that is often committed.
        workspace_config = dict(server_config)
        workspace_config["type"] = "stdio"
        env_block = dict(workspace_config.get("env") or {})
        env_block.pop("E2B_API_KEY", None)
        if env_block:
            workspace_config["env"] = env_block
        else:
            workspace_config.pop("env", None)
        mcp_servers = existing.get("servers")
        if not isinstance(mcp_servers, dict):
            mcp_servers = {}
        mcp_servers["easy-sandbox"] = workspace_config
        existing["servers"] = mcp_servers
    else:
        # Cursor and Claude use mcpServers
        mcp_servers = existing.get("mcpServers")
        if not isinstance(mcp_servers, dict):
            mcp_servers = {}
        mcp_servers["easy-sandbox"] = server_config
        existing["mcpServers"] = mcp_servers

    # Write config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")

    fmt.print_success(f"MCP Server config written to {config_path}")
    if not ctx.obj.get("quiet"):
        click.echo()
        click.echo("Registered tools:")
        tool_names = [
            ("create_sandbox", "Create a cloud sandbox"),
            ("run_code", "Execute code"),
            ("run_command", "Execute a command"),
            ("read_file", "Read a file"),
            ("write_file", "Write a file"),
            ("list_files", "List files"),
            ("kill_sandbox", "Destroy a sandbox"),
        ]
        for name, desc in tool_names:
            click.echo(f"  • {name:<18s} — {desc}")
        click.echo()
        if target == "cursor":
            click.echo("Please restart Cursor to apply changes.")
        elif target == "claude":
            click.echo("Please restart Claude Desktop to apply changes.")
        elif target == "vscode":
            click.echo("Please reload the VS Code window to apply changes.")
            click.echo(
                "The workspace MCP file does not contain the API key. "
                "ebx mcp start reads it from the environment or ~/.ebx."
            )


def _runtime_dir() -> Path:
    """Directory for the local MCP server pid and log.

    ``EBX_MCP_RUNTIME_DIR`` overrides the default ``~/.ebx/run`` so tests do
    not touch a developer's running server.
    """
    override = os.environ.get("EBX_MCP_RUNTIME_DIR")
    if override:
        return Path(override)
    return Path.home() / ".ebx" / "run"


def _server_state_path() -> Path:
    """JSON file recording the local MCP server process."""
    return _runtime_dir() / "mcp-server.json"


def _server_log_path() -> Path:
    """Log file for a background HTTP MCP server."""
    return _runtime_dir() / "mcp-server.log"


def _read_server_state() -> dict[str, Any] | None:
    """Return the recorded server state, or None when the file is absent."""
    path = _server_state_path()
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _pid_alive(pid: int) -> bool:
    """Return whether ``pid`` is a running process."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _running_server() -> dict[str, Any] | None:
    """Return the state file when its pid is still alive."""
    state = _read_server_state()
    if not state:
        return None
    pid = state.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return None
    return state


def _write_server_state(state: dict[str, Any]) -> None:
    """Persist the local server record."""
    path = _server_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _release_server_slot() -> None:
    """Remove the state file when it still belongs to this process."""
    state = _read_server_state()
    if state and state.get("pid") == os.getpid():
        with contextlib.suppress(OSError):
            _server_state_path().unlink()


def _claim_server_slot(state: dict[str, Any]) -> None:
    """Record this process, or exit when another local server is alive."""
    existing = _running_server()
    if existing is not None and existing.get("pid") != os.getpid():
        mode = existing.get("mode", "stdio")
        click.echo(
            f"Error: an MCP server is already running (pid {existing.get('pid')}, {mode}).\n"
            "Stop it with: ebx mcp stop",
            err=True,
        )
        raise SystemExit(1)
    state["pid"] = os.getpid()
    _write_server_state(state)


def _quiet(ctx: click.Context) -> bool:
    """Whether the root CLI asked for quiet output."""
    obj = ctx.obj or {}
    return bool(obj.get("quiet"))


def _note(ctx: click.Context, text: str) -> None:
    """Write a startup note to stderr. Stdout stays reserved for JSON-RPC."""
    if _quiet(ctx):
        return
    click.echo(text, err=True)


def _configured_label(value: str | None) -> str:
    """Describe a secret without printing it."""
    return "configured" if value else "not configured"


def _print_stdio_banner(
    ctx: click.Context,
    *,
    template: str,
    api_key: str | None,
    api_url: str | None,
    domain: str | None,
) -> None:
    """Tell a human operator what this waiting process is."""
    from easy_sandbox.agent.mcp import MCP_PROTOCOL_VERSION
    from easy_sandbox.agent.tools import TOOL_SCHEMAS

    tools = ", ".join(tool["name"] for tool in TOOL_SCHEMAS)
    _note(
        ctx,
        "\n".join(
            [
                "Easy Sandbox MCP server",
                "  transport:  STDIO (newline-delimited JSON-RPC)",
                f"  protocol:   {MCP_PROTOCOL_VERSION}",
                f"  template:   {template}",
                f"  api key:    {_configured_label(api_key)}",
                f"  api url:    {api_url or 'region default'}",
                f"  domain:     {domain or 'region default'}",
                f"  tools:      {tools}",
                "Auth: STDIO has no Bearer token. Sandbox calls use the API key above.",
                "Waiting for JSON-RPC on stdin. Responses are written to stdout.",
                "Stop with Ctrl-C, or from another terminal: ebx mcp stop",
                "Background HTTP server: ebx mcp start --http --background",
            ]
        ),
    )


def _print_http_banner(
    ctx: click.Context,
    *,
    host: str,
    port: int,
    template: str,
    api_key: str | None,
    auth_token: str | None,
) -> None:
    """Describe the HTTP listener before uvicorn takes over."""
    from easy_sandbox.agent.mcp_http import MCP_PROTOCOL_VERSION

    _note(
        ctx,
        "\n".join(
            [
                "Easy Sandbox MCP server",
                "  transport:  Streamable HTTP",
                f"  protocol:   {MCP_PROTOCOL_VERSION}",
                f"  endpoint:   http://{host}:{port}/mcp",
                f"  health:     http://{host}:{port}/health",
                f"  template:   {template}",
                f"  api key:    {_configured_label(api_key)}",
                f"  auth:       {_configured_label(auth_token)}",
                "Stop with Ctrl-C, or from another terminal: ebx mcp stop",
            ]
        ),
    )


def _is_loopback(host: str) -> bool:
    """True for hosts that are not reachable from another machine."""
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def _spawn_background(command: list[str], env: dict[str, str]) -> int:
    """Start a detached MCP HTTP process and return when it has claimed a pid."""
    runtime = _runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = _server_log_path()
    log_file = log_path.open("a", encoding="utf-8")
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        popen_kwargs["creationflags"] = 0x00000200 | 0x00000008
    else:
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )
    finally:
        log_file.close()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = ""
            try:
                tail = log_path.read_text(encoding="utf-8")[-2000:]
            except OSError:
                tail = ""
            click.echo(
                "Error: the background MCP server exited before it was ready.\n" + tail,
                err=True,
            )
            raise SystemExit(1)
        state = _read_server_state()
        if state and state.get("pid") == proc.pid:
            return proc.pid
        time.sleep(0.1)
    click.echo(
        f"Error: timed out waiting for the background MCP server (pid {proc.pid}).\n"
        f"Log: {log_path}",
        err=True,
    )
    raise SystemExit(1)


@mcp.command()
@click.option(
    "--template",
    default="code-interpreter-v1",
    help="Default sandbox template ID or alias (default: code-interpreter-v1).",
)
@click.option("--api-key", default=None, envvar="E2B_API_KEY", help="API key override.")
@click.option("--api-url", default=None, envvar="E2B_API_URL", help="API URL override.")
@click.option("--domain", default=None, envvar="E2B_DOMAIN", help="Domain override.")
@click.option(
    "--http",
    "use_http",
    is_flag=True,
    default=False,
    help="Serve Streamable HTTP instead of STDIO.",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="HTTP bind address.")
@click.option("--port", default=9000, show_default=True, type=int, help="HTTP bind port.")
@click.option(
    "--auth-token",
    default=None,
    envvar="EBX_MCP_AUTH_TOKEN",
    help="Bearer token for the HTTP server. Required when --host is not loopback.",
)
@click.option(
    "--background",
    is_flag=True,
    default=False,
    help="Detach an HTTP server. Stop it later with 'ebx mcp stop'.",
)
@click.pass_context
@handle_errors
def start(
    ctx: click.Context,
    template: str,
    api_key: str | None,
    api_url: str | None,
    domain: str | None,
    use_http: bool,
    host: str,
    port: int,
    auth_token: str | None,
    background: bool,
) -> None:
    """Start the MCP server and print its configuration to stderr.

    The default transport is STDIO: an IDE writes JSON-RPC to stdin and reads
    responses from stdout. Run it in a terminal to see the configuration and
    stop it with Ctrl-C or 'ebx mcp stop'.

    --http listens for Streamable HTTP. --background detaches that HTTP
    server; STDIO cannot keep a client attached after detach, so --background
    starts HTTP.

    \b
    Examples:
      ebx mcp start
      ebx mcp start --template python-hello
      ebx mcp start --http --port 9000
      ebx mcp start --http --background
      ebx mcp stop

    \b
    Related commands:
      ebx mcp install --target cursor  Register the STDIO command in an IDE
      ebx mcp stop                     Stop the local MCP server
      ebx mcp status                   Check authentication and IDE setup
    """
    if not api_key:
        api_key = _read_api_key()
    if background:
        use_http = True

    if use_http:
        _start_http(
            ctx,
            template=template,
            api_key=api_key,
            api_url=api_url,
            domain=domain,
            host=host,
            port=port,
            auth_token=(auth_token or "").strip() or None,
            background=background,
        )
        return

    _start_stdio(
        ctx,
        template=template,
        api_key=api_key,
        api_url=api_url,
        domain=domain,
    )


def _start_stdio(
    ctx: click.Context,
    *,
    template: str,
    api_key: str | None,
    api_url: str | None,
    domain: str | None,
) -> None:
    """Run the STDIO server in the foreground."""
    from easy_sandbox.agent.mcp import SandboxMCPServer

    _claim_server_slot({"mode": "stdio", "template": template})
    _print_stdio_banner(
        ctx,
        template=template,
        api_key=api_key,
        api_url=api_url,
        domain=domain,
    )
    server = SandboxMCPServer(
        api_key=api_key,
        api_url=api_url,
        domain=domain,
        template=template,
    )
    try:
        asyncio.run(server.run())
    finally:
        _release_server_slot()


def _start_http(
    ctx: click.Context,
    *,
    template: str,
    api_key: str | None,
    api_url: str | None,
    domain: str | None,
    host: str,
    port: int,
    auth_token: str | None,
    background: bool,
) -> None:
    """Run or detach the Streamable HTTP server."""
    if not _is_loopback(host) and not auth_token:
        click.echo(
            "Error: --host is not loopback, so a non-empty --auth-token "
            "(or EBX_MCP_AUTH_TOKEN) is required.",
            err=True,
        )
        raise SystemExit(1)

    if background:
        env = os.environ.copy()
        env.pop("EBX_MCP_AUTH_TOKEN", None)
        if auth_token:
            env["EBX_MCP_AUTH_TOKEN"] = auth_token
        # The key stays in the environment. Putting it on the child argv
        # would show it in the process list.
        if api_key:
            env["E2B_API_KEY"] = api_key
        command = [
            sys.executable,
            "-m",
            "easy_sandbox.cli.main",
            "mcp",
            "start",
            "--http",
            "--template",
            template,
            "--host",
            host,
            "--port",
            str(port),
        ]
        if api_url:
            command.extend(["--api-url", api_url])
        if domain:
            command.extend(["--domain", domain])
        pid = _spawn_background(command, env)
        _note(
            ctx,
            "\n".join(
                [
                    "MCP HTTP server is running in the background.",
                    f"  pid:      {pid}",
                    f"  endpoint: http://{host}:{port}/mcp",
                    f"  log:      {_server_log_path()}",
                    "Stop it with: ebx mcp stop",
                ]
            ),
        )
        return

    try:
        import uvicorn
    except ImportError:
        click.echo(
            "Error: HTTP mode needs uvicorn. Install it with: pip install 'easy-sandbox[mcp]'",
            err=True,
        )
        raise SystemExit(1) from None

    from easy_sandbox.agent.mcp_http import create_mcp_app

    _claim_server_slot(
        {
            "mode": "http",
            "template": template,
            "host": host,
            "port": port,
            "log": str(_server_log_path()),
        }
    )
    if not auth_token:
        _note(ctx, "Warning: HTTP authentication is disabled. Bind stays on the loopback host.")
    _print_http_banner(
        ctx,
        host=host,
        port=port,
        template=template,
        api_key=api_key,
        auth_token=auth_token,
    )
    app = create_mcp_app(
        auth_token=auth_token,
        api_key=api_key,
        api_url=api_url,
        domain=domain,
        template=template,
    )
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        _release_server_slot()


@mcp.command()
@click.pass_context
@handle_errors
def stop(ctx: click.Context) -> None:
    """Stop the local MCP server started by 'ebx mcp start'.

    Sends SIGTERM to the recorded pid (STDIO foreground or HTTP background)
    and waits for it to exit. Sandboxes owned by that server are destroyed
    during its shutdown.

    \b
    Examples:
      ebx mcp stop

    \b
    Related commands:
      ebx mcp start            Start STDIO in the foreground
      ebx mcp start --http --background
      ebx mcp status           Inspect configuration and whether a server is running
    """
    state = _running_server()
    if state is None:
        stale = _read_server_state()
        if stale is not None:
            _server_state_path().unlink(missing_ok=True)
        _note(ctx, "MCP server is not running.")
        return

    pid = int(state["pid"])
    mode = state.get("mode", "stdio")
    _note(ctx, f"Stopping MCP server (pid {pid}, {mode}).")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        click.echo(f"Error: could not stop pid {pid}: {exc}", err=True)
        raise SystemExit(1) from exc

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            recorded = _read_server_state()
            if recorded and recorded.get("pid") == pid:
                with contextlib.suppress(OSError):
                    _server_state_path().unlink()
            _note(ctx, "MCP server stopped.")
            return
        time.sleep(0.1)

    click.echo(f"Error: pid {pid} did not exit after SIGTERM.", err=True)
    raise SystemExit(1)


@mcp.command()
@click.pass_context
@handle_errors
def status(ctx: click.Context) -> None:
    """Show MCP tools, authentication state, and IDE installation status.

    \b
    Examples:
      ebx mcp status
      ebx --json mcp status

    \b
    Related commands:
      ebx mcp install --target cursor
      ebx mcp start
      ebx config get sandbox_api_key
    """
    fmt = get_formatter(ctx)

    api_key = _read_api_key()

    from easy_sandbox.agent.tools import TOOL_SCHEMAS

    data: dict[str, Any] = {
        "server": "easy-sandbox",
        "transport": "stdio",
        "tools_count": len(TOOL_SCHEMAS),
        "tools": [t["name"] for t in TOOL_SCHEMAS],
        "auth_configured": bool(api_key),
        "mcp_running": _running_server() is not None,
    }

    # Check if installed in various IDEs
    for ide_name, path_fn in _IDE_CONFIG_MAP.items():
        try:
            config_path = path_fn()
            if config_path.is_file():
                config = json.loads(config_path.read_text())
                key = "servers" if ide_name == "vscode" else "mcpServers"
                installed = "easy-sandbox" in config.get(key, {})
                data[f"installed_{ide_name}"] = installed
            else:
                data[f"installed_{ide_name}"] = False
        except Exception:
            data[f"installed_{ide_name}"] = False

    fmt.print_dict(data)


# ---------------------------------------------------------------------------
# deploy command
# ---------------------------------------------------------------------------

_DEPLOY_REQUIREMENTS = """easy-sandbox[mcp]
uvicorn>=0.29
"""

_DEPLOY_APP_PY = (
    '"""ASGI entry point for the FC MCP server."""\n'
    "import os\n"
    "\n"
    "from easy_sandbox.agent.mcp_http import create_mcp_app, require_auth_token\n"
    "\n"
    "# Remote clients can reach this process. Do not boot with auth disabled.\n"
    "app = create_mcp_app(\n"
    '    auth_token=require_auth_token(os.environ.get("EBX_MCP_AUTH_TOKEN")),\n'
    '    api_key=os.environ.get("E2B_API_KEY")'
    ' or os.environ.get("SANDBOX_API_KEY"),\n'
    '    api_url=os.environ.get("E2B_API_URL")'
    ' or os.environ.get("SANDBOX_API_BASE_URL"),\n'
    '    domain=os.environ.get("E2B_DOMAIN"),\n'
    '    template=os.environ.get("SANDBOX_TEMPLATE",'
    ' os.environ.get("EBX_TEMPLATE", "base")),\n'
    ")\n"
)


def _generate_token() -> str:
    """Generate a cryptographically secure random Bearer token."""
    return secrets.token_urlsafe(32)


def _read_token_file(path: str) -> str:
    """Read a Bearer token from a file."""
    return Path(path).read_text().strip()


@mcp.command()
@click.option("--name", default="easy-sandbox-mcp", help="FC function name for the artifact.")
@region_option
@click.option(
    "--template",
    default="base",
    help="Default sandbox template for MCP sessions.",
)
@click.option("--memory", type=int, default=512, help="FC function memory (MB).")
@click.option("--timeout", "fc_timeout", type=int, default=600, help="FC function timeout (s).")
@click.option(
    "--auth-token-file",
    default=None,
    type=click.Path(exists=True),
    help="Path to a non-empty Bearer token file.",
)
@click.option(
    "--generate-token",
    is_flag=True,
    default=False,
    help="Auto-generate a random Bearer token.",
)
@click.option(
    "--enable-session-affinity/--no-session-affinity",
    default=True,
    help="Enable Mcp-Session-Id affinity (requires FC MCP support).",
)
@click.option(
    "--api-key",
    default=None,
    envvar="E2B_API_KEY",
    help="E2B_API_KEY to inject into the FC function env.",
)
@click.option(
    "--custom-domain",
    default=None,
    help="Custom domain for the MCP endpoint.",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(),
    help="Write the FC deployment artifact to this directory.",
)
@click.pass_context
@handle_errors
def deploy(
    ctx: click.Context,
    name: str,
    region: str | None,
    template: str,
    memory: int,
    fc_timeout: int,
    auth_token_file: str | None,
    generate_token: bool,
    enable_session_affinity: bool,
    api_key: str | None,
    custom_domain: str | None,
    output_dir: str | None,
) -> None:
    """Generate an Alibaba Cloud FC deployment artifact.

    Creates a Streamable HTTP ASGI application artifact and prints manual
    FC deployment steps. Automatic FC API deployment is not implemented.

    The artifact contains ``requirements.txt``, ``app.py`` (ASGI entry
    point), and ``config.yaml`` (a YAML deployment manifest with FC function
    settings and environment variables).

    ``--region`` overrides the FC region for this invocation; without it the
    region comes from ``ebx config set region`` / the ``SANDBOX_REGION``
    environment variable and defaults to ``cn-hangzhou``.

    A non-empty Bearer token is required (--generate-token or
    --auth-token-file). POST and DELETE /mcp are implemented. GET /mcp
    returns 405 until SSE server notifications exist. The function
    environment sets SANDBOX_REGION to the selected region.

    \b
    Examples:
      ebx mcp deploy --generate-token --api-key $E2B_API_KEY
      ebx mcp deploy --auth-token-file ./token.txt --region cn-shanghai
      ebx mcp deploy --generate-token --output-dir ./deploy-artifact

    \b
    Related commands:
      ebx mcp start                 Run the local STDIO server
      ebx mcp status                Inspect MCP authentication state
      ebx config set sandbox_api_key VALUE  Configure sandbox authentication
    """
    fmt = get_formatter(ctx)

    region = resolve_region(region)

    # --- Resolve auth token ---
    auth_token = ""
    if auth_token_file:
        auth_token = _read_token_file(auth_token_file)
    elif generate_token:
        auth_token = _generate_token()
    elif os.environ.get("EBX_MCP_AUTH_TOKEN", "").strip():
        auth_token = os.environ["EBX_MCP_AUTH_TOKEN"].strip()

    if not auth_token:
        click.echo(
            "Error: a non-empty MCP Bearer token is required. "
            "Pass --generate-token or --auth-token-file. "
            "Refusing to write an artifact that would disable client authentication.",
            err=True,
        )
        raise SystemExit(1)

    # --- Resolve API key ---
    if not api_key:
        api_key = _read_api_key()

    if not api_key:
        click.echo(
            "Warning: No E2B_API_KEY provided. The generated MCP Server artifact "
            "cannot create sandboxes until --api-key or E2B_API_KEY is configured.",
            err=True,
        )

    # --- Build deploy artifact ---
    if output_dir:
        artifact_dir = Path(output_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
    else:
        artifact_dir = Path(tempfile.mkdtemp(prefix="ebx-mcp-deploy-"))

    # requirements.txt
    (artifact_dir / "requirements.txt").write_text(_DEPLOY_REQUIREMENTS)

    # app.py — ASGI entry point
    (artifact_dir / "app.py").write_text(_DEPLOY_APP_PY)

    # config.yaml — provider-neutral YAML deployment manifest, not an FC API payload
    env_vars: dict[str, str] = {
        "EBX_MCP_AUTH_TOKEN": auth_token,
        "EBX_TEMPLATE": template,
        "SANDBOX_TEMPLATE": template,
        "SANDBOX_REGION": region,
    }
    if api_key:
        env_vars["E2B_API_KEY"] = api_key

    api_url = os.environ.get("E2B_API_URL") or os.environ.get("SANDBOX_API_BASE_URL")
    if api_url:
        env_vars["E2B_API_URL"] = api_url

    fc_config: dict[str, Any] = {
        "function_name": name,
        "region": region,
        "runtime": "python3.10",
        "handler": "app.app",
        "memory": memory,
        "timeout": fc_timeout,
        "environment_variables": env_vars,
        "http_trigger": {
            "methods": ["POST", "GET", "DELETE"],
            "enable_session_affinity": enable_session_affinity,
        },
    }
    if custom_domain:
        fc_config["custom_domain"] = custom_domain

    import yaml  # provided by the cli extra, same as cli/commands/template.py

    (artifact_dir / "config.yaml").write_text(
        yaml.safe_dump(fc_config, default_flow_style=False, sort_keys=False, allow_unicode=True)
    )

    fmt.print_success(f"FC deployment artifact written to {artifact_dir}")
    _print_artifact_summary(fmt, artifact_dir, fc_config, auth_token)
    _print_manual_deploy_steps(artifact_dir, enable_session_affinity)
    _print_ide_config(auth_token, custom_domain)


def _print_artifact_summary(
    fmt: Any,
    artifact_dir: Path,
    fc_config: dict[str, Any],
    auth_token: str | None,
) -> None:
    """Print a summary of the deploy artifact."""
    click.echo()
    click.echo("Artifact contents:")
    for f in sorted(artifact_dir.iterdir()):
        click.echo(f"  {f.name}")
    click.echo()
    click.echo(f"  Function: {fc_config['function_name']}")
    click.echo(f"  Region:   {fc_config['region']}")
    click.echo(f"  Memory:   {fc_config['memory']} MB")
    click.echo(f"  Timeout:  {fc_config['timeout']} s")
    if auth_token:
        # Show only first 8 chars for security
        masked = auth_token[:8] + "..." if len(auth_token) > 8 else auth_token
        click.echo(f"  Token:    {masked}")


def _print_manual_deploy_steps(
    artifact_dir: Path,
    enable_session_affinity: bool,
) -> None:
    """Print provider-neutral manual FC deployment guidance."""
    click.echo()
    click.echo("Automatic FC API deployment is not implemented. Manual steps:")
    click.echo(f"  1. Review and package the files in {artifact_dir}.")
    click.echo("  2. Use the official Alibaba Cloud FC console or SDK to create the function.")
    click.echo(
        "  3. Translate config.yaml settings through the official console/SDK, "
        "then create an HTTP trigger for POST/GET/DELETE."
    )
    if enable_session_affinity:
        click.echo("  4. Enable Mcp-Session-Id affinity if the selected FC runtime supports it.")
    else:
        click.echo("  4. Session affinity is disabled in this artifact.")
    click.echo("  5. Replace <FC_HTTP_TRIGGER_URL> below with the resulting trigger URL.")
    click.echo("  6. Clients should call DELETE /mcp when a session ends.")
    click.echo("  Note: GET /mcp returns 405 until SSE server notifications exist.")
    click.echo("  Security: config.yaml contains secrets; do not commit it to version control.")


def _print_ide_config(
    auth_token: str | None,
    custom_domain: str | None,
) -> None:
    """Print an IDE config template without exposing a plaintext token."""
    endpoint = f"https://{custom_domain}/mcp" if custom_domain else "<FC_HTTP_TRIGGER_URL>/mcp"

    ide_config: dict[str, Any] = {
        "mcpServers": {
            "easy-sandbox-remote": {
                "url": endpoint,
            }
        }
    }
    if auth_token is not None:
        ide_config["mcpServers"]["easy-sandbox-remote"]["headers"] = {
            "Authorization": "Bearer <BEARER_TOKEN>"
        }

    click.echo()
    click.echo("IDE config template (replace placeholders; do not commit secrets):")
    click.echo(json.dumps(ide_config, indent=2, ensure_ascii=False))
