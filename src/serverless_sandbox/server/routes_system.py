"""System-information, environment-variable, port/package/metrics endpoints.

Provides:
- ``GET /capabilities`` — list all capability groups and their enabled state
- ``GET /system/info`` — OS, CPU, memory, disk, Python version
- ``GET /env`` — filtered environment variables (sensitive values redacted)
- ``POST /env`` — set environment variables (protected keys blocked)
- ``GET /ports`` — listening TCP ports
- ``GET /packages`` — installed packages (pip / npm)
- ``GET /system/metrics`` — live resource-usage metrics

All handlers use only the Python standard library (no *psutil*).
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess  # noqa: S404
import sys
import time
from typing import Any

from .router import CapabilityGroup, default_table
from .types import ServerRequest, ServerResponse

__all__ = [
    "handle_capabilities",
    "handle_env_get",
    "handle_env_set",
    "handle_packages",
    "handle_ports",
    "handle_system_info",
    "handle_system_metrics",
]

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

#: Sub-strings whose presence in a variable name makes it sensitive.
_ENV_BLACKLIST_TOKENS: frozenset[str] = frozenset({
    "TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL",
})

#: Variable names that ``POST /env`` may never overwrite.
_PROTECTED_ENV_VARS: frozenset[str] = frozenset({
    "PATH", "HOME", "USER", "SHELL", "SBOX_SERVER_TOKEN",
})

# ---------------------------------------------------------------------------
# Boot timestamp (approximate process start).
# ---------------------------------------------------------------------------

_BOOT_TIME: float = time.time()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_sensitive(name: str) -> bool:
    """Return ``True`` if *name* looks like it could contain a credential."""
    upper = name.upper()
    return any(tok in upper for tok in _ENV_BLACKLIST_TOKENS)


def _read_proc_file(path: str) -> str | None:
    """Read a ``/proc`` file, returning ``None`` when unavailable."""
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def _parse_meminfo() -> dict[str, int]:
    """Parse ``/proc/meminfo`` into a ``{key: kB_value}`` mapping."""
    text = _read_proc_file("/proc/meminfo")
    if text is None:
        return {}
    result: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        val_str = parts[1].strip().split()[0]  # "16384 kB" -> "16384"
        try:
            result[key] = int(val_str)
        except ValueError:
            continue
    return result


def _memory_fallback() -> tuple[int, int]:
    """Return ``(total_mb, available_mb)`` using :mod:`resource` on non-Linux."""
    try:
        import resource  # noqa: PLC0415

        # soft limit of address space (bytes) — very rough proxy
        soft, _hard = resource.getrlimit(resource.RLIMIT_AS)
        total = soft // (1024 * 1024) if soft > 0 and soft != resource.RLIM_INFINITY else 0
        return total, 0
    except Exception:  # noqa: BLE001
        return 0, 0


def _parse_proc_net_tcp(path: str) -> list[dict[str, Any]]:
    """Parse ``/proc/net/tcp`` (or ``tcp6``) into listening-port dicts."""
    text = _read_proc_file(path)
    if text is None:
        return []
    results: list[dict[str, Any]] = []
    lines = text.strip().splitlines()
    for line in lines[1:]:  # skip header
        fields = line.split()
        if len(fields) < 4:
            continue
        # st field (index 3) — 0A = LISTEN
        if fields[3] != "0A":
            continue
        local = fields[1]  # e.g. "0100007F:1F90"
        addr_hex, port_hex = local.rsplit(":", 1)
        port = int(port_hex, 16)
        # Decode address
        protocol = "tcp6" if "tcp6" in path else "tcp"
        if len(addr_hex) == 8:
            # IPv4 — stored in little-endian hex
            octets = [str(int(addr_hex[i:i + 2], 16)) for i in range(6, -1, -2)]
            address = ".".join(octets)
        else:
            address = "[::]"
        # PID: field 9 or uid-based — not always available without root
        pid: int | None = None
        results.append({
            "port": port,
            "protocol": protocol,
            "address": address,
            "pid": pid,
        })
    return results


def _ports_via_ss() -> list[dict[str, Any]]:
    """Fallback: use ``ss -tlnp`` to list listening TCP ports."""
    try:
        proc = subprocess.run(  # noqa: S603
            shlex.split("ss -tlnp"),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        return []
    results: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]  # e.g. "0.0.0.0:8080" or "[::]:443"
        match = re.search(r":(\d+)$", local)
        if not match:
            continue
        port = int(match.group(1))
        address = local[: match.start()]
        pid: int | None = None
        # Try to extract PID from the last column (users:...)
        if len(parts) >= 6:
            pid_match = re.search(r"pid=(\d+)", parts[-1])
            if pid_match:
                pid = int(pid_match.group(1))
        results.append({
            "port": port,
            "protocol": "tcp",
            "address": address,
            "pid": pid,
        })
    return results


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_capabilities(request: ServerRequest) -> ServerResponse:
    """``GET /capabilities`` — list capability groups and their enabled state."""
    groups = default_table().list_groups()
    return ServerResponse.ok({"groups": groups})


def handle_system_info(request: ServerRequest) -> ServerResponse:
    """``GET /system/info`` — OS / CPU / memory / disk / Python info."""
    uname = platform.uname()

    # Memory
    meminfo = _parse_meminfo()
    if meminfo:
        mem_total_mb = meminfo.get("MemTotal", 0) // 1024
        mem_avail_mb = meminfo.get("MemAvailable", 0) // 1024
    else:
        mem_total_mb, mem_avail_mb = _memory_fallback()

    # Disk
    try:
        usage = shutil.disk_usage("/")
        disk_total_gb = round(usage.total / (1024 ** 3), 2)
        disk_free_gb = round(usage.free / (1024 ** 3), 2)
    except OSError:
        disk_total_gb = 0.0
        disk_free_gb = 0.0

    return ServerResponse.ok({
        "os": uname.system,
        "arch": uname.machine,
        "cpu_count": os.cpu_count() or 0,
        "memory_total_mb": mem_total_mb,
        "memory_available_mb": mem_avail_mb,
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "python_version": sys.version.split()[0],
        "hostname": uname.node,
    })


def handle_env_get(request: ServerRequest) -> ServerResponse:
    """``GET /env`` — list environment variables with blacklist filtering.

    Query parameter ``filter`` accepts a comma-separated whitelist of names.
    Variables whose names contain security-sensitive tokens are always excluded.
    """
    raw_filter = request.query.get("filter", [""])[0]
    whitelist: set[str] | None = None
    if raw_filter:
        whitelist = {v.strip() for v in raw_filter.split(",") if v.strip()}

    variables: dict[str, str] = {}
    for name, value in os.environ.items():
        if _is_sensitive(name):
            continue
        if whitelist is not None and name not in whitelist:
            continue
        variables[name] = value

    return ServerResponse.ok({"variables": variables})


def handle_env_set(request: ServerRequest) -> ServerResponse:
    """``POST /env`` — set environment variables.

    Body: ``{"vars": {"KEY": "value", ...}}``.
    Protected variables (PATH, HOME, USER, SHELL, SBOX_SERVER_TOKEN) cannot
    be overwritten.
    """
    body = request.body or {}
    env_vars: dict[str, str] = body.get("vars", {})
    if not isinstance(env_vars, dict):
        return ServerResponse.error(400, "'vars' must be an object", "ValueError")

    # Validate protected keys first
    blocked = sorted(k for k in env_vars if k in _PROTECTED_ENV_VARS)
    if blocked:
        return ServerResponse.error(
            403,
            f"Cannot overwrite protected variable(s): {', '.join(blocked)}",
            "PermissionError",
        )

    updated: list[str] = []
    for key, value in env_vars.items():
        os.environ[key] = str(value)
        updated.append(key)

    return ServerResponse.ok({"updated": sorted(updated)})


def handle_ports(request: ServerRequest) -> ServerResponse:
    """``GET /ports`` — list listening TCP ports."""
    listening: list[dict[str, Any]] = []

    # Try /proc/net/tcp{,6} first
    tcp4 = _parse_proc_net_tcp("/proc/net/tcp")
    tcp6 = _parse_proc_net_tcp("/proc/net/tcp6")
    listening.extend(tcp4)
    listening.extend(tcp6)

    # Fallback to ss if /proc was empty
    if not listening:
        listening = _ports_via_ss()

    return ServerResponse.ok({"listening": listening})


def handle_packages(request: ServerRequest) -> ServerResponse:
    """``GET /packages`` — list installed packages for a given manager.

    Query parameter ``manager`` selects ``pip`` (default) or ``npm``.
    """
    manager = request.query.get("manager", ["pip"])[0]

    if manager == "pip":
        cmd_parts = [sys.executable, "-m", "pip", "list", "--format", "json"]
    elif manager == "npm":
        cmd_parts = shlex.split("npm list --json --depth=0")
    else:
        return ServerResponse.error(
            400,
            f"Unsupported package manager: {manager!r}; use 'pip' or 'npm'",
            "ValueError",
        )

    try:
        proc = subprocess.run(  # noqa: S603
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return ServerResponse.ok({"manager": manager, "packages": []})
    except subprocess.TimeoutExpired:
        return ServerResponse.error(500, f"{manager} timed out", "TimeoutError")
    except Exception as exc:  # noqa: BLE001
        return ServerResponse.error(500, str(exc), type(exc).__name__)

    packages: list[dict[str, str]] = []
    if manager == "pip":
        try:
            raw = json.loads(proc.stdout)
            for item in raw:
                packages.append({
                    "name": item.get("name", ""),
                    "version": item.get("version", ""),
                })
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    elif manager == "npm":
        try:
            raw = json.loads(proc.stdout)
            deps = raw.get("dependencies", {})
            for name, info in deps.items():
                ver = info.get("version", "") if isinstance(info, dict) else str(info)
                packages.append({"name": name, "version": ver})
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    return ServerResponse.ok({"manager": manager, "packages": packages})


def handle_system_metrics(request: ServerRequest) -> ServerResponse:
    """``GET /system/metrics`` — live resource-usage metrics."""
    # CPU load
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0

    # Memory
    meminfo = _parse_meminfo()
    if meminfo:
        mem_total_kb = meminfo.get("MemTotal", 0)
        mem_avail_kb = meminfo.get("MemAvailable", 0)
        mem_total_mb = mem_total_kb // 1024
        mem_used_mb = (mem_total_kb - mem_avail_kb) // 1024
    else:
        mem_total_mb, _ = _memory_fallback()
        mem_used_mb = 0

    mem_percent = round(mem_used_mb / mem_total_mb * 100, 1) if mem_total_mb else 0.0

    # Disk
    try:
        usage = shutil.disk_usage("/")
        disk_total_gb = round(usage.total / (1024 ** 3), 2)
        disk_used_gb = round(usage.used / (1024 ** 3), 2)
        disk_percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
    except OSError:
        disk_total_gb = 0.0
        disk_used_gb = 0.0
        disk_percent = 0.0

    # Uptime
    uptime_seconds = round(time.time() - _BOOT_TIME, 1)

    return ServerResponse.ok({
        "cpu_load_1m": round(load1, 2),
        "cpu_load_5m": round(load5, 2),
        "cpu_load_15m": round(load15, 2),
        "memory_used_mb": mem_used_mb,
        "memory_total_mb": mem_total_mb,
        "memory_percent": mem_percent,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_percent": disk_percent,
        "uptime_seconds": uptime_seconds,
    })


# ---------------------------------------------------------------------------
# Register routes on the default table (import side-effect)
# ---------------------------------------------------------------------------

_table = default_table()

# CORE group — no auth required
_table.register(
    "GET", "/capabilities", handle_capabilities,
    group=CapabilityGroup.CORE, auth_required=False, name="capabilities",
)

# SYSTEM group
_table.register(
    "GET", "/system/info", handle_system_info,
    group=CapabilityGroup.SYSTEM, name="system_info",
)
_table.register(
    "GET", "/env", handle_env_get,
    group=CapabilityGroup.SYSTEM, name="env_get",
)
_table.register(
    "POST", "/env", handle_env_set,
    group=CapabilityGroup.SYSTEM, name="env_set",
)
_table.register(
    "GET", "/ports", handle_ports,
    group=CapabilityGroup.SYSTEM, name="ports",
)
_table.register(
    "GET", "/packages", handle_packages,
    group=CapabilityGroup.SYSTEM, name="packages",
)
_table.register(
    "GET", "/system/metrics", handle_system_metrics,
    group=CapabilityGroup.SYSTEM, name="system_metrics",
)
