"""Authentication CLI commands: login, logout, status."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors

_EBX_DIR = Path.home() / ".ebx"
_CONFIG_FILE = _EBX_DIR / "config.toml"
# 凭证存储路径：~/.ebx/.env
# 与 transport/config.py 的 _ENV_FILE_CANDIDATES 保持一致（其中包含 ~/.ebx/.env）
_ENV_FILE = _EBX_DIR / ".env"


@click.group()
def auth() -> None:
    """Authentication management."""


@auth.command()
@click.option("--api-key", prompt=True, hide_input=True, help="Your E2B_API_KEY")
@click.pass_context
@handle_errors
def login(ctx: click.Context, api_key: str) -> None:
    """Store API key for authentication."""
    fmt = get_formatter(ctx)

    if not api_key.strip():
        fmt.print_error("API key cannot be empty.")
        sys.exit(2)

    # Write to ~/.ebx/.env
    _EBX_DIR.mkdir(parents=True, exist_ok=True)

    # 官方推荐使用 E2B_API_KEY，SANDBOX_API_KEY 保留为向后兼容
    # Read existing .env content, replace or add E2B_API_KEY
    env_lines: list[str] = []
    key_found = False
    if _ENV_FILE.is_file():
        for line in _ENV_FILE.read_text().splitlines():
            if line.startswith("E2B_API_KEY=") or line.startswith("SANDBOX_API_KEY="):
                if not key_found:
                    env_lines.append(f"E2B_API_KEY={api_key}")
                    key_found = True
                # Skip legacy SANDBOX_API_KEY lines
            else:
                env_lines.append(line)
    if not key_found:
        env_lines.append(f"E2B_API_KEY={api_key}")

    _ENV_FILE.write_text("\n".join(env_lines) + "\n")
    # 安全加固：限制文件权限为仅所有者可读写 (chmod 600)
    _ENV_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)

    masked = api_key[:4] + "*" * max(0, len(api_key) - 8) + api_key[-4:] if len(api_key) >= 8 else "****"
    fmt.print_success(f"API key saved ({masked}).")


@auth.command()
@click.pass_context
@handle_errors
def logout(ctx: click.Context) -> None:
    """Remove stored credentials."""
    fmt = get_formatter(ctx)

    if _ENV_FILE.is_file():
        # 官方推荐使用 E2B_API_KEY，SANDBOX_API_KEY 保留为向后兼容
        # Remove E2B_API_KEY and legacy SANDBOX_API_KEY lines
        lines = _ENV_FILE.read_text().splitlines()
        remaining = [l for l in lines if not l.startswith("E2B_API_KEY=") and not l.startswith("SANDBOX_API_KEY=")]
        if remaining:
            _ENV_FILE.write_text("\n".join(remaining) + "\n")
        else:
            _ENV_FILE.unlink()
        fmt.print_success("Credentials removed.")
    else:
        fmt.print_success("No stored credentials found.")


@auth.command()
@click.pass_context
@handle_errors
def status(ctx: click.Context) -> None:
    """Show current authentication status."""
    fmt = get_formatter(ctx)

    # 官方推荐使用 E2B_API_KEY，SANDBOX_API_KEY 保留为向后兼容
    # Check sources in priority order: env E2B_API_KEY > env SANDBOX_API_KEY > file
    api_key = os.environ.get("E2B_API_KEY") or os.environ.get("SANDBOX_API_KEY")
    source = "environment"

    if not api_key and _ENV_FILE.is_file():
        for line in _ENV_FILE.read_text().splitlines():
            if line.startswith("E2B_API_KEY=") or line.startswith("SANDBOX_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                source = str(_ENV_FILE)
                break

    ak_id = os.environ.get("ALICLOUD_ACCESS_KEY_ID")
    ak_secret = os.environ.get("ALICLOUD_ACCESS_KEY_SECRET")

    data: dict[str, Any] = {}

    if api_key:
        masked = api_key[:4] + "*" * max(0, len(api_key) - 8) + api_key[-4:] if len(api_key) >= 8 else "****"
        data["API Key"] = masked
        data["Source"] = source
        data["Auth Mode"] = "api_key"
    elif ak_id and ak_secret:
        masked_id = ak_id[:4] + "****" if len(ak_id) >= 4 else "****"
        data["Access Key ID"] = masked_id
        data["Auth Mode"] = "ak_sk"
        data["Source"] = "environment"
    else:
        data["Auth Mode"] = "none"
        data["Status"] = "Not authenticated"

    fmt.print_dict(data)
