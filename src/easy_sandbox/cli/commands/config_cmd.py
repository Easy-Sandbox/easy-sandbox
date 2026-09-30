"""Configuration management CLI commands: init, get, set, list."""

from __future__ import annotations

import contextlib
import os
import re
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

# Keys that users can configure. One name per credential: the sandbox
# control-plane key is ``sandbox_api_key``; NL inference and the coding
# agent share one LLM profile (``llm_api_key`` / ``llm_base_url`` /
# ``llm_model``).
_ALLOWED_KEYS: dict[str, str] = {
    "sandbox_api_key": (
        "Sandbox service API key (E2B-compatible; env vars E2B_API_KEY > SANDBOX_API_KEY)"
    ),
    "access_key_id": "Alibaba Cloud AccessKey ID for template deploy / ACR push",
    "access_key_secret": "Alibaba Cloud AccessKey Secret for template deploy / ACR push",
    "acr_namespace": ("ACR namespace for template build, push, and install (env: ACR_NAMESPACE)"),
    "api_url": "Platform API URL (e.g. https://api.cn-hangzhou.e2b.fc.aliyuncs.com)",
    "region": "Default region (e.g. cn-hangzhou, cn-shanghai)",
    "http_timeout": "HTTP request timeout in seconds",
    "http2": "Enable HTTP/2 for platform connections (true/false)",
    "max_retries": "Maximum retry attempts",
    "domain": "Envd domain",
    "llm_api_key": "LLM API key for NL inference and the coding agent (stored in ~/.ebx/.env)",
    "llm_model": "LLM model name (default: qwen3-coder-plus)",
    "llm_base_url": "LLM API base URL, OpenAI-compatible (default: DashScope compatible-mode)",
    "github_token": "GitHub token for template downloads / rate limits (stored in ~/.ebx/.env)",
}

_ENV_FILE = _EBX_DIR / ".env"

# Keys stored in ~/.ebx/.env (mapped to their env-var name) rather than
# config.toml. Credentials live here so they stay together and reuse the
# env-var names that the transport layer already reads.
_ENV_STORED_KEYS: dict[str, str] = {
    "sandbox_api_key": "E2B_API_KEY",
    "access_key_id": "ALICLOUD_ACCESS_KEY_ID",
    "access_key_secret": "ALICLOUD_ACCESS_KEY_SECRET",
    "acr_namespace": "ACR_NAMESPACE",
    "llm_api_key": "EBX_LLM_API_KEY",
    "github_token": "GITHUB_TOKEN",
}

# Older CLI names that still work for ``config get`` / ``config set`` but
# are not shown by ``config list``. ``api_key`` is the previous name of
# ``sandbox_api_key``; the stored env var is still ``E2B_API_KEY``.
_KEY_ALIASES: dict[str, str] = {
    "api_key": "sandbox_api_key",
}

# Keys removed from the config surface. ``config get`` / ``config set``
# name the replacement instead of accepting them.
_REMOVED_KEYS: dict[str, str] = {
    "qwen_code_api_key": "llm_api_key",
    "qwen_code_base_url": "llm_base_url",
    "qwen_code_model": "llm_model",
}

# Storage written by older releases, read only when the unified key is
# unset. Never listed. ``llm_*`` always wins when both are present.
_LEGACY_ENV_FALLBACKS: dict[str, tuple[str, ...]] = {
    "llm_api_key": ("EBX_QWEN_CODE_API_KEY",),
}
_LEGACY_TOML_FALLBACKS: dict[str, str] = {
    "llm_base_url": "qwen_code_base_url",
    "llm_model": "qwen_code_model",
}

# Env-stored keys whose value may still live in an old ``[transport]``
# section of config.toml (written before the secure-storage migration).
# Reading prefers the process environment and ~/.ebx/.env; re-setting the
# key removes the TOML copy, and clearing removes both locations.
_LEGACY_TOML_ENV_KEYS = {"llm_api_key"}

# Functional groups for ``config list``: stable order, one group per topic.
# Every _ALLOWED_KEYS entry appears in exactly one group; group titles are
# display-only and never take part in ``config get`` / ``config set``.
_CONFIG_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Sandbox authentication", ("sandbox_api_key",)),
    ("Alibaba Cloud credentials", ("access_key_id", "access_key_secret", "acr_namespace")),
    ("Connection", ("api_url", "region", "domain", "http_timeout", "http2", "max_retries")),
    ("LLM", ("llm_api_key", "llm_model", "llm_base_url")),
    ("Integrations", ("github_token",)),
)

# Keys that are sensitive and should be masked in output
_SENSITIVE_KEYS = {
    "sandbox_api_key",
    "llm_api_key",
    "access_key_secret",
    "github_token",
}

# Environment variables that override each key at runtime, in priority
# order. A set process variable always wins over ~/.ebx (system config).
# Transport entries mirror easy_sandbox.transport.config._ENV_VAR_MAP;
# the LLM entries are the same chain the coding agent and deploy use.
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "sandbox_api_key": ("E2B_API_KEY", "SANDBOX_API_KEY"),
    "access_key_id": ("ALICLOUD_ACCESS_KEY_ID", "AccessKey"),
    "access_key_secret": ("ALICLOUD_ACCESS_KEY_SECRET", "AccessSecret"),
    "acr_namespace": ("ACR_NAMESPACE",),
    "api_url": ("E2B_API_URL", "SANDBOX_API_BASE_URL"),
    "domain": ("E2B_DOMAIN",),
    "region": ("SANDBOX_REGION",),
    "http_timeout": ("SANDBOX_HTTP_TIMEOUT",),
    "llm_api_key": (
        "EBX_LLM_API_KEY",
        "BAILIAN_CODING_PLAN_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
        "EBX_QWEN_CODE_API_KEY",
    ),
    "llm_base_url": ("EBX_LLM_BASE_URL", "OPENAI_BASE_URL"),
    "llm_model": ("EBX_LLM_MODEL", "OPENAI_MODEL"),
    "github_token": ("GITHUB_TOKEN",),
}


