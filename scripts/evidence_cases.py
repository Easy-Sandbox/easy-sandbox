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
_CFG_CMD = "easy_sandbox.cli.commands.config_cmd"
_MCP_CMD = "easy_sandbox.cli.commands.mcp"
_LOAD_CFG = "easy_sandbox.transport.config.load_config"
_CREATE_AUTH = "easy_sandbox.transport.auth.create_auth_provider"
_HTTP_CLIENT = "easy_sandbox.transport.http.HttpClient"
_SANDBOX_PROTO = "easy_sandbox.protocol.sandbox.SandboxProtocol"
_QWEN_FIND_BIN = "easy_sandbox.agent.qwen_code.find_qwen_code_binary"
_QWEN_RESOLVE_CREDS = "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials"
_CODEGEN_PREPARE = "easy_sandbox.agent.codegen.prepare_workdir"
_CODEGEN_GEN = "easy_sandbox.agent.codegen.generate_template_files"
_CLARIFY_RESEARCH = "easy_sandbox.agent.clarify.run_research"
_CLARIFY_EVAL = "easy_sandbox.agent.clarify.evaluate"
_TMPL_DO_DEPLOY = "easy_sandbox.cli.commands.template.do_deploy"
_TMPL_NS = "easy_sandbox.cli.commands.template.resolve_acr_namespace"


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

# Process-environment variables that could leak into config reads; every
# _cfg() context clears them all, then optionally re-populates via extra_env.
_CFG_ENV_VARS = (
    "E2B_API_KEY",
    "E2B_API_URL",
    "E2B_DOMAIN",
    "SANDBOX_API_KEY",
    "SANDBOX_API_BASE_URL",
    "SANDBOX_REGION",
    "SANDBOX_HTTP_TIMEOUT",
    "ALICLOUD_ACCESS_KEY_ID",
    "ALICLOUD_ACCESS_KEY_SECRET",
    "AccessKey",
    "AccessSecret",
    "GITHUB_TOKEN",
    "EBX_QWEN_CODE_API_KEY",
    "EBX_LLM_API_KEY",
)


def _cfg(toml: str = "", env: str = "", extra_env: dict[str, str] | None = None):
    """Config command mock — patches _CONFIG_FILE / _EBX_DIR / _ENV_FILE.

    *env* is the content of the ~/.ebx/.env file; *extra_env* injects process
    environment variables (the full _CFG_ENV_VARS list is cleared first).
    """

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
            saved = {k: os.environ.pop(k) for k in _CFG_ENV_VARS if k in os.environ}
            injected = extra_env or {}
            try:
                os.environ.update(injected)
                with (
                    patch(f"{_CFG_CMD}._CONFIG_FILE", cf),
                    patch(f"{_CFG_CMD}._EBX_DIR", tmp),
                    patch(f"{_CFG_CMD}._ENV_FILE", ef),
                ):
                    yield {}
            finally:
                for key in injected:
                    os.environ.pop(key, None)
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


def _mcp_install_cursor():
    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        # ``mcp install`` resolves the path via the module-level
        # ``_IDE_CONFIG_MAP`` (captured at import time), so patching the
        # function alone is ineffective. Patch ``Path.home`` instead — this
        # also isolates ``_read_api_key``'s ~/.ebx/.env lookup.
        with (
            tempfile.TemporaryDirectory() as td,
            patch("pathlib.Path.home", return_value=Path(td)),
        ):
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


