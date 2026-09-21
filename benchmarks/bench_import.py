"""模块导入时间基准测试。"""
import time

def bench_import():
    modules = [
        "easy_sandbox",
        "easy_sandbox.models",
        "easy_sandbox.transport",
        "easy_sandbox.protocol",
        "easy_sandbox.api",
        "easy_sandbox.agent",
        "easy_sandbox.declarative",
        "easy_sandbox.integrations",
        "easy_sandbox.session",
    ]
    for mod in modules:
        start = time.perf_counter()
        __import__(mod)
        elapsed = time.perf_counter() - start
        print(f"  import {mod}: {elapsed:.3f}s")

if __name__ == "__main__":
    print("=== Import Benchmark ===")
    bench_import()
