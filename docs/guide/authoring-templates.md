# 编写模板

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

本文档介绍如何创建自定义 Easy Sandbox 模板，包括目录结构、字段参考、能力声明、自定义命令和发布流程。

---

## 模板目录结构

一个完整的模板目录结构如下：

```text
my-template/
├── template.yaml      # 必须 — 模板定义
├── Dockerfile         # 可选 — 自定义 Docker 构建（优先于 template.yaml 中的构建步骤）
├── commands.py        # 可选 — 通过 @sandbox.register 注册自定义命令
└── README.md          # 可选 — 模板说明
```

`template.yaml` 是唯一必需的文件。

---

## template.yaml 基础示例

```yaml
name: my-python-template
version: "1.0.0"
description: "Python 数据分析环境，预装 pandas 和 matplotlib"

base: python:3.11-slim

system_packages:
  - curl
  - git

python_packages:
  - pandas
  - matplotlib
  - numpy

env:
  PYTHONUNBUFFERED: "1"
  APP_DIR: "/app"

capabilities:
  - shell
  - files
  - code
  - terminal

ports:
  - 8080
```

---

## 字段参考

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | `str` | ✅ | — | 模板名称 |
| `version` | `str` | ❌ | `"1.0.0"` | 语义版本号 |
| `description` | `str` | ❌ | `""` | 模板描述 |
| `base` | `str` | ❌ | `"ubuntu:22.04"` | 基础 Docker 镜像 |
| `system_packages` | `list[str]` | ❌ | `[]` | apt 安装的系统包 |
| `python_packages` | `list[str]` | ❌ | `[]` | pip 安装的 Python 包 |
| `node_packages` | `list[str]` | ❌ | `[]` | npm 全局安装的 Node 包 |
| `commands` | `list[str]` | ❌ | `[]` | 构建时执行的 Shell 命令 |
| `env` | `dict[str, str]` | ❌ | `{}` | 环境变量 |
| `copy_files` | `dict[str, str]` | ❌ | `{}` | 文件复制映射（src → dst） |
| `cpu_count` | `int` | ❌ | `None` | 默认 CPU 核数 |
| `memory_mb` | `int` | ❌ | `None` | 默认内存 MB |
| `ports` | `list[int]` | ❌ | `[]` | 暴露的端口列表 |
| `author` | `str` | ❌ | `""` | 作者 |
| `license` | `str` | ❌ | `""` | 许可证 |
| `tags` | `list[str]` | ❌ | `[]` | 标签 |
| `capabilities` | `list[str]` | ❌ | `None` | 能力声明（见下文） |
| `custom_commands` | `dict` | ❌ | `{}` | 自定义命令（见下文） |

详细的字段定义参见 [template.yaml 规范](../reference/template-yaml-spec.md)。

---

## 能力声明

通过 `capabilities` 字段声明模板支持的运行时能力：

```yaml
capabilities:
  - shell      # Shell 命令执行
  - files      # 文件系统操作
  - code       # Code Interpreter
  - terminal   # PTY 终端
  - ports      # 端口网络访问
```

**标准能力集**：`shell`、`files`、`code`、`terminal`、`ports`

**默认能力集**（不声明 `capabilities` 时）：`shell`、`files`、`code`

`terminal` 和 `ports` 必须在模板中显式声明才能使用。SDK 在调用相关功能前会通过 `check_capability()` 函数进行门禁检查，若能力未启用会抛出 `CapabilityNotSupportedError`（E3004）。

> **Server 端能力组**：服务端有 8 个能力组（CORE, COMMANDS, FILE_OPS, PROCESS, TERMINAL, SYSTEM, DEV_TOOLS, BROWSER）。其中 TERMINAL 默认启用，仅 DEV_TOOLS 和 BROWSER 默认禁用（`_DEFAULT_DISABLED = {DEV_TOOLS, BROWSER}`）。

---

## 自定义命令

### 在 template.yaml 中声明

```yaml
custom_commands:
  dev:
    cmd: "python -m flask run --host=0.0.0.0 --port={port}"
    description: "启动开发服务器"
    cwd: "/app"
    timeout: 300
    env:
      FLASK_ENV: development
    args:
      - name: port
        type: string
        required: false
        default: "8080"
        description: "监听端口"

  test:
    cmd: "python -m pytest {path} -v"
    description: "运行测试"
    cwd: "/app"
    timeout: 120
    args:
      - name: path
        type: string
        required: false
        default: "tests/"
        description: "测试路径"
```

**命令字段**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cmd` | `str` | — | Shell 命令模板，用 `{name}` 引用参数 |
| `description` | `str` | `""` | 命令描述 |
| `cwd` | `str` | `"/app"` | 工作目录 |
| `timeout` | `int` | `60` | 超时秒数 |
| `env` | `dict` | `{}` | 环境变量 |
| `args` | `list` | `[]` | 参数定义 |

**参数字段**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | — | 参数名（对应 `{placeholder}`） |
| `type` | `str` | `"string"` | 类型：`string`/`integer`/`float`/`boolean` |
| `required` | `bool` | `false` | 是否必需 |
| `default` | `str` | `None` | 默认值 |
| `description` | `str` | `""` | 参数描述 |

### 通过 @sandbox.register 注册

在 `commands.py` 中通过装饰器注册 Python 函数作为自定义命令：

```python
from easy_sandbox.declarative import sandbox

@sandbox.register
def demo(x: int, y: str) -> str:
    return f"{y}={x}"

# 启用内置路由
sandbox.register.upload()    # POST /upload
sandbox.register.download()  # GET  /download
```

注册的命令通过沙箱内 HTTP server 提供服务，客户端通过 `sandbox.run_command()` 或 `ebx run` 调用。

---

## Dockerfile 自定义

当需要更精细的控制时，可以直接提供 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pandas matplotlib numpy

WORKDIR /app

ENV PYTHONUNBUFFERED=1
```

`Dockerfile` 存在时优先于 `template.yaml` 中的构建步骤（`system_packages`、`python_packages`、`commands` 等）。

---

## 发布模板

### 发布到 GitHub

将模板目录推送到 GitHub 仓库，其他用户即可通过以下命令安装：

```bash
ebx template install your-org/your-template
```

### 本地安装

```bash
ebx template install ./my-template --registry-type local
```

模板安装后保存在 `~/.ebx/templates/` 目录下。

---

## 下一步

- [使用模板](using-templates.md) — 安装和使用模板
- [template.yaml 规范](../reference/template-yaml-spec.md) — 所有字段精确定义
- [声明式用法](declarative-usage.md) — @sandbox 装饰器
