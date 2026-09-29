"""Configuration management CLI commands: init, get, set, list."""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from easy_sandbox.cli.formatters import OutputFormatter, get_formatter
from easy_sandbox.cli.main import handle_errors

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_EBX_DIR = Path.home() / ".ebx"
_CONFIG_FILE = _EBX_DIR / "config.toml"

# Keys that users can configure
_ALLOWED_KEYS: dict[str, str] = {
    "api_key": "E2B API Key",
    "access_key_id": "Alibaba Cloud AccessKey ID for template deploy / ACR push",
    "access_key_secret": "Alibaba Cloud AccessKey Secret for template deploy / ACR push",
    "api_url": "Platform API URL (e.g. https://api.cn-hangzhou.e2b.fc.aliyuncs.com)",
    "region": "Default region (e.g. cn-hangzhou, cn-shanghai)",
    "http_timeout": "HTTP request timeout in seconds",
    "http2": "Enable HTTP/2 for platform connections (true/false)",
    "max_retries": "Maximum retry attempts",
    "domain": "Envd domain",
    "llm_api_key": "LLM API Key for NL inference",
    "llm_model": "LLM model name (e.g. qwen-plus)",
    "llm_base_url": "LLM API base URL (OpenAI-compatible)",
    "qwen_code_api_key": "Qwen Code API Key for AI template generation (stored in ~/.ebx/.env)",
    "qwen_code_base_url": "Qwen Code OpenAI-compatible base URL",
    "qwen_code_model": "Qwen Code model name (e.g. qwen3-coder-plus)",
    "github_token": "GitHub token for template downloads / rate limits (stored in ~/.ebx/.env)",
}

_ENV_FILE = _EBX_DIR / ".env"

# Keys stored in ~/.ebx/.env (mapped to their env-var name) rather than
# config.toml. Credentials live here so they stay together and reuse the
# env-var names that the transport layer already reads.
_ENV_STORED_KEYS: dict[str, str] = {
    "api_key": "E2B_API_KEY",
    "access_key_id": "ALICLOUD_ACCESS_KEY_ID",
    "access_key_secret": "ALICLOUD_ACCESS_KEY_SECRET",
    "qwen_code_api_key": "EBX_QWEN_CODE_API_KEY",
    "github_token": "GITHUB_TOKEN",
}

# Keys that are sensitive and should be masked in output
_SENSITIVE_KEYS = {
    "api_key",
    "llm_api_key",
    "access_key_secret",
    "qwen_code_api_key",
    "github_token",
}

# Environment variables that override each key at runtime, in priority
# order. Transport entries mirror easy_sandbox.transport.config._ENV_VAR_MAP;
# the EBX_* entries are read by the CLI / agent layers.
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "api_key": ("E2B_API_KEY", "SANDBOX_API_KEY"),
    "access_key_id": ("ALICLOUD_ACCESS_KEY_ID", "AccessKey"),
    "access_key_secret": ("ALICLOUD_ACCESS_KEY_SECRET", "AccessSecret"),
    "api_url": ("E2B_API_URL", "SANDBOX_API_BASE_URL"),
    "domain": ("E2B_DOMAIN",),
    "region": ("SANDBOX_REGION",),
    "http_timeout": ("SANDBOX_HTTP_TIMEOUT",),
    "qwen_code_api_key": ("EBX_QWEN_CODE_API_KEY",),
    "llm_api_key": ("EBX_LLM_API_KEY",),
    "github_token": ("GITHUB_TOKEN",),
}


def load_config_dict() -> dict[str, Any]:
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
    """Mask a sensitive value, showing only first 3 and last 3 characters.

    Values of 8 characters or fewer are masked completely: their first/last
    characters would otherwise leak most of a short secret.
    """
    s = str(value)
    if len(s) <= 8:
        return "***" if s else ""
    return s[:3] + "***" + s[-3:]


def write_env_var(env_var: str, value: str) -> None:
    """Write or update *env_var* in the ~/.ebx/.env file.

    The file stores credentials, so owner-only permissions (``0600``) are
    enforced after every write. A failing chmod (exotic filesystems) is
    ignored on purpose: storing a key must never fail for a permission-only
    reason.
    """
    _EBX_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{env_var}="
    lines: list[str] = []
    found = False
    if _ENV_FILE.is_file():
        for line in _ENV_FILE.read_text().splitlines():
            if line.startswith(prefix):
                lines.append(f"{prefix}{value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{prefix}{value}")
    _ENV_FILE.write_text("\n".join(lines) + "\n")
    with contextlib.suppress(OSError):
        os.chmod(_ENV_FILE, 0o600)


