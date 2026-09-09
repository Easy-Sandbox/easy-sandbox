"""E2B 风格数据分析 Demo / E2B-Style Data Analysis Demo

API 风格: E2B（命令式）
Style: E2B (imperative)

场景 / Scenario:
    上传 CSV 销售数据 → 用 pandas 分析 → 生成统计报告 → 下载结果
    Upload CSV sales data → analyze with pandas → generate report → download results

工作流 / Workflow:
    Sandbox.create() → commands.run() → files.write() → commands.run() → files.read() → kill()
"""

import asyncio
import os

from serverless_sandbox import Sandbox, SandboxError

# ── 内嵌销售数据 / Embedded sales CSV data ────────────────────────────────
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

# ── 分析脚本（将在沙箱中执行）/ Analysis script (runs inside sandbox) ─────
ANALYZE_SCRIPT = """\
import pandas as pd
import json

# 读取数据 / Read data
df = pd.read_csv("/app/data.csv")

# 1. 总销售额 / Total revenue
total_revenue = df["amount"].sum()

# 2. 按产品分组 / Group by product
product_stats = df.groupby("product").agg(
    total_quantity=("quantity", "sum"),
    total_revenue=("amount", "sum"),
    avg_order_value=("amount", "mean"),
    order_count=("product", "count"),
).reset_index()

# 3. 最畅销产品 / Best-selling product
best_product = product_stats.loc[product_stats["total_revenue"].idxmax()]

# 4. 日均销售 / Daily average
daily_avg = df.groupby("date")["amount"].sum().mean()

# 5. 生成报告 / Generate report
report_lines = [
    "=" * 55,
    "  Sales Analysis Report / 销售分析报告",
    "=" * 55,
    "",
    f"  总记录数 / Total records    : {len(df)}",
    f"  总销售额 / Total revenue    : ¥{total_revenue:,.2f}",
    f"  日均销售 / Daily avg revenue: ¥{daily_avg:,.2f}",
    f"  平均订单额 / Avg order value: ¥{df['amount'].mean():,.2f}",
    "",
    "-" * 55,
    "  按产品汇总 / Product Summary",
    "-" * 55,
]
for _, row in product_stats.iterrows():
    report_lines.append(
        f"  {row['product']:<12s} "
        f"数量={row['total_quantity']:>5.0f}  "
        f"收入=¥{row['total_revenue']:>10,.2f}  "
        f"均价=¥{row['avg_order_value']:>8,.2f}"
    )
report_lines += [
    "",
    "-" * 55,
    f"  🏆 最畅销产品 / Top product: {best_product['product']}",
    f"     总收入 / Revenue: ¥{best_product['total_revenue']:,.2f}",
    "=" * 55,
]

report_text = "\\n".join(report_lines)
print(report_text)

# 保存报告到文件 / Save report to file
with open("/app/report.txt", "w") as f:
    f.write(report_text)

# 保存 JSON 摘要 / Save JSON summary
summary = {
    "total_records": len(df),
    "total_revenue": float(total_revenue),
    "daily_avg_revenue": round(float(daily_avg), 2),
    "best_product": best_product["product"],
    "best_product_revenue": float(best_product["total_revenue"]),
    "product_breakdown": product_stats.to_dict(orient="records"),
}
with open("/app/summary.json", "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print("\\n✓ 报告已保存 / Report saved to /app/report.txt")
print("✓ 摘要已保存 / Summary saved to /app/summary.json")
"""


async def main() -> None:
    """E2B 风格: 命令式沙箱操作演示 / E2B style: imperative sandbox demo."""
    # 从环境变量获取 API Key / Get API key from environment
    api_key = os.environ.get("E2B_API_KEY", "")

    print("=" * 55)
    print("  E2B 风格数据分析 Demo / E2B-Style Data Analysis")
    print("=" * 55)

    try:
        # ── Step 1: 创建沙箱 / Create sandbox ─────────────────────────
        print("\n[1/6] 创建沙箱 / Creating sandbox...")
        async with await Sandbox.create(
            template="base",
            api_key=api_key,
            timeout=300,
            metadata={"demo": "e2b-data-analysis"},
        ) as sandbox:
            print(f"  ✓ 沙箱已创建 id={sandbox.id}")

            # ── Step 2: 安装依赖 / Install dependencies ───────────────
            print("\n[2/6] 安装 pandas / Installing pandas...")
            result = await sandbox.commands.run(
                "pip install pandas --quiet",
                timeout=120,
            )
            if not result.success:
                print(f"  ✗ 安装失败: {result.stderr}")
                return
            print("  ✓ pandas 已安装")

            # ── Step 3: 上传数据 / Upload data ────────────────────────
            print("\n[3/6] 上传 CSV 数据 / Uploading CSV data...")
            await sandbox.files.write("/app/data.csv", SALES_CSV)
            print("  ✓ 已写入 /app/data.csv")

            # 验证文件 / Verify file
            exists = await sandbox.files.exists("/app/data.csv")
            print(f"  ✓ 文件存在: {exists}")

            # ── Step 4: 上传分析脚本 / Upload analysis script ─────────
            print("\n[4/6] 上传分析脚本 / Uploading analysis script...")
            await sandbox.files.write("/app/analyze.py", ANALYZE_SCRIPT)
            print("  ✓ 已写入 /app/analyze.py")

            # ── Step 5: 执行分析 / Run analysis ───────────────────────
            print("\n[5/6] 执行数据分析 / Running analysis...")
            result = await sandbox.commands.run(
                "python3 /app/analyze.py",
                timeout=60,
            )
            if result.success:
                print()
                print(result.stdout)
            else:
                print(f"  ✗ 分析失败 (exit={result.exit_code})")
                print(f"  stderr: {result.stderr}")
                return

            # ── Step 6: 下载结果 / Download results ───────────────────
            print("\n[6/6] 读取分析结果 / Reading results...")
            report = await sandbox.files.read("/app/report.txt")
            summary_json = await sandbox.files.read("/app/summary.json")
            print(f"  ✓ 报告长度: {len(report)} 字符")
            print(f"  ✓ JSON 摘要: {summary_json[:100]}...")

        # async with 退出后沙箱自动销毁 / Sandbox auto-killed on exit
        print("\n✓ 沙箱已自动销毁 / Sandbox auto-destroyed")

    except SandboxError as e:
        print(f"\n✗ 沙箱错误 / Sandbox error: {e}")
    except Exception as e:
        print(f"\n✗ 未知错误 / Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
