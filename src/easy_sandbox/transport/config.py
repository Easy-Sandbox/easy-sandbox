"""Layered configuration loading.

Priority: code params > process environment (E2B_* first, SANDBOX_* fallback)
> .env files > ~/.ebx/config.toml > defaults. A blank or whitespace-only
value does not count and does not hide the next layer.

``.env`` files are merged per key. ``./.env`` overrides ``~/.ebx/.env`` when
both set the same key; a key missing from the project file still comes from
the system file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from easy_sandbox.utils.logging import get_logger

logger = get_logger("transport.config")

# envd 数据平面固定端口（已实测验证）
ENVD_PORT: int = 49983

_EBX_DIR = Path.home() / ".ebx"  # SDK extension
_CONFIG_FILE = _EBX_DIR / "config.toml"  # SDK extension
# Earlier entries win per key. A missing key falls through to the next file.
_ENV_FILE_CANDIDATES = [Path(".env"), _EBX_DIR / ".env"]
# Project dotenv only. The CLI reads this between the process environment
# and ~/.ebx. Tests point it at a missing file so a repo .env cannot leak.
_PROJECT_ENV_FILE = Path(".env")

# Module-level cache
_cached_config: TransportConfig | None = None


class TransportConfig(BaseModel):
    """Transport-layer configuration.

    Loaded lazily from multiple sources with priority:
    code params > env vars (E2B_* > SANDBOX_*) > .env files > config.toml > defaults
    """

    # API endpoints
    api_url: str = Field(
        default="https://api.cn-hangzhou.e2b.fc.aliyuncs.com",
        description="Platform API URL",
    )
    domain: str = Field(
        default="cn-hangzhou.e2b.fc.aliyuncs.com",
        description="Data-plane domain",
    )
    region: str = "cn-hangzhou"

    # Authentication
    api_key: str | None = Field(default=None, description="Sandbox API key (E2B_API_KEY)")
    access_key_id: str | None = Field(
        default=None, description="Alibaba Cloud AK (ALICLOUD_ACCESS_KEY_ID)"
    )
    access_key_secret: str | None = Field(
        default=None, description="Alibaba Cloud SK (ALICLOUD_ACCESS_KEY_SECRET)"
    )

    # HTTP settings
    http_timeout: float = Field(default=30.0, ge=1.0, description="HTTP request timeout in seconds")
    max_connections: int = Field(default=100, ge=1)
    max_keepalive_connections: int = Field(default=20, ge=1)
    keepalive_expiry: float = Field(default=30.0, ge=1.0)
    http2: bool = True

    # WebSocket settings
    ws_ping_interval: float = Field(
        default=30.0, ge=1.0, description="WebSocket ping interval in seconds"
    )

    # Retry settings
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay: float = Field(default=1.0, ge=0.1)

    model_config = {"extra": "ignore"}

    # --- backward-compat aliases ---
    @property
    def api_base_url(self) -> str:
        """Deprecated alias for api_url. Kept for backward compatibility."""
        return self.api_url

    def build_envd_url(self, sandbox_id: str) -> str:
        """构建 envd 数据平面 URL（已实测验证）。

        格式: https://{ENVD_PORT}-{sandbox_id}.{domain}
        """
        return f"https://{ENVD_PORT}-{sandbox_id}.{self.domain}"


# Single merged env-var mapping. E2B_* entries are listed first so they can
# be checked with higher priority at read time.
_ENV_VAR_MAP: list[tuple[str, str, bool]] = [
    # (env_var_name, field_name, is_e2b_official)
    ("E2B_API_KEY", "api_key", True),
    ("E2B_API_URL", "api_url", True),
    ("E2B_DOMAIN", "domain", True),
    ("SANDBOX_API_KEY", "api_key", False),
    ("ALICLOUD_ACCESS_KEY_ID", "access_key_id", False),
    ("ALICLOUD_ACCESS_KEY_SECRET", "access_key_secret", False),
    ("AccessKey", "access_key_id", False),
    ("AccessSecret", "access_key_secret", False),
    ("SANDBOX_API_BASE_URL", "api_url", False),
    ("SANDBOX_REGION", "region", False),
    ("SANDBOX_HTTP_TIMEOUT", "http_timeout", False),
]

# Fields that need numeric conversion
_NUMERIC_FIELDS: set[str] = {"http_timeout"}


def _coerce_value(field_name: str, raw: str) -> Any:
    """Convert a raw string value to the appropriate type for *field_name*.

    A blank or whitespace-only value is unset, so it does not hide the next
    configuration layer.
    """
    text = raw.strip()
    if not text:
        return None
    if field_name in _NUMERIC_FIELDS:
        try:
            return float(text)
        except ValueError:
            logger.warning("Invalid numeric value for %s: %s", field_name, text)
            return None
    return text


def _load_toml_file(path: Path) -> dict[str, Any]:
    """Load a TOML file, returning empty dict on failure."""
    if not path.is_file():
        return {}
    try:
        try:
            import tomllib  # type: ignore[import-not-found]  # Python 3.11+
        except ImportError:
            import tomli as tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
        logger.debug("Loaded config from %s", path)
        return dict(data)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def _load_dotenv_file() -> dict[str, str]:
    """Merge every existing ``.env`` candidate into one env-like dict.

    Candidates are listed highest priority first. A key set in an earlier
    file wins; a key that file does not set still comes from a later file.
    Empty values are ignored so they do not hide a real key.
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        return {}

    merged: dict[str, str] = {}
    for candidate in reversed(_ENV_FILE_CANDIDATES):
        if not candidate.is_file():
            continue
        values = dotenv_values(candidate)
        logger.debug("Loaded .env from %s", candidate)
        for key, value in values.items():
            if value and value.strip():
                merged[key] = value.strip()
    return merged