def _create_codegen(
    description: str = "运行 python",
    template_name: str = "ebx-nl-python-ev001",
    assessment: Any = None,
):
    """Mock the AI codegen pipeline → deploy → Sandbox.create.

    Patches the Qwen Code adapter (binary + credentials), the two
    clarification seams (``clarify.run_research`` — the plain research
    round that settles the public facts on the native session — and
    ``clarify.evaluate`` — the one structured assessment round the create
    flow runs before generating), the generation workspace, the codegen
    orchestrator, the build/deploy pipeline, and ``run_sync`` so the whole
    ``ebx create "<description>"`` path runs offline.

    *assessment* is the assessment object the mocked round returns; ``None``
    models a fully complete description (the one-question-per-round loop
    asks nothing).
    """

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        from easy_sandbox.agent.clarify import ClarifyAssessment
        from easy_sandbox.agent.codegen import CodegenResult
        from easy_sandbox.agent.qwen_code import QwenCodeCredentials

        sb = _make_sb(tmpl=template_name)
        # Stable placeholder workspace so evidence output is platform-neutral
        # (the real path is ~/.ebx/generated/<slug>-<stamp>-<token>).
        workdir = Path("/home/user/.ebx/generated") / template_name
        gen = CodegenResult(
            workdir=workdir,
            template_name=template_name,
            dockerfile=workdir / "Dockerfile",
            template_yaml=workdir / "template.yaml",
            description=description,
            raw_output="generated",
        )
        creds = QwenCodeCredentials(
            source="qwen-stored",
            api_key="sk-ev",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3-coder-plus",
        )
        resolved = (
            assessment
            if assessment is not None
            else ClarifyAssessment(completeness=1.0, question=None)
        )
        with (
            patch(_QWEN_FIND_BIN, return_value=Path("/opt/qwen/bin/qwen")),
            patch(_QWEN_RESOLVE_CREDS, return_value=creds),
            patch(_CODEGEN_PREPARE, return_value=(workdir, template_name)),
            patch(_CLARIFY_RESEARCH, return_value=True),
            patch(_CLARIFY_EVAL, return_value=resolved),
            patch(_CODEGEN_GEN, return_value=gen),
            patch(
                _TMPL_DO_DEPLOY,
                return_value={"TemplateID": "tmpl-ev-ai-001", "Status": "success"},
            ),
            patch(_TMPL_NS, return_value="acr-ev-ns"),
            patch(f"{_CFG_CMD}.load_config_dict", return_value={}),
            patch(f"{_CFG_CMD}.read_env_var", return_value=None),
            patch(_RUN_SYNC, return_value=sb),
        ):
            yield {}

    return _ctx


