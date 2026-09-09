# 浏览器自动化模板

预装 Playwright + Chromium 的沙箱环境，适用于网页抓取、UI 自动化测试和浏览器交互任务。

## 环境说明

| 类别 | 内容 |
|------|------|
| **基础镜像** | mcr.microsoft.com/playwright/python:v1.40.0-jammy |
| **浏览器** | Chromium（通过 Playwright 管理） |
| **Python 包** | `playwright`、`beautifulsoup4`、`lxml`、`httpx`、`Pillow` |
| **系统工具** | curl、wget、xvfb、jq |
| **资源配置** | 2 CPU / 4096 MB 内存 |

## 安装方式

**从本地安装：**

```bash
sbox install ./examples/templates/browser-automation --registry-type local
```

**从 GitHub 安装：**

```bash
sbox install Serverless-Sandbox/awesome-templates//browser-automation
```

## 使用示例

创建沙箱实例：

```bash
sbox create --template browser-automation
```

在沙箱中运行网页截图脚本：

```bash
sbox exec <sandbox-id> -- python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('https://example.com')
    page.screenshot(path='/workspace/screenshot.png')
    browser.close()
"
```

使用 Python SDK：

```python
from serverless_sandbox import Sandbox

sandbox = Sandbox.create(template="browser-automation")

# 执行网页抓取
code = '''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()
'''
result = sandbox.code.execute(code)
print(result.stdout)
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DISPLAY` | X 虚拟帧缓冲显示编号 | `:99` |
| `PLAYWRIGHT_BROWSERS_PATH` | 浏览器安装路径 | `/ms-playwright` |

### Headless 与 Headed 模式

默认以 headless 模式运行（无需 GUI）。如需 headed 模式，请先启动 Xvfb：

```bash
Xvfb :99 -screen 0 1920x1080x24 &
```

## 注意事项

- **内存消耗**：浏览器运行时内存消耗较大，建议保持 4096 MB 以上配置。
- **仅含 Chromium**：为减小镜像体积，默认只安装 Chromium。如需 Firefox 或 WebKit，可在沙箱内执行 `python3 -m playwright install firefox`。
- **网络访问**：网页抓取任务需要外网访问权限，请确保沙箱网络策略允许出站连接。
- **截图与文件**：生成的截图和文件保存在 `/workspace` 目录下，可通过文件 API 下载。
