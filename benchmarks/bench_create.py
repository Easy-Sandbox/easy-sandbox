"""沙箱创建性能基准。目标：P95 < 3s"""
import asyncio
import os
import time
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

async def bench_create():
    """测试沙箱创建时间。"""
    from easy_sandbox.transport.config import TransportConfig
    from easy_sandbox.transport.auth import ApiKeyAuth
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.protocol.sandbox import SandboxProtocol
    from easy_sandbox.models.sandbox import SandboxConfig

    api_key = os.environ.get("E2B_API_KEY", "")
    if not api_key:
        print("ERROR: E2B_API_KEY environment variable is required.")
        print("  export E2B_API_KEY=e2b_your_api_key_here")
        sys.exit(1)
    api_url = os.environ.get("E2B_API_URL", "https://api.cn-hangzhou.e2b.fc.aliyuncs.com")
    domain = os.environ.get("E2B_DOMAIN", "cn-hangzhou.e2b.fc.aliyuncs.com")
    
    config = TransportConfig(api_key=api_key, api_url=api_url, domain=domain)
    auth = ApiKeyAuth(api_key=api_key)
    http = HttpClient(config=config, auth=auth)
    proto = SandboxProtocol(http_client=http)
    
    sandbox_config = SandboxConfig(template="base", timeout=60, env_vars={}, metadata={})
    
    times = []
    sandbox_ids = []
    
    for i in range(3):
        start = time.perf_counter()
        result = await proto.create(config=sandbox_config)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        sid = result.sandbox_id
        sandbox_ids.append(sid)
        print(f"  Create #{i+1}: {elapsed:.3f}s (id={sid[:20]}...)")
    
    # Cleanup
    for sid in sandbox_ids:
        try:
            await proto.kill(sid)
        except Exception:
            pass
    
    await http.close()
    
    avg = sum(times) / len(times)
    p95 = sorted(times)[int(len(times) * 0.95)]
    print(f"\nCreate sandbox: avg={avg:.3f}s, p95={p95:.3f}s (target: <3.0s)")

if __name__ == "__main__":
    print("=== Sandbox Create Benchmark ===")
    asyncio.run(bench_create())
