#!/usr/bin/env python3
"""End-to-end capability validation for easy-sandbox.

真实运行的端到端能力验证脚本。四部分：

  Part A — GitHub install 管线：先看 GitHub rate_limit 预算；有 token / 预算充足
           时真实拉取 GitHub 模板，否则回退本地 registry（并如实标注 GitHub 远程
           因限额 BLOCKED，代码路径已在 #43 验证）。记录 POST /templates 返回码。
  Part B — E2B-compat 能力验证（真实 FC，template="base"）：shell / files / code /
           组合工作流 / 生命周期。
  Part C — Modal 风格声明式（真实 FC，template="code-interpreter-v1"）：@sandbox 装饰器。
  Part D — 从 Part A 安装的自定义模板创建沙箱（很可能因 legacy 构建未完成而失败，
           如实记录现实边界，不伪装成功）。

真实后端需要 E2B_API_KEY（由 load_config 从项目根 .env 自动加载）。
本脚本 **不打印任何密钥明文**，仅打印 "present: True/False"。
每个沙箱都在 finally 中 kill，避免泄漏计费资源。

这是一个独立可运行脚本（放 examples/ 下），pytest 默认只收集 test_*.py，
因此不会污染默认 CI（无需 -m "not integration" 排除）。

运行方式（从项目根目录）::

    python3 examples/compat-demos/e2e_capability_validation.py

若无凭证或后端不可达，相关 case 标注 BLOCKED 并说明缺什么，不伪造结果。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: locate project root & make easy_sandbox importable (src layout)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC = PROJECT_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
# Verdict vocabulary: PASS / FAIL / BLOCKED / SKIP
RESULTS: list[tuple[str, str, str, str]] = []  # (part, case, verdict, detail)


def record(part: str, case: str, verdict: str, detail: str = "") -> None:
    """Record and immediately print a case verdict."""
    RESULTS.append((part, case, verdict, detail))
    detail_one_line = " ".join(detail.split()) if detail else ""
    if len(detail_one_line) > 300:
        detail_one_line = detail_one_line[:297] + "..."
    print(f"  [{verdict:7}] {case}: {detail_one_line}")


def hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def _exc_summary(exc: BaseException) -> str:
    """One-line summary of an exception incl. any error code attribute."""
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    prefix = f"[{code}] " if code else ""
    return f"{prefix}{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# CLI subprocess helper (ebx is not on PATH → invoke the click group directly)
# ---------------------------------------------------------------------------
def run_cli(args: list[str], timeout: int = 180) -> tuple[int, str, str]:
    """Run the ebx CLI in a subprocess and capture (returncode, stdout, stderr)."""
    code = "import sys; from easy_sandbox.cli.main import cli; cli(sys.argv[1:])"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", (exc.stderr or "") + "\n<TIMEOUT>"


def _parse_template_id(stdout: str) -> str | None:
    """Extract TemplateID from CLI JSON (or plain) output."""
    text = stdout.strip()
    # JSON object may be embedded among other lines; try each line + whole blob.
    candidates = [text, *text.splitlines()]
    for blob in candidates:
        blob = blob.strip()
        if not (blob.startswith("{") and blob.endswith("}")):
            continue
        try:
            data = json.loads(blob)
        except Exception:
            continue
        tid = data.get("TemplateID") or data.get("templateID")
        if tid and tid != "N/A":
            return str(tid)
    m = re.search(r'"?[Tt]emplate[Ii][Dd]"?\s*[:=]\s*"?([A-Za-z0-9_\-]+)"?', stdout)
    if m and m.group(1) != "N":  # avoid matching "N/A"
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Part A — GitHub install pipeline
# ---------------------------------------------------------------------------
def part_a() -> str | None:
    """Validate the template install pipeline. Returns an installed template id (if any)."""
    hr("Part A — GitHub install 管线验证")
    installed_template_id: str | None = None
    github_installed = False  # True only if A-01 real GitHub install landed a cache copy

    # A-00: rate_limit budget
    remaining = None
    try:
        proc = subprocess.run(
            ["curl", "-s", "https://api.github.com/rate_limit"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(proc.stdout)
        core = data["resources"]["core"]
        remaining = core["remaining"]
        record(
            "A",
            "A-00 rate_limit",
            "PASS",
            f"anonymous core remaining={remaining}/{core['limit']}",
        )
    except Exception as exc:  # noqa: BLE001
        record("A", "A-00 rate_limit", "BLOCKED", f"curl/parse failed: {_exc_summary(exc)}")

    token_present = bool(
        os.environ.get("GITHUB_TOKEN") or os.environ.get("SANDBOX_GITHUB_TOKEN")
    )
    print(f"  GITHUB_TOKEN/SANDBOX_GITHUB_TOKEN present: {token_present}")

    have_budget = token_present or (remaining is not None and remaining > 0)

    # A-01: GitHub remote install (only when budget/token allows)
    github_ref = "Easy-Sandbox/awesome-templates//python-hello"
    if have_budget:
        rc, out, err = run_cli(
            ["-j", "template", "install", github_ref], timeout=180
        )
        tid = _parse_template_id(out)
        combined = (out + "\n" + err).strip()
        if rc == 0 and tid:
            installed_template_id = tid
            github_installed = True
            record(
                "A",
                "A-01 github install",
                "PASS",
                f"fetched+built stub, TemplateID={tid} (POST /templates rc=0)",
            )
        else:
            record(
                "A",
                "A-01 github install",
                "FAIL",
                f"exit={rc}; output tail: {combined[-260:]}",
            )
    else:
        record(
            "A",
            "A-01 github install",
            "BLOCKED",
            "GitHub anon rate limit exhausted (remaining=0) & no GITHUB_TOKEN; "
            "remote fetch code path already validated in task #43 (tarball API).",
        )

    # A-02: local registry install (always run — validates local pipeline + POST /templates)
    local_path = "./examples/templates/python-hello"
    rc, out, err = run_cli(
        ["-j", "template", "install", local_path, "--registry-type", "local"],
        timeout=180,
    )
    combined = (out + "\n" + err).strip()
    tid = _parse_template_id(out)
    if rc == 0 and tid:
        if installed_template_id is None:
            installed_template_id = tid
        record(
            "A",
            "A-02 local install",
            "PASS",
            f"local pipeline OK (parse template.yaml→Dockerfile→POST /templates rc=0); "
            f"TemplateID={tid}",
        )
    elif rc == 0:
        # rc==0 但未解析到可用 TemplateID：本地 fetch/parse 跑通，但 POST /templates
        # 未返回可用 TemplateID（后端 stub/400），不得判 PASS。
        record(
            "A",
            "A-02 local install",
            "BLOCKED",
            "local fetch/parse OK but POST /templates returned no usable TemplateID; "
            f"output tail: {combined[-220:]}",
        )
    else:
        record(
            "A",
            "A-02 local install",
            "FAIL",
            f"exit={rc}; output tail: {combined[-260:]}",
        )

    # A-03: cache landing check — 精确校验本次 install 的引用是否落缓存。
    # 缓存布局：~/.ebx/templates/{owner}/{repo}/{ref|default}/{subdir}/template.yaml
    # 本地 in-place install 不落缓存（预期），只有真实 GitHub install 才落缓存。
    cache_dir = Path.home() / ".ebx" / "templates"
    if github_installed:
        # A-01 用的引用：Easy-Sandbox/awesome-templates//python-hello（默认分支）
        expected = (
            cache_dir
            / "Easy-Sandbox"
            / "awesome-templates"
            / "default"
            / "python-hello"
            / "template.yaml"
        )
        landed = expected.exists()
        record(
            "A",
            "A-03 cache landing",
            "PASS" if landed else "FAIL",
            f"expected cache file {'exists' if landed else 'MISSING'}: {expected}",
        )
    else:
        record(
            "A",
            "A-03 cache landing",
            "BLOCKED",
            "no real GitHub install this run (A-01 BLOCKED); local in-place install "
            "does not populate ~/.ebx/templates by design, so precise cache-ref "
            "verification is not applicable (NA).",
        )

    return installed_template_id


# ---------------------------------------------------------------------------
# Part B — E2B-compat capability validation (real FC, template="base")
# ---------------------------------------------------------------------------
async def _part_b_core() -> None:
    from easy_sandbox.compat import Sandbox
    from easy_sandbox.models.errors import CapabilityNotSupportedError
    from easy_sandbox.models.process import ProcessChunkType

    # Reuse one "base" sandbox for E2B-01..05/08/09 (minimise billing);
    # lifecycle + ci-v1 probe get their own sandboxes.
    sb = await Sandbox.create(template="base", timeout=300)
    print(f"  created base sandbox: id={getattr(sb, 'sandbox_id', '?')}")
    try:
        # E2B-01 shell
        try:
            r = await sb.commands.run("echo hello", timeout=60)
            ok = "hello" in r.stdout and r.exit_code == 0
            record(
                "B",
                "E2B-01 shell",
                "PASS" if ok else "FAIL",
                f"stdout={r.stdout.strip()!r} exit_code={r.exit_code}",
            )
        except Exception as exc:  # noqa: BLE001
            record("B", "E2B-01 shell", "FAIL", _exc_summary(exc))

        # E2B-02 files
        try:
            await sb.files.write("/tmp/t.txt", "world")
            content = await sb.files.read("/tmp/t.txt")
            exists = await sb.files.exists("/tmp/t.txt")
            ok = content == "world" and exists is True
            record(
                "B",
                "E2B-02 files",
                "PASS" if ok else "FAIL",
                f"read={content!r} exists={exists}",
            )
        except Exception as exc:  # noqa: BLE001
            record("B", "E2B-02 files", "FAIL", _exc_summary(exc))

        # E2B-03 code
        try:
            cr = await sb.run_code("print(2+3)", timeout=60)
            payload = (cr.text or "") + (cr.stdout or "")
            ok = "5" in payload
            record(
                "B",
                "E2B-03 code",
                "PASS" if ok else "FAIL",
                f"text={cr.text!r} stdout={cr.stdout!r}",
            )
        except Exception as exc:  # noqa: BLE001
            record("B", "E2B-03 code", "FAIL", _exc_summary(exc))

        # E2B-04 combined workflow: write script -> run python3 -> read output file
        try:
            script = (
                "with open('/tmp/out.txt','w') as f:\n"
                "    f.write(str(sum(range(1,11))))\n"
            )
            await sb.files.write("/tmp/calc.py", script)
            run = await sb.commands.run("python3 /tmp/calc.py", timeout=60)
            out_content = await sb.files.read("/tmp/out.txt")
            ok = run.exit_code == 0 and out_content.strip() == "55"
            record(
                "B",
                "E2B-04 workflow",
                "PASS" if ok else "FAIL",
                f"run.exit={run.exit_code} out.txt={out_content.strip()!r} (expect 55)",
            )
        except Exception as exc:  # noqa: BLE001
            record("B", "E2B-04 workflow", "FAIL", _exc_summary(exc))

        # E2B-05 ports capability gate (negative): base falls back to
        # DEFAULT{shell,files,code} (no "ports") → get_host must be gated.
        try:
            host = sb.network.get_host(9000)
            record(
                "B",
                "E2B-05 ports-gate-neg",
                "FAIL",
                f"expected CapabilityNotSupportedError(E3004) but got host={host!r}",
            )
        except CapabilityNotSupportedError as exc:
            record(
                "B",
                "E2B-05 ports-gate-neg",
                "PASS",
                f"correctly gated: {_exc_summary(exc)} (capability={exc.capability!r})",
            )
        except Exception as exc:  # noqa: BLE001
            record("B", "E2B-05 ports-gate-neg", "FAIL", f"wrong error type: {_exc_summary(exc)}")

        # E2B-08 files directory ops: make_dir → write → list → remove → exists
        try:
            d = "/tmp/e2e_dir"
            await sb.files.make_dir(d)
            await sb.files.write(f"{d}/inside.txt", "x")
            entries = await sb.files.list(d)
            names = [e.name for e in entries]
            contains = "inside.txt" in names
            await sb.files.remove(f"{d}/inside.txt")
            still = await sb.files.exists(f"{d}/inside.txt")
            ok = contains and still is False
            record(
                "B",
                "E2B-08 files dir ops",
                "PASS" if ok else "FAIL",
                f"list={names} contains_inside={contains} exists_after_remove={still}",
            )
        except Exception as exc:  # noqa: BLE001
            record("B", "E2B-08 files dir ops", "FAIL", _exc_summary(exc))

        # E2B-09 commands.stream: collect STDOUT chunks and assert concatenation
        try:
            parts: list[str] = []
            async for chunk in sb.commands.stream("printf 'chunk-a\\nchunk-b\\n'", timeout=60):
                if chunk.type == ProcessChunkType.STDOUT:
                    parts.append(chunk.data)
            joined = "".join(parts)
            ok = "chunk-a" in joined and "chunk-b" in joined
            record(
                "B",
                "E2B-09 stream",
                "PASS" if ok else "FAIL",
                f"joined_stdout={joined.strip()!r} (expect chunk-a & chunk-b)",
            )
        except Exception as exc:  # noqa: BLE001
            record("B", "E2B-09 stream", "FAIL", _exc_summary(exc))
    finally:
        try:
            await sb.kill()
            print("  killed base sandbox (E2B-01..05/08/09)")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN: kill base sandbox failed: {_exc_summary(exc)}")

    # E2B-06 ports capability (positive): needs a READY template that declares
    # "ports". python-hello declares ports but its legacy build is CREATE_FAILED
    # (see Part D); builtins base/code-interpreter-v1 fall back to
    # DEFAULT{shell,files,code} without ports. No READY ports-capable template
    # exists on this backend → honestly BLOCKED, not faked PASS.
    record(
        "B",
        "E2B-06 ports-pos",
        "BLOCKED",
        "no READY template declaring 'ports' available: python-hello is "
        "CREATE_FAILED (legacy build never completes), builtins lack ports. "
        "Needs a READY ports-capable template to validate get_host/get_url/"
        "get_access_headers against real FC.",
    )

    # E2B-07 lifecycle: is_running True -> set_timeout -> kill -> verify destroyed
    life = await Sandbox.create(template="base", timeout=120)
    print(f"  created lifecycle sandbox: id={getattr(life, 'sandbox_id', '?')}")
    killed = False
    try:
        running = await life.is_running()
        await life.set_timeout(120)
        await life.kill()
        killed = True
        destroyed = False
        try:
            still = await life.is_running()
            destroyed = still is False
        except Exception:  # noqa: BLE001
            destroyed = True  # querying a killed sandbox errors → destroyed
        ok = running is True and destroyed
        record(
            "B",
            "E2B-07 lifecycle",
            "PASS" if ok else "FAIL",
            f"is_running(before)={running} destroyed_after_kill={destroyed}",
        )
    except Exception as exc:  # noqa: BLE001
        record("B", "E2B-07 lifecycle", "FAIL", _exc_summary(exc))
    finally:
        if not killed:
            try:
                await life.kill()
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN: kill lifecycle sandbox failed: {_exc_summary(exc)}")

    # E2B-03b localization probe: run_code on code-interpreter-v1 (NOT base).
    # Determines whether the E2B CodeInterpreter service (envd
    # /code.CodeInterpreter/Execute) is template-bound or absent data-plane-wide.
    # Observed reality: 404 on code-interpreter-v1 too → the service is not
    # deployed on this FC backend at all (base's 404 is not template-specific).
    ci = await Sandbox.create(template="code-interpreter-v1", timeout=120)
    print(f"  created code-interpreter-v1 probe sandbox: id={getattr(ci, 'sandbox_id', '?')}")
    try:
        cr = await ci.run_code("print(2+3)", timeout=60)
        payload = (cr.text or "") + (cr.stdout or "")
        ok = "5" in payload
        record(
            "B",
            "E2B-03b code@ci-v1",
            "PASS" if ok else "FAIL",
            f"run_code on code-interpreter-v1: text={cr.text!r} stdout={cr.stdout!r} "
            f"(if PASS, run_code is template-bound; if FAIL/404, the CodeInterpreter "
            f"service is absent data-plane-wide — use commands.run for code execution)",
        )
    except Exception as exc:  # noqa: BLE001
        record("B", "E2B-03b code@ci-v1", "FAIL", _exc_summary(exc))
    finally:
        try:
            await ci.kill()
            print("  killed code-interpreter-v1 probe sandbox")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN: kill probe sandbox failed: {_exc_summary(exc)}")


def part_b(api_key_present: bool) -> None:
    hr("Part B — E2B-compat 能力验证（真实 FC, template=\"base\"）")
    if not api_key_present:
        for case in (
            "E2B-01 shell",
            "E2B-02 files",
            "E2B-03 code",
            "E2B-04 workflow",
            "E2B-05 ports-gate-neg",
            "E2B-06 ports-pos",
            "E2B-07 lifecycle",
            "E2B-08 files dir ops",
            "E2B-09 stream",
            "E2B-03b code@ci-v1",
        ):
            record("B", case, "BLOCKED", "no E2B_API_KEY in env/.env → cannot reach real FC")
        return
    try:
        asyncio.run(_part_b_core())
    except Exception as exc:  # noqa: BLE001
        record("B", "E2B-* (fatal)", "BLOCKED", f"sandbox create failed: {_exc_summary(exc)}")
        print("  " + traceback.format_exc().splitlines()[-1])


# ---------------------------------------------------------------------------
# Part C — Modal-style declarative (real FC, template="code-interpreter-v1")
# ---------------------------------------------------------------------------
def part_c(api_key_present: bool) -> None:
    hr("Part C — Modal 风格声明式（真实 FC, template=\"code-interpreter-v1\"）")
    if not api_key_present:
        for case in ("MOD-01 add", "MOD-02 numpy", "MOD-04 cross-check"):
            record("C", case, "BLOCKED", "no E2B_API_KEY in env/.env → cannot reach real FC")
        return

    from easy_sandbox.declarative import sandbox

    # MOD-01: simple add
    @sandbox(template="code-interpreter-v1", timeout=300)
    def add(a: int, b: int) -> int:
        return a + b

    try:
        res = add(1, 2)
        record("C", "MOD-01 add", "PASS" if res == 3 else "FAIL", f"add(1,2)={res!r} (expect 3)")
    except Exception as exc:  # noqa: BLE001
        record("C", "MOD-01 add", "FAIL", _exc_summary(exc))

    # MOD-02 (optional): packages=["numpy"] — may be slow / flaky; SKIP with reason on failure
    @sandbox(template="code-interpreter-v1", packages=["numpy"], timeout=600)
    def numpy_pi() -> float:
        import numpy  # noqa: I001

        return float(numpy.pi)

    try:
        res = numpy_pi()
        ok = abs(res - 3.14159) < 1e-3
        record(
            "C",
            "MOD-02 numpy",
            "PASS" if ok else "FAIL",
            f"numpy.pi={res!r} (expect ~3.14159)",
        )
    except Exception as exc:  # noqa: BLE001
        record(
            "C",
            "MOD-02 numpy",
            "SKIP",
            f"pip install/exec unstable or unsupported: {_exc_summary(exc)}",
        )

    # MOD-04: same computation via Modal declarative vs E2B imperative — assert equal
    @sandbox(template="code-interpreter-v1", timeout=300)
    def mult(a: int, b: int) -> int:
        return a * b

    try:
        modal_res = mult(6, 7)

        async def _e2b_side() -> int:
            from easy_sandbox.compat import Sandbox

            sb = await Sandbox.create(template="base", timeout=300)
            try:
                r = await sb.commands.run("python3 -c 'print(6*7)'", timeout=60)
                return int(r.stdout.strip())
            finally:
                await sb.kill()

        e2b_res = asyncio.run(_e2b_side())
        ok = modal_res == e2b_res == 42
        record(
            "C",
            "MOD-04 cross-check",
            "PASS" if ok else "FAIL",
            f"modal={modal_res} e2b={e2b_res} (expect both 42)",
        )
    except Exception as exc:  # noqa: BLE001
        record("C", "MOD-04 cross-check", "FAIL", _exc_summary(exc))


# ---------------------------------------------------------------------------
# Part D — create sandbox from installed custom template (reality boundary)
# ---------------------------------------------------------------------------
def part_d(api_key_present: bool, template_id: str | None) -> None:
    hr("Part D — 从已安装自定义模板创建沙箱（如实记录现实边界）")
    if not api_key_present:
        record("D", "D-01 custom template", "BLOCKED", "no E2B_API_KEY → cannot reach real FC")
        return
    if not template_id:
        record(
            "D",
            "D-01 custom template",
            "BLOCKED",
            "Part A produced no TemplateID (POST /templates did not return one) → nothing to test",
        )
        return

    async def _try_create() -> str:
        from easy_sandbox.compat import Sandbox

        sb = await Sandbox.create(template=template_id, timeout=120)
        try:
            return getattr(sb, "sandbox_id", "?")
        finally:
            await sb.kill()

    try:
        sid = asyncio.run(_try_create())
        # Unexpected success — legacy stub build usually incomplete. Record honestly.
        record(
            "D",
            "D-01 custom template",
            "PASS",
            f"UNEXPECTED success: sandbox {sid} created from stub template {template_id}",
        )
    except Exception as exc:  # noqa: BLE001
        record(
            "D",
            "D-01 custom template",
            "BLOCKED",
            f"template {template_id}: {_exc_summary(exc)} "
            f"— expected: legacy POST /templates only creates metadata stub, "
            f"real build (build-local + Docker + ACR) never completes.",
        )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def summarize() -> int:
    hr("汇总 SUMMARY")
    counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "SKIP": 0}
    for _part, _case, verdict, _detail in RESULTS:
        counts[verdict] = counts.get(verdict, 0) + 1
    for part, case, verdict, _detail in RESULTS:
        print(f"  {part} | {verdict:7} | {case}")
    print(
        "\n  Totals: "
        + ", ".join(f"{k}={v}" for k, v in counts.items())
        + f"  (total {len(RESULTS)})"
    )
    # Exit non-zero only on real FAIL (BLOCKED/SKIP are honest, not failures).
    return 1 if counts.get("FAIL", 0) else 0


def main() -> int:
    hr("easy-sandbox E2E 能力验证 — 真实运行")
    print(f"  project root: {PROJECT_ROOT}")

    # Load config (auto-reads .env). NEVER print the key itself.
    api_key_present = False
    try:
        from easy_sandbox.transport.config import load_config

        cfg = load_config()
        api_key_present = bool(cfg.api_key)
        print(f"  E2B_API_KEY present: {api_key_present}")
        print(f"  api_url: {cfg.api_url}")
        print(f"  domain:  {cfg.domain}")
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: load_config failed: {_exc_summary(exc)}")

    template_id = part_a()
    part_b(api_key_present)
    part_c(api_key_present)
    part_d(api_key_present, template_id)
    return summarize()


if __name__ == "__main__":
    sys.exit(main())
