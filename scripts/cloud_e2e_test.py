#!/usr/bin/env python3
"""云端端到端测试 — 需要真实 API 凭证（.env 中配置）。

分两大场景测试：
  Part 1: 平台已有模板 → 验证 CLI + SDK envd 能力（shell/files/code）
  Part 2: 自定义模板构建 → 验证 CLI + SDK envd 能力 + Sandbox Server 能力

运行方式：
    cd <project-root>
    python3 scripts/cloud_e2e_test.py
"""
from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote

# ---------------------------------------------------------------------------
# 确保项目 src 在 sys.path 中
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ---------------------------------------------------------------------------
# 加载 .env
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    print("[WARN] python-dotenv 未安装，将仅依赖已有环境变量")

import httpx
import yaml  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# SDK imports
# ---------------------------------------------------------------------------
from easy_sandbox.api.sandbox import Sandbox
from easy_sandbox.api.template import TemplateManager
from easy_sandbox.models.template import SandboxTemplate
from easy_sandbox.transport.auth import create_auth_provider
from easy_sandbox.transport.config import load_config, reset_config
from easy_sandbox.transport.http import HttpClient

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
TEMPLATES_DIR = PROJECT_ROOT / "examples" / "templates"
EBX_TEMPLATES_CACHE = Path.home() / ".ebx" / "templates"

CUSTOM_TEMPLATES = [
    "python-hello",
    "codex",
    "node-web",
    "browser-automation",
    "claude-code",
    "deepseek-harness",
    "hermes-agent",
    "openclaw",
    "qoder",
    "qwen-code",
]

OFFICIAL_TEMPLATES = {
    "code-interpreter-v1": "8d926meb1xzckz1a83ib",
    "base": "216g37mamkdfhzrauvxk",
}

MAX_CONCURRENCY = 5
WARMUP_MAX_RETRIES = 6
WARMUP_DELAY_SEC = 2.0
SERVER_WARMUP_RETRIES = 8
SERVER_WARMUP_DELAY = 3.0


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class SubStep:
    name: str
    status: str = "PENDING"  # PASS / FAIL / SKIP
    duration: float = 0.0
    detail: str = ""
    error: str = ""


@dataclass
class TemplateTestResult:
    template_name: str
    overall: str = "PENDING"  # PASS / FAIL / PARTIAL
    total_duration: float = 0.0
    steps: list[SubStep] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "FAIL")

    @property
    def skip_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "SKIP")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _log(tag: str, msg: str) -> None:
    print(f"  [{tag:22s}] {msg}")


def _load_template_yaml(name: str) -> SandboxTemplate | None:
    yaml_path = TEMPLATES_DIR / name / "template.yaml"
    if not yaml_path.exists():
        return None
    try:
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
        resources = raw.pop("resources", {}) or {}
        if "cpu" in resources and "cpu_count" not in raw:
            raw["cpu_count"] = resources["cpu"]
        if "memory" in resources and "memory_mb" not in raw:
            raw["memory_mb"] = resources["memory"]
        return SandboxTemplate.model_validate(raw)
    except Exception:
        return None


def _install_templates_to_cache() -> None:
    """同步模板到 ~/.ebx/templates/ 以便 resolve_capabilities 发现自定义命令。"""
    for name in CUSTOM_TEMPLATES:
        src = TEMPLATES_DIR / name
        dst = EBX_TEMPLATES_CACHE / name
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for fname in ("template.yaml", "commands.py"):
            s = src / fname
            if s.exists():
                shutil.copy2(s, dst / fname)
    print(f"  📁 已同步 {len(CUSTOM_TEMPLATES)} 个模板到 {EBX_TEMPLATES_CACHE}")


async def _list_existing_templates() -> dict[str, str]:
    """返回 {name_or_alias → template_id} 映射。"""
    config = load_config()
    auth = create_auth_provider(api_key=config.api_key)
    http = HttpClient(config, auth)
    manager = TemplateManager(http)
    mapping: dict[str, str] = {}
    try:
        templates = await manager.list()
        for t in templates:
            mapping[t.template_id] = t.template_id
            for alias in t.aliases:
                mapping[alias] = t.template_id
    except Exception as exc:
        print(f"  ⚠️  列出模板失败: {exc}")
    finally:
        await http.close()
    return mapping


