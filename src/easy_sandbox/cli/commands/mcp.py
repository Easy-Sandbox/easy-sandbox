"""MCP Server CLI commands: install, start, status."""
from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
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
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
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
