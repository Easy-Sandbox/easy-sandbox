"""CLI 启动时间基准测试。目标：< 200ms"""
import time
import subprocess

def bench_cli_help():
    """测试 ebx --help 启动时间。"""
    times = []
    for _ in range(5):
        start = time.perf_counter()
        subprocess.run(
            ["python3", "-m", "easy_sandbox.cli.main", "--help"],
            capture_output=True, cwd="/Users/anycodes/Documents/Qoder/2026-09-01/chat-1"
        )
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    avg = sum(times) / len(times)
    p95 = sorted(times)[int(len(times) * 0.95)]
    print(f"CLI --help startup: avg={avg:.3f}s, p95={p95:.3f}s (target: <0.2s)")
    return avg, p95

def bench_cli_subcommand():
    """测试子命令启动时间。"""
    commands = [
        ["sandbox", "--help"],
        ["template", "--help"],
        ["session", "--help"],
        ["mcp", "--help"],
        ["skill", "--help"],
    ]
    for cmd in commands:
        start = time.perf_counter()
        subprocess.run(
            ["python3", "-m", "easy_sandbox.cli.main"] + cmd,
            capture_output=True, cwd="/Users/anycodes/Documents/Qoder/2026-09-01/chat-1"
        )
        elapsed = time.perf_counter() - start
        print(f"  ebx {' '.join(cmd)}: {elapsed:.3f}s")

if __name__ == "__main__":
    print("=== CLI Startup Benchmark ===")
    bench_cli_help()
    print()
    bench_cli_subcommand()
