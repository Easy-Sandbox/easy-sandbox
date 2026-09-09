#!/usr/bin/env python3
"""Quick test: try different build header/body combinations."""
import asyncio, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from serverless_sandbox.api.docker_builder import ACRConfig, _get_acr_auth_token
from serverless_sandbox.transport.config import load_config, reset_config
from serverless_sandbox.transport.auth import create_auth_provider
from serverless_sandbox.transport.http import HttpClient
from serverless_sandbox.protocol.template import TemplateProtocol

AK = os.environ.get("AccessKey", "")
SK = os.environ.get("AccessSecret", "")
ACREE = os.environ.get("ACREE_INSTANCE_ID", "")
ACR_REG = os.environ.get("ACR_REGISTRY", "registry.cn-hangzhou.aliyuncs.com")
ACR_NS = os.environ.get("ACR_NAMESPACE", "serverless-sandbox-test")
ACR_REPO = os.environ.get("ACR_REPO", "python-hello")

# Reuse the image we already pushed — set ACR_TAG env var to override
ACR_TAG = os.environ.get("ACR_TAG", "latest")
ACR_REF = f"{ACR_REG}/{ACR_NS}/{ACR_REPO}:{ACR_TAG}"

# Get temp credentials
temp = _get_acr_auth_token(AK, SK, "cn-hangzhou", instance_id=ACREE or None)
TMP_USER = temp.get("tempUserName", "")
TMP_TOKEN = temp.get("authorizationToken", "")
print(f"Temp user: {TMP_USER}")

# Strategies to test
STRATEGIES = [
    {
        "name": "no-headers (fromImageRegistry only)",
        "acr_headers": None,
        "from_image_registry": {
            "url": f"https://{ACR_REG}",
            "username": TMP_USER,
            "password": TMP_TOKEN,
        },
    },
    {
        "name": "no-dest-ref (builder, acr type, no Dest-Image-Ref)",
        "acr_headers": {
            "X-E2B-Template-Build-Mode": "builder",
            "X-E2B-Template-Source-Registry-Type": "acr",
            "X-E2B-Template-Source-Username": TMP_USER,
            "X-E2B-Template-Source-Password": TMP_TOKEN,
        },
        "from_image_registry": None,
    },
    {
        "name": "direct + no-dest-ref",
        "acr_headers": {
            "X-E2B-Template-Build-Mode": "direct",
            "X-E2B-Template-Source-Registry-Type": "acr",
            "X-E2B-Template-Source-Username": TMP_USER,
            "X-E2B-Template-Source-Password": TMP_TOKEN,
        },
        "from_image_registry": None,
    },
]


async def try_strategy(proto: TemplateProtocol, strategy: dict, ts: int) -> bool:
    name = strategy["name"]
    print(f"\n{'='*60}\nStrategy: {name}\n{'='*60}")
    
    tpl_name = f"qbt-{ts}-{name[:8].replace(' ', '_')}"
    
    # v3 create
    v3 = await proto.create_v3(tpl_name, cpu_count=2, memory_mb=2048)
    tid = v3["templateID"]
    bid = v3["buildID"]
    print(f"  Created: templateID={tid}, buildID={bid}")
    
    # v2 trigger
    try:
        await proto.trigger_build_v2(
            tid, bid,
            from_image=ACR_REF,
            from_image_registry=strategy.get("from_image_registry"),
            acr_headers=strategy.get("acr_headers"),
        )
        print("  Trigger: OK")
    except Exception as e:
        print(f"  Trigger FAILED: {e}")
        await proto.delete(tid)
        return False
    
    # Poll (120s max)
    elapsed = 0
    last_logs = 0
    while elapsed < 120:
        sd = await proto.get_build_status(tid, bid)
        st = sd.get("status", "building")
        
        try:
            logs = await proto.get_build_logs(tid, bid)
            for entry in logs[last_logs:]:
                print(f"  [{entry.get('level','?').upper()}] {entry.get('message','')}")
            last_logs = len(logs)
        except:
            pass
        
        print(f"  Status: {st} ({elapsed}s)")
        if st == "ready":
            print(f"  ✅ BUILD SUCCEEDED! templateID={tid}")
            await proto.delete(tid)
            return True
        elif st == "error":
            reason = sd.get("reason", {}).get("message", sd.get("error", "?"))
            print(f"  ❌ Build error: {reason}")
            # Print full log entries
            entries = sd.get("logEntries", [])
            for e in entries:
                if e.get("level") == "error":
                    print(f"  ERROR DETAIL: {e.get('message', '')[:500]}")
            await proto.delete(tid)
            return False
        
        await asyncio.sleep(10)
        elapsed += 10
    
    print(f"  ⏱ Timed out after 120s (still building)")
    await proto.delete(tid)
    return False


async def main():
    reset_config()
    config = load_config()
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http = HttpClient(config, auth)
    ts = int(time.time())
    
    try:
        proto = TemplateProtocol(http)
        for strategy in STRATEGIES:
            success = await try_strategy(proto, strategy, ts)
            if success:
                print(f"\n🎉 Strategy '{strategy['name']}' WORKED!")
                return
            print()
        
        print("\n❌ All strategies failed.")
    finally:
        await http.close()

asyncio.run(main())
