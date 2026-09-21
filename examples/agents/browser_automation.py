"""浏览器自动化示例 / Browser Automation in Sandbox

演示在沙箱中安装 Playwright，执行网页爬取，获取截图。
Shows how to install Playwright in a sandbox, scrape a web page, and capture screenshots.

注意: Playwright 安装较大（~200MB+），需要足够的沙箱超时时间。
"""

import asyncio
import os

from easy_sandbox import Sandbox

# Playwright 爬取脚本
SCRAPER_SCRIPT = """\
import asyncio
from playwright.async_api import async_playwright

async def scrape():
    async with async_playwright() as p:
        # 启动 Chromium（无头模式）
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        # ── 访问目标页面 ──────────────────────────────────────────
        url = "https://example.com"
        print(f"正在访问: {url}")
        await page.goto(url, wait_until="networkidle")

        # ── 获取页面标题 ──────────────────────────────────────────
        title = await page.title()
        print(f"页面标题: {title}")

        # ── 提取页面文本 ──────────────────────────────────────────
        heading = await page.text_content("h1")
        print(f"H1 内容: {heading}")

        paragraphs = await page.query_selector_all("p")
        print(f"段落数量: {len(paragraphs)}")
        for i, p_el in enumerate(paragraphs[:3]):
            text = await p_el.text_content()
            print(f"  段落 {i+1}: {text[:80]}...")

        # ── 获取所有链接 ──────────────────────────────────────────
        links = await page.query_selector_all("a")
        print(f"\\n链接数量: {len(links)}")
        for link in links:
            href = await link.get_attribute("href")
            text = await link.text_content()
            print(f"  [{text.strip()}] -> {href}")

        # ── 截图保存 ──────────────────────────────────────────────
        screenshot_path = "/app/screenshot.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"\\n截图已保存: {screenshot_path}")

        # ── 获取页面 HTML ─────────────────────────────────────────
        html = await page.content()
        with open("/app/page.html", "w") as f:
            f.write(html)
        print(f"HTML 已保存: /app/page.html ({len(html)} 字符)")

        await browser.close()
        print("\\n浏览器已关闭")

asyncio.run(scrape())
"""


async def main() -> None:
    api_key = os.environ.get("E2B_API_KEY", "")

    # 使用 base 模板，因为需要手动安装 Playwright 和 Chromium。
    # 如果已部署了 browser-automation 模板，可直接使用 template="browser-automation"
    # 就无需手动安装步骤。
    async with await Sandbox.create(
        template="base",
        api_key=api_key,
        timeout=900,  # Playwright 安装较慢，给足时间
    ) as sandbox:
        print(f"✓ 沙箱已创建: {sandbox.id}")

        # ── 1. 安装 Playwright ───────────────────────────────────────
        print("⏳ 正在安装 Playwright（这可能需要几分钟）...")

        # 安装 Python 包
        result = await sandbox.commands.run(
            "pip install playwright --quiet",
            timeout=120,
        )
        if not result.success:
            print(f"✗ pip install 失败: {result.stderr}")
            return
        print("  ✓ playwright Python 包安装完成")

        # 安装浏览器二进制（只安装 chromium 以节省时间）
        result = await sandbox.commands.run(
            "playwright install chromium --with-deps",
            timeout=300,
        )
        if not result.success:
            print(f"✗ 浏览器安装失败: {result.stderr}")
            return
        print("  ✓ Chromium 浏览器安装完成")

        # ── 2. 上传并执行爬取脚本 ────────────────────────────────────
        await sandbox.files.write("/app/scraper.py", SCRAPER_SCRIPT)
        print("\n⏳ 正在执行网页爬取...\n")

        result = await sandbox.commands.run(
            "python /app/scraper.py",
            timeout=60,
        )

        if result.success:
            print(result.stdout)
        else:
            print(f"✗ 爬取失败 (exit={result.exit_code})")
            if result.stderr:
                print(f"stderr: {result.stderr[:500]}")

        # ── 3. 验证截图文件 ──────────────────────────────────────────
        screenshot_exists = await sandbox.files.exists("/app/screenshot.png")
        if screenshot_exists:
            info = await sandbox.files.get_info("/app/screenshot.png")
            print(f"\n截图文件大小: {info.size:,} bytes")

            # 下载截图到本地（可选）
            # await sandbox.files.download("/app/screenshot.png", "./screenshot.png")
            # print("✓ 截图已下载到本地")

        # ── 4. 查看保存的 HTML ───────────────────────────────────────
        html_exists = await sandbox.files.exists("/app/page.html")
        if html_exists:
            html_content = await sandbox.files.read("/app/page.html")
            print(f"HTML 内容前 200 字符:\n{html_content[:200]}...")

        # ── 5. 列出生成的文件 ────────────────────────────────────────
        print("\n/app 目录文件:")
        entries = await sandbox.files.list("/app")
        for entry in entries:
            icon = '📁' if entry.type.value == 'directory' else '📄'
            print(f"  {icon} {entry.name}")

    print("\n✓ 沙箱已自动销毁")


if __name__ == "__main__":
    asyncio.run(main())