def read_env_var(env_var: str) -> str | None:
    """Read *env_var* from the ~/.ebx/.env file."""
    if not _ENV_FILE.is_file():
        return None
    prefix = f"{env_var}="
    for line in _ENV_FILE.read_text().splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    return None


def remove_env_var(env_var: str) -> bool:
    """Remove *env_var* from the ~/.ebx/.env file.

    Returns ``True`` when a stored line was removed. The file itself is
    deleted once no entries remain, so the key truly returns to "not set".
    """
    if not _ENV_FILE.is_file():
        return False
    prefix = f"{env_var}="
    original = _ENV_FILE.read_text().splitlines()
    kept = [line for line in original if not line.startswith(prefix)]
    if len(kept) == len(original):
        return False
    if any(line.strip() for line in kept):
        _ENV_FILE.write_text("\n".join(kept) + "\n")
    else:
        _ENV_FILE.unlink()
    return True


def resolve_github_token(explicit: str | None = None) -> str | None:
    """Resolve the effective GitHub token for template downloads.

    Precedence (highest first):

    1. *explicit* — the ``--token`` value: a conscious one-off override that
       may leak into shell history and process listings;
    2. the process environment variable ``GITHUB_TOKEN``;
    3. the persistent ``github_token`` stored by ``ebx config set``
       (``~/.ebx/.env``);
    4. no token (``None``).

    The token value is never printed, logged, or persisted by this helper.
    """
    for candidate in (explicit, os.environ.get("GITHUB_TOKEN")):
        if candidate and candidate.strip():
            return candidate.strip()
    stored = read_env_var(_ENV_STORED_KEYS["github_token"])
    if stored and stored.strip():
        return stored.strip()
    return None


def _business_default(key: str) -> Any | None:
    """Return the built-in default actually used for *key* (None = none).

    ``api_url`` / ``domain`` default to the values derived from the
    effective region, mirroring :func:`easy_sandbox.transport.config.load_config`;
    ``qwen_code_base_url`` / ``qwen_code_model`` fall back to the Qwen Code
    adapter's DashScope defaults.
    """
    if key in ("qwen_code_base_url", "qwen_code_model"):
        from easy_sandbox.agent.qwen_code import (  # lazy: keep startup fast
            _DEFAULT_OPENAI_BASE_URL,
            _DEFAULT_OPENAI_MODEL,
        )

        default: Any = (
            _DEFAULT_OPENAI_BASE_URL if key == "qwen_code_base_url" else _DEFAULT_OPENAI_MODEL
        )
        return default
    if key in ("api_url", "domain"):
        region, _source = _effective_value("region")
        if key == "api_url":
            return f"https://api.{region}.e2b.fc.aliyuncs.com"
        return f"{region}.e2b.fc.aliyuncs.com"
    from easy_sandbox.transport.config import TransportConfig

    default = getattr(TransportConfig(), key, None)
    if default is None or default == "":
        return None
    return default


def _env_override_name(key: str) -> str | None:
    """Return the environment variable currently overriding *key*, if any."""
    for name in _ENV_OVERRIDES.get(key, ()):
        if os.environ.get(name):
            return name
    return None


def _effective_value(key: str) -> tuple[Any | None, str]:
    """Return ``(value, source)`` for *key*.

    *source* is ``"env"`` (process environment), ``"user"`` (stored in
    ~/.ebx/config.toml or ~/.ebx/.env), ``"default"`` (built-in) or
    ``"unset"`` (no value anywhere). An empty string is never treated as a
    valid stored value.
    """
    env_name = _env_override_name(key)
    if env_name is not None:
        return os.environ[env_name], "env"
    if key in _ENV_STORED_KEYS:
        stored = read_env_var(_ENV_STORED_KEYS[key])
        if stored:
            return stored, "user"
        return None, "unset"
    stored_value = load_config_dict().get(key)
    if stored_value not in (None, ""):
        return stored_value, "user"
    default = _business_default(key)
    if default is None:
        return None, "unset"
    return default, "default"


def _display_value(key: str, value: Any) -> str:
    """Render *value* for display, masking sensitive keys."""
    text = str(value)
    return _mask_value(text) if key in _SENSITIVE_KEYS else text


