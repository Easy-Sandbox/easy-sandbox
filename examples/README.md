# Easy Sandbox — Examples

**English** | [中文](README.zh-CN.md)

This directory contains complete usage examples for the Easy Sandbox SDK, covering everything from basic operations to advanced scenarios.

## Prerequisites

### 1. Install the SDK

```bash
# Full install (recommended — includes CLI + declarative decorator)
pip install "easy-sandbox[all]"

# Or install selectively
pip install "easy-sandbox[cli]"           # CLI only
pip install "easy-sandbox[declarative]"   # @sandbox decorator only

# From source
pip install -e .
```

### 2. Configure Credentials

```bash
# Option 1: Environment variable
export E2B_API_KEY="your-api-key"

# Option 2: CLI config (persisted to ~/.ebx/config.toml)
ebx config set api_key your-api-key

# For the Codex Agent example, also set:
export OPENAI_API_KEY="your-openai-key-here"
```

> **Environment variables:** envd uses direct exec — shell features (`$VAR`, pipes, redirects) require `sh -c '...'`. Use `printenv VAR` to read a variable. See the [Environment Variables guide (EN)](../docs/en/guide/environment-variables.md) | [环境变量指南 (中文)](../docs/zh/guide/environment-variables.md) for details.

## Directory Structure

```
examples/
├── quickstart/                # Quick start examples
│   ├── 01_hello.py            # Basic sandbox ops — create, execute, lifecycle
│   ├── 02_file_ops.py         # File operations — read/write, directory management
│   ├── 03_web_service.py      # Web service — start server, get public URL
│   ├── 04_data_analysis.py    # Data analysis — CSV upload, pandas analysis
│   └── 05_decorator_usage.py  # @sandbox decorator — declarative remote execution
├── agents/                    # Agent integration examples
│   ├── codex_agent.py         # Codex Agent — AI code generation & execution
│   └── browser_automation.py  # Browser automation — Playwright scraping & screenshots
├── compat-demos/              # E2B/Modal compatibility demos
│   ├── e2b_data_analysis.py   # E2B-style data analysis
│   ├── e2b_web_scraper.py     # E2B-style web scraping
│   ├── modal_compute.py       # Modal-style scientific computing
│   ├── modal_data_analysis.py # Modal-style data analysis
│   └── comparison.py          # E2B vs Modal style comparison
└── templates/                 # Sandbox templates (Dockerfile + template.yaml)
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

## Example Catalog

### quickstart/ — Getting Started

| File | Description | Use Case |
|------|-------------|----------|
| [`01_hello.py`](quickstart/01_hello.py) | **Basic sandbox ops** — create, execute commands, lifecycle | SDK onboarding |
| [`02_file_ops.py`](quickstart/02_file_ops.py) | **File operations** — read/write, directories, binary files | Data exchange |
| [`03_web_service.py`](quickstart/03_web_service.py) | **Web service** — start Express server, get public URL | Web dev, API testing |
| [`04_data_analysis.py`](quickstart/04_data_analysis.py) | **Data analysis** — upload CSV, pandas analysis, run_code | Data science |
| [`05_decorator_usage.py`](quickstart/05_decorator_usage.py) | **@sandbox decorator** — declarative remote execution | Simplified calls |

### agents/ — Agent Integration

| File | Description | Use Case |
|------|-------------|----------|
| [`codex_agent.py`](agents/codex_agent.py) | **Codex Agent** — AI code generation & execution | AI programming |
| [`browser_automation.py`](agents/browser_automation.py) | **Browser automation** — Playwright scraping & screenshots | Web scraping |

### compat-demos/ — Compatibility Layer

| File | Description | Use Case |
|------|-------------|----------|
| [`e2b_data_analysis.py`](compat-demos/e2b_data_analysis.py) | **E2B-style data analysis** | E2B migration |
| [`e2b_web_scraper.py`](compat-demos/e2b_web_scraper.py) | **E2B-style web scraping** | E2B migration |
| [`modal_compute.py`](compat-demos/modal_compute.py) | **Modal-style scientific computing** | Modal migration |
| [`modal_data_analysis.py`](compat-demos/modal_data_analysis.py) | **Modal-style data analysis** | Modal migration |
| [`comparison.py`](compat-demos/comparison.py) | **E2B vs Modal style comparison** | API style selection |

## Running Examples

```bash
# Basic example
python examples/quickstart/01_hello.py

# Data analysis
python examples/quickstart/04_data_analysis.py

# @sandbox decorator
python examples/quickstart/05_decorator_usage.py

# E2B compatibility
python examples/compat-demos/e2b_data_analysis.py
```

## Core API Reference

### Execution Methods

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(template="base", api_key="...") as sandbox:

    # 1. Bare shell — sandbox.run(cmd)
    proc = await sandbox.run("echo hello")
    print(proc.stdout, proc.exit_code)

    # 2. Code interpreter — sandbox.run_code(code)
    code_result = await sandbox.run_code("print(1 + 1)")
    print(code_result.text)   # "2"

    # 3. Named command — sandbox.custom(name, **kwargs)
    #    Resolves template custom_commands (A) then SandboxServer (B)
    cmd_result = await sandbox.custom("hello", name="Alice")
    print(cmd_result.value)   # command return value
    print(cmd_result.source)  # "template" or "server"
```

> **E2B compatibility:** `sandbox.commands.run(cmd)` is the low-level entry that `sandbox.run()` delegates to. Existing E2B code continues to work.

### File Operations

```python
    # Write and read files
    await sandbox.files.write("/app/data.txt", "content")
    content = await sandbox.files.read("/app/data.txt")
```

### Network

```python
    # Get public URL for a port
    url = sandbox.network.get_url(3000)
```

### Declarative Decorator

```python
from easy_sandbox.declarative import sandbox

@sandbox(template="code-interpreter", packages=["numpy"])
def compute(n: int) -> float:
    import numpy as np
    return float(np.random.random(n).mean())

result = compute(1000)  # runs in a remote sandbox automatically
```
