"""CLI Evidence Cases — single source of truth for CLI input→output evidence harness.

Defines EvidenceCase dataclass, full registry (~70+ cases), mock builders
(reusing the run_sync-patch pattern with realistic SandboxInfo), and a
normalize() function that masks non-deterministic fragments.
"""
from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator
from unittest.mock import AsyncMock, MagicMock, patch


# ═══════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EvidenceCase:
    """A single CLI evidence case."""

    command: list[str]
    description: str
    category: str  # 'A' = offline deterministic, 'B' = backend-dependent (mocked)
    mock_setup: Callable[[], ContextManager[dict[str, Any]]] | None
    output_file: str  # golden file base name (no extension)


# ═══════════════════════════════════════════════════════════════════════════
# Output helpers
# ═══════════════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    """Mask non-deterministic fragments for golden-file comparison."""
    # Sandbox IDs
    text = re.sub(r"sbx-[a-z0-9-]{6,}", "sbx-XXXXX", text)
    # ISO timestamps
    text = re.sub(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?",
        "YYYY-MM-DDTHH:MM:SS",
        text,
    )
    # Envd / sandbox URLs
    text = re.sub(r"https://\d+-sbx-[a-z0-9.-]+[^\s\"']*", "https://ENVD_URL", text)
    text = re.sub(r"https://sbx-[a-z0-9.-]+[^\s\"']*", "https://ENVD_URL", text)
    # execution_time in JSON
    text = re.sub(r'"execution_time":\s*[\d.]+', '"execution_time": 0.0', text)
    # Temp paths (macOS /var/folders, Linux /tmp)
    text = re.sub(r"/(?:tmp|var/folders)/[^\s\"']+", "/TMPPATH", text)
    # Home dirs
    text = re.sub(r"/Users/[^\s/\"']+", "/HOME", text)
    text = re.sub(r"C:\\Users\\[^\s\\\"']+", "/HOME", text)
    # Strip per-line trailing whitespace
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip() + "\n" if text.strip() else "\n"


def format_result(stdout: str, stderr: str, exit_code: int) -> str:
    """Combine stdout / exit_code / stderr into a single golden-file string."""
    parts: list[str] = []
    if stdout:
        parts.append(stdout.rstrip("\n"))
    parts.append(f"[exit_code:{exit_code}]")
    if stderr.strip():
        parts.append(f"[stderr]\n{stderr.rstrip()}")
    return "\n".join(parts) + "\n"


# ═══════════════════════════════════════════════════════════════════════════
# Patch targets
# ═══════════════════════════════════════════════════════════════════════════

_RUN_SYNC = "easy_sandbox.utils.async_bridge.run_sync"
_SANDBOX_CONNECT = "easy_sandbox.api.sandbox.Sandbox.connect"
_SANDBOX_CREATE = "easy_sandbox.api.sandbox.Sandbox.create"
_SANDBOX_CONNECT = "easy_sandbox.api.sandbox.Sandbox.connect"
_SANDBOX_CREATE = "easy_sandbox.api.sandbox.Sandbox.create"
_CFG_CMD = "easy_sandbox.cli.commands.config_cmd"
_MCP_CMD = "easy_sandbox.cli.commands.mcp"
_LOAD_CFG = "easy_sandbox.transport.config.load_config"
_CREATE_AUTH = "easy_sandbox.transport.auth.create_auth_provider"
_HTTP_CLIENT = "easy_sandbox.transport.http.HttpClient"
_SANDBOX_PROTO = "easy_sandbox.protocol.sandbox.SandboxProtocol"
_REG_CACHE = "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR"


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox mock builder
# ═══════════════════════════════════════════════════════════════════════════

def _make_sb(
    sid: str = "sbx-ev-001",
    tmpl: str = "base",
    status: str = "running",
    region: str = "cn-hangzhou",
) -> MagicMock:
    """Build a realistic mock Sandbox with SandboxInfo."""
    from easy_sandbox.models.sandbox import SandboxInfo

    sb_info = SandboxInfo.model_validate(
        {
            "sandboxID": sid,
            "templateID": tmpl,
            "status": status,
            "region": region,
            "timeout": 300,
            "envdUrl": f"https://{sid}.{region}.e2b.fc.aliyuncs.com",
            "envdAccessToken": "tok-ev",
        }
    )
    sb = MagicMock()
    sb.id = sb_info.sandbox_id
    sb.status = sb_info.status
    sb.url = sb_info.envd_url
    sb.info = sb_info
    sb.files = MagicMock()
    sb.files.write = AsyncMock()
    sb.files.read_bytes = AsyncMock(return_value=b"downloaded-content")
    sb.commands = MagicMock()
    sb.commands.run = AsyncMock()
    sb.kill = AsyncMock()
    return sb


