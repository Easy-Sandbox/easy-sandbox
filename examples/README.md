# Easy Sandbox SDK 使用示例

本目录包含 Easy Sandbox SDK 的完整使用示例，覆盖从基础操作到高级场景。

## 前置条件

### 1. 安装 SDK

```bash
# 完整安装（推荐，包含 CLI + 声明式装饰器）
pip install easy-sandbox[all]

# 或按需安装
pip install easy-sandbox[cli]          # 仅 CLI
pip install easy-sandbox[declarative]  # 仅 @sandbox 装饰器

# 从源码安装
pip install -e .
```

### 2. 配置 API Key

```bash
# 方式一：环境变量
export E2B_API_KEY="your-api-key"

# 方式二：CLI 配置（持久化到 ~/.ebx/config.toml）
ebx config set api_key your-api-key

# 如需运行 Codex Agent 示例，还需配置：
export OPENAI_API_KEY="your-openai-key-here"
```

## 目录结构

```
examples/
├── quickstart/              # 快速入门示例
│   ├── 01_hello.py          # 基础沙箱操作 — 创建、执行命令、生命周期
│   ├── 02_file_ops.py       # 文件操作 — 读写文件、目录管理
│   ├── 03_web_service.py    # Web 服务 — 启动服务、获取公网 URL
│   ├── 04_data_analysis.py  # 数据分析 — CSV 上传、pandas 分析
│   └── 05_decorator_usage.py # @sandbox 装饰器 — 声明式远程执行
├── agents/                  # Agent 集成示例
│   ├── codex_agent.py       # Codex Agent — AI 代码生成与执行
│   └── browser_automation.py # 浏览器自动化 — Playwright 爬取与截图
├── compat-demos/            # E2B/Modal 兼容示例
│   ├── e2b_data_analysis.py # E2B 风格数据分析
│   ├── e2b_web_scraper.py   # E2B 风格网页爬取
│   ├── modal_compute.py     # Modal 风格科学计算
│   ├── modal_data_analysis.py # Modal 风格数据分析
│   └── comparison.py        # E2B vs Modal 风格对比
└── templates/               # 沙箱模板（Dockerfile + template.yaml）
    ├── browser-automation/
    ├── claude-code/
    ├── codex/
    ├── deepseek-harness/
    ├── hermes-agent/
    ├── node-web/
    ├── openclaw/
    ├── python-hello/
    ├── qoder/
    └── qwen-code/
```

## 示例列表

### quickstart/ — 快速入门

| 文件 | 说明 | 适用场景 |
|------|------|----------|
| [`01_hello.py`](quickstart/01_hello.py) | **基础沙箱操作** — 创建、执行命令、生命周期管理 | SDK 入门，快速上手 |
| [`02_file_ops.py`](quickstart/02_file_ops.py) | **文件操作** — 读写文件、目录管理、二进制文件 | 文件处理，数据交换 |
| [`03_web_service.py`](quickstart/03_web_service.py) | **Web 服务** — 启动 Express 服务、获取公网 URL | Web 开发，API 测试 |
| [`04_data_analysis.py`](quickstart/04_data_analysis.py) | **数据分析** — 上传 CSV、pandas 分析、run_code | 数据科学，报表生成 |
| [`05_decorator_usage.py`](quickstart/05_decorator_usage.py) | **@sandbox 装饰器** — 声明式远程执行 | 远程计算，简化调用 |

### agents/ — Agent 集成

| 文件 | 说明 | 适用场景 |
|------|------|----------|
| [`codex_agent.py`](agents/codex_agent.py) | **Codex Agent** — AI 代码生成与执行 | AI 编程，自动化任务 |
| [`browser_automation.py`](agents/browser_automation.py) | **浏览器自动化** — Playwright 爬取与截图 | 网页爬取，自动化测试 |

### compat-demos/ — 兼容层演示

| 文件 | 说明 | 适用场景 |
|------|------|----------|
| [`e2b_data_analysis.py`](compat-demos/e2b_data_analysis.py) | **E2B 风格数据分析** — E2B 兼容 API 数据分析 | 数据分析，E2B 迁移 |
| [`e2b_web_scraper.py`](compat-demos/e2b_web_scraper.py) | **E2B 风格网页爬取** — E2B 兼容 API 爬取 | 网页爬取，E2B 迁移 |
| [`modal_compute.py`](compat-demos/modal_compute.py) | **Modal 风格科学计算** — Modal 兼容 API 计算 | 科学计算，Modal 迁移 |
| [`modal_data_analysis.py`](compat-demos/modal_data_analysis.py) | **Modal 风格数据分析** — Modal 兼容 API 分析 | 数据分析，Modal 迁移 |
| [`comparison.py`](compat-demos/comparison.py) | **E2B vs Modal 风格对比** — 两种风格对比演示 | API 风格选型 |

## 快速开始

运行任意示例：

```bash
# 基础示例
python examples/quickstart/01_hello.py

# 数据分析
python examples/quickstart/04_data_analysis.py

# @sandbox 装饰器
python examples/quickstart/05_decorator_usage.py

# E2B 兼容
python examples/compat-demos/e2b_data_analysis.py
```

## 核心 API 速览

```python
from easy_sandbox import Sandbox

# 创建沙箱（推荐使用 async with 自动管理生命周期）
async with await Sandbox.create(template="base", api_key="...") as sandbox:

    # 执行命令
    result = await sandbox.commands.run("echo hello")
    print(result.stdout, result.exit_code)

    # 文件操作
    await sandbox.files.write("/app/data.txt", "内容")
    content = await sandbox.files.read("/app/data.txt")

    # 执行代码
    code_result = await sandbox.run_code("print(1 + 1)")
    print(code_result.text)

    # 端口访问
    url = sandbox.network.get_url(3000)
```

```python
# @sandbox 装饰器 — 声明式远程执行
from easy_sandbox.declarative import sandbox

@sandbox(template="code-interpreter", packages=["numpy"])
def compute(n: int) -> float:
    import numpy as np
    return float(np.random.random(n).mean())

result = compute(1000)  # 自动在远程沙箱中执行
```