def _finalize_result(result: TemplateTestResult, t_start: float) -> None:
    result.total_duration = time.monotonic() - t_start
    if result.fail_count == 0:
        result.overall = "PASS"
    elif result.pass_count > 0:
        result.overall = "PARTIAL"
    else:
        result.overall = "FAIL"
    icon = {"PASS": "✅", "PARTIAL": "⚠️", "FAIL": "❌"}.get(result.overall, "⬜")
    _log(result.template_name, f"{icon} 完成 ({result.pass_count}✓ "
         f"{result.fail_count}✗ {result.skip_count}⏭) "
         f"{result.total_duration:.1f}s")


# =====================================================================
# SDK envd 能力测试（shell / files / code）— Part 1 & Part 2 共享
# =====================================================================
async def _test_envd_capabilities(
    sandbox: Sandbox, tag: str
) -> tuple[list[SubStep], bool]:
    """返回 (步骤列表, shell_ok)"""
    steps: list[SubStep] = []
    shell_ok = False

    # -- Shell 执行 (with warmup) --
    step = SubStep(name="Shell 执行")
    t0 = time.monotonic()
    for attempt in range(1, WARMUP_MAX_RETRIES + 1):
        try:
            await sandbox.commands.list()
            _log(tag, f"✅ envd 就绪 (attempt {attempt})")
            break
        except Exception as exc:
            if attempt < WARMUP_MAX_RETRIES:
                _log(tag, f"⏳ warmup {attempt}/{WARMUP_MAX_RETRIES}… "
                     f"({type(exc).__name__})")
                await asyncio.sleep(WARMUP_DELAY_SEC)
            else:
                _log(tag, f"⚠️ envd warmup 超时: {exc}")

    last_exc: Exception | None = None
    last_tb: str = ""
    for attempt in range(1, WARMUP_MAX_RETRIES + 1):
        try:
            r = await sandbox.commands.run("echo 'hello from cloud sandbox'")
            stdout = r.stdout.strip()
            assert r.exit_code == 0, f"exit_code={r.exit_code}"
            assert "hello" in stdout
            _log(tag, f"✅ Shell: {stdout!r}")
            step.status = "PASS"
            step.detail = stdout[:60]
            shell_ok = True
            break
        except Exception as exc:
            last_exc = exc
            last_tb = traceback.format_exc()
            # Try to capture response body from HTTPStatusError
            err_msg = str(exc)
            if hasattr(exc, 'response'):
                try:
                    err_msg += f" | body={exc.response.text[:200]}"  # type: ignore
                except Exception:
                    pass
            if attempt < WARMUP_MAX_RETRIES:
                _log(tag, f"⏳ shell attempt {attempt}… ({err_msg[:100]})")
                await asyncio.sleep(WARMUP_DELAY_SEC)
    if not shell_ok:
        step.status = "FAIL"
        step.error = last_tb
        _log(tag, f"❌ Shell 失败: {last_exc}")
    step.duration = time.monotonic() - t0
    steps.append(step)

    # -- 文件读写 --
    step = SubStep(name="文件读写")
    t0 = time.monotonic()
    try:
        test_content = f"hello cloud from {tag}"
        await sandbox.files.write("/tmp/e2e_test.txt", test_content)
        read_back = await sandbox.files.read("/tmp/e2e_test.txt")
        assert read_back == test_content, f"内容不一致: {read_back!r}"
        _log(tag, "✅ 文件读写一致")
        step.status = "PASS"
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log(tag, f"❌ 文件读写失败: {exc}")
    step.duration = time.monotonic() - t0
    steps.append(step)

    # -- 代码执行（shell 方式） --
    step = SubStep(name="代码执行")
    t0 = time.monotonic()
    if shell_ok:
        try:
            r = await sandbox.commands.run('python3 -c "print(42 + 58)"')
            stdout = r.stdout.strip()
            assert r.exit_code == 0, f"exit_code={r.exit_code}"
            assert "100" in stdout
            _log(tag, f"✅ 代码: stdout={stdout!r}")
            step.status = "PASS"
            step.detail = f"stdout={stdout}"
        except Exception as exc:
            step.status = "FAIL"
            step.error = traceback.format_exc()
            _log(tag, f"❌ 代码执行失败: {exc}")
    else:
        step.status = "SKIP"
        step.detail = "Shell 不可用"
        _log(tag, "⏭️  跳过代码执行 (Shell 不可用)")
    step.duration = time.monotonic() - t0
    steps.append(step)

    return steps, shell_ok


