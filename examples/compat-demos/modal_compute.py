"""Modal 风格计算 Demo / Modal-Style Compute Demo

API 风格: Modal（声明式）
Style: Modal (declarative)

场景 / Scenario:
    用 @sandbox 装饰器在远程沙箱执行计算密集任务
    Use @sandbox decorator for compute-intensive tasks in remote sandbox

工作流 / Workflow:
    @sandbox(packages=[...]) + def func() → 直接调用 → 自动创建沙箱 → 执行 → 返回结果
    @sandbox(packages=[...]) + def func() → direct call → auto sandbox → execute → return
"""

import os
import time

# 确保 API Key 可用 / Ensure API key is available
API_KEY = os.environ.get("E2B_API_KEY", "")

from easy_sandbox.declarative import sandbox


# ── 示例 1: 蒙特卡洛法计算 π / Monte Carlo Pi estimation ──────────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["numpy", "scipy"],
    api_key=API_KEY,
    timeout=120,
)
def monte_carlo_pi(n_samples: int) -> dict:
    """在远程沙箱中用蒙特卡洛法估算 π / Estimate π using Monte Carlo in sandbox."""
    import numpy as np

    rng = np.random.default_rng(42)
    points = rng.random((n_samples, 2))
    inside = np.sum(np.linalg.norm(points, axis=1) <= 1.0)
    pi_estimate = 4.0 * inside / n_samples
    error = abs(pi_estimate - np.pi)

    return {
        "pi_estimate": float(pi_estimate),
        "samples": n_samples,
        "points_inside": int(inside),
        "absolute_error": float(error),
        "relative_error_pct": float(error / np.pi * 100),
    }


# ── 示例 2: 矩阵乘法性能测试 / Matrix multiplication benchmark ──────────
@sandbox(
    template="code-interpreter-v1",
    packages=["numpy"],
    api_key=API_KEY,
    timeout=120,
)
def matrix_multiply(size: int) -> dict:
    """在远程沙箱中测试矩阵乘法性能 / Benchmark matrix multiplication in sandbox."""
    import numpy as np
    import time as _time

    rng = np.random.default_rng(123)
    A = rng.random((size, size))
    B = rng.random((size, size))

    start = _time.perf_counter()
    C = A @ B
    elapsed = _time.perf_counter() - start

    return {
        "matrix_size": size,
        "computation_time_sec": round(elapsed, 4),
        "result_trace": float(np.trace(C)),
        "result_max": float(np.max(C)),
        "gflops": round((2 * size**3) / elapsed / 1e9, 2),
    }


# ── 示例 3: 统计分布拟合 / Statistical distribution fitting ──────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["numpy", "scipy"],
    api_key=API_KEY,
    timeout=120,
)
def fit_distribution(n_samples: int, distribution: str) -> dict:
    """在远程沙箱中生成随机数据并拟合分布 / Generate data and fit distribution."""
    import numpy as np
    from scipy import stats

    rng = np.random.default_rng(99)

    # 生成数据 / Generate data
    if distribution == "normal":
        data = rng.normal(loc=50, scale=10, size=n_samples)
    elif distribution == "exponential":
        data = rng.exponential(scale=5, size=n_samples)
    elif distribution == "uniform":
        data = rng.uniform(low=0, high=100, size=n_samples)
    else:
        data = rng.standard_normal(n_samples)

    # 拟合正态分布 / Fit normal distribution
    mu, sigma = stats.norm.fit(data)
    # K-S 检验 / K-S test
    ks_stat, ks_pvalue = stats.kstest(data, "norm", args=(mu, sigma))

    return {
        "distribution": distribution,
        "n_samples": n_samples,
        "fit_mean": round(float(mu), 4),
        "fit_std": round(float(sigma), 4),
        "data_min": round(float(np.min(data)), 4),
        "data_max": round(float(np.max(data)), 4),
        "ks_statistic": round(float(ks_stat), 6),
        "ks_pvalue": round(float(ks_pvalue), 6),
        "normality_pass": ks_pvalue > 0.05,
    }


def main() -> None:
    """运行所有 Modal 风格计算示例 / Run all Modal-style compute demos."""
    print("=" * 60)
    print("  Modal 风格计算 Demo / Modal-Style Compute Demo")
    print("  使用 @sandbox 装饰器 — 函数自动在远程沙箱中执行")
    print("  Using @sandbox decorator — functions run in remote sandbox")
    print("=" * 60)

    # ── 示例 1: 蒙特卡洛 π ────────────────────────────────────────────
    print("\n── 示例 1: 蒙特卡洛法估算 π / Monte Carlo Pi ──")
    try:
        start = time.perf_counter()
        result = monte_carlo_pi(10_000_000)
        elapsed = time.perf_counter() - start

        print(f"  π ≈ {result['pi_estimate']}")
        print(f"  采样点数 / Samples     : {result['samples']:,}")
        print(f"  圆内点数 / Inside circle: {result['points_inside']:,}")
        print(f"  绝对误差 / Abs error   : {result['absolute_error']:.6f}")
        print(f"  相对误差 / Rel error   : {result['relative_error_pct']:.4f}%")
        print(f"  总耗时 / Total time    : {elapsed:.2f}s (含沙箱创建)")
    except Exception as e:
        print(f"  ✗ 执行失败 / Failed: {e}")

    # ── 示例 2: 矩阵乘法 ─────────────────────────────────────────────
    print("\n── 示例 2: 矩阵乘法性能 / Matrix Multiplication ──")
    sizes = [500, 1000]
    for size in sizes:
        try:
            start = time.perf_counter()
            result = matrix_multiply(size)
            elapsed = time.perf_counter() - start

            print(f"  [{size}x{size}] 计算耗时={result['computation_time_sec']}s, "
                  f"GFLOPS={result['gflops']}, "
                  f"trace={result['result_trace']:.2f}, "
                  f"总耗时={elapsed:.2f}s")
        except Exception as e:
            print(f"  [{size}x{size}] ✗ 失败: {e}")

    # ── 示例 3: 分布拟合 ─────────────────────────────────────────────
    print("\n── 示例 3: 统计分布拟合 / Distribution Fitting ──")
    distributions = ["normal", "exponential", "uniform"]
    for dist_name in distributions:
        try:
            result = fit_distribution(50_000, dist_name)
            normality = "✓ 通过" if result["normality_pass"] else "✗ 不通过"
            print(f"  [{dist_name:>12s}] μ={result['fit_mean']:>8.4f}, "
                  f"σ={result['fit_std']:>8.4f}, "
                  f"KS={result['ks_statistic']:.6f}, "
                  f"正态检验: {normality}")
        except Exception as e:
            print(f"  [{dist_name:>12s}] ✗ 失败: {e}")

    print("\n✓ 所有计算示例完成 / All compute demos completed")


if __name__ == "__main__":
    main()
