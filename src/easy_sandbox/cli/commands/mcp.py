"""MCP Server CLI commands: install, start, status, deploy."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import secrets
import tempfile
from pathlib import Path
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors

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
    """Get the VS Code settings.json path (workspace level)."""
    return Path.cwd() / ".vscode" / "settings.json"


_IDE_CONFIG_MAP = {
    "cursor": _get_cursor_config_path,
    "claude": _get_claude_config_path,
    "vscode": _get_vscode_config_path,
}


def _read_api_key() -> str | None:
    """Read the API key from env or stored config."""
    key = os.environ.get("E2B_API_KEY") or os.environ.get("SANDBOX_API_KEY")
    if key:
        return key
    env_file = Path.home() / ".ebx" / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.startswith("E2B_API_KEY=") or line.startswith("SANDBOX_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


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

    config: dict[str, Any] = {
        "command": "ebx",
        "args": ["mcp", "start"],
    }
    if env_block:
        config["env"] = env_block
    return config


# ---------------------------------------------------------------------------
# MCP command group
# ---------------------------------------------------------------------------


@click.group()
def mcp() -> None:
    """MCP Server management — IDE integration."""


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

    Generates the correct MCP config and writes it to the IDE's
    configuration file.
    """
    fmt = get_formatter(ctx)

    path_fn = _IDE_CONFIG_MAP[target]
    config_path = path_fn()

    # Read existing config if present
    existing: dict[str, Any] = {}
    if config_path.is_file():
        try:
            existing = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Build server config
    server_config = _build_mcp_server_config()

    # Merge based on IDE type
    if target == "vscode":
        mcp_servers = existing.get("mcp.servers", {})
        mcp_servers["easy-sandbox"] = server_config
        existing["mcp.servers"] = mcp_servers
    else:
        # Cursor and Claude use mcpServers
        mcp_servers = existing.get("mcpServers", {})
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
            ("create_sandbox", "创建云端沙箱"),
            ("run_code", "执行代码"),
            ("run_command", "执行命令"),
            ("read_file", "读取文件"),
            ("write_file", "写入文件"),
            ("list_files", "列出文件"),
            ("kill_sandbox", "销毁沙箱"),
        ]
        for name, desc in tool_names:
            click.echo(f"  • {name:<18s} — {desc}")
        click.echo()
        if target == "cursor":
            click.echo("Please restart Cursor to apply changes.")
        elif target == "claude":
            click.echo("Please restart Claude Desktop to apply changes.")
        elif target == "vscode":
            click.echo("Please reload VS Code window to apply changes.")


@mcp.command()
@click.option("--template", default="code-interpreter-v1", help="Default sandbox template.")
@click.option("--api-key", default=None, envvar="E2B_API_KEY", help="API key override.")
@click.option("--api-url", default=None, envvar="E2B_API_URL", help="API URL override.")
@click.option("--domain", default=None, envvar="E2B_DOMAIN", help="Domain override.")
@handle_errors
def start(
    template: str,
    api_key: str | None,
    api_url: str | None,
    domain: str | None,
) -> None:
    """Start MCP Server in STDIO mode.

    This is typically called by the IDE, not manually.
    The server reads JSON-RPC messages from stdin and writes responses to stdout.
    """
    from easy_sandbox.agent.mcp import SandboxMCPServer

    # Fallback: read API key from stored config
    if not api_key:
        api_key = _read_api_key()

    server = SandboxMCPServer(
        api_key=api_key,
        api_url=api_url,
        domain=domain,
        template=template,
    )
    asyncio.run(server.run())


@mcp.command()
@click.pass_context
@handle_errors
def status(ctx: click.Context) -> None:
    """Show MCP Server status and configuration."""
    fmt = get_formatter(ctx)

    api_key = _read_api_key()

    from easy_sandbox.agent.tools import TOOL_SCHEMAS

    data: dict[str, Any] = {
        "server": "easy-sandbox",
        "transport": "stdio",
        "tools_count": len(TOOL_SCHEMAS),
        "tools": [t["name"] for t in TOOL_SCHEMAS],
        "auth_configured": bool(api_key),
    }

    # Check if installed in various IDEs
    for ide_name, path_fn in _IDE_CONFIG_MAP.items():
        try:
            config_path = path_fn()
            if config_path.is_file():
                config = json.loads(config_path.read_text())
                key = "mcp.servers" if ide_name == "vscode" else "mcpServers"
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
    '"""ASGI entry point for FC MCP Server."""\n'
    "import os\n"
    "\n"
    "from easy_sandbox.agent.mcp_http import create_mcp_app\n"
    "\n"
    "# Read config from FC function environment variables\n"
    "app = create_mcp_app(\n"
    '    auth_token=os.environ.get("EBX_MCP_AUTH_TOKEN"),\n'
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
@click.option("--region", default="cn-hangzhou", help="FC region.")
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
    help="Path to a Bearer token file; an empty token fails closed.",
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
    region: str,
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

    POST and DELETE /mcp are implemented. GET /mcp currently returns 501;
    SSE server notifications are planned for Phase 2.

    \b
    Example:
      ebx mcp deploy --generate-token --api-key $E2B_API_KEY
      ebx mcp deploy --auth-token-file ./token.txt --region cn-shanghai
      ebx mcp deploy --output-dir ./deploy-artifact
    """
    fmt = get_formatter(ctx)

    # --- Resolve auth token ---
    auth_token: str | None = None
    token_was_configured = False
    if auth_token_file:
        token_was_configured = True
        auth_token = _read_token_file(auth_token_file)
    elif generate_token:
        token_was_configured = True
        auth_token = _generate_token()
    elif "EBX_MCP_AUTH_TOKEN" in os.environ:
        token_was_configured = True
        auth_token = os.environ["EBX_MCP_AUTH_TOKEN"].strip()

    if token_was_configured and not auth_token:
        click.echo(
            "Warning: The configured MCP Bearer token is empty. The artifact "
            "will fail closed and reject every MCP request until a non-empty "
            "EBX_MCP_AUTH_TOKEN is configured.",
            err=True,
        )
    elif auth_token is None:
        click.echo(
            "Warning: No MCP Bearer token configured; client authentication "
            "will be disabled. Prefer --generate-token for remote deployments.",
            err=True,
        )

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

    # config.yaml — provider-neutral deployment manifest, not an FC API payload
    env_vars: dict[str, str] = {}
    if api_key:
        env_vars["E2B_API_KEY"] = api_key
    if token_was_configured:
        env_vars["EBX_MCP_AUTH_TOKEN"] = auth_token or ""
    env_vars["EBX_TEMPLATE"] = template

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

    (artifact_dir / "config.yaml").write_text(
        json.dumps(fc_config, indent=2, ensure_ascii=False) + "\n"
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
    click.echo("  Note: GET /mcp returns 501 until Phase 2 SSE support is implemented.")
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