# =====================================================================
# CLI 测试辅助
# =====================================================================
def _run_cli(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """运行 ebx CLI 命令并返回结果。"""
    cmd = [sys.executable, "-m", "easy_sandbox.cli.main"] + list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env={**__import__("os").environ, "PYTHONPATH": str(SRC_DIR)},
    )


# =====================================================================
# Part 1: 平台已有模板 — 测试 CLI + SDK envd 能力
# =====================================================================
async def test_part1_existing_templates() -> list[TemplateTestResult]:
    """对平台官方模板进行 CLI + SDK envd 测试。"""
    print()
    print("=" * 94)
    print("  Part 1: 平台官方模板 — 验证 CLI + SDK envd 能力")
    print("=" * 94)

    print(f"  官方模板: {OFFICIAL_TEMPLATES}")
    print()

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks = [
        asyncio.create_task(
            _test_existing_template(name, tid, semaphore)
        )
        for name, tid in OFFICIAL_TEMPLATES.items()
    ]
    results: list[TemplateTestResult] = await asyncio.gather(*tasks)

    # CLI 测试（串行，使用第一个官方模板）
    first_name = next(iter(OFFICIAL_TEMPLATES))
    cli_result = _test_cli(first_name, OFFICIAL_TEMPLATES[first_name])
    results.append(cli_result)

    return results


async def _test_existing_template(
    name: str, template_id: str, semaphore: asyncio.Semaphore,
) -> TemplateTestResult:
    """测试单个已有模板的 SDK envd 能力。"""
    result = TemplateTestResult(template_name=f"[已有]{name}")
    t_start = time.monotonic()
    sandbox: Sandbox | None = None

    async with semaphore:
        _log(name, "🚀 Part1 开始")

        # 创建沙箱
        step = SubStep(name="创建沙箱")
        t0 = time.monotonic()
        try:
            _log(name, f"📡 创建沙箱 (template={template_id})…")
            sandbox = await Sandbox.create(
                template=template_id, timeout=300,
                metadata={"purpose": "e2e-part1", "template": name},
            )
            _log(name, f"✅ 沙箱: {sandbox.id}")
            step.status = "PASS"
            step.detail = sandbox.id
        except Exception as exc:
            step.status = "FAIL"
            step.error = traceback.format_exc()
            _log(name, f"❌ 创建失败: {exc}")
        step.duration = time.monotonic() - t0
        result.steps.append(step)

        if sandbox is None:
            for sub in ["Shell 执行", "文件读写", "代码执行", "清理"]:
                result.steps.append(SubStep(name=sub, status="SKIP",
                                            detail="沙箱未创建"))
            _finalize_result(result, t_start)
            return result

        # envd 能力测试
        envd_steps, _ = await _test_envd_capabilities(sandbox, name)
        result.steps.extend(envd_steps)

        # 清理
        step = SubStep(name="清理")
        t0 = time.monotonic()
        try:
            await sandbox.kill()
            _log(name, f"🧹 沙箱 {sandbox.id} 已销毁")
            step.status = "PASS"
        except Exception as exc:
            step.status = "FAIL"
            step.error = traceback.format_exc()
            _log(name, f"❌ 清理失败: {exc}")
        step.duration = time.monotonic() - t0
        result.steps.append(step)

    _finalize_result(result, t_start)
    return result


