"""E2B vs Modal 风格对比 Demo / E2B vs Modal Style Comparison Demo

本文件在一个文件中展示同一任务用两种 API 风格的实现，
让用户直观对比 E2B（命令式）和 Modal（声明式）的差异。

This file demonstrates the same task implemented in both API styles,
allowing users to directly compare E2B (imperative) vs Modal (declarative).

对比任务 / Comparison tasks:
  1. 斐波那契数列计算 / Fibonacci sequence
  2. 列表排序与统计 / List sorting and statistics
"""

import asyncio
import os
import time

API_KEY = os.environ.get("E2B_API_KEY", "")

from serverless_sandbox import Sandbox, SandboxError
from serverless_sandbox.declarative import sandbox


# ═══════════════════════════════════════════════════════════════════════════
#  任务 1: 斐波那契数列 / Task 1: Fibonacci Sequence
# ═══════════════════════════════════════════════════════════════════════════


# ── E2B 风格 / E2B Style ─────────────────────────────────────────────────
async def e2b_fibonacci(n: int) -> list[int]:
    """E2B 风格: 手动创建沙箱 → 写代码 → 执行 → 解析输出。
    E2B style: manually create sandbox → write code → execute → parse output.
    """
    async with await Sandbox.create(
        template="base",
        api_key=API_KEY,
        timeout=60,
    ) as sandbox:
        # 需要手动编写代码字符串、上传、执行、解析
        code = f"""\
import json
def fib(n):
    if n <= 0:
        return []
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]

print(json.dumps(fib({n})))
"""
        await sandbox.files.write("/app/fib.py", code)
        result = await sandbox.commands.run("python3 /app/fib.py")

        if not result.success:
            raise RuntimeError(f"执行失败: {result.stderr}")

        import json
        return json.loads(result.stdout.strip())


# ── Modal 风格 / Modal Style ─────────────────────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    api_key=API_KEY,
    timeout=60,
)
def modal_fibonacci(n: int) -> list:
    """Modal 风格: 像写本地函数一样，装饰器处理一切。
    Modal style: write like a local function, decorator handles everything.
    """
    if n <= 0:
        return []
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]


# ═══════════════════════════════════════════════════════════════════════════
#  任务 2: 列表排序与统计 / Task 2: Sorting & Statistics
# ═══════════════════════════════════════════════════════════════════════════


# ── E2B 风格 / E2B Style ─────────────────────────────────────────────────
async def e2b_sort_and_stats(numbers: list[float]) -> dict:
    """E2B 风格: 传数据到沙箱 → 安装 numpy → 计算统计 → 解析结果。
    E2B style: send data → install numpy → compute stats → parse result.
    """
    import json

    async with await Sandbox.create(
        template="base",
        api_key=API_KEY,
        timeout=120,
    ) as sandbox:
        # 1. 安装 numpy
        await sandbox.commands.run("pip install numpy --quiet", timeout=60)

        # 2. 写入数据和脚本
        data_json = json.dumps(numbers)
        code = f"""\
import json
import numpy as np

data = np.array(json.loads('{data_json}'))
sorted_data = np.sort(data).tolist()

result = {{
    "sorted": sorted_data,
    "mean": float(np.mean(data)),
    "median": float(np.median(data)),
    "std": float(np.std(data)),
    "min": float(np.min(data)),
    "max": float(np.max(data)),
    "count": len(data),
}}
print(json.dumps(result))
"""
        await sandbox.files.write("/app/stats.py", code)

        # 3. 执行
        result = await sandbox.commands.run("python3 /app/stats.py")
        if not result.success:
            raise RuntimeError(f"执行失败: {result.stderr}")

        return json.loads(result.stdout.strip())