# ═══════════════════════════════════════════════════════════════════════════
# Generic mock factories  (each returns a *callable* → ContextManager)
# ═══════════════════════════════════════════════════════════════════════════

def _cfg(toml: str = "", env: str = ""):
    """Config command mock — patches _CONFIG_FILE / _EBX_DIR / _ENV_FILE."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cf, ef = tmp / "config.toml", tmp / ".env"
            if toml:
                cf.write_text(toml)
            if env:
                ef.write_text(env)
            # Temporarily remove env-vars that could leak into config reads
            saved = {k: os.environ.pop(k) for k in ("E2B_API_KEY", "SANDBOX_API_KEY") if k in os.environ}
            try:
                with (
                    patch(f"{_CFG_CMD}._CONFIG_FILE", cf),
                    patch(f"{_CFG_CMD}._EBX_DIR", tmp),
                    patch(f"{_CFG_CMD}._ENV_FILE", ef),
                ):
                    yield {}
            finally:
                os.environ.update(saved)

    return _ctx


def _rs(*values: Any):
    """Patch run_sync to return *values* in call order."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        seq = list(values)
        idx = [0]

        def _se(_coro: Any) -> Any:
            i = idx[0]
            idx[0] += 1
            if i < len(seq):
                v = seq[i]
                if isinstance(v, BaseException):
                    raise v
                return v
            return MagicMock()

        with patch(_RUN_SYNC, side_effect=_se):
            yield {}

    return _ctx


def _proto_rs(*values: Any):
    """Protocol-chain mock (load_config → auth → http → proto) + run_sync."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        seq = list(values)
        idx = [0]

        def _se(_coro: Any) -> Any:
            i = idx[0]
            idx[0] += 1
            if i < len(seq):
                v = seq[i]
                if isinstance(v, BaseException):
                    raise v
                return v
            return MagicMock()

        with (
            patch(
                _LOAD_CFG,
                return_value=MagicMock(api_key="test-k", access_key_id=None, access_key_secret=None),
            ),
            patch(_CREATE_AUTH, return_value=MagicMock()),
            patch(_HTTP_CLIENT),
            patch(_SANDBOX_PROTO),
            patch(_RUN_SYNC, side_effect=_se),
        ):
            yield {}

    return _ctx


def _rs_err(exc: BaseException):
    """Patch run_sync to raise *exc* on any call."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        with patch(_RUN_SYNC, side_effect=exc):
            yield {}

    return _ctx


# ─── specialised mocks ────────────────────────────────────────────────────


def _tmpl_cache():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as td:
            with patch(_REG_CACHE, Path(td)):
                yield {}

    return _ctx


def _mcp_install_cursor():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as td:
            with patch(f"{_MCP_CMD}._get_cursor_config_path", return_value=Path(td) / "mcp.json"):
                yield {}

    return _ctx


def _mcp_status():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with (
                patch(f"{_MCP_CMD}._get_cursor_config_path", return_value=tmp / "c.json"),
                patch(f"{_MCP_CMD}._get_claude_config_path", return_value=tmp / "cl.json"),
                patch(f"{_MCP_CMD}._get_vscode_config_path", return_value=tmp / "vs.json"),
                patch(f"{_MCP_CMD}._read_api_key", return_value=None),
            ):
                yield {}

    return _ctx


def _create_nl(tmpl: str, display: str, kw: str, cpu: int = 2, mem: int = 4096):
    """Mock for NL inference → Sandbox.create."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        from easy_sandbox.agent.infer import InferResult

        sb = _make_sb(tmpl=tmpl)
        calls = [0]

        def _se(_c: Any) -> Any:
            calls[0] += 1
            if calls[0] == 1:
                return InferResult(
                    template=tmpl,
                    display_name=display,
                    cpu=cpu,
                    memory=mem,
                    confidence=0.88,
                    reasoning=f"关键词匹配: {kw}",
                )
            return sb

        with patch(_RUN_SYNC, side_effect=_se):
            yield {}

    return _ctx


def _exec(stdout: str = "hello\n", stderr: str = "", exit_code: int = 0):
    """Mock Sandbox.connect + commands.run (merged single run_sync)."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        from easy_sandbox.models.process import ProcessResult

        sb = _make_sb()
        pr = ProcessResult(stdout=stdout, stderr=stderr, exit_code=exit_code, execution_time=0.1)
        sb.commands.run = AsyncMock(return_value=pr)
        with patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb):
            yield {}

    return _ctx