def load_config_dict() -> dict[str, Any]:
    """Load the ``[transport]`` section of the config file as a plain dict."""
    data = _load_full_config()
    transport = data.get("transport")
    if isinstance(transport, dict):
        return transport
    # Legacy flat files kept the transport keys at the top level.
    return {key: value for key, value in data.items() if not isinstance(value, dict)}


# ---------------------------------------------------------------------------
# Full-config read/write (hand-rolled TOML: no extra runtime dependencies)
# ---------------------------------------------------------------------------


def _load_full_config_with_error() -> tuple[dict[str, Any], Exception | None]:
    """Load the whole TOML file as ``(data, error)``.

    ``error`` is ``None`` for a missing file or a successful parse, and the
    parsing exception when the file exists but is corrupted.
    """
    if not _CONFIG_FILE.is_file():
        return {}, None
    try:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            import tomli as tomllib
        with open(_CONFIG_FILE, "rb") as f:
            raw = tomllib.load(f)
        parsed: dict[str, Any] = raw
        return parsed, None
    except Exception as exc:
        return {}, exc


def _load_full_config() -> dict[str, Any]:
    """Load the whole TOML config file as a dict (``{}`` on any error)."""
    data, _error = _load_full_config_with_error()
    return data


def _toml_value(value: Any) -> str:
    """Serialise *value* as a TOML value (scalars and flat arrays)."""
    if isinstance(value, bool):  # before int: bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return f'"{value}"'


def _write_table(lines: list[str], name: str, table: dict[str, Any]) -> None:
    """Append a ``[name]`` section: scalar keys first, then sub-tables."""
    lines.append(f"[{name}]")
    for key, value in table.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_value(value)}")
    for key, sub in table.items():
        if isinstance(sub, dict):
            lines.append("")
            _write_table(lines, f"{name}.{key}", sub)


def _save_full_config(data: dict[str, Any]) -> None:
    """Write the whole config *data* back to the TOML file, section by section.

    Callers pass the full dictionary read with :func:`_load_full_config`, so
    updating one section (e.g. ``[transport]``) never drops the others.
    """
    _EBX_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_value(value)}")
    for name, table in data.items():
        if isinstance(table, dict):
            if lines:
                lines.append("")
            _write_table(lines, name, table)
    content = "\n".join(lines) + "\n" if lines else ""
    _CONFIG_FILE.write_text(content, encoding="utf-8")


def _save_config_dict(data: dict[str, Any]) -> None:
    """Save the ``[transport]`` dict, preserving every other section."""
    full = _load_full_config()
    if "transport" not in full:
        # Legacy flat file: keep real sections only; the root scalars are
        # rewritten below as the [transport] table.
        full = {key: value for key, value in full.items() if isinstance(value, dict)}
    full["transport"] = data
    _save_full_config(full)


# ---------------------------------------------------------------------------
# Shortcuts ([shortcuts] section)
# ---------------------------------------------------------------------------

# ``[shortcuts]`` table header (optionally followed by a comment).
_SHORTCUTS_HEADER_RE = re.compile(r"^\s*\[shortcuts\]\s*(?:#.*)?$")
# Any TOML table header — marks the end of the ``[shortcuts]`` block.
_TABLE_HEADER_RE = re.compile(r"^\s*\[")
# Valid shortcut alias: letters, digits, dash and underscore.
_SHORTCUT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Display comments for the aliases written into the generated section.
_SHORTCUT_COMMENTS: dict[str, str] = {
    "create": "Create a new sandbox",
    "list": "List all sandboxes",
    "info": "Show sandbox details",
    "kill": "Terminate a sandbox",
    "exec": "Execute a command in sandbox",
    "connect": "Connect to a sandbox",
    "upload": "Upload files to sandbox",
    "download": "Download files from sandbox",
    "run": "Run a custom command in sandbox",
    "install": "Install a template from registry",
    "init": "Scaffold a new template project",
    "deploy": "Deploy a template",
    "files": "List files in sandbox",
    "ps": "List processes in sandbox",
    "sys": "Show sandbox system info",
    "logs": "View process logs",
    "build": "Build a template image",
    "search": "Search template registry",
}

# Additional aliases shipped commented out in the generated section; users
# uncomment a line to enable it.
_SHORTCUT_SUGGESTIONS: tuple[tuple[str, str], ...] = (
    ("files", "sandbox files list"),
    ("ps", "sandbox process list"),
    ("sys", "sandbox system info"),
    ("logs", "sandbox process logs"),
    ("build", "template build"),
    ("search", "template search"),
)


def _read_shortcuts_section(data: dict[str, Any]) -> dict[str, str]:
    """Extract the ``[shortcuts]`` alias → target mapping from *data*."""
    shortcuts = data.get("shortcuts")
    if not isinstance(shortcuts, dict):
        return {}
    result: dict[str, str] = {}
    for alias, target in shortcuts.items():
        if isinstance(alias, str) and isinstance(target, str):
            result[alias] = target
    return result


def load_shortcuts() -> dict[str, str]:
    """Load the ``[shortcuts]`` section of the config file.

    The config file is the single source of truth: only the aliases actually
    present in the file are returned — remapped or deleted defaults included,
    there is no implicit fallback to the built-in defaults. A corrupted file
    yields a stderr warning (with repair options) and an empty mapping; the
    CLI keeps working.
    """
    data, error = _load_full_config_with_error()
    if error is not None:
        _warn_corrupted_config(error)
        return {}
    return _read_shortcuts_section(data)


