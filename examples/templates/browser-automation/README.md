# 浏览器自动化模板

预装 Playwright + Chromium 的沙箱环境，适用于网页抓取、UI 自动化测试和浏览器交互任务。

本模板启用了 **BROWSER** 内置能力组，提供 8 个低层浏览器端点，同时注册了 3 个面向 AI Agent 的高层业务命令。

## 环境说明

| 类别 | 内容 |
|------|------|
| **基础镜像** | mcr.microsoft.com/playwright/python:v1.40.0-jammy |
| **浏览器** | Chromium（通过 Playwright 管理） |
| **Python 包** | `playwright`、`beautifulsoup4`、`lxml`、`httpx`、`Pillow` |
| **系统工具** | curl、wget、xvfb、jq |
| **资源配置** | 2 CPU / 4096 MB 内存 |
| **启用能力组** | `BROWSER`、`FILE_OPS`、`PROCESS` |

## 安装方式

**从本地安装：**

```bash
ebx install ./examples/templates/browser-automation --registry-type local
```

**从 GitHub 安装：**

```bash
ebx install Easy-Sandbox/awesome-templates//browser-automation
```

## 高层业务命令

模板注册了以下面向 AI Agent 工作流的高层命令：

### `browse(url, action="screenshot")`

智能浏览 — 导航到 URL 并根据 action 执行不同操作。

| action | 行为 |
|--------|------|
| `screenshot` | 截取整页截图，返回保存路径 |
| `extract` | 获取页面可见文本内容 |
| `links` | 提取页面中所有超链接（href + text） |
| `full` | 截图 + 标题 + 前 500 字文本摘要 |

### `scrape(url, selector)`

按 CSS 选择器提取元素文本内容。返回匹配元素的文本数组。

### `fill_form(url, fields_json)`

自动填表 — 导航到 URL，按 JSON 描述逐个填写表单字段。

`fields_json` 格式：

```json
[
  {"selector": "#email", "value": "test@example.com"},
  {"selector": "#password", "value": "123456"}
]
```

## 内置 BROWSER 端点

启用 `CapabilityGroup.BROWSER` 后，以下低层 HTTP 端点可直接调用：

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/browser/navigate` | 导航到指定 URL |
| POST | `/browser/screenshot` | 截取页面截图（返回 base64） |
| GET  | `/browser/content` | 获取页面 HTML 或纯文本 |
| POST | `/browser/click` | 点击指定元素 |
| POST | `/browser/type` | 向指定元素输入文本 |
| POST | `/browser/evaluate` | 在页面中执行 JavaScript |
| POST | `/browser/pdf` | 生成页面 PDF（返回 base64） |
| GET  | `/browser/console` | 获取收集的控制台日志 |

## 使用示例

创建沙箱实例：

```bash
ebx create --template browser-automation
```

使用高层命令截图：

```bash
ebx exec <sandbox-id> browse --url https://example.com --action screenshot
```

使用高层命令提取文本：

```bash
ebx exec <sandbox-id> browse --url https://example.com --action extract
```

使用高层命令抓取指定元素：

```bash
ebx exec <sandbox-id> scrape --url https://example.com --selector "h1"
```

使用 Python SDK：

```python
from easy_sandbox import Sandbox

sandbox = Sandbox.create(template="browser-automation")

# 截取网页截图
result = sandbox.commands.run("browse", url="https://example.com", action="screenshot")
print(result)  # {"action": "screenshot", "url": "...", "path": "/workspace/screenshot_xxx.png"}

# 提取页面文本
result = sandbox.commands.run("browse", url="https://example.com", action="extract")
print(result["text"])

# 按选择器抓取
result = sandbox.commands.run("scrape", url="https://example.com", selector="h1")
print(result["texts"])

# 自动填表
import json
fields = [
    {"selector": "#email", "value": "test@example.com"},
    {"selector": "#password", "value": "secret"},
]
result = sandbox.commands.run("fill_form", url="https://example.com/login", fields_json=json.dumps(fields))
print(result)
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

- **持久化浏览器实例**：模板使用模块级 Playwright 单例，首次调用时创建，后续命令复用同一实例，性能远优于每次创建/销毁。
- **内存消耗**：浏览器运行时内存消耗较大，建议保持 4096 MB 以上配置。
- **仅含 Chromium**：为减小镜像体积，默认只安装 Chromium。如需 Firefox 或 WebKit，可在沙箱内执行 `python3 -m playwright install firefox`。
- **网络访问**：网页抓取任务需要外网访问权限，请确保沙箱网络策略允许出站连接。
- **截图与文件**：生成的截图和文件保存在 `/workspace` 目录下，可通过文件 API 下载。
