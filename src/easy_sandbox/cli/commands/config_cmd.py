"""Configuration management CLI commands: get, set, list, reset."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors

_EBX_DIR = Path.home() / ".ebx"
_CONFIG_FILE = _EBX_DIR / "config.toml"

# Keys that users can configure
_ALLOWED_KEYS: dict[str, str] = {
    "api_key": "E2B API Key",
    "api_url": "Platform API URL (e.g. https://api.cn-hangzhou.e2b.fc.aliyuncs.com)",
    "region": "Default region (e.g. cn-hangzhou, cn-shanghai)",
    "http_timeout": "HTTP request timeout in seconds",
    "http2": "Enable HTTP/2 for platform connections (true/false)",
    "max_retries": "Maximum retry attempts",
    "domain": "Envd domain",
    "llm_api_key": "LLM API Key for NL inference",
    "llm_model": "LLM model name (e.g. qwen-plus)",
    "llm_base_url": "LLM API base URL (OpenAI-compatible)",
}

_ENV_FILE = _EBX_DIR / ".env"

# Keys that are sensitive and should be masked in output
_SENSITIVE_KEYS = {"api_key", "llm_api_key"}


def _load_config_dict() -> dict[str, Any]:
    """Load the TOML config file as a plain dict."""
    if not _CONFIG_FILE.is_file():
        return {}
    try:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            import tomli as tomllib
        with open(_CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        return data.get("transport", data)  # type: ignore[no-any-return]
    except Exception:
        return {}


def _save_config_dict(data: dict[str, Any]) -> None:
    """Save config dict to TOML file."""
    _EBX_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["[transport]"]
    for k, v in sorted(data.items()):
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        else:
            lines.append(f"{k} = {v}")
    _CONFIG_FILE.write_text("\n".join(lines) + "\n")


def _mask_value(value: str) -> str:
    """Mask a sensitive value, showing only first 3 and last 3 characters."""
    s = str(value)
    if len(s) <= 8:
        return s[:2] + "***" + s[-1:]
    return s[:3] + "***" + s[-3:]


def _write_env_api_key(api_key: str) -> None:
    """Write or update E2B_API_KEY in ~/.ebx/.env file."""
    _EBX_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if _ENV_FILE.is_file():
        for line in _ENV_FILE.read_text().splitlines():
            if line.startswith("E2B_API_KEY="):
                lines.append(f"E2B_API_KEY={api_key}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"E2B_API_KEY={api_key}")
    _ENV_FILE.write_text("\n".join(lines) + "\n")


def _read_env_api_key() -> str | None:
    """Read E2B_API_KEY from ~/.ebx/.env file."""
    if not _ENV_FILE.is_file():
        return None
    for line in _ENV_FILE.read_text().splitlines():
        if line.startswith("E2B_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


@click.group("config")
def config() -> None:
    """Configuration management."""


@config.command()
@click.argument("key")
@click.pass_context
@handle_errors
def get(ctx: click.Context, key: str) -> None:
    """Get a configuration value."""
    fmt = get_formatter(ctx)

    if key not in _ALLOWED_KEYS:
        fmt.print_error(
            f"Unknown config key: {key!r}",
            suggestion=f"Available keys: {', '.join(sorted(_ALLOWED_KEYS))}",
        )
        sys.exit(2)

    if key == "api_key":
        # Read from env file
        value = _read_env_api_key()
        if value is None:
            import os

            value = os.environ.get("E2B_API_KEY")
        if value:
            fmt.print_data(_mask_value(value))
        else:
            fmt.print_data("(not set)")
        return

    data = _load_config_dict()
    value = data.get(key)

    if value is None:
        # Fall back to TransportConfig defaults
        from easy_sandbox.transport.config import TransportConfig

        defaults = TransportConfig()
        value = getattr(defaults, key, None)

    if value is not None and key in _SENSITIVE_KEYS:
        fmt.print_data(_mask_value(str(value)))
    else:
        fmt.print_data(value)


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
@handle_errors
def set_value(ctx: click.Context, key: str, value: str) -> None:
    """Set a configuration value."""
    fmt = get_formatter(ctx)

    if key not in _ALLOWED_KEYS:
        fmt.print_error(
            f"Unknown config key: {key!r}",
            suggestion=f"Available keys: {', '.join(sorted(_ALLOWED_KEYS))}",
        )
        sys.exit(2)

    if key == "api_key":
        _write_env_api_key(value)
        fmt.print_success(f"Set api_key = {_mask_value(value)}")
        return

    data = _load_config_dict()

    # Coerce numeric values
    if key in ("http_timeout",):
        try:
            data[key] = float(value)
        except ValueError:
            fmt.print_error(f"Invalid numeric value: {value!r}")
            sys.exit(2)
    elif key in ("max_retries",):
        try:
            data[key] = int(value)
        except ValueError:
            fmt.print_error(f"Invalid integer value: {value!r}")
            sys.exit(2)
    elif key in ("http2",):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            data[key] = True
        elif lowered in ("false", "0", "no", "off"):
            data[key] = False
        else:
            fmt.print_error(f"Invalid boolean value: {value!r} (expected true/false)")
            sys.exit(2)
    else:
        data[key] = value

    _save_config_dict(data)
    display_value = _mask_value(value) if key in _SENSITIVE_KEYS else value
    fmt.print_success(f"Set {key} = {display_value}")


@config.command("list")
@click.pass_context
@handle_errors
def list_config(ctx: click.Context) -> None:
    """List all configuration values."""
    fmt = get_formatter(ctx)

    # Load user overrides
    user_data = _load_config_dict()

    # Get defaults
    from easy_sandbox.transport.config import TransportConfig

    defaults = TransportConfig()

    # BUG-02: In JSON mode, output pure values without source annotations.
    if fmt.use_json:
        result_json: dict[str, Any] = {}
        api_key = _read_env_api_key()
        result_json["api_key"] = _mask_value(api_key) if api_key else None
        for key, _desc in sorted(_ALLOWED_KEYS.items()):
            if key == "api_key":
                continue
            value = user_data.get(key)
            if value is not None:
                result_json[key] = _mask_value(str(value)) if key in _SENSITIVE_KEYS else value
            else:
                default_val = getattr(defaults, key, None)
                result_json[key] = default_val if default_val != "" else None
        fmt.print_dict(result_json)
        return

    result: dict[str, str] = {}
    # Show api_key (masked)
    api_key = _read_env_api_key()
    if api_key:
        result["api_key"] = f"{_mask_value(api_key)} (user)"
    else:
        result["api_key"] = "(not set)"

    for key, _desc in sorted(_ALLOWED_KEYS.items()):
        if key == "api_key":
            continue  # already handled above
        value = user_data.get(key)
        if value is not None:
            display = _mask_value(str(value)) if key in _SENSITIVE_KEYS else str(value)
            result[key] = f"{display} (user)"
        else:
            default_val = getattr(defaults, key, "")
            result[key] = f"{default_val} (default)"

    fmt.print_dict(result)


@config.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
@handle_errors
def reset(ctx: click.Context, yes: bool) -> None:
    """Reset configuration to defaults."""
    fmt = get_formatter(ctx)

    if not yes:
        click.confirm("Reset all configuration to defaults?", abort=True)

    cleaned = False
    if _CONFIG_FILE.is_file():
        _CONFIG_FILE.unlink()
        cleaned = True
    # BUG-01: Also remove the .env file that stores api_key.
    if _ENV_FILE.is_file():
        _ENV_FILE.unlink()
        cleaned = True

    if cleaned:
        fmt.print_success("Configuration reset to defaults (including api_key).")
    else:
        fmt.print_success("No configuration file found (already using defaults).")