def _warn_corrupted_config(error: Exception) -> None:
    """Print the corruption warning (stderr) with repair options."""
    click.echo(
        "⚠ Warning: ~/.ebx/config.toml is corrupted and cannot be parsed.\n"
        f"  Error: {error}\n"
        "\n"
        "  Options:\n"
        "    • Fix manually: edit ~/.ebx/config.toml\n"
        "    • Reset config: ebx config init (re-run guided setup)\n"
        "    • Reset shortcuts only: ebx config init --reset-shortcuts\n"
        "\n"
        "  Shortcuts are unavailable; the built-in commands "
        "(sandbox/config/mcp/template) still work.",
        err=True,
    )


def _has_shortcuts_section(text: str) -> bool:
    """Whether *text* contains a ``[shortcuts]`` table header."""
    return any(_SHORTCUTS_HEADER_RE.match(line) for line in text.splitlines())


def _shortcut_line(alias: str, target: str, *, enabled: bool) -> str:
    """Render one section line with the trailing comment aligned."""
    line = f'{alias} = "{target}"'
    if not enabled:
        line = f"# {line}"
    comment = _SHORTCUT_COMMENTS.get(alias, "")
    if not comment:
        return line
    return f"{line.ljust(36)}# {comment}"


def _generate_shortcuts_section() -> str:
    """Render the default ``[shortcuts]`` TOML block.

    Enabled aliases come from the CLI defaults (``_DEFAULT_SHORTCUTS``); any
    alias whose target cannot be resolved at runtime is skipped, so the
    generated file never contains a dead shortcut. The additional commands
    are appended commented out, ready to be uncommented.
    """
    from easy_sandbox.cli.main import _DEFAULT_SHORTCUTS, _SHORTCUT_TARGET_MAP

    sandbox_lines: list[str] = []
    other_lines: list[str] = []
    for alias, target in _DEFAULT_SHORTCUTS.items():
        if _SHORTCUT_TARGET_MAP.get(target) is None:
            continue
        line = _shortcut_line(alias, target, enabled=True)
        if target.startswith("sandbox "):
            sandbox_lines.append(line)
        else:
            other_lines.append(line)
    suggestion_lines = [
        _shortcut_line(alias, target, enabled=False) for alias, target in _SHORTCUT_SUGGESTIONS
    ]
    lines = [
        "[shortcuts]",
        "# === Sandbox shortcuts (enabled by default) ===",
        *sandbox_lines,
        "",
        "# === Template shortcuts (enabled by default) ===",
        *other_lines,
        "",
        "# === More commands (uncomment to enable) ===",
        *suggestion_lines,
    ]
    return "\n".join(lines) + "\n"


def _append_shortcuts_section() -> None:
    """Append the default ``[shortcuts]`` block to an existing config file."""
    try:
        text = _CONFIG_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        text += "\n"
    _CONFIG_FILE.write_text(text + _generate_shortcuts_section(), encoding="utf-8")


def _strip_shortcuts_section(text: str) -> str:
    """Return *text* without its ``[shortcuts]`` block.

    The block spans from the ``[shortcuts]`` header to the next table header
    (or end of file); the blank separator line in front of it is dropped too.
    """
    kept: list[str] = []
    in_shortcuts = False
    for line in text.splitlines():
        if _SHORTCUTS_HEADER_RE.match(line):
            in_shortcuts = True
            while kept and not kept[-1].strip():
                kept.pop()
            continue
        if in_shortcuts:
            if not _TABLE_HEADER_RE.match(line):
                continue
            in_shortcuts = False
        kept.append(line)
    result = "\n".join(kept)
    if not result.strip():
        return ""
    return result + "\n"


def _config_file_exists() -> bool:
    """Whether the config file exists *and* carries a ``[shortcuts]`` section.

    ``False`` makes the CLI bootstrap call :func:`_create_default_config`
    (fresh install, or a file predating the shortcuts feature). A corrupted
    file reports ``True`` so the automatic defaults never overwrite content
    the user may still want to repair.
    """
    if not _CONFIG_FILE.is_file():
        return False
    try:
        text = _CONFIG_FILE.read_text(encoding="utf-8")
    except OSError:
        return True
    if _has_shortcuts_section(text):
        return True
    _data, error = _load_full_config_with_error()
    return error is not None


def _create_default_config() -> None:
    """Materialise the default config: whole file, or missing section.

    * Missing file → fresh config with an empty ``[transport]`` table and the
      default ``[shortcuts]`` block.
    * Existing file without ``[shortcuts]`` → the default block is appended,
      preserving every stored value.
    * Corrupted file → left untouched (``load_shortcuts`` warns instead).
    """
    if _CONFIG_FILE.is_file():
        try:
            text = _CONFIG_FILE.read_text(encoding="utf-8")
        except OSError:
            return
        if _has_shortcuts_section(text):
            return
        _data, error = _load_full_config_with_error()
        if error is not None:
            return
        _append_shortcuts_section()
        return
    _EBX_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text("[transport]\n\n" + _generate_shortcuts_section(), encoding="utf-8")


def _ensure_shortcuts_section(fmt: OutputFormatter) -> None:
    """Append the default ``[shortcuts]`` block when the file lacks it."""
    if not _CONFIG_FILE.is_file() or _config_file_exists():
        return
    _append_shortcuts_section()
    fmt.print_success("Added default shortcuts to ~/.ebx/config.toml")