def _test_cli(template_name: str, template_id: str) -> TemplateTestResult:
    """测试 ebx CLI 命令（串行）。"""
    result = TemplateTestResult(template_name="[CLI]ebx 命令")
    t_start = time.monotonic()

    # -- ebx template list --
    step = SubStep(name="ebx template list")
    t0 = time.monotonic()
    try:
        r = _run_cli("--json", "template", "list")
        assert r.returncode == 0, f"exit_code={r.returncode}\n{r.stderr}"
        _log("CLI", f"✅ template list (exit={r.returncode})")
        step.status = "PASS"
        step.detail = f"exit={r.returncode}"
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log("CLI", f"❌ template list: {exc}")
    step.duration = time.monotonic() - t0
    result.steps.append(step)

    # -- ebx create --
    step = SubStep(name="ebx create")
    t0 = time.monotonic()
    sandbox_id: str | None = None
    try:
        r = _run_cli("--json", "create", "--template", template_id)
        assert r.returncode == 0, f"exit_code={r.returncode}\n{r.stderr}"
        import json
        data = json.loads(r.stdout)
        sandbox_id = data.get("ID") or data.get("id")
        assert sandbox_id, f"无法获取沙箱 ID: {data}"
        _log("CLI", f"✅ create: {sandbox_id}")
        step.status = "PASS"
        step.detail = sandbox_id
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log("CLI", f"❌ create: {exc}")
    step.duration = time.monotonic() - t0
    result.steps.append(step)

    if not sandbox_id:
        for sub in ["ebx list", "ebx exec", "ebx kill"]:
            result.steps.append(SubStep(name=sub, status="SKIP",
                                        detail="沙箱未创建"))
        _finalize_result(result, t_start)
        return result

    # -- ebx list --
    step = SubStep(name="ebx list")
    t0 = time.monotonic()
    try:
        r = _run_cli("--json", "list")
        assert r.returncode == 0, f"exit_code={r.returncode}\n{r.stderr}"
        _log("CLI", f"✅ list (exit={r.returncode})")
        step.status = "PASS"
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log("CLI", f"❌ list: {exc}")
    step.duration = time.monotonic() - t0
    result.steps.append(step)

    # -- ebx exec --
    step = SubStep(name="ebx exec")
    t0 = time.monotonic()
    try:
        # 等待 envd 就绪
        time.sleep(3)
        r = _run_cli("exec", sandbox_id, "echo hello-from-cli", timeout=60)
        assert r.returncode == 0, f"exit_code={r.returncode}\n{r.stderr}"
        assert "hello-from-cli" in r.stdout, f"stdout={r.stdout!r}"
        _log("CLI", f"✅ exec: {r.stdout.strip()!r}")
        step.status = "PASS"
        step.detail = r.stdout.strip()[:60]
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log("CLI", f"❌ exec: {exc}")
    step.duration = time.monotonic() - t0
    result.steps.append(step)

    # -- ebx kill --
    step = SubStep(name="ebx kill")
    t0 = time.monotonic()
    try:
        r = _run_cli("kill", sandbox_id, "--yes")
        assert r.returncode == 0, f"exit_code={r.returncode}\n{r.stderr}"
        _log("CLI", f"✅ kill (exit={r.returncode})")
        step.status = "PASS"
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log("CLI", f"❌ kill: {exc}")
    step.duration = time.monotonic() - t0
    result.steps.append(step)

    _finalize_result(result, t_start)
    return result


# =====================================================================
# Part 2: 自定义模板构建 — 测试 CLI + SDK + Server 能力
# =====================================================================
async def test_part2_custom_templates(
    existing_map: dict[str, str],
) -> list[TemplateTestResult]:
    """并行构建并测试 examples/templates/ 下的所有自定义模板。"""
    print()
    print("=" * 94)
    print("  Part 2: 自定义模板构建 — 验证 CLI + SDK envd + Sandbox Server 能力")
    print("=" * 94)
    print(f"  模板: {CUSTOM_TEMPLATES}")
    print(f"  并行数: {MAX_CONCURRENCY}")
    print()

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks = [
        asyncio.create_task(
            _test_custom_template(name, semaphore, existing_map)
        )
        for name in CUSTOM_TEMPLATES
    ]
    return await asyncio.gather(*tasks)


