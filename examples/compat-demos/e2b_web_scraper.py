"""E2B 风格网页爬取 Demo / E2B-Style Web Scraper Demo

API 风格: E2B（命令式）
Style: E2B (imperative)

场景 / Scenario:
    在沙箱中安装 requests + beautifulsoup4 → 编写爬虫脚本 → 执行爬取 → 获取结果
    Install requests + bs4 in sandbox → write scraper → execute → get results

工作流 / Workflow:
    Sandbox.create() → commands.run("pip install ...") → files.write(scraper) →
    commands.run(scraper) → print(result.stdout)
"""

import asyncio
import os

from serverless_sandbox import Sandbox, SandboxError

# ── 爬虫脚本（将在沙箱中执行）/ Scraper script (runs inside sandbox) ───────
SCRAPER_SCRIPT = """\
import requests
from bs4 import BeautifulSoup
import json

def scrape_example():
    \"\"\"爬取 example.com 并提取页面信息 / Scrape example.com and extract info.\"\"\"
    url = "https://example.com"
    print(f"正在爬取 / Fetching: {url}")
    print("-" * 50)

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # 提取信息 / Extract information
        result = {
            "url": url,
            "status_code": response.status_code,
            "title": soup.title.string if soup.title else "N/A",
            "headings": [],
            "paragraphs": [],
            "links": [],
            "meta_info": {},
        }

        # 标题 / Headings
        for tag in ["h1", "h2", "h3"]:
            for heading in soup.find_all(tag):
                result["headings"].append({
                    "level": tag,
                    "text": heading.get_text(strip=True),
                })

        # 段落 / Paragraphs
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                result["paragraphs"].append(text)

        # 链接 / Links
        for a in soup.find_all("a", href=True):
            result["links"].append({
                "text": a.get_text(strip=True),
                "href": a["href"],
            })

        # Meta 标签 / Meta tags
        for meta in soup.find_all("meta"):
            name = meta.get("name", meta.get("property", ""))
            content = meta.get("content", "")
            if name and content:
                result["meta_info"][name] = content

        # 输出结果 / Print results
        print(f"页面标题 / Title : {result['title']}")
        print(f"HTTP 状态 / Status: {result['status_code']}")
        print(f"标题数量 / Headings: {len(result['headings'])}")
        print(f"段落数量 / Paragraphs: {len(result['paragraphs'])}")
        print(f"链接数量 / Links: {len(result['links'])}")
        print()

        if result["headings"]:
            print("标题列表 / Headings:")
            for h in result["headings"]:
                print(f"  [{h['level']}] {h['text']}")
            print()

        if result["paragraphs"]:
            print("段落内容 / Paragraphs:")
            for i, p in enumerate(result["paragraphs"], 1):
                # 截断长文本 / Truncate long text
                display = p[:120] + "..." if len(p) > 120 else p
                print(f"  {i}. {display}")
            print()

        if result["links"]:
            print("链接列表 / Links:")
            for link in result["links"]:
                print(f"  [{link['text']}] → {link['href']}")
            print()

        # 保存 JSON 结果 / Save JSON result
        with open("/app/scrape_result.json", "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("✓ 结果已保存 / Saved to /app/scrape_result.json")

        return result

    except requests.RequestException as e:
        print(f"✗ 请求失败 / Request failed: {e}")
        return None

if __name__ == "__main__":
    scrape_example()
"""


async def main() -> None:
    """E2B 风格: 命令式网页爬取演示 / E2B style: imperative web scraping demo."""
    api_key = os.environ.get("E2B_API_KEY", "")

    print("=" * 55)
    print("  E2B 风格网页爬取 Demo / E2B-Style Web Scraper")
    print("=" * 55)

    try:
        # ── Step 1: 创建沙箱 / Create sandbox ─────────────────────────
        print("\n[1/5] 创建沙箱 / Creating sandbox...")
        async with await Sandbox.create(
            template="base",
            api_key=api_key,
            timeout=300,
            metadata={"demo": "e2b-web-scraper"},
        ) as sandbox:
            print(f"  ✓ 沙箱已创建 id={sandbox.id}")

            # ── Step 2: 安装依赖 / Install dependencies ───────────────
            print("\n[2/5] 安装依赖 / Installing dependencies...")
            result = await sandbox.commands.run(
                "pip install requests beautifulsoup4 --quiet",
                timeout=120,
            )
            if not result.success:
                print(f"  ✗ 安装失败: {result.stderr}")
                return
            print("  ✓ requests + beautifulsoup4 已安装")

            # 验证安装 / Verify installation
            result = await sandbox.commands.run(
                'python3 -c "import requests, bs4; '
                'print(f\'requests={requests.__version__}, bs4={bs4.__version__}\')"'
            )
            if result.success:
                print(f"  ✓ 版本: {result.stdout.strip()}")

            # ── Step 3: 上传爬虫脚本 / Upload scraper script ──────────
            print("\n[3/5] 上传爬虫脚本 / Uploading scraper script...")
            await sandbox.files.write("/app/scraper.py", SCRAPER_SCRIPT)
            print("  ✓ 已写入 /app/scraper.py")

            # ── Step 4: 执行爬取 / Run scraper ────────────────────────
            print("\n[4/5] 执行网页爬取 / Running web scraper...")
            result = await sandbox.commands.run(
                "python3 /app/scraper.py",
                timeout=30,
            )
            if result.success:
                print()
                print(result.stdout)
            else:
                print(f"  ✗ 爬取失败 (exit={result.exit_code})")
                if result.stderr:
                    print(f"  stderr: {result.stderr[:200]}")

            # ── Step 5: 获取 JSON 结果 / Retrieve JSON result ─────────
            print("\n[5/5] 读取爬取结果 / Reading scrape results...")
            try:
                json_result = await sandbox.files.read("/app/scrape_result.json")
                print(f"  ✓ JSON 结果 ({len(json_result)} 字符):")
                # 只显示前 300 个字符 / Show first 300 chars
                preview = json_result[:300]
                if len(json_result) > 300:
                    preview += "\n  ..."
                print(f"  {preview}")
            except Exception as e:
                print(f"  ⚠ 无法读取结果文件: {e}")

        print("\n✓ 沙箱已自动销毁 / Sandbox auto-destroyed")

    except SandboxError as e:
        print(f"\n✗ 沙箱错误 / Sandbox error: {e}")
    except Exception as e:
        print(f"\n✗ 未知错误 / Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
