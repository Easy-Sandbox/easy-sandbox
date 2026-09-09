"""模块导入时间基准测试。"""
import time

def bench_import():
    modules = [
        "serverless_sandbox",
        "serverless_sandbox.models",
        "serverless_sandbox.transport",
        "serverless_sandbox.protocol",
        "serverless_sandbox.api",
        "serverless_sandbox.agent",
        "serverless_sandbox.declarative",
        "serverless_sandbox.integrations",
        "serverless_sandbox.session",
    ]
    for mod in modules:
        start = time.perf_counter()
        __import__(mod)
        elapsed = time.perf_counter() - start
        print(f"  import {mod}: {elapsed:.3f}s")

if __name__ == "__main__":
    print("=== Import Benchmark ===")
    bench_import()
