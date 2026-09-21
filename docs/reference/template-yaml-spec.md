# template.yaml 规范

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

本文档精确定义 `template.yaml` 文件的所有字段（使用者视角）。

---

## 文件位置

模板的 `template.yaml` 位于模板目录根下：

```text
my-template/
├── template.yaml    ← 本文档定义的文件
├── Dockerfile       # 可选
└── ...
```

安装后位于 `~/.ebx/templates/<template-name>/template.yaml`。

---

## 完整字段定义

### 基础信息

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | `str` | ✅ | — | 模板名称，用于 `--template` 参数 |
| `version` | `str` | ❌ | `"1.0.0"` | 语义版本号 |
| `description` | `str` | ❌ | `""` | 模板描述 |
| `author` | `str` | ❌ | `""` | 作者 |
| `license` | `str` | ❌ | `""` | 许可证标识（如 `"MIT"`） |
| `tags` | `list[str]` | ❌ | `[]` | 分类标签 |

### 构建配置

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `base` | `str` | ❌ | `"ubuntu:22.04"` | 基础 Docker 镜像 |
| `system_packages` | `list[str]` | ❌ | `[]` | 通过 `apt-get install` 安装的系统包 |
| `python_packages` | `list[str]` | ❌ | `[]` | 通过 `pip install` 安装的 Python 包 |
| `node_packages` | `list[str]` | ❌ | `[]` | 通过 `npm install -g` 安装的 Node.js 包 |
| `commands` | `list[str]` | ❌ | `[]` | 构建时顺序执行的 Shell 命令（每条生成一个 `RUN` 指令） |
| `copy_files` | `dict[str, str]` | ❌ | `{}` | 文件复制映射，键为源路径，值为目标路径（生成 `COPY` 指令） |

> 当模板目录中存在 `Dockerfile` 时，`Dockerfile` 优先于上述构建字段。

### 运行时配置

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `env` | `dict[str, str]` | ❌ | `{}` | 环境变量（生成 `ENV` 指令） |
| `ports` | `list[int]` | ❌ | `[]` | 暴露的端口（生成 `EXPOSE` 指令） |

### 资源规格

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `cpu_count` | `int` | ❌ | `None` | 默认 CPU 核数 |
| `memory_mb` | `int` | ❌ | `None` | 默认内存 MB |

### 能力声明

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `capabilities` | `list[str] \| null` | ❌ | `null` | 运行时能力列表 |

**可选值**（标准能力集 `STANDARD_CAPABILITIES`）：

| 能力 | 说明 |
|------|------|
| `shell` | Shell 命令执行（`commands.run()` 等） |
| `files` | 文件系统操作（`files.read()` 等） |
| `code` | Code Interpreter 代码执行（`run_code()` 等） |
| `terminal` | PTY 终端会话（`get_terminal()`） |
| `ports` | 端口 URL 访问（`network.get_url()` 等） |

**行为规则**：
- `null`（未声明）→ 使用默认能力集 `{shell, files, code}`
- 显式列表 → 仅启用列出的能力（可以是标准能力集的子集或超集）
- 列表中的值必须是标准能力集中的项，否则校验失败（抛出 `TemplateParseError` E2004）

### 自定义命令

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `custom_commands` | `dict[str, Command]` | ❌ | `{}` | 命名命令映射 |

**Command 结构**：

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `cmd` | `str` | ✅ | — | Shell 命令模板，支持 `{placeholder}` 令牌 |
| `description` | `str` | ❌ | `""` | 命令描述 |
| `cwd` | `str` | ❌ | `"/app"` | 工作目录 |
| `timeout` | `int` | ❌ | `60` | 超时秒数 |
| `env` | `dict[str, str]` | ❌ | `{}` | 命令特定的环境变量 |
| `args` | `list[Arg]` | ❌ | `[]` | 参数定义列表 |

**Arg 结构**：

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | `str` | ✅ | — | 参数名（对应 `cmd` 中的 `{name}` 占位符） |
| `type` | `str` | ❌ | `"string"` | 类型：`string` / `integer` / `float` / `boolean` |
| `required` | `bool` | ❌ | `false` | 是否必需 |
| `default` | `str \| null` | ❌ | `null` | 默认值（字符串形式） |
| `description` | `str` | ❌ | `""` | 参数描述 |

---

## 完整示例

```yaml
name: flask-web
version: "2.0.0"
description: "Flask Web 开发环境"
author: "Easy Sandbox Team"
license: "MIT"
tags:
  - python
  - web
  - flask

base: python:3.11-slim

system_packages:
  - curl
  - git
  - postgresql-client

python_packages:
  - flask>=3.0
  - sqlalchemy>=2.0
  - gunicorn

commands:
  - "mkdir -p /app"

env:
  PYTHONUNBUFFERED: "1"
  FLASK_ENV: "development"

copy_files:
  ./requirements.txt: /app/requirements.txt

ports:
  - 5000
  - 8080

cpu_count: 2
memory_mb: 2048

capabilities:
  - shell
  - files
  - code
  - terminal
  - ports

custom_commands:
  dev:
    cmd: "flask run --host=0.0.0.0 --port={port}"
    description: "启动 Flask 开发服务器"
    cwd: "/app"
    timeout: 0
    env:
      FLASK_DEBUG: "1"
    args:
      - name: port
        type: string
        required: false
        default: "5000"
        description: "监听端口"

  test:
    cmd: "python -m pytest {path} -v --tb=short"
    description: "运行 pytest 测试"
    cwd: "/app"
    timeout: 120
    args:
      - name: path
        type: string
        required: false
        default: "tests/"
        description: "测试文件路径"

  migrate:
    cmd: "flask db upgrade"
    description: "执行数据库迁移"
    cwd: "/app"
    timeout: 60
```

---

## Dockerfile 转换

`template.yaml` 中的构建字段按以下顺序生成 Dockerfile 指令：

1. `base` → `FROM {base}`
2. `system_packages` → `RUN apt-get update && apt-get install -y {pkgs} && rm -rf /var/lib/apt/lists/*`
3. `python_packages` → `RUN pip install --no-cache-dir {pkgs}`
4. `node_packages` → `RUN npm install -g {pkgs}`
5. `commands` → 每条 `RUN {cmd}`
6. `env` → 每条 `ENV {key}={value}`
7. `copy_files` → 每条 `COPY {src} {dst}`