def _reset_shortcuts_section(fmt: OutputFormatter) -> None:
    """Rewrite ``[shortcuts]`` to its defaults, keeping every other section.

    Text-level surgery: even a corrupted file gets a valid shortcuts block
    without touching the (possibly hand-edited) transport content.
    """
    text = ""
    if _CONFIG_FILE.is_file():
        try:
            text = _CONFIG_FILE.read_text(encoding="utf-8")
        except OSError:
            text = ""
    remaining = _strip_shortcuts_section(text)
    _EBX_DIR.mkdir(parents=True, exist_ok=True)
    prefix = remaining + "\n" if remaining else ""
    _CONFIG_FILE.write_text(prefix + _generate_shortcuts_section(), encoding="utf-8")
    fmt.print_success("Reset [shortcuts] in ~/.ebx/config.toml to defaults")


def _get_shortcuts(fmt: OutputFormatter, key: str) -> None:
    """Implement ``config get shortcuts`` / ``config get shortcuts.NAME``."""
    _create_default_config()
    shortcuts = load_shortcuts()

    if key == "shortcuts":
        if not shortcuts:
            fmt.print_data("(no shortcuts configured)")
        else:
            fmt.print_dict(dict(shortcuts))
        return

    alias = key.split(".", 1)[1]
    if alias not in shortcuts:
        fmt.print_error(
            f"Unknown shortcut: {alias!r}",
            suggestion="See the configured shortcuts with 'ebx config get shortcuts'.",
        )
        sys.exit(2)
    fmt.print_data(shortcuts[alias])


def _align_suggestion(text: str) -> str:
    """Indent continuation lines under the ``Suggestion:`` label."""
    lines = text.splitlines()
    if len(lines) <= 1:
        return text
    indent = " " * len("  Suggestion: ")
    return lines[0] + "\n" + "\n".join(indent + line for line in lines[1:])


def _set_shortcut(fmt: OutputFormatter, alias: str, value: str) -> None:
    """Implement ``config set shortcuts.NAME VALUE`` (``""`` removes it)."""
    from easy_sandbox.cli.main import (
        _SHORTCUT_TARGET_MAP,
        RESERVED_NAMES,
        _describe_invalid_shortcut_target,
    )

    if alias in RESERVED_NAMES:
        fmt.print_error(
            f"Invalid shortcut name: {alias!r}",
            suggestion=(
                f"{alias!r} is a built-in command group and cannot be overridden. "
                f"Reserved names: {', '.join(sorted(RESERVED_NAMES))}."
            ),
        )
        sys.exit(2)
    if not _SHORTCUT_NAME_RE.match(alias):
        fmt.print_error(
            f"Invalid shortcut name: {alias!r}",
            suggestion="Shortcut names may contain letters, digits, '-' and '_'.",
        )
        sys.exit(2)

    _create_default_config()
    data, error = _load_full_config_with_error()
    if error is not None:
        _warn_corrupted_config(error)
        sys.exit(2)
    shortcuts = _read_shortcuts_section(data)

    if value.strip() == "":
        if alias not in shortcuts:
            fmt.print_success(f"No shortcut named {alias!r} (already not set).")
            return
        del shortcuts[alias]
        message = f"Removed shortcut {alias!r}"
    else:
        target = value.strip()
        if target not in _SHORTCUT_TARGET_MAP:
            hint = _describe_invalid_shortcut_target(target, alias=alias)
            fmt.print_error(
                f"Invalid shortcut target: {target!r}",
                suggestion=_align_suggestion(hint) if not fmt.use_json else hint,
            )
            sys.exit(2)
        shortcuts[alias] = target
        message = f"Set shortcut {alias} = {target}"

    data["shortcuts"] = shortcuts
    _save_full_config(data)
    fmt.print_success(message)


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
    3. ``GITHUB_TOKEN`` in the project ``.env``;
    4. the persistent ``github_token`` stored by ``ebx config set``
       (``~/.ebx/.env``);
    5. no token (``None``).

    The token value is never printed, logged, or persisted by this helper.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    value, source = _effective_value("github_token")
    if source == "unset" or not value:
        return None
    return str(value).strip()


def _canonicalize_key(key: str) -> str:
    """Map a deprecated CLI name to the key stored and listed today."""
    return _KEY_ALIASES.get(key, key)


def _reject_unknown_key(fmt: OutputFormatter, key: str) -> None:
    """Exit 2 for a key that is not configurable.

    Removed Qwen Code keys name their ``llm_*`` replacement. Every other
    unknown name lists the keys ``config list`` actually shows.
    """
    replacement = _REMOVED_KEYS.get(key)
    if replacement is not None:
        fmt.print_error(
            f"Config key {key!r} was removed.",
            suggestion=(
                f"Use {replacement!r}. NL inference and the coding agent share one "
                "LLM profile: llm_api_key, llm_base_url, llm_model."
            ),
        )
        sys.exit(2)
    fmt.print_error(
        f"Unknown config key: {key!r}",
        suggestion=f"Available keys: {', '.join(sorted(_ALLOWED_KEYS))}",
    )
    sys.exit(2)


def _business_default(key: str) -> Any | None:
    """Return the built-in default actually used for *key* (None = none).

    ``api_url`` / ``domain`` default to the values derived from the
    effective region, mirroring :func:`easy_sandbox.transport.config.load_config`.
    ``llm_base_url`` / ``llm_model`` default to the endpoint and model the
    coding agent uses when the user has not set them.
    """
    if key in ("api_url", "domain"):
        region, _source = _effective_value("region")
        if key == "api_url":
            return f"https://api.{region}.e2b.fc.aliyuncs.com"
        return f"{region}.e2b.fc.aliyuncs.com"
    if key == "llm_base_url":
        from easy_sandbox.agent.qwen_code import _DEFAULT_OPENAI_BASE_URL

        return _DEFAULT_OPENAI_BASE_URL
    if key == "llm_model":
        from easy_sandbox.agent.qwen_code import _DEFAULT_OPENAI_MODEL

        return _DEFAULT_OPENAI_MODEL
    from easy_sandbox.transport.config import TransportConfig

    default = getattr(TransportConfig(), key, None)
    if default is None or default == "":
        return None
    return default