def project_dotenv_value(names: tuple[str, ...]) -> str | None:
    """Return the first non-empty *names* entry in the project ``.env``.

    This is the layer between the process environment and ``~/.ebx``.
    It does not read ``~/.ebx/.env``; callers add that fallback themselves.
    """
    if not _PROJECT_ENV_FILE.is_file():
        return None
    try:
        from dotenv import dotenv_values

        values = dotenv_values(_PROJECT_ENV_FILE)
    except (OSError, ValueError):
        return None
    for name in names:
        value = values.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _read_env_vars() -> dict[str, Any]:
    """Read recognised environment variables.

    E2B_* official vars take precedence; SANDBOX_* vars act as fallbacks.
    Uses the single merged _ENV_VAR_MAP to avoid duplicate iteration.
    """
    result: dict[str, Any] = {}
    set_fields: set[str] = set()  # track fields already set (first-wins)

    for env_var, field_name, is_e2b in _ENV_VAR_MAP:
        if not is_e2b and field_name in set_fields:
            continue  # already provided by higher-priority var
        value = os.environ.get(env_var)
        if value is not None:
            coerced = _coerce_value(field_name, value)
            if coerced is not None:
                result[field_name] = coerced
                set_fields.add(field_name)
    return result


def _env_dict_to_fields(env_vals: dict[str, str]) -> dict[str, Any]:
    """Convert env-style key-values (from .env file) to TransportConfig field names.

    Applies the same priority: E2B_* entries override SANDBOX_* entries.
    """
    result: dict[str, Any] = {}
    set_fields: set[str] = set()

    for env_var, field_name, is_e2b in _ENV_VAR_MAP:
        if env_var not in env_vals:
            continue
        if not is_e2b and field_name in set_fields:
            continue
        coerced = _coerce_value(field_name, env_vals[env_var])
        if coerced is not None:
            result[field_name] = coerced
            set_fields.add(field_name)
    return result


def load_config(**overrides: Any) -> TransportConfig:
    """Load transport configuration with layered priority.

    Priority (highest to lowest):
    1. Code-level *overrides*
    2. Environment variables (E2B_* > SANDBOX_*)
    3. .env files, merged per key (``./.env`` overrides ``~/.ebx/.env``)
    4. ~/.ebx/config.toml (optional SDK extension)
    5. TransportConfig defaults

    A blank or whitespace-only override or environment value is ignored.

    Args:
        **overrides: Code-level parameter overrides (highest priority).

    Returns:
        Merged TransportConfig instance.
    """
    global _cached_config
    if _cached_config is not None and not overrides:
        return _cached_config

    # Accept legacy 'api_base_url' key from callers and remap it
    if "api_base_url" in overrides and "api_url" not in overrides:
        overrides["api_url"] = overrides.pop("api_base_url")

    # Layer 4 (lowest): config.toml
    merged: dict[str, Any] = {}
    toml_data = _load_toml_file(_CONFIG_FILE)
    if "transport" in toml_data:
        merged.update(toml_data["transport"])
    else:
        merged.update(toml_data)
    # Remap legacy key from toml
    if "api_base_url" in merged and "api_url" not in merged:
        merged["api_url"] = merged.pop("api_base_url")

    # Layer 3: .env file
    dotenv_vals = _load_dotenv_file()
    merged.update(_env_dict_to_fields(dotenv_vals))

    # Layer 2: environment variables
    merged.update(_read_env_vars())

    # Layer 1 (highest): code-level overrides. Blank strings are unset.
    applied_overrides: dict[str, Any] = {}
    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        applied_overrides[key] = value
    merged.update(applied_overrides)

    def _env_present(name: str) -> bool:
        raw = os.environ.get(name)
        return bool(raw and raw.strip())

    # Auto-derive api_url and domain from region when not explicitly set
    _explicit_url = (
        "api_url" in applied_overrides
        or "api_base_url" in applied_overrides
        or _env_present("SANDBOX_API_BASE_URL")
        or _env_present("E2B_API_URL")
    )
    if not _explicit_url and "region" in merged:
        merged.setdefault("api_url", f"https://api.{merged['region']}.e2b.fc.aliyuncs.com")
        merged.setdefault("domain", f"{merged['region']}.e2b.fc.aliyuncs.com")

    config = TransportConfig(**merged)

    if not overrides:
        _cached_config = config
    return config


def reset_config() -> None:
    """Clear the cached configuration (useful for testing)."""
    global _cached_config
    _cached_config = None


def http_timeout_configured() -> bool:
    """Return True when the user explicitly configured ``http_timeout``.

    Checks the same sources as :func:`load_config` (env vars, .env file,
    ``~/.ebx/config.toml``) without applying defaults.  The CLI uses this
    to decide whether a slow operation (e.g. sandbox create) should get a
    longer built-in HTTP timeout instead of the 30s default.
    """
    timeout = os.environ.get("SANDBOX_HTTP_TIMEOUT")
    if timeout and timeout.strip():
        return True
    # .env files use env-var-style keys (see _ENV_VAR_MAP), not field names.
    if "SANDBOX_HTTP_TIMEOUT" in _load_dotenv_file():
        return True
    toml_data = _load_toml_file(_CONFIG_FILE)
    section = toml_data.get("transport", toml_data)
    return "http_timeout" in section