# ── Modal 风格 / Modal Style ─────────────────────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["numpy"],
    api_key=API_KEY,
    timeout=120,
)
def modal_sort_and_stats(numbers: list) -> dict:
    """Modal 风格: 直接写逻辑，数据自动序列化传输。
    Modal style: write logic directly, data auto-serialized.
    """
    import numpy as np

    data = np.array(numbers)
    sorted_data = np.sort(data).tolist()

    return {
        "sorted": sorted_data,
        "mean": float(np.mean(data)),
        "median": float(np.median(data)),
        "std": float(np.std(data)),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "count": len(data),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  运行对比 / Run Comparison
# ═══════════════════════════════════════════════════════════════════════════


async def main() -> None:
    """运行 E2B vs Modal 风格对比 / Run E2B vs Modal comparison."""
    print("=" * 65)
    print("  E2B vs Modal 风格对比 Demo")
    print("  E2B vs Modal Style Comparison Demo")
    print("=" * 65)

    # ── 对比 1: 斐波那契数列 ──────────────────────────────────────────
    print("\n" + "─" * 65)
    print("  任务 1: 斐波那契数列 (n=20) / Task 1: Fibonacci (n=20)")
    print("─" * 65)

    # E2B 风格
    print("\n  【E2B 风格 / E2B Style】")
    print("  代码模式: Sandbox.create() → files.write() → commands.run() → 解析 stdout")
    try:
        start = time.perf_counter()
        e2b_result = await e2b_fibonacci(20)
        e2b_time = time.perf_counter() - start
        print(f"  结果: {e2b_result}")
        print(f"  耗时: {e2b_time:.2f}s")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        e2b_result = None
        e2b_time = 0

    # Modal 风格
    print("\n  【Modal 风格 / Modal Style】")
    print("  代码模式: @sandbox() + def func() → 直接调用")
    try:
        start = time.perf_counter()
        modal_result = modal_fibonacci(20)
        modal_time = time.perf_counter() - start
        print(f"  结果: {modal_result}")
        print(f"  耗时: {modal_time:.2f}s")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        modal_result = None
        modal_time = 0

    # 对比结果
    if e2b_result and modal_result:
        match = e2b_result == modal_result
        print(f"\n  ✓ 结果一致: {match}")

    # ── 对比 2: 排序与统计 ────────────────────────────────────────────
    print("\n" + "─" * 65)
    print("  任务 2: 排序与统计 / Task 2: Sort & Statistics")
    print("─" * 65)

    test_data = [42.5, 17.3, 88.1, 3.7, 56.9, 71.2, 25.6, 94.0, 8.4, 63.8]
    print(f"\n  输入数据: {test_data}")

    # E2B 风格
    print("\n  【E2B 风格 / E2B Style】")
    print("  代码模式: create → pip install → files.write(data+code) → run → parse")
    try:
        start = time.perf_counter()
        e2b_stats = await e2b_sort_and_stats(test_data)
        e2b_time = time.perf_counter() - start
        print(f"  排序: {e2b_stats['sorted']}")
        print(f"  均值={e2b_stats['mean']:.2f}, 中位={e2b_stats['median']:.2f}, "
              f"标准差={e2b_stats['std']:.2f}")
        print(f"  耗时: {e2b_time:.2f}s")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        e2b_stats = None

    # Modal 风格
    print("\n  【Modal 风格 / Modal Style】")
    print("  代码模式: @sandbox(packages=['numpy']) + def func(numbers) → 调用")
    try:
        start = time.perf_counter()
        modal_stats = modal_sort_and_stats(test_data)
        modal_time = time.perf_counter() - start
        print(f"  排序: {modal_stats['sorted']}")
        print(f"  均值={modal_stats['mean']:.2f}, 中位={modal_stats['median']:.2f}, "
              f"标准差={modal_stats['std']:.2f}")
        print(f"  耗时: {modal_time:.2f}s")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        modal_stats = None

    # ── 总结对比 / Summary ────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  风格对比总结 / Style Comparison Summary")
    print("=" * 65)
    print("""
  ┌──────────────────┬─────────────────────────────────────────┐
  │                  │  E2B 风格 (命令式)                       │
  ├──────────────────┼─────────────────────────────────────────┤
  │ 创建沙箱          │  Sandbox.create(template=...)           │
  │ 安装依赖          │  commands.run("pip install ...")        │
  │ 传输数据          │  files.write() / 嵌入代码字符串          │
  │ 执行代码          │  commands.run("python3 script.py")      │
  │ 获取结果          │  解析 result.stdout / files.read()      │
  │ 清理资源          │  sandbox.kill() / async with            │
  │ 适用场景          │  复杂工作流、多步骤任务、需要精细控制      │
  ├──────────────────┼─────────────────────────────────────────┤
  │                  │  Modal 风格 (声明式)                     │
  ├──────────────────┼─────────────────────────────────────────┤
  │ 创建沙箱          │  自动（装饰器内部处理）                   │
  │ 安装依赖          │  packages=["numpy", ...]               │
  │ 传输数据          │  函数参数自动序列化                       │
  │ 执行代码          │  直接调用函数                            │
  │ 获取结果          │  函数返回值自动反序列化                    │
  │ 清理资源          │  自动（装饰器内部处理）                   │
  │ 适用场景          │  单函数计算、数据处理、快速原型             │
  └──────────────────┴─────────────────────────────────────────┘
""")
    print("✓ 对比 Demo 完成 / Comparison demo completed")


if __name__ == "__main__":
    asyncio.run(main())