def _env_override_name(key: str) -> str | None:
    """Return the environment variable currently overriding *key*, if any.

    A blank or whitespace-only value does not count, so the next layer
    (``./.env``, then ``~/.ebx``) is still used.
    """
    for name in _ENV_OVERRIDES.get(key, ()):
        value = os.environ.get(name)
        if value and value.strip():
            return name
    return None


def _effective_value(key: str) -> tuple[Any | None, str]:
    """Return ``(value, source)`` for *key*.

    *source* is ``"env"`` (process environment), ``"user"`` (stored in
    ~/.ebx/config.toml or ~/.ebx/.env), ``"default"`` (built-in) or
    ``"unset"`` (no value anywhere). An empty string is never treated as a
    valid stored value.

    Every key uses the same order: process environment, then ``./.env``,
    then the value stored under ~/.ebx, then a built-in default. A set
    environment variable always wins over a file. A key set in ``./.env``
    wins over the same key in ~/.ebx; a key the project file omits still
    comes from ~/.ebx. Env-stored keys read ~/.ebx/.env; keys in
    ``_LEGACY_TOML_ENV_KEYS`` additionally fall back to an old
    ``[transport]`` value in config.toml.
    """
    env_name = _env_override_name(key)
    if env_name is not None:
        return os.environ[env_name], "env"
    # A project .env sits between the process environment and ~/.ebx.
    # The same key in ~/.ebx is used only when the project file omits it.
    from easy_sandbox.transport.config import project_dotenv_value

    project_value = project_dotenv_value(_ENV_OVERRIDES.get(key, ()))
    if project_value:
        return project_value, "user"
    if key in _ENV_STORED_KEYS:
        stored = read_env_var(_ENV_STORED_KEYS[key])
        if stored:
            return stored, "user"
        if key in _LEGACY_TOML_ENV_KEYS:
            legacy = load_config_dict().get(key)
            if legacy not in (None, ""):
                return legacy, "user"
        for legacy_env in _LEGACY_ENV_FALLBACKS.get(key, ()):
            process_value = os.environ.get(legacy_env)
            if process_value:
                return process_value, "env"
            legacy_stored = read_env_var(legacy_env)
            if legacy_stored:
                return legacy_stored, "user"
        return None, "unset"
    config = load_config_dict()
    stored_value = config.get(key)
    if stored_value not in (None, ""):
        return stored_value, "user"
    legacy_toml = _LEGACY_TOML_FALLBACKS.get(key)
    if legacy_toml is not None:
        legacy_value = config.get(legacy_toml)
        if legacy_value not in (None, ""):
            return legacy_value, "user"
    default = _business_default(key)
    if default is None:
        return None, "unset"
    return default, "default"


def _display_value(key: str, value: Any) -> str:
    """Render *value* for display, masking sensitive keys."""
    text = str(value)
    return _mask_value(text) if key in _SENSITIVE_KEYS else text


def _remove_toml_key(key: str) -> bool:
    """Remove *key* from the ``[transport]`` table; return whether it existed.

    Other sections and the shortcuts table are preserved; the file itself
    is deleted once nothing of value remains (mirrors the behaviour of
    :func:`_clear_stored_value` for plain TOML keys).
    """
    full = _load_full_config()
    data = load_config_dict()
    if key not in data:
        return False
    del data[key]
    other_sections = {
        name: table
        for name, table in full.items()
        if isinstance(table, dict) and table and name != "transport"
    }
    if data or other_sections:
        _save_config_dict(data)
    elif _CONFIG_FILE.is_file():
        _CONFIG_FILE.unlink()
    return True