def _clear_stored_value(fmt: OutputFormatter, key: str) -> None:
    """Remove the persistent value for *key* (``ebx config set KEY ""``).

    An empty string is never stored as a credential or override: the key
    falls back to its built-in default or to not-set. When an environment
    variable still overrides the key at runtime, the user is told about it
    without ever printing its value.
    """
    if key in _ENV_STORED_KEYS:
        removed = remove_env_var(_ENV_STORED_KEYS[key])
    else:
        data = load_config_dict()
        removed = key in data
        if removed:
            del data[key]
            if data:
                _save_config_dict(data)
            elif _CONFIG_FILE.is_file():
                _CONFIG_FILE.unlink()

    default = _business_default(key)
    if removed:
        message = f"Cleared {key}"
        if default is not None:
            message += f" (falls back to default: {default})"
        else:
            message += " (now not set)"
    else:
        message = f"No stored value for {key}"
        if default is not None:
            message += f" (already using default: {default})"
        else:
            message += " (already not set)"

    env_name = _env_override_name(key)
    if env_name is not None:
        message += (
            f"; environment variable {env_name} still overrides it at runtime (value not shown)"
        )
    fmt.print_success(message + ".")


@click.group("config")
def config() -> None:
    """Manage persistent credentials and CLI defaults.

    Values are read from ~/.ebx/config.toml and ~/.ebx/.env. Environment
    variables can still override the stored configuration at runtime.

    \b
    Examples:
      ebx config init
      ebx config list
      ebx config get region
      ebx config set http_timeout 120
      ebx config set github_token     Prompt for the token (masked input)
      ebx config set region ""       Clear one stored value

    \b
    Related commands:
      ebx config init           Guided setup (platform, region, Qwen Code)
      ebx config get            Read one effective value
      ebx config set            Store or update one value
      ebx config set KEY ""     Clear the stored value for KEY
    """


@config.command()
@click.argument("key")
@click.pass_context
@handle_errors
def get(ctx: click.Context, key: str) -> None:
    """Get a configuration value by KEY.

    Prints the effective value: the process environment wins, then the
    value stored by ``ebx config set``, then the built-in default. Keys
    without any of these print ``(not set)``. Sensitive keys are masked.

    \b
    Available keys:
      api_key            E2B API Key (stored in ~/.ebx/.env, shown masked)
      access_key_id      Alibaba Cloud AccessKey ID for AK/SK auth
                         (template deploy, ACR push; stored in ~/.ebx/.env)
      access_key_secret  Alibaba Cloud AccessKey Secret for AK/SK auth
                         (template deploy, ACR push; stored in ~/.ebx/.env,
                         shown masked)
      api_url            Platform API URL
      domain             Envd data-plane domain
      region             Default region (e.g. cn-hangzhou)
      http_timeout       HTTP request timeout in seconds
      http2              Enable HTTP/2 (true/false)
      max_retries        Maximum retry attempts
      llm_api_key        LLM API Key for NL inference (shown masked)
      llm_model          LLM model name (e.g. qwen-plus)
      llm_base_url       LLM API base URL (OpenAI-compatible)
      qwen_code_api_key  Qwen Code API key for AI template generation
                         (stored in ~/.ebx/.env, shown masked)
      qwen_code_base_url Qwen Code OpenAI-compatible base URL
      qwen_code_model    Qwen Code model name (e.g. qwen3-coder-plus)
      github_token       GitHub token for template downloads (stored in
                         ~/.ebx/.env, shown masked)

    \b
    Examples:
      ebx config get api_key
      ebx config get region
      ebx config list          # show all values at once

    \b
    Related commands:
      ebx config list          Show every effective value and its source
      ebx config set KEY VALUE
      ebx config set KEY ""    Clear one stored value
    """
    fmt = get_formatter(ctx)

    if key not in _ALLOWED_KEYS:
        fmt.print_error(
            f"Unknown config key: {key!r}",
            suggestion=f"Available keys: {', '.join(sorted(_ALLOWED_KEYS))}",
        )
        sys.exit(2)

    value, _source = _effective_value(key)
    if value is None:
        fmt.print_data("(not set)")
        return
    fmt.print_data(_display_value(key, value))


