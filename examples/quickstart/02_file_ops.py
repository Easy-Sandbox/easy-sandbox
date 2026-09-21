"""文件操作示例 / File Operations

演示沙箱内的文件读写、目录管理、上传下载等操作。
Shows file read/write, directory management, upload/download in a sandbox.
"""

import asyncio
import os

from easy_sandbox import Sandbox


async def main() -> None:
    api_key = os.environ.get("E2B_API_KEY", "")

    async with await Sandbox.create(
        template="base",
        api_key=api_key,
    ) as sandbox:
        print(f"✓ 沙箱已创建: {sandbox.id}")

        # ── 1. 写入文本文件 ──────────────────────────────────────────
        await sandbox.files.write("/app/hello.txt", "你好，Sandbox！\nHello, Sandbox!\n")
        print("✓ 已写入 /app/hello.txt")

        # ── 2. 读取文本文件 ──────────────────────────────────────────
        content = await sandbox.files.read("/app/hello.txt")
        print(f"读取内容:\n{content}")

        # ── 3. 创建目录结构 ──────────────────────────────────────────
        await sandbox.files.make_dir("/app/data/reports")
        print("✓ 已创建目录 /app/data/reports")

        # ── 4. 批量写入多个文件 ──────────────────────────────────────
        files_to_create = {
            "/app/data/config.json": '{"version": "1.0", "debug": true}',
            "/app/data/notes.txt": "这是一个测试笔记\n第二行内容\n",
            "/app/data/reports/summary.csv": "name,score\nAlice,95\nBob,87\nCharlie,92\n",
        }
        for path, data in files_to_create.items():
            await sandbox.files.write(path, data)
            print(f"  ✓ 写入 {path}")

        # ── 5. 列出目录内容 ──────────────────────────────────────────
        entries = await sandbox.files.list("/app/data")
        print("\n/app/data 目录内容:")
        for entry in entries:
            icon = '📁' if entry.type.value == 'directory' else '📄'
            print(f"  {icon} {entry.name}  ({entry.size} bytes)")

        # ── 6. 检查文件是否存在 ──────────────────────────────────────
        exists = await sandbox.files.exists("/app/data/config.json")
        print(f"\nconfig.json 存在: {exists}")

        missing = await sandbox.files.exists("/app/data/missing.txt")
        print(f"missing.txt 存在: {missing}")

        # ── 7. 写入二进制文件 ─────────────────────────────────────────
        binary_data = bytes(range(256))  # 0x00 ~ 0xFF
        await sandbox.files.write("/app/data/sample.bin", binary_data)
        print("✓ 已写入二进制文件 /app/data/sample.bin")

        # 读取二进制文件
        raw = await sandbox.files.read_bytes("/app/data/sample.bin")
        print(f"  读回 {len(raw)} 字节, 前 8 字节: {raw[:8].hex()}")

        # ── 8. 文件重命名 / 移动 ─────────────────────────────────────
        await sandbox.files.move("/app/data/notes.txt", "/app/data/notes_backup.txt")
        print("✓ 已将 notes.txt 移动为 notes_backup.txt")

        # ── 9. 删除文件 ──────────────────────────────────────────────
        await sandbox.files.remove("/app/data/sample.bin")
        print("✓ 已删除 sample.bin")

        # ── 10. 获取文件详细信息 ─────────────────────────────────────
        info = await sandbox.files.get_info("/app/data/config.json")
        print(f"\nconfig.json 信息: name={info.name}, size={info.size}")

    print("✓ 沙箱已自动销毁")


if __name__ == "__main__":
    asyncio.run(main())