def _create_codegen_not_installed():
    """Mock: Qwen Code binary missing → Quick Setup + E2005 (no deploy)."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        with patch(_QWEN_FIND_BIN, return_value=None):
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


def _connect_repl():
    """Mock for ``ebx connect`` — deterministic three-line REPL session.

    Line 1 (``ls /app``) succeeds and registers ``ls`` as a session-verified
    executable; line 2 (``sl``) hits the structured envd "not found" error so
    the golden file shows the single friendly notice plus the spelling hint;
    line 3 exits.  ``builtins.input`` is patched so no stdin is needed.
    """

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        from easy_sandbox.models.errors import EnvdRpcError
        from easy_sandbox.models.process import ProcessResult

        sb = _make_sb()
        ls_result = ProcessResult(stdout="app.py\n", stderr="", exit_code=0, execution_time=0.1)
        missing = EnvdRpcError(
            "envd rejected process.Process/Start with HTTP 500",
            status_code=500,
            rpc_path="/process.Process/Start",
            envd_error={
                "error": {
                    "code": 500,
                    "message": 'exec: "sl": executable file not found in $PATH',
                }
            },
        )
        sb.commands.run = AsyncMock(side_effect=[ls_result, missing])
        with (
            patch(_SANDBOX_CONNECT, new_callable=AsyncMock, return_value=sb),
            patch("builtins.input", side_effect=["ls /app", "sl", "exit"]),
        ):
            yield {}

    return _ctx


def _run_cmd(custom_commands: dict[str, Any]):
    """Mock for ``ebx run`` — exercises the REAL :meth:`Sandbox.custom` dispatch.

    Patches ``Sandbox.connect`` as AsyncMock so the merged
    ``_connect_and_run`` coroutine executes with the real ``run_sync``.
    The stubbed ``commands.run`` echoes the fully-resolved shell command
    so the golden file proves placeholder substitution / arg validation
    really happened (not a canned shell).

    Unknown command names fall through to the (unreachable) SandboxServer
    and raise ``CommandNotFoundError`` from the real dispatch logic, which
    the CLI turns into an error message + exit code 2.  The server probe is
    pre-marked failed so the lookup is deterministic and offline.
    """

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        from easy_sandbox.api.sandbox import Sandbox
        from easy_sandbox.models.process import ProcessResult

        sb = _make_sb()
        sb._custom_commands = custom_commands
        # Mechanism B (SandboxServer) is unreachable in this offline mock;
        # pre-mark the probe so unknown names raise CommandNotFoundError
        # deterministically instead of attempting a real HTTP call.
        sb._server_probe_failed = True

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
        # Bind the real Sandbox.custom so dispatch/parsing is genuinely
        # exercised (template mechanism A resolution + arg validation).
        # ``custom`` delegates template execution to ``_run_template_command``,
        # which must also be the real bound method (otherwise the MagicMock
        # attribute is awaited and blows up).
        sb._run_template_command = (
            lambda name, kwargs: Sandbox._run_template_command(sb, name, kwargs)
        )
        sb.custom = lambda name, **kw: Sandbox.custom(sb, name, **kw)

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
        mock_http = MagicMock()
        mock_http.platform_request = AsyncMock(return_value=resp)
        mock_http.close = AsyncMock()
        with (
            patch(
                _LOAD_CFG,
                return_value=MagicMock(api_key="k", access_key_id=None, access_key_secret=None),
            ),
            patch(_CREATE_AUTH, return_value=MagicMock()),
            patch(_HTTP_CLIENT, return_value=mock_http),
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
        mock_http = MagicMock()
        mock_http.platform_request = AsyncMock(return_value=resp)
        mock_http.close = AsyncMock()
        with (
            patch(
                _LOAD_CFG,
                return_value=MagicMock(api_key="k", access_key_id=None, access_key_secret=None),
            ),
            patch(_CREATE_AUTH, return_value=MagicMock()),
            patch(_HTTP_CLIENT, return_value=mock_http),
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


# ─── GitHub rate-limit mocks (task 206) ───────────────────────────────────
# The anonymous rate limit is injected at the httpx boundary so the real
# production branches run: the template-index 403 branch and the tarball
# 403 branch both translate into the unified GitHubRateLimitError guidance.


def _rate_limited_response(url: str, *, status: int = 403) -> Any:
    """Build a real ``httpx.Response`` shaped like GitHub's anonymous rate limit."""
    import httpx

    request = httpx.Request("GET", url)
    return httpx.Response(
        status,
        request=request,
        headers={"X-RateLimit-Remaining": "0"},
        text='{"message": "API rate limit exceeded for anonymous requests."}',
    )