def _clear_stored_value(fmt: OutputFormatter, key: str) -> None:
    """Remove the persistent value for *key*.

    Used by ``ebx config delete KEY`` and ``ebx config set KEY ""``.

    An empty string is never stored as a credential or override: the key
    falls back to its built-in default or to not-set. When an environment
    variable still overrides the key at runtime, the user is told about it
    without ever printing its value.

    Keys in ``_LEGACY_TOML_ENV_KEYS`` (``llm_api_key``) are cleared from
    both the secure ``~/.ebx/.env`` storage and any legacy TOML copy, so a
    removed value can never resurrect from the old location.
    """
    if key in _ENV_STORED_KEYS:
        removed = remove_env_var(_ENV_STORED_KEYS[key])
        if key in _LEGACY_TOML_ENV_KEYS:
            removed = _remove_toml_key(key) or removed
        for legacy_env in _LEGACY_ENV_FALLBACKS.get(key, ()):
            removed = remove_env_var(legacy_env) or removed
    else:
        removed = _remove_toml_key(key)
        legacy_toml = _LEGACY_TOML_FALLBACKS.get(key)
        if legacy_toml is not None:
            removed = _remove_toml_key(legacy_toml) or removed

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
      ebx config delete region   Remove one stored value

    \b
    Related commands:
      ebx config init           Guided setup (credentials, region, ACR, LLM)
      ebx config get            Read one effective value
      ebx config set            Store or update one value
      ebx config delete KEY     Remove one stored value
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
      sandbox_api_key    Sandbox service API key (E2B-compatible; env vars
                         E2B_API_KEY > SANDBOX_API_KEY; stored in ~/.ebx/.env,
                         shown masked). ``api_key`` is accepted as an alias.
      access_key_id      Alibaba Cloud AccessKey ID for AK/SK auth
                         (template deploy, ACR push; stored in ~/.ebx/.env)
      access_key_secret  Alibaba Cloud AccessKey Secret for AK/SK auth
                         (template deploy, ACR push; stored in ~/.ebx/.env,
                         shown masked)
      acr_namespace      ACR namespace for template build, push, and install
                         (stored in ~/.ebx/.env as ACR_NAMESPACE)
      api_url            Platform API URL
      domain             Envd data-plane domain
      region             Default region (e.g. cn-hangzhou)
      http_timeout       HTTP request timeout in seconds
      http2              Enable HTTP/2 (true/false)
      max_retries        Maximum retry attempts
      llm_api_key        LLM API key for NL inference and the coding agent
                         (stored in ~/.ebx/.env as EBX_LLM_API_KEY, shown
                         masked; a legacy config.toml value is still readable)
      llm_model          LLM model name (default: qwen3-coder-plus)
      llm_base_url       LLM API base URL, OpenAI-compatible
                         (default: DashScope compatible-mode)
      github_token       GitHub token for template downloads (stored in
                         ~/.ebx/.env, shown masked)
      shortcuts          All top-level shortcuts configured in
                         ~/.ebx/config.toml
      shortcuts.<name>   Target command of one configured shortcut

    \b
    Examples:
      ebx config get sandbox_api_key
      ebx config get region
      ebx config list          # show all values at once
      ebx config get shortcuts           # all configured aliases
      ebx config get shortcuts.list      # target of one alias

    \b
    Related commands:
      ebx config list          Show every effective value and its source
      ebx config set KEY VALUE
      ebx config set KEY ""    Clear one stored value
    """
    fmt = get_formatter(ctx)
    key = _canonicalize_key(key)

    if key == "shortcuts" or key.startswith("shortcuts."):
        _get_shortcuts(fmt, key)
        return

    if key not in _ALLOWED_KEYS:
        _reject_unknown_key(fmt, key)
        return

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

    Settings are stored in ~/.ebx/config.toml, except credentials
    (sandbox_api_key, access_key_id, access_key_secret, acr_namespace,
    llm_api_key, github_token) which are
    written to ~/.ebx/.env using their environment-variable names. Setting
    llm_api_key also removes any legacy config.toml copy of it (the secret
    migrates to the 0600-protected ~/.ebx/.env storage).

    Passing an empty VALUE clears the stored value for KEY instead: the key
    falls back to its built-in default or becomes not set. An empty string
    is never stored as a credential or override. Environment variables that
    are still exported keep overriding the key at runtime; their values are
    never printed. Clearing llm_api_key removes both the ~/.ebx/.env entry
    and any legacy config.toml copy.

    In an interactive terminal VALUE may be omitted: sensitive keys
    (github_token, sandbox_api_key, access_key_secret, llm_api_key) are then
    read through the masked (asterisk) input and the typed value is never
    echoed; other keys use a visible prompt. Pressing Enter at the prompt
    cancels without changing anything. In CI / non-interactive sessions
    VALUE is required.

    \b
    Available keys (expected value):
      sandbox_api_key    Sandbox service API key, E2B-compatible (string;
                         env vars E2B_API_KEY > SANDBOX_API_KEY).
                         ``api_key`` is accepted as an alias.
      access_key_id      Alibaba Cloud AccessKey ID for AK/SK auth, used by
                         template deploy and ACR push (string)
      access_key_secret  Alibaba Cloud AccessKey Secret for AK/SK auth, used by
                         template deploy and ACR push (string)
      acr_namespace      ACR namespace for template build, push, and install
                         (string; stored in ~/.ebx/.env as ACR_NAMESPACE)
      api_url            Platform API URL (e.g. https://api.cn-hangzhou.e2b.fc.aliyuncs.com)
      domain             Envd data-plane domain (e.g. cn-hangzhou.e2b.fc.aliyuncs.com)
      region             Default region (e.g. cn-hangzhou, cn-shanghai)
      http_timeout       HTTP request timeout in seconds (number, e.g. 120)
      http2              Enable HTTP/2 (true/false)
      max_retries        Maximum retry attempts (integer, e.g. 3)
      llm_api_key        LLM API key for NL inference and the coding agent,
                         e.g. a DashScope/ModelStudio key (string; stored in
                         ~/.ebx/.env as EBX_LLM_API_KEY)
      llm_model          LLM model name (default: qwen3-coder-plus)
      llm_base_url       LLM API base URL, OpenAI-compatible (string;
                         default: DashScope compatible-mode)
      github_token       GitHub token for template downloads, used by
                         'ebx template install' / 'ebx template search'
                         (string; stored in ~/.ebx/.env)
      shortcuts.<name>   Top-level shortcut. The value is the command path
                         without the "ebx" prefix, for example
                         "template init" (not "ebx template init"):
                         'ebx config set shortcuts.ps "sandbox process list"';
                         an empty VALUE removes the shortcut

    \b
    Examples:
      ebx config set sandbox_api_key YOUR_API_KEY
      ebx config set access_key_id YOUR_ACCESS_KEY_ID
      ebx config set access_key_secret YOUR_ACCESS_KEY_SECRET
      ebx config set acr_namespace YOUR_ACR_NAMESPACE
      ebx config set region cn-hangzhou
      ebx config set http_timeout 120
      ebx config set http2 false
      ebx config set llm_api_key YOUR_DASHSCOPE_OR_LLM_KEY
      ebx config set region ""          # clear the stored region
      ebx config set sandbox_api_key ""  # remove the stored sandbox API key
      ebx config set github_token      # masked prompt (VALUE omitted)
      ebx config set github_token YOUR_GITHUB_TOKEN
      ebx config set github_token ""    # remove the stored token
      ebx config set shortcuts.ps "sandbox process list"
      ebx config set shortcuts.ps ""    # remove the 'ps' shortcut

    \b
    Related commands:
      ebx config get KEY       Verify the effective value
      ebx config list          Review effective values and sources
      ebx config delete KEY    Remove one stored value
    """
    fmt = get_formatter(ctx)

    if key.startswith("shortcuts."):
        alias = key.split(".", 1)[1]
        if value is None:
            value = _prompt_missing_value(fmt, key)
            if value is None:
                return
        _set_shortcut(fmt, alias, value)
        return

    key = _canonicalize_key(key)
    if key not in _ALLOWED_KEYS:
        _reject_unknown_key(fmt, key)
        return

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
        if key in _LEGACY_TOML_ENV_KEYS:
            # Migrate away from the legacy plaintext copy in config.toml:
            # after this write the secret lives only in the 0600-protected
            # ~/.ebx/.env storage, never in two places at once.
            _remove_toml_key(key)
        for legacy_env in _LEGACY_ENV_FALLBACKS.get(key, ()):
            # The unified key replaces the older Qwen Code secret.
            remove_env_var(legacy_env)
        display_value = _mask_value(value) if key in _SENSITIVE_KEYS else value
        fmt.print_success(f"Set {key} = {display_value}")
        return

    data = load_config_dict()
    legacy_toml = _LEGACY_TOML_FALLBACKS.get(key)
    if legacy_toml is not None:
        data.pop(legacy_toml, None)

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