@config.command("set")
@click.argument("key")
@click.argument("value", required=False)
@click.pass_context
@handle_errors
def set_value(ctx: click.Context, key: str, value: str | None) -> None:
    """Set a configuration value: KEY [VALUE].

    Settings are stored in ~/.ebx/config.toml, except credentials (api_key,
    access_key_id, access_key_secret, qwen_code_api_key, github_token)
    which are written to ~/.ebx/.env using their environment-variable names.

    Passing an empty VALUE clears the stored value for KEY instead: the key
    falls back to its built-in default or becomes not set. An empty string
    is never stored as a credential or override. Environment variables that
    are still exported keep overriding the key at runtime; their values are
    never printed.

    In an interactive terminal VALUE may be omitted: sensitive keys
    (github_token, api_key, access_key_secret, qwen_code_api_key) are then
    read through the masked (asterisk) input and the typed value is never
    echoed; other keys use a visible prompt. Pressing Enter at the prompt
    cancels without changing anything. In CI / non-interactive sessions
    VALUE is required.

    \b
    Available keys (expected value):
      api_key            E2B API Key (string)
      access_key_id      Alibaba Cloud AccessKey ID for AK/SK auth, used by
                         template deploy and ACR push (string)
      access_key_secret  Alibaba Cloud AccessKey Secret for AK/SK auth, used by
                         template deploy and ACR push (string)
      api_url            Platform API URL (e.g. https://api.cn-hangzhou.e2b.fc.aliyuncs.com)
      domain             Envd data-plane domain (e.g. cn-hangzhou.e2b.fc.aliyuncs.com)
      region             Default region (e.g. cn-hangzhou, cn-shanghai)
      http_timeout       HTTP request timeout in seconds (number, e.g. 120)
      http2              Enable HTTP/2 (true/false)
      max_retries        Maximum retry attempts (integer, e.g. 3)
      llm_api_key        LLM API Key for NL inference (string)
      llm_model          LLM model name (e.g. qwen-plus)
      llm_base_url       LLM API base URL, OpenAI-compatible (string)
      qwen_code_api_key  Qwen Code API key for AI template generation,
                         e.g. a DashScope/ModelStudio key (string;
                         stored in ~/.ebx/.env)
      qwen_code_base_url Qwen Code OpenAI-compatible base URL (string)
      qwen_code_model    Qwen Code model name (e.g. qwen3-coder-plus)
      github_token       GitHub token for template downloads, used by
                         'ebx template install' / 'ebx template search'
                         (string; stored in ~/.ebx/.env)

    \b
    Examples:
      ebx config set api_key YOUR_API_KEY
      ebx config set access_key_id YOUR_ACCESS_KEY_ID
      ebx config set access_key_secret YOUR_ACCESS_KEY_SECRET
      ebx config set region cn-hangzhou
      ebx config set http_timeout 120
      ebx config set http2 false
      ebx config set region ""          # clear the stored region
      ebx config set api_key ""         # remove the stored API key
      ebx config set github_token      # masked prompt (VALUE omitted)
      ebx config set github_token YOUR_GITHUB_TOKEN
      ebx config set github_token ""    # remove the stored token

    \b
    Related commands:
      ebx config get KEY       Verify the effective value
      ebx config list          Review effective values and sources
    """
    fmt = get_formatter(ctx)

    if key not in _ALLOWED_KEYS:
        fmt.print_error(
            f"Unknown config key: {key!r}",
            suggestion=f"Available keys: {', '.join(sorted(_ALLOWED_KEYS))}",
        )
        sys.exit(2)

    if value is None:
        value = _prompt_missing_value(fmt, key)
        if value is None:
            return

    # Empty values clear the stored override — they are never written as a
    # credential or an empty-string override.
    if value.strip() == "":
        _clear_stored_value(fmt, key)
        return

    if key in _ENV_STORED_KEYS:
        write_env_var(_ENV_STORED_KEYS[key], value)
        display_value = _mask_value(value) if key in _SENSITIVE_KEYS else value
        fmt.print_success(f"Set {key} = {display_value}")
        return

    data = load_config_dict()

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
    """List all effective configuration values and their sources.

    Sources: ``(env)`` a process environment variable, ``(user)`` a value
    stored with ``ebx config set``, ``(default)`` a built-in default, and
    ``(not set)`` when no value exists anywhere. Sensitive values are
    always masked.

    \b
    Examples:
      ebx config list
      ebx --json config list
      ebx config get http_timeout

    \b
    Related commands:
      ebx config get KEY        Inspect one effective value
      ebx config set KEY VALUE
      ebx config set KEY ""     Clear one stored value
    """
    fmt = get_formatter(ctx)

    # Credentials first (stable order), then the remaining keys sorted.
    ordered_keys = list(_ENV_STORED_KEYS) + sorted(
        k for k in _ALLOWED_KEYS if k not in _ENV_STORED_KEYS
    )

    # BUG-02: In JSON mode, output pure values without source annotations.
    if fmt.use_json:
        result_json: dict[str, Any] = {}
        for key in ordered_keys:
            value, _source = _effective_value(key)
            if value is None:
                result_json[key] = None
            elif key in _SENSITIVE_KEYS:
                result_json[key] = _mask_value(str(value))
            else:
                result_json[key] = value
        fmt.print_dict(result_json)
        return

    result: dict[str, str] = {}
    for key in ordered_keys:
        value, source = _effective_value(key)
        if value is None:
            result[key] = "(not set)"
        else:
            result[key] = f"{_display_value(key, value)} ({source})"
    fmt.print_dict(result)