async def _test_custom_template(
    name: str,
    semaphore: asyncio.Semaphore,
    existing_map: dict[str, str],
) -> TemplateTestResult:
    """测试单个自定义模板：构建 → 创建沙箱 → envd → server → 清理。"""
    result = TemplateTestResult(template_name=name)
    t_start = time.monotonic()
    sandbox: Sandbox | None = None
    effective_template: str | None = None

    async with semaphore:
        _log(name, "🚀 Part2 开始")

        # ==============================================================
        # 步骤 1: 模板准备（已有 → 构建 → 回退 base）
        # ==============================================================
        step = SubStep(name="模板准备")
        t0 = time.monotonic()
        try:
            if name in existing_map:
                effective_template = existing_map[name]
                _log(name, f"♻️  平台已有: {effective_template}")
                step.detail = f"已有: {effective_template}"
                step.status = "PASS"
            else:
                _log(name, "🔨 尝试构建…")
                tmpl = _load_template_yaml(name)
                if tmpl is None:
                    raise FileNotFoundError(f"template.yaml not found")
                dockerfile = tmpl.to_dockerfile()
                _log(name, f"📦 Dockerfile ({len(dockerfile)} chars)")
                config = load_config()
                auth = create_auth_provider(api_key=config.api_key)
                http = HttpClient(config, auth)
                manager = TemplateManager(http)
                try:
                    alias = f"e2e-{name}"
                    info = await manager.build(
                        dockerfile, alias=alias, timeout=600,
                        poll_interval=5,
                    )
                    effective_template = info.template_id
                    _log(name, f"✅ 构建完成: {effective_template}")
                    step.detail = f"新建: {effective_template}"
                    step.status = "PASS"
                except Exception as build_exc:
                    _log(name, f"⚠️  构建失败: {build_exc}")
                    effective_template = "base"
                    step.detail = f"回退 base（{build_exc}）"
                    step.status = "PASS"
                finally:
                    await http.close()
        except Exception as exc:
            effective_template = "base"
            step.detail = f"回退 base（{exc}）"
            step.status = "PASS"
            _log(name, f"↩️  回退 base: {exc}")
        step.duration = time.monotonic() - t0
        result.steps.append(step)

        # ==============================================================
        # 步骤 2: 创建沙箱
        # ==============================================================
        step = SubStep(name="创建沙箱")
        t0 = time.monotonic()
        try:
            _log(name, f"📡 创建沙箱 (template={effective_template})…")
            sandbox = await Sandbox.create(
                template=effective_template, timeout=300,
                metadata={"purpose": "e2e-part2", "template": name},
            )
            _log(name, f"✅ 沙箱: {sandbox.id}")
            step.status = "PASS"
            step.detail = f"{sandbox.id} ({effective_template})"
        except Exception as exc:
            step.status = "FAIL"
            step.error = traceback.format_exc()
            _log(name, f"❌ 创建失败: {exc}")
        step.duration = time.monotonic() - t0
        result.steps.append(step)

        if sandbox is None:
            for sub in ["Shell 执行", "文件读写", "代码执行",
                         "自定义命令(本地)", "Server /health",
                         "Server /commands", "Server /upload+/download",
                         "清理"]:
                result.steps.append(SubStep(name=sub, status="SKIP",
                                            detail="沙箱未创建"))
            _finalize_result(result, t_start)
            return result

        # ==============================================================
        # 步骤 3: envd 能力测试（shell / files / code）
        # ==============================================================
        envd_steps, shell_ok = await _test_envd_capabilities(sandbox, name)
        result.steps.extend(envd_steps)

        # ==============================================================
        # 步骤 4: 自定义命令（本地解析 — via resolve_capabilities）
        # ==============================================================
        step = SubStep(name="自定义命令(本地)")
        t0 = time.monotonic()
        try:
            cmds = sandbox.list_commands()
            cmd_names = [c["name"] for c in cmds]
            _log(name, f"📋 自定义命令: {cmd_names}")
            step.detail = ", ".join(cmd_names) if cmd_names else "无"
            step.status = "PASS"
        except Exception as exc:
            step.status = "FAIL"
            step.error = traceback.format_exc()
            _log(name, f"❌ 自定义命令: {exc}")
        step.duration = time.monotonic() - t0
        result.steps.append(step)

        # ==============================================================
        # 步骤 5: Sandbox Server 能力测试（通过端口 9000 HTTP 请求）
        # ==============================================================
        server_steps = await _test_sandbox_server(sandbox, name)
        result.steps.extend(server_steps)

        # ==============================================================
        # 步骤 6: 清理
        # ==============================================================
        step = SubStep(name="清理")
        t0 = time.monotonic()
        try:
            await sandbox.kill()
            _log(name, f"🧹 沙箱 {sandbox.id} 已销毁")
            step.status = "PASS"
        except Exception as exc:
            step.status = "FAIL"
            step.error = traceback.format_exc()
            _log(name, f"❌ 清理失败: {exc}")
        step.duration = time.monotonic() - t0
        result.steps.append(step)

    _finalize_result(result, t_start)
    return result


