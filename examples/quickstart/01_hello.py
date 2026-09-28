"""基础沙箱操作示例 / Basic Sandbox Operations

演示如何创建沙箱、执行命令、获取输出、管理生命周期。
Shows how to create a sandbox, run commands, capture output, and manage lifecycle.
"""

import asyncio
import os

from easy_sandbox import Sandbox


async def main() -> None:
    # 从环境变量读取 API Key（不要硬编码）
    api_key = os.environ.get("E2B_API_KEY", "")

    # ── 1. 使用 async with 自动管理沙箱生命周期 ──────────────────────
    async with await Sandbox.create(
        template="base",
        api_key=api_key,
        timeout=300,                                     # 沙箱 300 秒后自动销毁
        metadata={"purpose": "basic-demo"},              # 附加元数据
        envs={"MY_VAR": "hello-sandbox"},                # 注入环境变量
    ) as sandbox:
        print(f"✓ 沙箱已创建  id={sandbox.id}  status={sandbox.status.value}")

        # ── 2. 执行简单命令 ──────────────────────────────────────────
        result = await sandbox.commands.run("echo 'Hello from Sandbox!'")
        print(f"stdout : {result.stdout.strip()}")
        print(f"exit   : {result.exit_code}")

        # ── 3. 执行 Python 脚本 ─────────────────────────────────────
        result = await sandbox.commands.run(
            'python3 -c "import platform; print(platform.platform())"'
        )
        print(f"系统信息: {result.stdout.strip()}")

        # ── 4. 读取注入的环境变量 ────────────────────────────────────
        # 注意: envd 直接 exec，不经过 shell 展开，"echo $MY_VAR" 无法
        # 解析变量。改用 printenv 直接读取环境变量。
        result = await sandbox.commands.run("printenv MY_VAR")
        print(f"MY_VAR = {result.stdout.strip()}")

        # ── 5. 演示管道和 shell 语法 ──────────────────────────────────
        # envd exec 不会处理管道 (|)、重定向 (>) 和 && 等 shell 语法，
        # 需要显式用 sh -c 包装。
        result = await sandbox.commands.run("sh -c 'ls / | head -5'")
        print(f"根目录前 5 项:\n{result.stdout}")

        # ── 6. 带错误处理的命令 ─────────────────────────────────────
        result = await sandbox.commands.run("ls /nonexistent", timeout=10)
        if not result.success:
            print(f"命令失败 (exit={result.exit_code}): {result.stderr.strip()}")

        # ── 7. 查看沙箱运行状态 ─────────────────────────────────────
        running = await sandbox.is_running()
        print(f"沙箱运行中: {running}")

    # async with 退出后沙箱自动 kill
    print("✓ 沙箱已自动销毁")


if __name__ == "__main__":
    asyncio.run(main())