def _print_noninteractive_setup() -> None:
    """Print the non-interactive commands equivalent to the guided wizard."""
    lines = [
        "Non-interactive setup. Run these commands to configure ebx:",
        "",
        "  ebx config set api_key <E2B_API_KEY>",
        "  ebx config set region cn-hangzhou",
        "  ebx config set qwen_code_api_key <DASHSCOPE_OR_MODELSTUDIO_KEY>",
        "",
        "  # Optional overrides and AK/SK for template deploy:",
        "  ebx config set qwen_code_base_url <OPENAI_COMPATIBLE_BASE_URL>",
        "  ebx config set qwen_code_model qwen3-coder-plus",
        "  ebx config set access_key_id <ALICLOUD_ACCESS_KEY_ID>",
        "  ebx config set access_key_secret <ALICLOUD_ACCESS_KEY_SECRET>",
        "",
        "Environment variables (E2B_API_KEY, EBX_QWEN_CODE_API_KEY,",
        "ALICLOUD_ACCESS_KEY_ID, ALICLOUD_ACCESS_KEY_SECRET) override stored values.",
    ]
    for line in lines:
        click.echo(line)


@config.command("init")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Non-interactive: print the equivalent commands instead of prompting",
)
@click.pass_context
@handle_errors
def init(ctx: click.Context, yes: bool) -> None:
    """Guided setup: platform credentials, region, and Qwen Code (AI).

    In a terminal this prompts for the platform API key, the default
    region, and the Qwen Code API key used for AI template generation
    (``ebx create "<description>"``). Secrets are typed with asterisk
    feedback (never echoed) when the terminal supports it, and stored in
    ~/.ebx/.env; the region goes to ~/.ebx/config.toml.

    In non-TTY environments (CI, piped input) the wizard never blocks: it
    prints the equivalent non-interactive ``ebx config set ...`` commands
    and exits successfully. ``--yes`` behaves the same way.

    \b
    Examples:
      ebx config init
      ebx config init --yes     # print non-interactive commands

    \b
    Related commands:
      ebx config list           Review effective values and sources
      ebx config set KEY VALUE  Set one value directly
      ebx config set KEY ""     Clear one stored value
    """
    fmt = get_formatter(ctx)

    # Never block in CI / piped sessions.
    if yes or not sys.stdin.isatty():
        _print_noninteractive_setup()
        return

    click.echo("ebx guided configuration (press Enter to keep the current value or skip):")
    click.echo()

    api_key = _prompt_secret("1/3 Platform API key (E2B_API_KEY, input masked)")
    if api_key.strip():
        write_env_var("E2B_API_KEY", api_key.strip())
        fmt.print_success("Stored api_key in ~/.ebx/.env")

    data = load_config_dict()
    current_region = str(data.get("region") or "cn-hangzhou")
    region = click.prompt("2/3 Region", default=current_region, show_default=True)
    if region.strip():
        data["region"] = region.strip()
        _save_config_dict(data)
        fmt.print_success(f"Set region = {region.strip()}")

    qwen_key = _prompt_secret("3/3 Qwen Code API key (DashScope/ModelStudio, input masked)")
    if qwen_key.strip():
        write_env_var("EBX_QWEN_CODE_API_KEY", qwen_key.strip())
        fmt.print_success("Stored qwen_code_api_key in ~/.ebx/.env")

    click.echo()
    fmt.print_success("Configuration complete. Review it with 'ebx config list'.")


# ---------------------------------------------------------------------------
# Masked secret input (asterisk feedback; no new dependencies)
# ---------------------------------------------------------------------------


def _mask_supported() -> bool:
    """Whether the current stdin can render asterisk-masked input."""
    try:
        if not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:  # pragma: no cover - non-Windows guard
            return False
        return hasattr(msvcrt, "getwch")
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
    except ImportError:  # pragma: no cover - platform without termios
        return False
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        return False
    try:
        return os.isatty(fd)
    except OSError:
        return False