@config.command("delete")
@click.argument("key")
@click.pass_context
@handle_errors
def delete_value(ctx: click.Context, key: str) -> None:
    """Remove one stored configuration value.

    Deletes the value written by ``ebx config set``. The key then falls
    back to its built-in default or becomes not set. An environment
    variable that still overrides the key is left in place and named in
    the result, without printing its value. ``~/.ebx`` itself is not
    removed. ``ebx config set KEY ""`` does the same thing.

    ``shortcuts.<name>`` removes that one alias. Built-in command names
    (``sandbox``, ``template``, ``config``, ``mcp``) cannot be deleted.

    \b
    Examples:
      ebx config delete acr_namespace
      ebx config delete access_key_secret
      ebx config delete shortcuts.ps

    \b
    Related commands:
      ebx config list          See what is still stored
      ebx config set KEY VALUE Store a value again
      ebx config set KEY ""    The same removal, via set
    """
    fmt = get_formatter(ctx)

    if key.startswith("shortcuts."):
        alias = key.split(".", 1)[1]
        _set_shortcut(fmt, alias, "")
        return

    key = _canonicalize_key(key)
    if key not in _ALLOWED_KEYS:
        _reject_unknown_key(fmt, key)
        return
    _clear_stored_value(fmt, key)


@config.command("list")
@click.pass_context
@handle_errors
def list_config(ctx: click.Context) -> None:
    """List all effective configuration values and their sources.

    Values are grouped by function — Sandbox authentication, Alibaba
    Cloud credentials, connection, LLM, integrations, and shortcuts —
    in a stable order. Group titles are
    display-only: ``config get`` and ``config set`` keep taking the bare
    key names, and ``--json`` output stays a flat ``{key: value}`` map.

    Sources: ``(env)`` a process environment variable, ``(user)`` a value
    in ``./.env`` or stored with ``ebx config set``, ``(default)`` a
    built-in default, and ``(not set)`` when no value exists anywhere.
    A set environment variable wins over either file. ``./.env`` wins
    over ``~/.ebx`` for a key it sets; a key it omits still comes from
    ``~/.ebx``. Sensitive values are always masked.

    \b
    Examples:
      ebx config list
      ebx --json config list
      ebx config get http_timeout

    \b
    Related commands:
      ebx config get KEY        Inspect one effective value
      ebx config set KEY VALUE
      ebx config delete KEY     Remove one stored value
    """
    fmt = get_formatter(ctx)

    # Stable order: the functional groups, then any key the groups do not
    # cover yet (safety net so a newly added key is never invisible).
    grouped: list[tuple[str, tuple[str, ...]]] = [
        (title, keys) for title, keys in _CONFIG_GROUPS if keys
    ]
    covered = {key for _title, keys in grouped for key in keys}
    leftover = tuple(k for k in _ALLOWED_KEYS if k not in covered)
    if leftover:
        grouped.append(("Other", leftover))
    ordered_keys = [key for _title, keys in grouped for key in keys]

    # Configured shortcuts: the file is the single source of truth, each
    # alias is annotated as matching the defaults or user-defined.
    _create_default_config()
    shortcuts = load_shortcuts()
    shortcut_rows: list[tuple[str, str]] = []
    if shortcuts:
        from easy_sandbox.cli.main import _DEFAULT_SHORTCUTS

        for alias, target in shortcuts.items():
            shortcut_source = "default" if _DEFAULT_SHORTCUTS.get(alias) == target else "user"
            shortcut_rows.append((f"shortcuts.{alias}", f"{target} ({shortcut_source})"))

    def _render(key: str) -> str:
        value, source = _effective_value(key)
        if value is None:
            return "(not set)"
        return f"{_display_value(key, value)} ({source})"

    # BUG-02: In JSON mode, output pure values without source annotations.
    # The grouping is display-only, so JSON stays a flat {key: value} map
    # in the same stable order.
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
        result_json["shortcuts"] = load_shortcuts()
        fmt.print_dict(result_json)
        return

    if fmt.quiet:
        for _title, keys in grouped:
            for key in keys:
                click.echo(_render(key))
        for _alias, rendered in shortcut_rows:
            click.echo(rendered)
        return

    max_key_len = max((len(key) for key in ordered_keys), default=0)
    for index, (title, keys) in enumerate(grouped):
        if index:
            click.echo()
        header = f"── {title} "
        click.echo(header + "─" * max(0, 64 - len(header)))
        for key in keys:
            click.echo(f"{key.ljust(max_key_len)}  {_render(key)}")

    if shortcut_rows:
        if grouped:
            click.echo()
        header = "── Shortcuts "
        click.echo(header + "─" * max(0, 64 - len(header)))
        shortcut_width = max((len(alias) for alias, _ in shortcut_rows), default=0)
        for alias, rendered in shortcut_rows:
            click.echo(f"{alias.ljust(shortcut_width)}  {rendered}")