def _upload_file():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        sb = _make_sb()
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write("print('hello')\n")
            fpath = f.name
        try:
            with patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb):
                yield {"command": ["upload", "sbx-ev-001", fpath, "/app/script.py"]}
        finally:
            Path(fpath).unlink(missing_ok=True)

    return _ctx


def _upload_dir():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        sb = _make_sb()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "a.py").write_text("# a\n")
            (tmp / "b.py").write_text("# b\n")
            with patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb):
                yield {"command": ["upload", "sbx-ev-001", td, "/app/data/"]}

    return _ctx


def _download_file():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        sb = _make_sb()
        with tempfile.TemporaryDirectory() as td:
            local = str(Path(td) / "result.csv")
            with patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb):
                yield {"command": ["download", "sbx-ev-001", "/app/result.csv", local]}

    return _ctx


def _run_cmd(custom_commands: dict[str, Any]):
    """Mock for ``ebx run`` — exercises the REAL :meth:`Sandbox.run` dispatch.

    Patches ``Sandbox.connect`` as AsyncMock so the merged
    ``_connect_and_run`` coroutine executes with the real ``run_sync``.
    The stubbed ``commands.run`` echoes the fully-resolved shell command
    so the golden file proves placeholder substitution / arg validation
    really happened (not a canned shell).

    Unknown command names raise ``ValueError`` from the real dispatch logic,
    which the CLI lets propagate (exit code 1).
    """

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        from easy_sandbox.api.sandbox import Sandbox
        from easy_sandbox.models.process import ProcessResult

        sb = _make_sb()
        sb._custom_commands = custom_commands

        async def _fake_run(
            cmd_str: str,
            *,
            timeout: int = 60,
            env: Any = None,
            cwd: str = "/app",
            **_kw: Any,
        ) -> ProcessResult:
            return ProcessResult(
                stdout=f"$ {cmd_str}\n[cwd={cwd} timeout={timeout}s]\n",
                stderr="",
                exit_code=0,
                execution_time=0.05,
            )

        sb.commands.run = _fake_run
        # Bind the real Sandbox.run so dispatch/parsing is genuinely exercised.
        sb.run = lambda name, **kw: Sandbox.run(sb, name, **kw)

        with patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb):
            yield {}

    return _ctx


def _kill_all():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        import asyncio as _aio

        from easy_sandbox.models.sandbox import SandboxInfo

        infos = [
            SandboxInfo.model_validate(
                {
                    "sandboxID": f"sbx-all-{i:03d}",
                    "templateID": "base",
                    "status": "running",
                    "region": "cn-hangzhou",
                }
            )
            for i in range(2)
        ]
        sb = _make_sb()
        calls = [0]

        def _se(coro: Any) -> Any:
            calls[0] += 1
            if calls[0] == 1:
                return infos
            # _connect_and_kill: run the merged coroutine
            return _aio.run(coro)

        with (
            patch(
                _LOAD_CFG,
                return_value=MagicMock(api_key="k", access_key_id=None, access_key_secret=None),
            ),
            patch(_CREATE_AUTH, return_value=MagicMock()),
            patch(_HTTP_CLIENT),
            patch(_SANDBOX_PROTO),
            patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb),
            patch(_RUN_SYNC, side_effect=_se),
        ):
            yield {}

    return _ctx