@contextlib.contextmanager
def _tty_char_reader() -> Iterator[Callable[[], str]]:
    """Yield a callable returning the next character typed on the TTY.

    The terminal is switched to cbreak mode (no echo, no line buffering;
    Ctrl-C still raises KeyboardInterrupt) and its previous attributes are
    always restored afterwards.
    """
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import msvcrt

        yield msvcrt.getwch  # type: ignore[attr-defined]
        return

    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        with open(fd, encoding="utf-8", errors="replace", closefd=False) as stream:
            yield lambda: stream.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _feed_masked(chunk: str, chars: list[str], write: Callable[[str], None]) -> str | None:
    """Consume one input *chunk*; return the finished line, else None.

    One ``*`` is written per printable character; Backspace erases one,
    Enter finishes the line, Ctrl-C raises KeyboardInterrupt and Ctrl-D /
    Ctrl-Z on an empty line raise EOFError. Typed characters are never
    echoed.
    """
    for ch in chunk:
        if ch in ("\r", "\n"):
            write("\n")
            return "".join(chars)
        if ch in ("\x7f", "\x08"):  # Backspace / DEL
            if chars:
                chars.pop()
                write("\b \b")
            continue
        if ch == "\x03":  # Ctrl-C
            raise KeyboardInterrupt
        if ch in ("\x04", "\x1a"):  # Ctrl-D / Ctrl-Z
            write("\n")
            if not chars:
                raise EOFError("End of masked input")
            return "".join(chars)
        if ch.isprintable():
            chars.append(ch)
            write("*")
    return None


def _read_masked_line(
    prompt_text: str,
    *,
    reader: Callable[[], str] | None = None,
    writer: Callable[[str], None] | None = None,
) -> str:
    """Read one line from the TTY printing one asterisk per character.

    *reader* / *writer* are injectable for tests. Raises ``EOFError`` on
    terminal EOF and ``KeyboardInterrupt`` on Ctrl-C; typed characters are
    never echoed.
    """

    def _default_write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    write = writer or _default_write
    write(prompt_text)
    chars: list[str] = []
    with contextlib.ExitStack() as stack:
        read = reader
        if read is None:
            read = stack.enter_context(_tty_char_reader())
        while True:
            chunk = read()
            if chunk == "":
                write("\n")
                raise EOFError("End of masked input")
            finished = _feed_masked(chunk, chars, write)
            if finished is not None:
                return finished


def _prompt_secret(prompt_text: str) -> str:
    """Prompt for a secret, showing ``*`` per keystroke when possible.

    Falls back to a no-echo prompt (with an explicit notice) when the
    terminal cannot render asterisk feedback.
    """
    if _mask_supported():
        try:
            return _read_masked_line(f"{prompt_text}: ")
        except (EOFError, KeyboardInterrupt):
            raise click.Abort() from None
    click.echo(
        "Note: asterisk masking is not supported by this terminal; typed input will not be echoed.",
        err=True,
    )
    return click.prompt(prompt_text, hide_input=True, default="", show_default=False)


def _prompt_missing_value(fmt: OutputFormatter, key: str) -> str | None:
    """Prompt for a VALUE omitted from ``ebx config set KEY`` (task 206).

    Sensitive keys reuse the existing asterisk-masked input
    (:func:`_prompt_secret`); other keys use a visible prompt. Returns the
    entered value, or ``None`` when the user pressed Enter without typing
    anything - nothing changes, because clearing a value still requires the
    explicit empty argument (``ebx config set KEY ""``). Without an
    interactive terminal the command exits with code 2 instead of blocking a
    CI job. Typed characters are never echoed for sensitive keys.
    """
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        interactive = False

    if not interactive:
        suggestion = f"Pass the value explicitly: 'ebx config set {key} <VALUE>'."
        env_var = _ENV_STORED_KEYS.get(key)
        if env_var is not None:
            suggestion += (
                f" In CI, inject the {env_var} environment variable as a secret "
                "instead of storing it locally."
            )
        fmt.print_error(
            f"Missing VALUE for {key!r} and stdin is not an interactive terminal.",
            suggestion=suggestion,
        )
        sys.exit(2)

    if key in _SENSITIVE_KEYS:
        entered = _prompt_secret(f"{key} (input masked; press Enter to cancel)")
    else:
        entered = click.prompt(key, default="", show_default=False)
    if entered.strip() == "":
        fmt.print_success(f"No value entered; {key} was not changed.")
        return None
    return entered
