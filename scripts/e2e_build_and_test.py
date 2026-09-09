#!/usr/bin/env python3
"""E2E: local Docker build → ACR push → template creation → server test.

Usage:
    .venv/bin/python scripts/e2e_build_and_test.py

This script exercises the FULL SDK custom-template chain with NO fallback:

  Phase 1: DockerBuilder — local build + ACR push + v3/v2 template creation
  Phase 2: Create sandbox from our custom template → test all Server endpoints

If any step fails, the script records the failure and continues to the
cleanup phase. There is NO degradation to preset templates.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx  # noqa: E402
from serverless_sandbox.api.docker_builder import ACRConfig, DockerBuilder, _get_acr_auth_token  # noqa: E402
from serverless_sandbox.api.sandbox import Sandbox  # noqa: E402
from serverless_sandbox.transport.config import load_config, reset_config  # noqa: E402

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "examples" / "templates" / "python-hello"
COMMANDS_PY = TEMPLATE_DIR / "commands.py"

# ── Credentials from env ──
API_KEY = os.environ.get("E2B_API_KEY", "")
AK = os.environ.get("AccessKey", "")
SK = os.environ.get("AccessSecret", "")

# ACR config
ACR_REGISTRY = os.environ.get("ACR_REGISTRY", "registry.cn-hangzhou.aliyuncs.com")
ACR_NAMESPACE = os.environ.get("ACR_NAMESPACE", "serverless-sandbox-test")
ACR_REPO = os.environ.get("ACR_REPO", "python-hello")
ACREE_INSTANCE_ID = os.environ.get("ACREE_INSTANCE_ID", "")

# ── Result tracking ──
checks: dict[str, dict] = {}


def report(name: str, status: str, **extra: object) -> None:
    entry = {"status": status, **extra}
    checks[name] = entry
    icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚠️"}.get(status, "?")
    print(f"  {icon} {name}: {status}", flush=True)
    for k, v in extra.items():
        print(f"      {k}: {str(v)[:200]}", flush=True)


# ======================================================================
# Phase 1: Local Docker build → ACR push → Template creation
# ======================================================================

async def phase1_build_and_push() -> str | None:
    """Full DockerBuilder chain. Returns template_id or None on failure."""
    print("\n" + "=" * 60)
    print("PHASE 1: Local Docker Build → ACR Push → Template Creation")
    print("=" * 60, flush=True)

    builder = DockerBuilder()

    # 1.1: Check Docker
    print("\n[1.1] Checking Docker daemon...", flush=True)
    if not builder.check_docker():
        report("docker_check", "FAIL", reason="Docker daemon not accessible")
        return None
    report("docker_check", "PASS")

    # 1.2: Inject SDK wheel into build context
    print("\n[1.2] Building SDK wheel and injecting into docker context...", flush=True)
    injected_wheels: list[Path] = []
    try:
        injected_wheels = DockerBuilder.inject_sdk_wheel(TEMPLATE_DIR, PROJECT_ROOT)
        if injected_wheels:
            report("inject_wheel", "PASS",
                   wheels=[w.name for w in injected_wheels])
        else:
            report("inject_wheel", "FAIL", reason="No wheel built")
            return None
    except Exception as exc:
        report("inject_wheel", "FAIL", error=str(exc))
        return None

    # 1.3: Build Docker image locally
    ts = int(time.time())
    local_tag = f"python-hello-e2e:{ts}"
    print(f"\n[1.3] Building Docker image locally: {local_tag}", flush=True)
    try:
        builder.build(
            context_dir=TEMPLATE_DIR,
            tag=local_tag,
            platform="linux/amd64",
            on_output=lambda line: print(f"    {line}", flush=True),
        )
        report("docker_build", "PASS", tag=local_tag)
    except Exception as exc:
        report("docker_build", "FAIL", error=str(exc))
        return None
    finally:
        # Clean up injected wheels
        for whl in injected_wheels:
            try:
                whl.unlink(missing_ok=True)
            except OSError:
                pass

    # 1.4: ACR login + tag + push
    print("\n[1.4] Pushing to ACR...", flush=True)
    if not AK or not SK:
        report("acr_push", "FAIL",
               reason="No AccessKey/AccessSecret in .env — cannot push to ACR")
        return None

    acr = ACRConfig(
        registry=ACR_REGISTRY,
        namespace=ACR_NAMESPACE,
        repo=ACR_REPO,
        username=AK,
        password=SK,
        acree_instance_id=ACREE_INSTANCE_ID,
    )
    acr_tag = f"e2e-{ts}"
    acr_ref = acr.tagged_ref(acr_tag)

    # Get temp ACR credentials for both docker login and platform headers
    acr_temp_user = ""
    acr_temp_token = ""
    try:
        builder.login_acr_with_aksk(
            acr.registry, AK, SK,
            region="cn-hangzhou",
            instance_id=ACREE_INSTANCE_ID or None,
        )
        # Also fetch temp credentials for platform headers
        try:
            temp_creds = _get_acr_auth_token(
                AK, SK, "cn-hangzhou",
                instance_id=ACREE_INSTANCE_ID or None,
            )
            acr_temp_user = temp_creds.get("tempUserName", "")
            acr_temp_token = temp_creds.get("authorizationToken", "")
            print(f"    ACR temp user: {acr_temp_user}", flush=True)
        except Exception as exc:
            print(f"    Warning: Could not fetch separate temp creds: {exc}", flush=True)
        report("acr_login", "PASS", registry=acr.registry)
    except Exception as exc:
        report("acr_login", "FAIL", error=str(exc))
        return None

    try:
        builder.tag(local_tag, acr_ref)
        builder.push(
            acr_ref,
            on_output=lambda line: print(f"    {line}", flush=True),
        )
        report("acr_push", "PASS", ref=acr_ref)
    except Exception as exc:
        report("acr_push", "FAIL", error=str(exc))
        return None

    # 1.5: Create template via v3/v2 API
    print("\n[1.5] Creating template on platform (v3/v2 API)...", flush=True)
    reset_config()

    from serverless_sandbox.transport.auth import create_auth_provider
    from serverless_sandbox.transport.http import HttpClient
    from serverless_sandbox.protocol.template import TemplateProtocol

    config = load_config()
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)
    template_id = None

    try:
        protocol = TemplateProtocol(http_client)
        template_name = f"e2e-python-hello-{ts}"

        # v3: create metadata
        v3_data = await protocol.create_v3(
            template_name, cpu_count=2, memory_mb=2048,
        )
        template_id = v3_data.get("templateID", "")
        build_id = v3_data.get("buildID", "")
        report("template_v3_create", "PASS",
               templateID=template_id, buildID=build_id)

        # v2: trigger build using standard fromImageRegistry (NOT ACR headers).
        # The quick_build_test proved that fromImageRegistry alone works for
        # personal ACR; the X-E2B-Template-* headers are ACR-EE-only.
        from_image_registry = {
            "url": f"https://{acr.registry}",
            "username": acr_temp_user or AK,
            "password": acr_temp_token or SK,
        }
        print(f"    fromImage: {acr_ref}", flush=True)
        print(f"    fromImageRegistry: url={acr.registry} user={acr_temp_user or 'AK'}", flush=True)

        try:
            await protocol.trigger_build_v2(
                template_id, build_id,
                from_image=acr_ref,
                from_image_registry=from_image_registry,
                # No acr_headers — personal ACR uses body-only approach
            )
            report("template_v2_trigger", "PASS")
        except Exception as exc:
            report("template_v2_trigger", "FAIL", error=str(exc))

        # Wait for build (120s in quick test; allow 300s for safety)
        build_success = False
        try:
            elapsed = 0
            last_log_count = 0
            while elapsed < 300:
                status_data = await protocol.get_build_status(
                    template_id, build_id,
                )
                status = status_data.get("status", "building")

                # Fetch and print new build logs
                try:
                    logs = await protocol.get_build_logs(template_id, build_id)
                    for entry in logs[last_log_count:]:
                        lvl = entry.get("level", "info").upper()
                        msg = entry.get("message", "")
                        print(f"    [{lvl}] {msg}", flush=True)
                    last_log_count = len(logs)
                except Exception:
                    pass

                print(f"    Build status: {status} (elapsed {elapsed}s)", flush=True)
                if status == "ready":
                    report("template_build_wait", "PASS")
                    build_success = True
                    break
                elif status == "error":
                    error_msg = status_data.get("error", "Unknown")
                    reason = status_data.get("reason", {})
                    report("template_build_wait", "FAIL",
                           error=f"Build error: {error_msg}",
                           reason=reason,
                           raw_status=status_data)
                    break
                await asyncio.sleep(10)
                elapsed += 10
            else:
                report("template_build_wait", "FAIL",
                       error=f"Timed out after 300s",
                       last_status=status_data)
        except Exception as exc:
            report("template_build_wait", "FAIL", error=str(exc))

    except Exception as exc:
        report("template_creation", "FAIL", error=str(exc))
    finally:
        await http_client.close()

    return template_id


# ======================================================================
# Phase 2: Server Capability Test (ONLY from custom template)
# ======================================================================

async def phase2_server_test(template_id: str) -> None:
    """Test all server capabilities using a sandbox from our custom template."""
    print("\n" + "=" * 60)
    print("PHASE 2: Server Capability Test (Custom Template)")
    print(f"  Template ID: {template_id}")
    print("=" * 60, flush=True)

    reset_config()

    # 2.1: Create sandbox from custom template
    print("\n[2.1] Creating sandbox from custom template...", flush=True)
    sandbox = None
    try:
        sandbox = await Sandbox.create(template=template_id, timeout=300)
        report("sandbox_create", "PASS",
               sandbox_id=sandbox.id, template=template_id)
    except Exception as exc:
        report("sandbox_create", "FAIL", error=str(exc))
        return

    try:
        # 2.2: Start server inside the sandbox.
        # FC custom-image runtime does NOT execute the container CMD.
        # envd takes over as PID 1, so we must start our server manually.
        print("\n[2.2] Starting server inside sandbox via envd shell...", flush=True)

        # Quick check: is anything listening on port 9000?
        try:
            diag = await sandbox.commands.run("python3 -c \"import socket; s=socket.socket(); s.settimeout(1); err=s.connect_ex(('127.0.0.1',9000)); print('port9000=open' if err==0 else f'port9000=closed({err})'); s.close()\"")
            print(f"    Port check: {diag.stdout.strip()}", flush=True)
        except Exception as exc:
            print(f"    Port check failed: {exc}", flush=True)

        # Start the server in the background
        try:
            start_result = await sandbox.commands.run(
                'nohup python3 /app/commands.py > /tmp/server.log 2>&1 & echo "PID=$!"'
            )
            print(f"    Start server: exit={start_result.exit_code} out={start_result.stdout.strip()!r}", flush=True)
        except Exception as exc:
            print(f"    Start server failed: {exc}", flush=True)
            report("server_startup", "FAIL", error=str(exc))

        # Wait for server to become ready
        server_ready = False
        for attempt in range(10):
            await asyncio.sleep(2)
            try:
                check = await sandbox.commands.run("python3 -c \"import socket; s=socket.socket(); s.settimeout(1); err=s.connect_ex(('127.0.0.1',9000)); print('open' if err==0 else 'closed'); s.close()\"")
                if 'open' in check.stdout:
                    server_ready = True
                    print(f"    Server ready after {(attempt+1)*2}s", flush=True)
                    break
                print(f"    Port 9000 not ready yet ({(attempt+1)*2}s)...", flush=True)
            except Exception:
                print(f"    Port check error ({(attempt+1)*2}s)...", flush=True)

        if server_ready:
            report("server_startup", "PASS")
        else:
            # Print server log for debugging
            try:
                log_result = await sandbox.commands.run("cat /tmp/server.log 2>&1 || true")
                print(f"    Server log: {log_result.stdout[:500]}", flush=True)
            except Exception:
                pass
            report("server_startup", "FAIL", error="Server did not start within 20s")

        # Internal verification: test from within the sandbox
        print("\n[2.2b] Internal verification...", flush=True)
        try:
            diag = await sandbox.commands.run(
                'python3 -c "import urllib.request; r=urllib.request.urlopen(\'http://127.0.0.1:9000/commands\'); print(r.read().decode())"'
            )
            print(f"    Internal /commands: exit={diag.exit_code} stdout={diag.stdout.strip()!r}", flush=True)
        except Exception as exc:
            print(f"    Internal /commands failed: {exc}", flush=True)

        # 2.3: Get server URL
        # Bypass sandbox.network.get_url() which checks for 'ports' capability
        # — custom templates created via API fall back to DEFAULT_CAPABILITIES
        # (shell, files, code) which does NOT include 'ports'.
        # Construct the URL directly using the known pattern.
        print("\n[2.3] Getting server URL (direct construction)...", flush=True)
        config = load_config()
        server_url = f"https://9000-{sandbox.id}.{config.domain}"
        access_headers = {}
        if sandbox._envd_token and sandbox._envd_token.token:
            access_headers["X-Access-Token"] = sandbox._envd_token.token
        report("get_url_9000", "PASS", url=server_url)

        # 2.4-2.9: Test server endpoints
        # Helper: make a request with 502 retry (FC gateway can be flaky)
        async def _fetch(
            method: str, url: str, *,
            headers: dict | None = None,
            json_body: dict | None = None,
            params: dict | None = None,
            retries: int = 5,
            backoff: float = 3.0,
        ) -> httpx.Response:
            """HTTP request with 502/503 retry."""
            last_exc: Exception | None = None
            for attempt in range(retries):
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(30.0),
                        follow_redirects=True,
                    ) as c:
                        resp = await c.request(
                            method, url,
                            headers=headers or {},
                            json=json_body,
                            params=params,
                        )
                    if resp.status_code not in (502, 503):
                        return resp
                    print(f"    [retry {attempt+1}/{retries}] HTTP {resp.status_code}", flush=True)
                except Exception as exc:
                    last_exc = exc
                    print(f"    [retry {attempt+1}/{retries}] {exc}", flush=True)
                await asyncio.sleep(backoff * (attempt + 1))
            # Return last response or raise
            if last_exc:
                raise last_exc
            return resp  # type: ignore[possibly-undefined]

        def _diag(resp: httpx.Response) -> None:
            ct = resp.headers.get('content-type', '?')
            raw = resp.text[:300] if resp.text else '(empty)'
            print(f"    HTTP {resp.status_code} | content-type: {ct}", flush=True)
            print(f"    body: {raw}", flush=True)

        req_headers = {**access_headers}

        # 2.4: GET /health
        print("\n[2.4] GET /health...", flush=True)
        try:
            resp = await _fetch("GET", f"{server_url}/health", headers=req_headers)
            _diag(resp)
            body = resp.json()
            health_ok = resp.status_code == 200 and body.get("status") == "ok"
            report("health", "PASS" if health_ok else "FAIL",
                   http_status=resp.status_code, body=body)
        except Exception as exc:
            report("health", "FAIL", error=str(exc))

        # 2.5: GET /commands
        print("\n[2.5] GET /commands...", flush=True)
        try:
            resp = await _fetch("GET", f"{server_url}/commands", headers=req_headers)
            _diag(resp)
            body = resp.json()
            cmd_names = [c["name"] for c in body.get("commands", [])]
            has_hello = "hello" in cmd_names
            report("list_commands", "PASS" if has_hello else "FAIL",
                   http_status=resp.status_code, commands=cmd_names)
        except Exception as exc:
            report("list_commands", "FAIL", error=str(exc))

        # 2.6: POST /commands/hello
        print("\n[2.6] POST /commands/hello...", flush=True)
        try:
            resp = await _fetch(
                "POST", f"{server_url}/commands/hello",
                headers={**req_headers, "Content-Type": "application/json"},
                json_body={"name": "E2E-Test"},
            )
            _diag(resp)
            body = resp.json()
            expected = "Hello, E2E-Test!"
            ok = resp.status_code == 200 and body.get("result") == expected
            report("run_command_hello", "PASS" if ok else "FAIL",
                   http_status=resp.status_code, result=body.get("result"),
                   expected=expected)
        except Exception as exc:
            report("run_command_hello", "FAIL", error=str(exc))

        # 2.7: POST /upload
        print("\n[2.7] POST /upload...", flush=True)
        try:
            test_data = b"e2e-test-payload-XYZ-2026"
            b64_data = base64.b64encode(test_data).decode("ascii")
            resp = await _fetch(
                "POST", f"{server_url}/upload",
                headers={**req_headers, "Content-Type": "application/json"},
                json_body={"path": "/home/user/test_upload.txt",
                           "content_base64": b64_data},
            )
            _diag(resp)
            body = resp.json()
            ok = resp.status_code == 200 and body.get("bytes") == len(test_data)
            report("upload", "PASS" if ok else "FAIL",
                   http_status=resp.status_code, body=body)
        except Exception as exc:
            report("upload", "FAIL", error=str(exc))

        # 2.8: GET /download
        print("\n[2.8] GET /download...", flush=True)
        try:
            resp = await _fetch(
                "GET", f"{server_url}/download",
                headers=req_headers,
                params={"path": "/home/user/test_upload.txt"},
            )
            _diag(resp)
            body = resp.json()
            downloaded = base64.b64decode(body.get("content_base64", ""))
            roundtrip_ok = downloaded == test_data
            report("download", "PASS" if roundtrip_ok else "FAIL",
                   http_status=resp.status_code, roundtrip_ok=roundtrip_ok)
        except Exception as exc:
            report("download", "FAIL", error=str(exc))

        # 2.9: POST /commands/run_script
        print("\n[2.9] POST /commands/run_script...", flush=True)
        try:
            resp = await _fetch(
                "POST", f"{server_url}/commands/run_script",
                headers={**req_headers, "Content-Type": "application/json"},
                json_body={"code": "print(2 + 3)"},
            )
            _diag(resp)
            body = resp.json()
            ok = resp.status_code == 200 and "5" in str(body.get("result", ""))
            report("run_script", "PASS" if ok else "FAIL",
                   http_status=resp.status_code, result=body.get("result"))
        except Exception as exc:
            report("run_script", "FAIL", error=str(exc))

    except Exception as exc:
        report("server_test_unexpected", "FAIL", error=str(exc))
    finally:
        # Cleanup sandbox
        print("\n[2.10] Cleaning up sandbox...", flush=True)
        if sandbox:
            try:
                await sandbox.kill()
                report("cleanup_sandbox", "PASS")
            except Exception as exc:
                report("cleanup_sandbox", "FAIL", error=str(exc))


# ======================================================================
# Phase 3: Cleanup template
# ======================================================================

async def phase3_cleanup(template_id: str | None) -> None:
    if not template_id:
        return
    print("\n" + "=" * 60)
    print("PHASE 3: Cleanup test template")
    print("=" * 60, flush=True)

    reset_config()
    from serverless_sandbox.transport.auth import create_auth_provider
    from serverless_sandbox.transport.http import HttpClient
    from serverless_sandbox.protocol.template import TemplateProtocol

    config = load_config()
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)
    try:
        protocol = TemplateProtocol(http_client)
        await protocol.delete(template_id)
        report("delete_template", "PASS", templateID=template_id)
    except Exception as exc:
        report("delete_template", "FAIL", error=str(exc))
    finally:
        await http_client.close()


# ======================================================================
# Main
# ======================================================================

async def main() -> None:
    print("=" * 60)
    print("  Serverless Sandbox — E2E Custom Template Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Template Dir: {TEMPLATE_DIR}")
    print(f"  ACR: {ACR_REGISTRY}/{ACR_NAMESPACE}/{ACR_REPO}")
    print(f"  ACR EE Instance: {ACREE_INSTANCE_ID or '(not set)'}")
    print("  NO FALLBACK — custom template only")
    print("=" * 60, flush=True)

    # Phase 1
    template_id = await phase1_build_and_push()

    # Phase 2 — ONLY if Phase 1 produced a template
    if template_id:
        build_ok = checks.get("template_build_wait", {}).get("status") == "PASS"
        if build_ok:
            await phase2_server_test(template_id)
        else:
            print("\n⚠️  Template build not ready — skipping server test")
            print("    This is expected if ACR EE is not configured.")
            report("server_test", "SKIP",
                   reason="Template build not ready (ACR EE likely required)")
    else:
        print("\n⚠️  Phase 1 did not produce a template — skipping Phase 2")
        report("server_test", "SKIP", reason="No custom template available")

    # Phase 3
    await phase3_cleanup(template_id)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = len(checks)
    passed = sum(1 for c in checks.values() if c["status"] == "PASS")
    failed = sum(1 for c in checks.values() if c["status"] == "FAIL")
    skipped = sum(1 for c in checks.values() if c["status"] == "SKIP")

    for name, check in checks.items():
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚠️"}.get(check["status"], "?")
        print(f"  {icon} {name}: {check['status']}")

    print(f"\nTotal: {total} | Pass: {passed} | Fail: {failed} | Skip: {skipped}")

    print("\n--- JSON ---")
    print(json.dumps(checks, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
