"""数据分析示例 / Data Analysis in Sandbox

演示在沙箱中上传 CSV 数据，使用 pandas 进行分析，获取统计结果。
Shows how to upload CSV data and run pandas analysis inside a sandbox.
"""

import asyncio
import os

from easy_sandbox import Sandbox

# 样本 CSV 数据
SAMPLE_CSV = """\
date,product,region,quantity,unit_price
2024-01-15,Widget A,North,120,29.99
2024-01-15,Widget B,South,85,49.99
2024-01-16,Widget A,East,200,29.99
2024-01-16,Widget C,North,50,99.99
2024-01-17,Widget B,West,150,49.99
2024-01-17,Widget A,South,90,29.99
2024-01-18,Widget C,East,75,99.99
2024-01-18,Widget B,North,110,49.99
2024-01-19,Widget A,West,180,29.99
2024-01-19,Widget C,South,60,99.99
2024-01-20,Widget A,North,220,29.99
2024-01-20,Widget B,East,95,49.99
"""

# pandas 分析脚本
ANALYSIS_SCRIPT = """\
import pandas as pd
import json

# 读取数据
df = pd.read_csv('/app/data/sales.csv')

# 1. 基础统计
print("=" * 50)
print("基础统计 / Basic Statistics")
print("=" * 50)
print(f"总行数: {len(df)}")
print(f"总销售额: ${(df['quantity'] * df['unit_price']).sum():,.2f}")
print()

# 2. 按产品汇总
print("按产品汇总 / By Product:")
product_summary = df.groupby('product').agg(
    total_qty=('quantity', 'sum'),
    avg_price=('unit_price', 'mean'),
    orders=('quantity', 'count'),
).reset_index()
product_summary['revenue'] = product_summary['total_qty'] * product_summary['avg_price']
print(product_summary.to_string(index=False))
print()

# 3. 按区域汇总
print("按区域汇总 / By Region:")
region_summary = df.groupby('region').agg(
    total_qty=('quantity', 'sum'),
    orders=('quantity', 'count'),
).reset_index()
print(region_summary.to_string(index=False))
print()

# 4. 数值列描述性统计
print("描述性统计 / Describe:")
print(df[['quantity', 'unit_price']].describe().to_string())
print()

# 5. 输出 JSON 格式的结果摘要
summary = {
    "total_rows": len(df),
    "total_revenue": round((df['quantity'] * df['unit_price']).sum(), 2),
    "top_product": product_summary.sort_values('revenue', ascending=False).iloc[0]['product'],
    "top_region": region_summary.sort_values('total_qty', ascending=False).iloc[0]['region'],
}
print("JSON 摘要:")
print(json.dumps(summary, ensure_ascii=False, indent=2))
"""


async def main() -> None:
    api_key = os.environ.get("E2B_API_KEY", "")

    async with await Sandbox.create(
        template="base",
        api_key=api_key,
        timeout=300,
    ) as sandbox:
        print(f"✓ 沙箱已创建: {sandbox.id}")

        # ── 1. 安装 pandas ───────────────────────────────────────────
        print("⏳ 正在安装 pandas...")
        result = await sandbox.commands.run(
            "pip install pandas --quiet",
            timeout=120,
        )
        if not result.success:
            print(f"✗ pip install 失败: {result.stderr}")
            return
        print("✓ pandas 安装完成")

        # ── 2. 上传 CSV 数据 ─────────────────────────────────────────
        await sandbox.files.make_dir("/app/data")
        await sandbox.files.write("/app/data/sales.csv", SAMPLE_CSV)
        print("✓ 已上传 sales.csv")

        # 验证文件已写入
        entries = await sandbox.files.list("/app/data")
        print(f"  /app/data 目录: {[e.name for e in entries]}")

        # ── 3. 上传并执行分析脚本 ────────────────────────────────────
        await sandbox.files.write("/app/analyze.py", ANALYSIS_SCRIPT)
        print("\n⏳ 正在执行数据分析...")

        result = await sandbox.commands.run(
            "python /app/analyze.py",
            timeout=60,
        )

        if result.success:
            print(result.stdout)
        else:
            print(f"✗ 分析脚本执行失败 (exit={result.exit_code})")
            print(f"stderr: {result.stderr}")

        # ── 4. 使用 run_code 直接执行代码片段 ────────────────────────
        print("\n" + "=" * 50)
        print("使用 run_code() 直接分析 / Direct code execution")
        print("=" * 50)

        code_result = await sandbox.run_code("""
import pandas as pd
df = pd.read_csv('/app/data/sales.csv')
df['revenue'] = df['quantity'] * df['unit_price']
top3 = df.nlargest(3, 'revenue')[['date', 'product', 'region', 'revenue']]
print("Top 3 单笔收入:")
print(top3.to_string(index=False))
""")
        print(code_result.text or code_result.stdout)

    print("\n✓ 沙箱已自动销毁")


if __name__ == "__main__":
    asyncio.run(main())
