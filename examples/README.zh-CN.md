# Easy Sandbox — 使用示例

[English](README.md) | **中文**

本目录包含 Easy Sandbox SDK 的完整使用示例，覆盖从基础操作到高级场景。

## 前置条件

### 1. 安装 SDK

```bash
# 完整安装（推荐，包含 CLI + 声明式装饰器）
pip install "easy-sandbox[all]"

# 或按需安装
pip install "easy-sandbox[cli]"           # 仅 CLI
pip install "easy-sandbox[declarative]"   # 仅 @sandbox 装饰器

# 从源码安装
pip install -e .
```

### 2. 配置凭证

```bash
# 方式一：环境变量
export E2B_API_KEY="your-api-key"

# 方式二：CLI 配置（持久化到 ~/.ebx/config.toml）
ebx config set api_key your-api-key

# 如需运行 Codex Agent 示例，还需配置：
export OPENAI_API_KEY="your-openai-key-here"
```

> **环境变量：** envd 使用直接执行（direct exec）—— Shell 特性（`$VAR` 展开、管道、重定向）需要 `sh -c '...'`。用 `printenv VAR` 读取变量值。详见[环境变量指南（中文）](../docs/zh/guide/environment-variables.md) | [Environment Variables (EN)](../docs/en/guide/environment-variables.md)。

## 目录结构

```
examples/
├── quickstart/                # 快速入门示例
│   ├── 01_hello.py            # 基础沙箱操作 —— 创建、执行命令、生命周期
│   ├── 02_file_ops.py         # 文件操作 —— 读写文件、目录管理
│   ├── 03_web_service.py      # Web 服务 —— 启动服务、获取公网 URL
│   ├── 04_data_analysis.py    # 数据分析 —— CSV 上传、pandas 分析
│   └── 05_decorator_usage.py  # @sandbox 装饰器 —— 声明式远程执行
├── agents/                    # Agent 集成示例
│   ├── codex_agent.py         # Codex Agent —— AI 代码生成与执行
│   └── browser_automation.py  # 浏览器自动化 —— Playwright 爬取与截图
├── compat-demos/              # E2B/Modal 兼容层演示
│   ├── e2b_data_analysis.py   # E2B 风格数据分析
│   ├── e2b_web_scraper.py     # E2B 风格网页爬取
│   ├── modal_compute.py       # Modal 风格科学计算
│   ├── modal_data_analysis.py # Modal 风格数据分析
│   └── comparison.py          # E2B vs Modal 风格对比
└── templates/                 # 沙箱模板（Dockerfile + template.yaml）
    ├── python-hello/
    ├── node-web/
    ├── browser-automation/
    ├── claude-code/
    ├── codex/
    ├── qoder/
    ├── qwen-code/
    ├── deepseek-harness/
    ├── hermes-agent/
    └── openclaw/
```

## 示例列表

### quickstart/ —— 快速入门

| 文件 | 说明 | 适用场景 |
|------|------|----------|
| [`01_hello.py`](quickstart/01_hello.py) | **基础沙箱操作** —— 创建、执行命令、生命周期管理 | SDK 入门 |
| [`02_file_ops.py`](quickstart/02_file_ops.py) | **文件操作** —— 读写文件、目录管理、二进制文件 | 数据交换 |
| [`03_web_service.py`](quickstart/03_web_service.py) | **Web 服务** —— 启动 Express 服务、获取公网 URL | Web 开发、API 测试 |
| [`04_data_analysis.py`](quickstart/04_data_analysis.py) | **数据分析** —— 上传 CSV、pandas 分析、run_code | 数据科学 |
| [`05_decorator_usage.py`](quickstart/05_decorator_usage.py) | **@sandbox 装饰器** —— 声明式远程执行 | 简化调用 |

### agents/ —— Agent 集成

| 文件 | 说明 | 适用场景 |
|------|------|----------|
| [`codex_agent.py`](agents/codex_agent.py) | **Codex Agent** —— AI 代码生成与执行 | AI 编程 |
| [`browser_automation.py`](agents/browser_automation.py) | **浏览器自动化** —— Playwright 爬取与截图 | 网页爬取 |

### compat-demos/ —— 兼容层演示

| 文件 | 说明 | 适用场景 |
|------|------|----------|
| [`e2b_data_analysis.py`](compat-demos/e2b_data_analysis.py) | **E2B 风格数据分析** | E2B 迁移 |
| [`e2b_web_scraper.py`](compat-demos/e2b_web_scraper.py) | **E2B 风格网页爬取** | E2B 迁移 |
| [`modal_compute.py`](compat-demos/modal_compute.py) | **Modal 风格科学计算** | Modal 迁移 |
| [`modal_data_analysis.py`](compat-demos/modal_data_analysis.py) | **Modal 风格数据分析** | Modal 迁移 |
| [`comparison.py`](compat-demos/comparison.py) | **E2B vs Modal 风格对比** | API 风格选型 |

## 运行示例

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

### 执行方法

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(template="base", api_key="...") as sandbox:

    # 1. 裸 Shell —— sandbox.run(cmd)
    proc = await sandbox.run("echo hello")
    print(proc.stdout, proc.exit_code)

    # 2. 代码解释器 —— sandbox.run_code(code)
    code_result = await sandbox.run_code("print(1 + 1)")
    print(code_result.text)   # "2"

    # 3. 命名命令 —— sandbox.custom(name, **kwargs)
    #    先查 template custom_commands (A)，再查 SandboxServer (B)
    cmd_result = await sandbox.custom("hello", name="Alice")
    print(cmd_result.value)   # 命令返回值
    print(cmd_result.source)  # "template" 或 "server"
```

> **E2B 兼容：** `sandbox.commands.run(cmd)` 是 `sandbox.run()` 的底层入口。已有 E2B 代码可直接使用。

### 文件操作

```python
    # 写入和读取文件
    await sandbox.files.write("/app/data.txt", "内容")
    content = await sandbox.files.read("/app/data.txt")
```

### 网络

```python
    # 获取端口的公网 URL
    url = sandbox.network.get_url(3000)
```

### 声明式装饰器

```python
from easy_sandbox.declarative import sandbox

@sandbox(template="code-interpreter", packages=["numpy"])
def compute(n: int) -> float:
    import numpy as np
    return float(np.random.random(n).mean())

result = compute(1000)  # 自动在远程沙箱中执行
```