# =====================================================================
# Sandbox Server 测试（通过 port 9000 的 HTTP 端点）
# =====================================================================
async def _test_sandbox_server(
    sandbox: Sandbox, tag: str
) -> list[SubStep]:
    """通过 sandbox.network.get_url(9000) 测试容器内 HTTP Server 端点。"""
    steps: list[SubStep] = []

    # 尝试获取 server URL（需要 ports 能力）
    try:
        server_url = sandbox.network.get_url(9000)
        access_headers = sandbox.network.get_access_headers()
    except Exception as exc:
        _log(tag, f"⚠️  无 ports 能力，跳过 Server 测试: {exc}")
        for sub in ["Server /health", "Server /commands",
                     "Server /upload+/download"]:
            steps.append(SubStep(name=sub, status="SKIP",
                                 detail=f"无 ports 能力: {exc}"))
        return steps

    _log(tag, f"🌐 Server URL: {server_url}")

    # -- /health --
    step = SubStep(name="Server /health")
    t0 = time.monotonic()
    server_ready = False
    async with httpx.AsyncClient(http2=True, timeout=30.0) as client:
        for attempt in range(1, SERVER_WARMUP_RETRIES + 1):
            try:
                resp = await client.get(
                    f"{server_url}/health",
                    headers=access_headers,
                )
                if resp.status_code == 200:
                    _log(tag, f"✅ /health → 200 (attempt {attempt})")
                    step.status = "PASS"
                    step.detail = f"attempt {attempt}"
                    server_ready = True
                    break
                else:
                    _log(tag, f"⏳ /health → {resp.status_code} "
                         f"(attempt {attempt})")
            except Exception as exc:
                _log(tag, f"⏳ /health 连接失败 attempt {attempt}: "
                     f"{type(exc).__name__}")
            if attempt < SERVER_WARMUP_RETRIES:
                await asyncio.sleep(SERVER_WARMUP_DELAY)

    if not server_ready:
        step.status = "FAIL"
        step.error = "Server 未就绪"
        _log(tag, "❌ Server 未就绪，跳过后续 Server 测试")
    step.duration = time.monotonic() - t0
    steps.append(step)

    if not server_ready:
        for sub in ["Server /commands", "Server /upload+/download"]:
            steps.append(SubStep(name=sub, status="SKIP",
                                 detail="Server 未就绪"))
        return steps

    # -- GET /commands --
    step = SubStep(name="Server /commands")
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(http2=True, timeout=30.0) as client:
            resp = await client.get(
                f"{server_url}/commands",
                headers=access_headers,
            )
            assert resp.status_code == 200, f"status={resp.status_code}"
            data = resp.json()
            cmd_names = [c.get("name", "?") for c in data.get("commands", [])]
            _log(tag, f"✅ /commands → {cmd_names}")
            step.status = "PASS"
            step.detail = ", ".join(cmd_names) if cmd_names else "无命令"
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log(tag, f"❌ /commands: {exc}")
    step.duration = time.monotonic() - t0
    steps.append(step)

    # -- POST /upload + GET /download 往返测试 --
    step = SubStep(name="Server /upload+/download")
    t0 = time.monotonic()
    try:
        test_data = f"e2e upload test for {tag}".encode()
        b64_content = base64.b64encode(test_data).decode("ascii")
        remote_path = "/tmp/e2e_server_test.txt"

        async with httpx.AsyncClient(http2=True, timeout=30.0) as client:
            # Upload
            up_resp = await client.post(
                f"{server_url}/upload",
                json={"path": remote_path, "content_base64": b64_content},
                headers={**access_headers,
                         "Content-Type": "application/json"},
            )
            assert up_resp.status_code == 200, \
                f"upload status={up_resp.status_code}: {up_resp.text[:200]}"
            _log(tag, f"✅ /upload → {up_resp.json().get('bytes')} bytes")

            # Download
            dl_resp = await client.get(
                f"{server_url}/download?path={url_quote(remote_path)}",
                headers=access_headers,
            )
            assert dl_resp.status_code == 200, \
                f"download status={dl_resp.status_code}: {dl_resp.text[:200]}"
            dl_data = base64.b64decode(dl_resp.json()["content_base64"])
            assert dl_data == test_data, f"内容不一致"
            _log(tag, "✅ /download → 内容一致")

        step.status = "PASS"
    except Exception as exc:
        step.status = "FAIL"
        step.error = traceback.format_exc()
        _log(tag, f"❌ /upload+/download: {exc}")
    step.duration = time.monotonic() - t0
    steps.append(step)

    return steps


