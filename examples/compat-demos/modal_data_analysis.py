"""Modal 风格数据分析 Demo / Modal-Style Data Analysis Demo

API 风格: Modal（声明式）
Style: Modal (declarative)

场景 / Scenario:
    与 E2B 数据分析 Demo 相同的场景，但使用 @sandbox 装饰器
    Same scenario as E2B data analysis demo, but using @sandbox decorator

工作流 / Workflow:
    @sandbox(packages=["pandas"]) + def analyze(csv_data) → 直接调用 → 返回分析结果
    @sandbox(packages=["pandas"]) + def analyze(csv_data) → direct call → return results

对比 E2B 风格:
    - E2B: 需要手动 create → install → write → run → read → kill
    - Modal: 一个装饰器 + 一次函数调用，一切自动完成
"""

import os

# 确保 API Key 可用 / Ensure API key is available
API_KEY = os.environ.get("E2B_API_KEY", "")

from serverless_sandbox.declarative import sandbox

# ── 内嵌销售数据（与 E2B Demo 相同）/ Same CSV data as E2B demo ──────────
SALES_CSV = """\
date,product,quantity,amount
2024-01-01,Widget A,10,1500.00
2024-01-02,Widget B,25,3750.00
2024-01-03,Widget A,15,2250.00
2024-01-04,Widget C,8,2400.00
2024-01-05,Widget B,30,4500.00
2024-01-06,Widget A,20,3000.00
2024-01-07,Widget C,12,3600.00
2024-01-08,Widget B,18,2700.00
2024-01-09,Widget A,22,3300.00
2024-01-10,Widget C,5,1500.00
2024-01-11,Widget B,35,5250.00
2024-01-12,Widget A,28,4200.00
2024-01-13,Widget C,10,3000.00
2024-01-14,Widget B,20,3000.00
2024-01-15,Widget A,16,2400.00
"""


# ── 示例 1: 完整数据分析 / Full data analysis ─────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["pandas"],
    api_key=API_KEY,
    timeout=120,
)
def analyze_sales(csv_data: str) -> dict:
    """在远程沙箱中分析销售数据 / Analyze sales data in remote sandbox.

    注意: 函数体内的代码在远程沙箱中执行，import 必须在函数内部。
    Note: Code inside runs remotely; imports must be inside the function.
    """
    import pandas as pd
    from io import StringIO

    df = pd.read_csv(StringIO(csv_data))

    # 总销售额 / Total revenue
    total_revenue = float(df["amount"].sum())

    # 按产品汇总 / Group by product
    product_summary = df.groupby("product").agg(
        total_qty=("quantity", "sum"),
        total_revenue=("amount", "sum"),
        avg_amount=("amount", "mean"),
        order_count=("product", "count"),
    ).reset_index()

    # 最畅销产品 / Best-selling product
    top_product = product_summary.loc[
        product_summary["total_revenue"].idxmax()
    ]

    # 按日期汇总趋势 / Daily trend
    daily_revenue = df.groupby("date")["amount"].sum()

    return {
        "total_records": len(df),
        "total_revenue": total_revenue,
        "avg_order_value": round(float(df["amount"].mean()), 2),
        "top_product": top_product["product"],
        "top_product_revenue": float(top_product["total_revenue"]),
        "product_breakdown": product_summary.to_dict(orient="records"),
        "daily_avg_revenue": round(float(daily_revenue.mean()), 2),
        "peak_day": daily_revenue.idxmax(),
        "peak_day_revenue": float(daily_revenue.max()),
    }


# ── 示例 2: 数据质量检查 / Data quality check ────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["pandas"],
    api_key=API_KEY,
    timeout=60,
)
def check_data_quality(csv_data: str) -> dict:
    """在远程沙箱中检查数据质量 / Check data quality in remote sandbox."""
    import pandas as pd
    from io import StringIO

    df = pd.read_csv(StringIO(csv_data))

    quality = {
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "column_names": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "null_counts": df.isnull().sum().to_dict(),
        "has_nulls": bool(df.isnull().any().any()),
        "duplicate_rows": int(df.duplicated().sum()),
        "unique_products": int(df["product"].nunique()),
        "date_range": {
            "min": str(df["date"].min()),
            "max": str(df["date"].max()),
        },
        "amount_stats": {
            "min": float(df["amount"].min()),
            "max": float(df["amount"].max()),
            "mean": round(float(df["amount"].mean()), 2),
            "median": float(df["amount"].median()),
        },
    }
    return quality