def _print_noninteractive_setup() -> None:
    """Print the non-interactive commands equivalent to the guided wizard."""
    lines = [
        "Non-interactive setup. Run these commands to configure ebx:",
        "",
        "  ebx config set sandbox_api_key <E2B_API_KEY>",
        "  ebx config set region cn-hangzhou",
        "  ebx config set llm_api_key <DASHSCOPE_OR_MODELSTUDIO_KEY>",
        "",
        "  # Required to build, push, and install templates:",
        "  ebx config set acr_namespace <ACR_NAMESPACE>",
        "  ebx config set access_key_id <ALICLOUD_ACCESS_KEY_ID>",
        "  ebx config set access_key_secret <ALICLOUD_ACCESS_KEY_SECRET>",
        "",
        "  # Optional overrides:",
        "  ebx config set llm_base_url <OPENAI_COMPATIBLE_BASE_URL>",
        "  ebx config set llm_model qwen3-coder-plus",
        "",
        "Environment variables (E2B_API_KEY, EBX_LLM_API_KEY, ACR_NAMESPACE,",
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
@click.option(
    "--reset-shortcuts",
    is_flag=True,
    help="Reset [shortcuts] section to defaults",
)
@click.pass_context
@handle_errors
def init(ctx: click.Context, yes: bool, reset_shortcuts: bool) -> None:
    """Guided setup: credentials, region, ACR namespace, and the LLM API key.

    In a terminal this prompts for the platform API key, the default
    region, the LLM API key used for AI template generation and NL
    inference (``ebx create "<description>"``; consumed by Qwen Code),
    the ACR namespace, and the Alibaba Cloud AccessKey pair. The last
    three are what ``ebx install`` and ``ebx template deploy`` need in
    order to build and push an image. Press Enter to skip a prompt.
    Secrets are typed with asterisk feedback (never echoed) when the
    terminal supports it, and stored in ~/.ebx/.env; the region goes to
    ~/.ebx/config.toml. The namespace is stored as ``ACR_NAMESPACE``.

    In non-TTY environments (CI, piped input) the wizard never blocks: it
    prints the equivalent non-interactive ``ebx config set ...`` commands
    and exits successfully. ``--yes`` behaves the same way.

    ``--reset-shortcuts`` restores the default ``[shortcuts]`` section of
    ~/.ebx/config.toml (and nothing else), then exits.

    \b
    Examples:
      ebx config init
      ebx config init --yes     # print non-interactive commands
      ebx config init --reset-shortcuts    # restore default shortcuts only

    \b
    Related commands:
      ebx config list           Review effective values and sources
      ebx config set KEY VALUE  Set one value directly
      ebx config set KEY ""     Clear one stored value
    """
    fmt = get_formatter(ctx)

    if reset_shortcuts:
        _reset_shortcuts_section(fmt)
        return

    # Never block in CI / piped sessions.
    if yes or not sys.stdin.isatty():
        _print_noninteractive_setup()
        return

    click.echo("ebx guided configuration (press Enter to keep the current value or skip):")
    click.echo()

    api_key = _prompt_secret("1/6 Sandbox API key (sandbox_api_key / E2B_API_KEY, input masked)")
    if api_key.strip():
        write_env_var("E2B_API_KEY", api_key.strip())
        fmt.print_success("Stored sandbox_api_key in ~/.ebx/.env")

    data = load_config_dict()
    current_region = str(data.get("region") or "cn-hangzhou")
    region = click.prompt("2/6 Region", default=current_region, show_default=True)
    if region.strip():
        data["region"] = region.strip()
        _save_config_dict(data)
        fmt.print_success(f"Set region = {region.strip()}")
    _ensure_shortcuts_section(fmt)

    llm_key = _prompt_secret("3/6 LLM API key (DashScope/ModelStudio, input masked)")
    if llm_key.strip():
        write_env_var("EBX_LLM_API_KEY", llm_key.strip())
        # Same migration as `ebx config set llm_api_key`: drop any legacy
        # plaintext copy in config.toml once the secure storage is written.
        _remove_toml_key("llm_api_key")
        fmt.print_success("Stored llm_api_key in ~/.ebx/.env")

    current_ns, _ns_source = _effective_value("acr_namespace")
    namespace = click.prompt(
        "4/6 ACR namespace (needed by ebx install / template deploy)",
        default=str(current_ns or ""),
        show_default=bool(current_ns),
    )
    if namespace.strip():
        write_env_var("ACR_NAMESPACE", namespace.strip())
        fmt.print_success(f"Set acr_namespace = {namespace.strip()}")

    access_key_id = click.prompt(
        "5/6 Alibaba Cloud AccessKey ID (template deploy / ACR push)",
        default="",
        show_default=False,
    )
    if access_key_id.strip():
        write_env_var("ALICLOUD_ACCESS_KEY_ID", access_key_id.strip())
        fmt.print_success("Stored access_key_id in ~/.ebx/.env")

    access_key_secret = _prompt_secret("6/6 Alibaba Cloud AccessKey Secret (input masked)")
    if access_key_secret.strip():
        write_env_var("ALICLOUD_ACCESS_KEY_SECRET", access_key_secret.strip())
        fmt.print_success("Stored access_key_secret in ~/.ebx/.env")

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
    return str(click.prompt(prompt_text, hide_input=True, default="", show_default=False))


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