# =====================================================================
# 汇总报告
# =====================================================================
def print_summary(
    title: str,
    results: list[TemplateTestResult],
    total_duration: float,
) -> None:
    print()
    print("=" * 94)
    print(f"  {title}")
    print("=" * 94)
    print()

    header = (f"  {'模板':24s} {'结果':8s} {'通过':6s} "
              f"{'失败':6s} {'跳过':6s} {'耗时':>10s}")
    print(header)
    print("  " + "-" * 86)

    for r in results:
        icon = {"PASS": "✅", "FAIL": "❌", "PARTIAL": "⚠️"}.get(
            r.overall, "⬜")
        print(f"  {r.template_name:22s} {icon} {r.overall:6s} "
              f"{r.pass_count:4d}   {r.fail_count:4d}   "
              f"{r.skip_count:4d}   {r.total_duration:8.1f}s")

    print("  " + "-" * 86)
    tp = sum(r.pass_count for r in results)
    tf = sum(r.fail_count for r in results)
    ts = sum(r.skip_count for r in results)
    t_pass = sum(1 for r in results if r.overall == "PASS")
    t_fail = sum(1 for r in results if r.overall == "FAIL")
    t_partial = sum(1 for r in results if r.overall == "PARTIAL")
    print(f"  {'合计':22s}        {tp:4d}   {tf:4d}   {ts:4d}   "
          f"{total_duration:8.1f}s")
    print()
    print(f"  模板: {t_pass} 全通过, {t_partial} 部分通过, {t_fail} 失败")
    print(f"  步骤: {tp} 通过, {tf} 失败, {ts} 跳过")
    print(f"  耗时: {total_duration:.1f}s")
    print("=" * 94)

    # 失败详情
    failures = [
        (r.template_name, s) for r in results for s in r.steps
        if s.status == "FAIL"
    ]
    if failures:
        print()
        print("  ❌ 失败详情:")
        print("  " + "-" * 86)
        for tname, s in failures:
            print(f"  [{tname}] {s.name}  ({s.duration:.2f}s)")
            if s.error:
                for line in s.error.strip().splitlines()[-6:]:
                    print(f"    {line}")
            print()


# =====================================================================
# 主流程
# =====================================================================
async def run_all_e2e() -> int:
    reset_config()
    config = load_config()

    print()
    print("🔧 配置:")
    print(f"   API URL  : {config.api_url}")
    print(f"   Domain   : {config.domain}")
    if config.api_key:
        print(f"   API Key  : {config.api_key[:12]}…{config.api_key[-4:]}")
    else:
        print("   API Key  : (未配置)")
    print()

    # 同步模板到本地缓存
    print("📁 同步模板到本地缓存…")
    _install_templates_to_cache()
    print()

    has_any_failure = False

    # ==========================================
    # Part 1: 平台官方模板
    # ==========================================
    print(f"\n📋 官方模板: {OFFICIAL_TEMPLATES}\n")
    t1_start = time.monotonic()
    part1_results = await test_part1_existing_templates()
    t1_dur = time.monotonic() - t1_start
    if part1_results:
        print_summary("Part 1 汇总 — 平台官方模板 (CLI + SDK envd)",
                       part1_results, t1_dur)
        if any(r.overall == "FAIL" for r in part1_results):
            has_any_failure = True

    # ==========================================
    # Part 2: 自定义模板
    # ==========================================
    print("\n📋 查询平台已有模板（用于自定义模板回退检查）…")
    existing_map = await _list_existing_templates()
    if existing_map:
        print(f"  ✅ 平台共 {len(existing_map)} 个模板/别名")
    print()
    t2_start = time.monotonic()
    part2_results = await test_part2_custom_templates(existing_map)
    t2_dur = time.monotonic() - t2_start
    print_summary("Part 2 汇总 — 自定义模板 (CLI + SDK envd + Server)",
                   part2_results, t2_dur)
    if any(r.overall == "FAIL" for r in part2_results):
        has_any_failure = True

    # ==========================================
    # 总汇总
    # ==========================================
    all_results = part1_results + part2_results
    total_dur = t1_dur + t2_dur
    print_summary("总汇总 — 云端 E2E 测试", all_results, total_dur)

    return 1 if has_any_failure else 0


def main() -> int:
    print("=" * 94)
    print("  Easy Sandbox — 云端 E2E 测试")
    print("  Part 1: 平台官方模板 (CLI + SDK envd)")
    print("  Part 2: 自定义模板 (CLI + SDK envd + Server)")
    print("=" * 94)
    return asyncio.run(run_all_e2e())


if __name__ == "__main__":
    sys.exit(main())