# ── 示例 3: 产品排名 / Product ranking ────────────────────────────────────
@sandbox(
    template="code-interpreter-v1",
    packages=["pandas"],
    api_key=API_KEY,
    timeout=60,
)
def rank_products(csv_data: str, metric: str = "amount") -> list:
    """在远程沙箱中按指标对产品排名 / Rank products by metric in sandbox."""
    import pandas as pd
    from io import StringIO

    df = pd.read_csv(StringIO(csv_data))
    ranking = (
        df.groupby("product")[metric]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    ranking["rank"] = range(1, len(ranking) + 1)
    return ranking.to_dict(orient="records")


def main() -> None:
    """运行所有 Modal 风格数据分析示例 / Run all Modal-style analysis demos."""
    print("=" * 60)
    print("  Modal 风格数据分析 Demo / Modal-Style Data Analysis")
    print("  使用 @sandbox 装饰器 — 像本地函数一样调用")
    print("  Using @sandbox decorator — call like local functions")
    print("=" * 60)

    # ── 示例 1: 完整数据分析 ──────────────────────────────────────────
    print("\n── 示例 1: 完整销售分析 / Full Sales Analysis ──")
    try:
        result = analyze_sales(SALES_CSV)
        print(f"  总记录数 / Total records : {result['total_records']}")
        print(f"  总收入 / Total revenue   : ¥{result['total_revenue']:,.2f}")
        print(f"  平均订单 / Avg order     : ¥{result['avg_order_value']:,.2f}")
        print(f"  日均收入 / Daily avg     : ¥{result['daily_avg_revenue']:,.2f}")
        print(f"  🏆 最畅销 / Top product  : {result['top_product']} "
              f"(¥{result['top_product_revenue']:,.2f})")
        print(f"  📈 峰值日 / Peak day     : {result['peak_day']} "
              f"(¥{result['peak_day_revenue']:,.2f})")
        print()
        print("  产品明细 / Product breakdown:")
        for p in result["product_breakdown"]:
            print(f"    {p['product']:<12s} 数量={p['total_qty']:>5.0f}  "
                  f"收入=¥{p['total_revenue']:>10,.2f}")
    except Exception as e:
        print(f"  ✗ 执行失败 / Failed: {e}")

    # ── 示例 2: 数据质量检查 ──────────────────────────────────────────
    print("\n── 示例 2: 数据质量检查 / Data Quality Check ──")
    try:
        quality = check_data_quality(SALES_CSV)
        print(f"  行数 / Rows        : {quality['total_rows']}")
        print(f"  列数 / Columns     : {quality['total_columns']}")
        print(f"  空值 / Has nulls   : {'是' if quality['has_nulls'] else '否'}")
        print(f"  重复行 / Duplicates : {quality['duplicate_rows']}")
        print(f"  产品种类 / Products: {quality['unique_products']}")
        print(f"  日期范围 / Date range: "
              f"{quality['date_range']['min']} ~ {quality['date_range']['max']}")
        stats = quality["amount_stats"]
        print(f"  金额统计 / Amount  : min=¥{stats['min']}, max=¥{stats['max']}, "
              f"avg=¥{stats['mean']}, median=¥{stats['median']}")
    except Exception as e:
        print(f"  ✗ 执行失败 / Failed: {e}")

    # ── 示例 3: 产品排名 ─────────────────────────────────────────────
    print("\n── 示例 3: 产品排名 / Product Ranking ──")
    try:
        # 按销售额排名 / Rank by revenue
        ranking = rank_products(SALES_CSV, metric="amount")
        print("  按销售额排名 / By revenue:")
        for item in ranking:
            print(f"    #{item['rank']} {item['product']:<12s} ¥{item['amount']:,.2f}")

        # 按数量排名 / Rank by quantity
        ranking = rank_products(SALES_CSV, metric="quantity")
        print("  按销售量排名 / By quantity:")
        for item in ranking:
            print(f"    #{item['rank']} {item['product']:<12s} {item['quantity']} 件")
    except Exception as e:
        print(f"  ✗ 执行失败 / Failed: {e}")

    print("\n✓ 所有分析示例完成 / All analysis demos completed")


if __name__ == "__main__":
    main()