def _kill_single_mock():
    """Mock for kill single sandbox (merged connect+kill)."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        sb = _make_sb()
        with patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb):
            yield {}

    return _ctx


def _tmpl_list_backend():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        resp = MagicMock()
        resp.json.return_value = [
            {"templateID": "tmpl-001", "alias": "python-base", "status": "ready"},
            {"templateID": "tmpl-002", "alias": "node-web", "status": "ready"},
        ]
        with (
            patch(
                _LOAD_CFG,
                return_value=MagicMock(api_key="k", access_key_id=None, access_key_secret=None),
            ),
            patch(_CREATE_AUTH, return_value=MagicMock()),
            patch(_HTTP_CLIENT),
            patch(_RUN_SYNC, side_effect=[resp, None]),
        ):
            yield {}

    return _ctx


def _tmpl_info_backend():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        resp = MagicMock()
        resp.json.return_value = {
            "templateID": "tmpl-001",
            "alias": "python-base",
            "status": "ready",
            "dockerfile": "FROM python:3.11-slim",
        }
        with (
            patch(
                _LOAD_CFG,
                return_value=MagicMock(api_key="k", access_key_id=None, access_key_secret=None),
            ),
            patch(_CREATE_AUTH, return_value=MagicMock()),
            patch(_HTTP_CLIENT),
            patch(_RUN_SYNC, side_effect=[resp, None]),
        ):
            yield {}

    return _ctx


def _tmpl_install_builtin():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        mock_ref = MagicMock()
        mock_ref.is_builtin = True
        with patch(_RUN_SYNC, return_value=mock_ref):
            yield {}

    return _ctx


# ═══════════════════════════════════════════════════════════════════════════
# Registry builder
# ═══════════════════════════════════════════════════════════════════════════


def _build_registry() -> list[EvidenceCase]:
    from easy_sandbox.models.errors import (
        AuthenticationError,
        CommandTimeoutError,
        QuotaExceededError,
        TemplateNotFoundError,
    )
    from easy_sandbox.models.sandbox import SandboxInfo
    from easy_sandbox.models.template import CustomCommand, CustomCommandArg

    E = EvidenceCase
    cases: list[EvidenceCase] = []

    # ── Help (27) ──────────────────────────────────────────────────────
    _help = [
        ([], "ebx"),
        (["create"], "create"),
        (["list"], "list"),
        (["info"], "info"),
        (["kill"], "kill"),
        (["exec"], "exec"),
        (["run"], "run"),
        (["connect"], "connect"),
        (["upload"], "upload"),
        (["download"], "download"),
        (["install"], "install"),
        (["config"], "config"),
        (["config", "get"], "config-get"),
        (["config", "set"], "config-set"),
        (["config", "list"], "config-list"),
        (["config", "reset"], "config-reset"),
        (["template"], "template"),
        (["template", "list"], "template-list"),
        (["template", "info"], "template-info"),
        (["template", "build"], "template-build"),
        (["template", "delete"], "template-delete"),
        (["template", "install"], "template-install"),
        (["template", "cache"], "template-cache"),
        (["mcp"], "mcp"),
        (["mcp", "install"], "mcp-install"),
        (["mcp", "start"], "mcp-start"),
        (["mcp", "status"], "mcp-status"),
    ]
    for cmd, name in _help:
        cases.append(E(cmd + ["--help"], f"{name} --help", "A", None, f"help-{name}"))

    # ── Version (1) ────────────────────────────────────────────────────
    cases.append(E(["--version"], "--version", "A", None, "version"))

    # ── Config (9) ─────────────────────────────────────────────────────
    cases.extend(
        [
            E(["config", "get", "region"], "config get region（默认值）", "A", _cfg(), "config-get-region"),
            E(["config", "get", "api_key"], "config get api_key（未设置）", "A", _cfg(), "config-get-apikey-unset"),
            E(
                ["config", "get", "api_key"],
                "config get api_key（已设置, masked）",
                "A",
                _cfg(env="E2B_API_KEY=sk-test-abcdef123456\n"),
                "config-get-apikey-set",
            ),
            E(["config", "get", "unknown_key"], "config get unknown_key（错误）", "A", _cfg(), "config-get-unknown"),
            E(["config", "set", "region", "cn-shanghai"], "config set region", "A", _cfg(), "config-set-region"),
            E(
                ["config", "set", "llm_api_key", "sk-mykey12345678"],
                "config set llm_api_key（masked）",
                "A",
                _cfg(),
                "config-set-llm-apikey",
            ),
            E(["config", "list"], "config list", "A", _cfg(), "config-list"),
            E(["--json", "config", "list"], "config list --json", "A", _cfg(), "config-list-json"),
            E(
                ["config", "reset", "--yes"],
                "config reset --yes",
                "A",
                _cfg(toml='[transport]\nregion = "cn-shanghai"\n'),
                "config-reset",
            ),
        ]
    )

    # ── Template cache (2) ─────────────────────────────────────────────
    cases.extend(
        [
            E(["template", "cache"], "template cache", "A", _tmpl_cache(), "template-cache"),
            E(["template", "cache", "--clear"], "template cache --clear", "A", _tmpl_cache(), "template-cache-clear"),
        ]
    )

    # ── MCP offline (3) ────────────────────────────────────────────────
    cases.extend(
        [
            E(
                ["mcp", "install", "--target", "cursor"],
                "mcp install --target cursor",
                "A",
                _mcp_install_cursor(),
                "mcp-install-cursor",
            ),
            E(["mcp", "status"], "mcp status", "A", _mcp_status(), "mcp-status"),
            E(["--json", "mcp", "status"], "mcp status --json", "A", _mcp_status(), "mcp-status-json"),
        ]
    )

    # ── Create (7) ─────────────────────────────────────────────────────
    cases.extend(
        [
            E(
                ["create", "--template", "base"],
                "create --template base",
                "B",
                _rs(_make_sb()),
                "create-template-base",
            ),
            E(
                ["--json", "create", "--template", "base"],
                "--json create --template base",
                "B",
                _rs(_make_sb()),
                "create-template-base-json",
            ),
            E(
                ["create", "运行 python"],
                'create NL "运行 python"',
                "B",
                _create_nl("code-interpreter", "Code Interpreter", "python, 运行"),
                "create-nl-python",
            ),
            E(
                ["create", "启动 Node.js 服务"],
                'create NL "启动 Node.js 服务"',
                "B",
                _create_nl("node-web", "Node.js Web", "node.js, web", cpu=1, mem=2048),
                "create-nl-nodejs",
            ),
            E(
                ["create", "-e", "FOO=bar", "--template", "base"],
                "create -e FOO=bar",
                "B",
                _rs(_make_sb()),
                "create-env",
            ),
            E(
                ["create", "-m", "project=demo", "--template", "base"],
                "create -m project=demo",
                "B",
                _rs(_make_sb()),
                "create-metadata",
            ),
            E(
                ["create", "-e", "INVALID", "--template", "base"],
                "create -e INVALID（格式错误）",
                "A",
                None,
                "create-env-invalid",
            ),
        ]
    )

    # ── List (4) ───────────────────────────────────────────────────────
    sb_infos = [
        SandboxInfo.model_validate(
            {"sandboxID": "sbx-list-001", "templateID": "python-base", "status": "running", "region": "cn-hangzhou"}
        ),
        SandboxInfo.model_validate(
            {"sandboxID": "sbx-list-002", "templateID": "node-web", "status": "stopped", "region": "cn-shanghai"}
        ),
    ]
    cases.extend(
        [
            E(["list"], "list（有数据）", "B", _proto_rs(sb_infos), "list"),
            E(["--json", "list"], "--json list", "B", _proto_rs(sb_infos), "list-json"),
            E(["list", "--status", "running"], "list --status running", "B", _proto_rs([sb_infos[0]]), "list-running"),
            E(["list"], "list（空）", "B", _proto_rs([]), "list-empty"),
        ]
    )

    # ── Info (2) ───────────────────────────────────────────────────────
    cases.extend(
        [
            E(["info", "sbx-ev-001"], "info sbx-ev-001", "B", _rs(_make_sb()), "info"),
            E(["--json", "info", "sbx-ev-001"], "--json info sbx-ev-001", "B", _rs(_make_sb()), "info-json"),
        ]
    )

    # ── Kill (3) ───────────────────────────────────────────────────────
    cases.extend(
        [
            E(["kill", "sbx-ev-001", "--yes"], "kill sbx-ev-001 --yes", "B", _kill_single_mock(), "kill-single"),
            E(["kill", "--all", "--yes"], "kill --all --yes", "B", _kill_all(), "kill-all"),
            E(["kill"], "kill（无 ID 错误）", "A", None, "kill-no-id"),
        ]
    )

    # ── Exec (4) ───────────────────────────────────────────────────────
    cases.extend(
        [
            E(["exec", "sbx-ev-001", "echo hello"], "exec 基本命令", "B", _exec(), "exec-basic"),
            E(["--json", "exec", "sbx-ev-001", "echo hello"], "--json exec", "B", _exec(), "exec-json"),
            E(
                ["exec", "sbx-ev-001", "bad_cmd"],
                "exec 非零退出码",
                "B",
                _exec(stdout="", stderr="command not found\n", exit_code=127),
                "exec-nonzero",
            ),
            E(
                ["exec", "--timeout", "10", "--cwd", "/tmp", "sbx-ev-001", "ls"],
                "exec --timeout --cwd",
                "B",
                _exec(stdout="file1\nfile2\n"),
                "exec-timeout-cwd",
            ),
        ]
    )

    # ── Run (custom command dispatch, 5) ───────────────────────────────
    run_cmds: dict[str, Any] = {
        "dev": CustomCommand(
            cmd="npm run dev -- --port {port}",
            description="Start the dev server",
            cwd="/app",
            timeout=30,
            args=[CustomCommandArg(name="port", default="3000", description="Listen port")],
        ),
        "test": CustomCommand(
            cmd="pytest {path}",
            description="Run the test suite",
            args=[CustomCommandArg(name="path", default="tests/")],
        ),
    }
    cases.extend(
        [
            E(
                ["run", "sbx-ev-001", "dev", "--arg", "port=8080"],
                "run dev --arg port=8080（占位符替换）",
                "B",
                _run_cmd(run_cmds),
                "run-dispatch",
            ),
            E(
                ["run", "sbx-ev-001", "test"],
                "run test（使用默认参数）",
                "B",
                _run_cmd(run_cmds),
                "run-default-arg",
            ),
            E(
                ["--json", "run", "sbx-ev-001", "dev", "--arg", "port=9000"],
                "--json run dev",
                "B",
                _run_cmd(run_cmds),
                "run-dispatch-json",
            ),
            E(
                ["run", "sbx-ev-001", "deploy"],
                "run deploy（命令名不存在）",
                "B",
                _run_cmd(run_cmds),
                "run-unknown-command",
            ),
            E(
                ["run", "sbx-ev-001", "dev", "--arg", "badformat"],
                "run dev --arg badformat（参数格式错误）",
                "A",
                None,
                "run-invalid-arg",
            ),
        ]
    )

    # ── Upload / Download (3) ──────────────────────────────────────────
    cases.extend(
        [
            E(
                ["upload", "sbx-ev-001", "PLACEHOLDER", "/app/script.py"],
                "upload 文件",
                "B",
                _upload_file(),
                "upload-file",
            ),
            E(
                ["upload", "sbx-ev-001", "PLACEHOLDER", "/app/data/"],
                "upload 目录",
                "B",
                _upload_dir(),
                "upload-dir",
            ),
            E(
                ["download", "sbx-ev-001", "/app/result.csv", "PLACEHOLDER"],
                "download 文件",
                "B",
                _download_file(),
                "download-file",
            ),
        ]
    )

    # ── Template backend (3) ───────────────────────────────────────────
    cases.extend(
        [
            E(["template", "list"], "template list（后端）", "B", _tmpl_list_backend(), "template-list-backend"),
            E(
                ["template", "info", "tmpl-001"],
                "template info tmpl-001",
                "B",
                _tmpl_info_backend(),
                "template-info-backend",
            ),
            E(
                ["template", "install", "base"],
                "template install base（内置）",
                "B",
                _tmpl_install_builtin(),
                "template-install-builtin",
            ),
        ]
    )

    # ── Error cases (4) ────────────────────────────────────────────────
    cases.extend(
        [
            E(
                ["create", "--template", "base"],
                "AuthenticationError",
                "B",
                _rs_err(AuthenticationError("Invalid API key")),
                "error-auth",
            ),
            E(
                ["create", "--template", "bad"],
                "TemplateNotFoundError",
                "B",
                _rs_err(TemplateNotFoundError("Template 'bad' not found")),
                "error-template-not-found",
            ),
            E(
                ["create", "--template", "base"],
                "QuotaExceededError",
                "B",
                _rs_err(QuotaExceededError("Sandbox quota exceeded")),
                "error-quota",
            ),
            E(
                ["exec", "sbx-ev-001", "sleep 999"],
                "CommandTimeoutError",
                "B",
                _rs_err(CommandTimeoutError("Command timed out after 60s")),
                "error-timeout",
            ),
        ]
    )

    return cases


# ═══════════════════════════════════════════════════════════════════════════
# Public registry
# ═══════════════════════════════════════════════════════════════════════════

REGISTRY: list[EvidenceCase] = _build_registry()
