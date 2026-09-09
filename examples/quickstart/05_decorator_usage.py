"""@sandbox 装饰器示例 / Declarative @sandbox Decorator

演示使用 @sandbox 装饰器将普通函数声明式地在远程沙箱中执行。
Shows how to use the @sandbox decorator for declarative remote execution.

需要安装: pip install serverless-sandbox[declarative]

工作流程:
  1. 创建远程沙箱
  2. 安装指定的 packages
  3. 序列化函数和参数 → 上传到沙箱
  4. 在沙箱中执行函数
  5. 反序列化结果返回本地
  6. 自动销毁沙箱
"""

import os

# 确保 API Key 在装饰器生效前可用
# @sandbox 装饰器会使用 api_key 参数或环境变量
API_KEY = os.environ.get("E2B_API_KEY", "")

# ── 从正确的路径导入装饰器 ────────────────────────────────────────────
from serverless_sandbox.declarative import sandbox


# ── 示例 1: 基础用法 — 蒙特卡洛法计算 π ──────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["numpy"],           # 在沙箱中自动 pip install numpy
    api_key=API_KEY,
)
def compute_pi(n: int) -> float:
    """在远程沙箱中使用蒙特卡洛方法计算 π 值。"""
    import numpy as np

    rng = np.random.default_rng(42)
    points = rng.random((n, 2))
    inside = np.sum(np.linalg.norm(points - 0.5, axis=1) <= 0.5)
    return float(4 * inside / n)


# ── 示例 2: 数据处理 — 返回结构化结果 ────────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["pandas"],
    api_key=API_KEY,
)
def analyze_data(records: list[dict]) -> dict:
    """在远程沙箱中用 pandas 分析数据并返回摘要。"""
    import pandas as pd

    df = pd.DataFrame(records)
    summary = {
        "count": len(df),
        "columns": list(df.columns),
        "stats": df.describe().to_dict(),
    }
    return summary


# ── 示例 3: 指定序列化方式 ───────────────────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    serializer="json",            # 可选: json / pickle / msgpack
    timeout=120,                  # 沙箱超时 120 秒
    api_key=API_KEY,
)
def fibonacci(n: int) -> list[int]:
    """在远程沙箱中计算斐波那契数列。"""
    if n <= 0:
        return []
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]


# ── 示例 4: 带环境变量 ──────────────────────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    envs={"APP_MODE": "sandbox-demo"},
    api_key=API_KEY,
)
def check_env() -> dict:
    """读取沙箱中的环境变量。"""
    import os
    return {
        "APP_MODE": os.environ.get("APP_MODE", "unknown"),
        "HOME": os.environ.get("HOME", "unknown"),
        "PATH": os.environ.get("PATH", "unknown")[:80] + "...",
    }


def main() -> None:
    """运行所有示例。

    注意: @sandbox 装饰的同步函数可以直接调用（内部自动处理 asyncio.run）。
    """
    print("=" * 60)
    print("@sandbox 装饰器示例 / Declarative Execution Demo")
    print("=" * 60)

    # 示例 1: 计算 π
    print("\n── 示例 1: 蒙特卡洛法计算 π ──")
    try:
        pi_value = compute_pi(1_000_000)
        print(f"π ≈ {pi_value}")
        print(f"误差: {abs(pi_value - 3.141592653589793):.6f}")
    except Exception as e:
        print(f"执行失败: {e}")

    # 示例 2: 数据分析
    print("\n── 示例 2: 数据分析 ──")
    try:
        records = [
            {"name": "Alice", "age": 30, "score": 95},
            {"name": "Bob", "age": 25, "score": 87},
            {"name": "Charlie", "age": 35, "score": 92},
            {"name": "Diana", "age": 28, "score": 88},
        ]
        result = analyze_data(records)
        print(f"  行数: {result['count']}")
        print(f"  列名: {result['columns']}")
    except Exception as e:
        print(f"执行失败: {e}")

    # 示例 3: 斐波那契数列
    print("\n── 示例 3: 斐波那契数列 ──")
    try:
        seq = fibonacci(15)
        print(f"  前 15 项: {seq}")
    except Exception as e:
        print(f"执行失败: {e}")

    # 示例 4: 环境变量
    print("\n── 示例 4: 环境变量 ──")
    try:
        env_info = check_env()
        for k, v in env_info.items():
            print(f"  {k} = {v}")
    except Exception as e:
        print(f"执行失败: {e}")

    print("\n✓ 所有示例完成")


if __name__ == "__main__":
    main()
