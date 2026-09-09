"""Codex Agent 集成示例 / Codex Agent Integration

演示创建 Codex 沙箱，配置 OpenAI API Key，运行 AI 编程任务。
Shows how to create a Codex sandbox, configure API keys, and run AI coding tasks.

前置条件:
  - 设置环境变量 E2B_API_KEY（沙箱平台 Key）
  - 设置环境变量 OPENAI_API_KEY（OpenAI Key，传入沙箱）
"""

import asyncio
import os

from serverless_sandbox import Sandbox


async def main() -> None:
    api_key = os.environ.get("E2B_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if not openai_key:
        print("⚠ 未设置 OPENAI_API_KEY 环境变量，部分功能将使用模拟模式")

    # ── 1. 创建沙箱并注入 OpenAI API Key ─────────────────────────────
    # 使用 codex 模板，预装了 openai SDK 和 Node.js 环境
    async with await Sandbox.create(
        template="codex",
        api_key=api_key,
        timeout=600,
        envs={
            "OPENAI_API_KEY": openai_key,
            "PYTHONUNBUFFERED": "1",
        },
        metadata={"purpose": "codex-agent-demo"},
    ) as sandbox:
        print(f"✓ 沙箱已创建: {sandbox.id}")

        # ── 2. 安装 openai SDK ──────────────────────────────────────
        print("⏳ 正在安装 openai SDK...")
        result = await sandbox.commands.run(
            "pip install openai --quiet",
            timeout=120,
        )
        if not result.success:
            print(f"✗ 安装失败: {result.stderr}")
            return
        print("✓ openai SDK 安装完成")

        # ── 3. 编写 AI 编程任务脚本 ─────────────────────────────────
        agent_script = '''\
"""使用 OpenAI API 生成代码并执行。"""
import os
import json

api_key = os.environ.get("OPENAI_API_KEY", "")

if not api_key:
    # 模拟模式 — 不调用真实 API
    print("运行在模拟模式（未设置 OPENAI_API_KEY）")
    generated_code = """
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)

data = [38, 27, 43, 3, 9, 82, 10]
print(f"排序前: {data}")
print(f"排序后: {quicksort(data)}")
"""
    print("模拟生成的代码:")
    print(generated_code)
    exec(generated_code)
else:
    # 真实模式 — 调用 OpenAI API
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "你是一个 Python 代码生成助手。只返回可执行的 Python 代码，不要返回 markdown。"},
            {"role": "user", "content": "写一个快速排序函数，并用示例数据 [38, 27, 43, 3, 9, 82, 10] 测试它。"},
        ],
        temperature=0.2,
    )
    generated_code = response.choices[0].message.content.strip()
    print("AI 生成的代码:")
    print(generated_code)
    print("\\n执行结果:")
    exec(generated_code)
'''

        await sandbox.files.write("/app/agent_task.py", agent_script)
        print("✓ 已写入 AI 编程任务脚本")

        # ── 4. 执行 AI 任务 ─────────────────────────────────────────
        print("\n⏳ 正在执行 AI 编程任务...\n")
        result = await sandbox.commands.run(
            "python /app/agent_task.py",
            timeout=60,
        )

        if result.success:
            print(result.stdout)
        else:
            print(f"✗ 执行失败 (exit={result.exit_code})")
            if result.stderr:
                print(f"stderr: {result.stderr}")

        # ── 5. 在沙箱中验证生成的代码可重复执行 ──────────────────────
        print("\n── 使用 run_code 验证排序算法 ──")
        code_result = await sandbox.run_code("""
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)

test_cases = [
    [38, 27, 43, 3, 9, 82, 10],
    [5, 1, 4, 2, 8],
    [],
    [1],
]

for tc in test_cases:
    print(f"  {tc} -> {quicksort(tc)}")
""")
        print(code_result.text or code_result.stdout)

    print("\n✓ 沙箱已自动销毁")


if __name__ == "__main__":
    asyncio.run(main())