def _mock_httpx_client(response: Any) -> MagicMock:
    """A stand-in ``httpx.AsyncClient`` whose GET returns *response*."""
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@contextmanager
def _without_env(*names: str) -> Iterator[None]:
    """Temporarily remove *names* from the process environment."""
    saved = {k: os.environ.pop(k) for k in names if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _tmpl_search_rate_limited():
    """`template search` hitting the real index client's 403 rate-limit branch."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        from easy_sandbox.utils.template_index import DEFAULT_INDEX_URL

        client = _mock_httpx_client(_rate_limited_response(DEFAULT_INDEX_URL))
        config = _cfg()()  # isolate ~/.ebx storage + credential env vars
        with (
            tempfile.TemporaryDirectory() as td,
            config,
            patch("easy_sandbox.utils.template_index.httpx.AsyncClient", return_value=client),
            patch("easy_sandbox.utils.template_index.INDEX_CACHE_DIR", Path(td)),
            _without_env("EBX_TEMPLATE_INDEX_URL"),
        ):
            yield {}

    return _ctx


def _tmpl_install_rate_limited():
    """`template install owner/repo//subdir@ref` hitting the real tarball 403."""

    @contextmanager
    def _ctx() -> Iterator[dict[str, Any]]:
        url = "https://api.github.com/repos/Easy-Sandbox/awesome-templates/tarball/v1.0"
        client = _mock_httpx_client(_rate_limited_response(url))
        config = _cfg()()  # isolate ~/.ebx storage + credential env vars
        with (
            tempfile.TemporaryDirectory() as td,
            config,
            patch("easy_sandbox.utils.registry.httpx.AsyncClient", return_value=client),
            patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", Path(td)),
        ):
            yield {}

    return _ctx


# ═══════════════════════════════════════════════════════════════════════════
# Registry builder
# ═══════════════════════════════════════════════════════════════════════════


def _build_registry() -> list[EvidenceCase]:
    from easy_sandbox.agent.clarify import ClarifyAssessment
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

    # ── Help (28) ──────────────────────────────────────────────────────
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
        (["config", "init"], "config-init"),
        (["template"], "template"),
        (["template", "list"], "template-list"),
        (["template", "info"], "template-info"),
        (["template", "build"], "template-build"),
        (["template", "init"], "template-init"),
        (["template", "delete"], "template-delete"),
        (["template", "install"], "template-install"),
        (["mcp"], "mcp"),
        (["mcp", "deploy"], "mcp-deploy"),
        (["mcp", "install"], "mcp-install"),
        (["mcp", "start"], "mcp-start"),
        (["mcp", "status"], "mcp-status"),
    ]
    for cmd, name in _help:
        cases.append(E(cmd + ["--help"], f"{name} --help", "A", None, f"help-{name}"))

    # ── Version (1) ────────────────────────────────────────────────────
    cases.append(E(["--version"], "--version", "A", None, "version"))

    # ── Config (20) ────────────────────────────────────────────────────
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
            E(
                ["config", "get", "api_key"],
                "config get api_key（进程环境变量, masked）",
                "A",
                _cfg(extra_env={"E2B_API_KEY": "sk-env-abcdef123456"}),
                "config-get-apikey-env",
            ),
            E(["config", "get", "unknown_key"], "config get unknown_key（错误）", "A", _cfg(), "config-get-unknown"),
            E(
                ["config", "get", "qwen_code_model"],
                "config get qwen_code_model（业务默认）",
                "A",
                _cfg(),
                "config-get-qwen-model",
            ),
            E(
                ["config", "get", "llm_model"],
                "config get llm_model（not set）",
                "A",
                _cfg(),
                "config-get-llm-model-unset",
            ),
            E(["config", "set", "region", "cn-shanghai"], "config set region", "A", _cfg(), "config-set-region"),
            E(
                ["config", "set", "llm_api_key", "sk-mykey12345678"],
                "config set llm_api_key（masked）",
                "A",
                _cfg(),
                "config-set-llm-apikey",
            ),
            E(
                ["config", "set", "region", ""],
                'config set region ""（清除, 回落默认）',
                "A",
                _cfg(toml='[transport]\nregion = "cn-shanghai"\n'),
                "config-set-empty-default",
            ),
            E(
                ["config", "set", "api_key", ""],
                'config set api_key ""（清除凭证）',
                "A",
                _cfg(env="E2B_API_KEY=sk-test-abcdef123456\n"),
                "config-set-empty-credential",
            ),
            E(
                ["config", "set", "region", ""],
                'config set region ""（env 仍生效, 值不显示）',
                "A",
                _cfg(
                    toml='[transport]\nregion = "cn-shanghai"\n',
                    extra_env={"SANDBOX_REGION": "cn-zhangjiakou"},
                ),
                "config-set-empty-env",
            ),
            E(["config", "list"], "config list", "A", _cfg(), "config-list"),
            E(["--json", "config", "list"], "config list --json", "A", _cfg(), "config-list-json"),
            E(
                ["config", "init"],
                "config init（非 TTY：打印非交互命令）",
                "A",
                _cfg(),
                "config-init",
            ),
            E(
                ["config", "set", "github_token", "ghp_evidence1234567890"],
                "config set github_token（masked）",
                "A",
                _cfg(),
                "config-set-github-token",
            ),
            E(
                ["config", "get", "github_token"],
                "config get github_token（未设置）",
                "A",
                _cfg(),
                "config-get-github-token-unset",
            ),
            E(
                ["config", "get", "github_token"],
                "config get github_token（已设置, masked）",
                "A",
                _cfg(env="GITHUB_TOKEN=ghp_evidence1234567890\n"),
                "config-get-github-token-set",
            ),
            E(
                ["config", "set", "github_token", ""],
                'config set github_token ""（清除）',
                "A",
                _cfg(env="GITHUB_TOKEN=ghp_evidence1234567890\n"),
                "config-set-github-token-clear",
            ),
            E(
                ["config", "set", "github_token"],
                "config set github_token（非 TTY：缺 VALUE）",
                "A",
                _cfg(),
                "config-set-github-token-missing-value",
            ),
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

    # ── Create (11) ─────────────────────────────────────────────────────
    # A description covering all six clarification facets (runtime,
    # dependencies, entry command, ports, resources, data) — used by the
    # cases that must reach a gate *after* the clarification step.
    complete_zh = (
        "用 Python 3.12，预装 pandas 和 jupyter，入口命令 jupyter notebook，"
        "端口 8888，2 核 4GB 内存，上传 data.csv 数据"
    )
    # Mocked assessment for the "too vague" case: below the 80% gate, with a
    # single question and a ready-to-use example — what a real Qwen Code
    # structured round returns for "运行 python".
    incomplete_assessment = ClarifyAssessment(
        completeness=0.3,
        question="需要暴露哪个端口？",
        missing=("dependencies", "entry command", "ports", "resources", "data"),
        example=(
            "Python 3.12 runtime with pandas and jupyter installed, entry command "
            "'jupyter notebook --ip 0.0.0.0', port 8888, 2 CPU 4 GB memory, upload "
            "a data.csv dataset"
        ),
    )
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
                ["create", "-y", "运行 python"],
                'create NL "运行 python"（AI 生成模板）',
                "B",
                _create_codegen("运行 python", "ebx-nl-python-ev001"),
                "create-nl-python",
            ),
            E(
                ["create", "-y", "启动 Node.js 服务"],
                'create NL "启动 Node.js 服务"（AI 生成模板）',
                "B",
                _create_codegen("启动 Node.js 服务", "ebx-nl-nodejs-ev001"),
                "create-nl-nodejs",
            ),
            E(
                ["create", complete_zh],
                "create NL 非交互描述完整（需确认）",
                "A",
                _create_codegen(complete_zh, "ebx-nl-python-ev001"),
                "create-nl-confirm-required",
            ),
            E(
                ["create", "运行 python"],
                "create NL 非交互描述不完整（E2008 + 缺失项 + 示例）",
                "A",
                _create_codegen(
                    "运行 python", "ebx-nl-python-ev001", incomplete_assessment
                ),
                "create-nl-clarify-required",
            ),
            E(
                ["create", "运行 python"],
                "create NL 未安装 Qwen Code（Quick Setup）",
                "A",
                _create_codegen_not_installed(),
                "create-nl-not-installed",
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
            E(
                ["create", "运行 python", "--template", "base"],
                "create 同时提供描述与 --template（拒绝）",
                "A",
                None,
                "create-nl-conflict",
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

    # ── Connect (1) ────────────────────────────────────────────────────
    cases.extend(
        [
            E(
                ["connect", "sbx-ev-001"],
                "connect 交互会话（命令不存在 → 单次友好提示 + 拼写建议）",
                "B",
                _connect_repl(),
                "connect-repl",
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

    # ── GitHub rate-limit guidance (2) ─────────────────────────────────
    cases.extend(
        [
            E(
                ["template", "search", "qwen"],
                "template search（匿名限流：统一引导）",
                "A",
                _tmpl_search_rate_limited(),
                "template-search-rate-limit",
            ),
            E(
                ["template", "install", "Easy-Sandbox/awesome-templates//codex-agent-api@v1.0"],
                "template install owner/repo//subdir@ref（匿名限流）",
                "B",
                _tmpl_install_rate_limited(),
                "template-install-rate-limit",
            ),
        ]
    )

    # ── Error cases (5) ────────────────────────────────────────────────
    cases.extend(
        [
            E(
                ["create"],
                "create 无参数（显式用法错误，不再默认 base）",
                "A",
                None,
                "error-create-noargs",
            ),
            E(
                ["crate"],
                "未知顶层命令（拼写建议）",
                "A",
                None,
                "error-unknown-suggestion",
            ),
            E(
                ["frobnicate"],
                "未知顶层命令（custom_commands / ebx run 引导）",
                "A",
                None,
                "error-unknown-custom-hint",
            ),
            E(
                ["init", "--help"],
                "顶层 init（ebx template init 快捷别名）",
                "A",
                None,
                "help-init-alias",
            ),
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
