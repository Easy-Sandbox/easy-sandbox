"""Web 服务示例 / Web Service in Sandbox

演示在沙箱中启动 Node.js Express 服务并获取访问地址。
Shows how to start a Node.js Express server in a sandbox and get its public URL.
"""

import asyncio
import os

from serverless_sandbox import Sandbox

# Express 应用代码
EXPRESS_APP = """\
const express = require('express');
const app = express();
const PORT = 3000;

app.get('/', (req, res) => {
    res.json({
        message: 'Hello from Sandbox!',
        timestamp: new Date().toISOString(),
        node_version: process.version,
    });
});

app.get('/health', (req, res) => {
    res.json({ status: 'ok', uptime: process.uptime() });
});

app.get('/api/echo', (req, res) => {
    res.json({ query: req.query, headers: req.headers });
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on port ${PORT}`);
});
"""

PACKAGE_JSON = """\
{
  "name": "sandbox-express-demo",
  "version": "1.0.0",
  "dependencies": {
    "express": "^4.18.0"
  }
}
"""


async def main() -> None:
    api_key = os.environ.get("E2B_API_KEY", "")

    # 注意：本示例需要 network.get_url()/get_host() 计算公网访问地址，
    # 而这依赖模板声明 "ports" 能力。默认的 "base" 模板只回落
    # DEFAULT_CAPABILITIES（shell/files/code，不含 ports），调用 network.*
    # 会抛 CapabilityNotSupportedError(E3004)。这里使用已声明 ports 能力的
    # node-web 模板（examples/templates/node-web），语义上也更契合 Node.js 服务。
    async with await Sandbox.create(
        template="node-web",
        api_key=api_key,
        timeout=600,
    ) as sandbox:
        print(f"✓ 沙箱已创建: {sandbox.id}")

        # ── 1. 写入项目文件 ──────────────────────────────────────────
        await sandbox.files.write("/app/package.json", PACKAGE_JSON)
        await sandbox.files.write("/app/server.js", EXPRESS_APP)
        print("✓ 已写入 server.js 和 package.json")

        # ── 2. 安装依赖 ─────────────────────────────────────────────
        print("⏳ 正在安装 npm 依赖...")
        result = await sandbox.commands.run(
            "npm install --production",
            cwd="/app",
            timeout=120,
        )
        if not result.success:
            print(f"✗ npm install 失败:\n{result.stderr}")
            return
        print("✓ 依赖安装完成")

        # ── 3. 后台启动服务 ──────────────────────────────────────────
        # 使用 start() 方法启动后台进程（不阻塞等待）
        reader = await sandbox.commands.start(
            "node server.js",
            cwd="/app",
            timeout=300,
        )
        print("✓ Express 服务启动中...")

        # 等待服务就绪
        await asyncio.sleep(3)

        # ── 4. 计算公网访问地址 ──────────────────────────────────────
        url = sandbox.network.get_url(3000)
        host = sandbox.network.get_host(3000)
        print(f"\n🌐 服务地址:")
        print(f"   URL  : {url}")
        print(f"   Host : {host}")

        # secure 模式需要 access token
        headers = sandbox.network.get_access_headers()
        if headers:
            print(f"   需要 Header: {headers}")

        # ── 5. 在沙箱内请求验证 ──────────────────────────────────────
        result = await sandbox.commands.run(
            "curl -s http://localhost:3000/",
            timeout=10,
        )
        print(f"\n📥 GET / 响应:\n   {result.stdout.strip()}")

        result = await sandbox.commands.run(
            "curl -s http://localhost:3000/health",
            timeout=10,
        )
        print(f"\n📥 GET /health 响应:\n   {result.stdout.strip()}")

        result = await sandbox.commands.run(
            'curl -s "http://localhost:3000/api/echo?foo=bar&lang=zh"',
            timeout=10,
        )
        print(f"\n📥 GET /api/echo 响应:\n   {result.stdout.strip()}")

    print("\n✓ 沙箱已自动销毁，服务已停止")


if __name__ == "__main__":
    asyncio.run(main())
