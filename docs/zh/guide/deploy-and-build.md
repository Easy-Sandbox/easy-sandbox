# 部署与构建

Easy Sandbox 提供三种构建与部署方式：**模板生命周期**（`ebx template init` → `ebx deploy` → `ebx create`）、**仅 SDK 的沙箱内 Agent 部署**，以及 **Image 链式构建**。

---

## 模板生命周期

一个沙箱模板要经过三步，每一步只做一件事，**“模板是什么”写在 `template.yaml` 里**，而不是命令行参数里。

| 步骤 | 命令 | 输入 | 是否用 AI |
|------|------|------|-----------|
| 1. 编写 | `ebx template init` / `ebx template init "描述"` / `ebx template init --adopt [目录]` | 脚手架 case、一句描述，或一个已有项目 | 可选 |
| 2. 发布 | `ebx deploy [PATH]` | 模板目录（`Dockerfile`、`template.yaml` 等） | 从不 |
| 3. 启动 | `ebx create --template <TEMPLATE_ID>` | 模板 ID | 从不 |

`ebx create "描述"` 是 1 + 2 + 3 合在一条命令里（推送任何东西之前都会先确认）。

```bash
# 1a. 已有项目：文件写回同一个目录
ebx template init --adopt ./app --hint "监听 8080"
ebx deploy ./app --acr-namespace my-ns

# 1b. 用一句话新建项目：文件落在 ./<name>/
ebx template init "一个 Python 数据分析环境"
ebx deploy ./<name> --acr-namespace my-ns

ebx create --template <TEMPLATE_ID>               # 3. 启动沙箱
```

`--adopt` 会把项目源码的一份副本发给模型（密钥已排除），写回的只有模板文件。规则、预览和 `--dry-run` 见 [编写模板 — 适配已有项目](authoring-templates.md#适配已有项目)。

否则你要在部署时对 AI 说明的那些内容——服务是什么、端口、资源、能力、环境变量、自定义命令——都在第 1 步写进 `template.yaml`（以及 `Dockerfile` / `commands.py`），在那里可以审阅、纳入版本管理。描述只需要在编写时说一次。

### ebx deploy — 发布步骤

`ebx deploy` 是一条**固定、确定性的流水线**，**不需要 LLM，也不需要 LLM Key**：

1. `docker build` 项目的 `Dockerfile`
2. 把镜像推送到阿里云 ACR
3. 注册为模板（`CreateTemplate`）
4. 等待模板就绪

它与 `ebx template deploy DIR` 是同一条流水线，只是 `PATH` 默认为 `.`，并接受后者的全部选项（`--acr-namespace`、`--alias`、`--yes`、`-v/--verbose`、`--region` 等）。它从 `template.yaml` 读取模板 `name`（未指定 `--acr-repo` 时用作 ACR 仓库名）、`resources.cpu`、`resources.memory` 和 `generation`；命令行选项优先。

交互式终端上，构建、推送和等待 READY 各自显示 `message... 12s` 标题，标题下方以灰色滚动最近四行日志，长时间的 `docker build` 不会只剩一个停住的转圈。某一步暂时没有输出时，耗时仍每秒刷新。`--verbose` 改为逐行打印完整日志。`--json`、`--quiet`、CI 和非 TTY 仍只留一行 progress。创建沙箱、上传、下载、拉取模板、用镜像注册模板、安装 coding-agent，以及 `ebx kill --all`，在终端上使用同一套会走动的标题。灰色行只放安全文本（路径、阶段、构建输出）；文件内容和凭证不会出现。这些命令在非终端上不为标题打印任何内容。

```bash
ebx deploy --acr-namespace my-ns          # 发布 ./（需要 ./Dockerfile）
ebx deploy ./my-template --yes -v         # 非交互，输出调试日志
```

目录里没有 `Dockerfile` 时命令会停下，并提示使用 `ebx template init --adopt`（已有项目）、`ebx template init "描述"`，或 `ebx template init -t`。

> **迁移说明。** 旧版本的 `ebx deploy ./p "说明"` 会在云端沙箱里启动 Agent，并要求 `BAILIAN_CODING_PLAN_API_KEY` / `DASHSCOPE_API_KEY` / `OPENAI_API_KEY`。`ebx deploy` 不再接受说明文字：请用 `ebx template init --adopt` 或 `ebx template init "描述"` 编写模板，再用 `ebx deploy` 发布。沙箱内 Agent 流程仍以 SDK 接口 `Sandbox.deploy()` 保留（见下）。`--traditional` 已弃用并被忽略。

---

## Sandbox.deploy（仅 SDK）

`Sandbox.deploy()` 会启动 `qwen-code` 模板沙箱、上传项目，由沙箱内的 Agent 分析、安装依赖、构建并启动服务。仅提供 Python API。

Agent 会自动：
1. 创建 `qwen-code` 模板的沙箱（默认 2 CPU / 4096MB 内存）
2. 上传项目目录
3. 分析项目结构和依赖
4. 安装依赖并构建
5. 启动服务

### 用法

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.deploy(
    project_path="./my-flask-app",
    description="部署这个 Flask 应用到 8080 端口",
    max_wall_time="10m",         # agent 最大运行时间（默认 10m）
    max_session_turns=100,       # qwen-code 会话轮次上限（默认 100）
    timeout=900,                 # 沙箱超时秒数（默认 900）
    cpu=2,                       # CPU 核数（默认 2）
    memory=4096,                 # 内存 MB（默认 4096）
    on_progress=lambda msg: print(f"[进度] {msg}"),
)

# sandbox 仍在运行，可继续操作
print(f"沙箱 ID: {sandbox.id}")
print(f"部署结果: {sandbox._deploy_result}")
```

### LLM Key 配置

`Sandbox.deploy()`（不是 `ebx deploy`）依赖 LLM API Key，SDK 按以下顺序查找：

1. `llm_api_key=` 参数
2. 进程环境变量：`EBX_LLM_API_KEY`，然后 `BAILIAN_CODING_PLAN_API_KEY`、`DASHSCOPE_API_KEY`、`OPENAI_API_KEY`，然后旧的 `EBX_QWEN_CODE_API_KEY`
3. `./.env` 里的同名变量
4. `ebx config set llm_api_key` 保存的 `EBX_LLM_API_KEY`（`~/.ebx/.env`）

地址和模型走同样的层次（`openai_base_url=` / `openai_model=`，然后 `EBX_LLM_BASE_URL` / `OPENAI_BASE_URL` 与 `EBX_LLM_MODEL` / `OPENAI_MODEL`，然后 `./.env` 里的同名变量，然后 `~/.ebx/config.toml`）。空白值不算已配置。完整表见 [凭证解析](../reference/configuration.md#凭证解析)。

若未找到密钥，抛出 `DeployLLMKeyMissingError`（E7001）。`ebx deploy` 不会抛出它。

---

## Image 链式 API

`Image` 类提供类似 Modal 的链式 API，用于声明式构建 Docker 镜像。

### 基础用法

```python
from easy_sandbox.api.image import Image

image = (
    Image.from_template("python-base")
    .pip_install("flask", "sqlalchemy")
    .apt_install("postgresql-client")
    .env(DATABASE_URL="postgresql://localhost/mydb")
    .run_command("echo 'setup complete'")
)
```

### 从 Docker 镜像开始

```python
image = (
    Image.from_image("python:3.11-slim")
    .pip_install("pandas", "matplotlib")
    .workdir("/app")
    .expose(8080)
    .entrypoint("python app.py")
)
```

### 链式方法

| 方法 | 说明 |
|------|------|
| `Image.from_template(name)` | 基于已有模板 |
| `Image.from_image(ref)` | 基于 Docker 镜像 |
| `.pip_install(*pkgs)` | 安装 pip 包 |
| `.apt_install(*pkgs)` | 安装系统包 |
| `.copy_local(src, dst)` | 复制本地文件 |
| `.env(**kv)` | 设置环境变量 |
| `.run_command(cmd)` | 构建时执行命令 |
| `.workdir(path)` | 设置工作目录 |
| `.expose(*ports)` | 暴露端口 |
| `.entrypoint(cmd)` | 设置入口命令 |

### 生成 Dockerfile

```python
dockerfile = image.to_dockerfile()
print(dockerfile)
# FROM python-base
# RUN pip install --no-cache-dir flask sqlalchemy
# RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*
# ENV DATABASE_URL=postgresql://localhost/mydb
# RUN echo 'setup complete'
```

### 构建为模板

```python
template_info = await image.build(
    alias="my-flask-app",  # 模板别名
    timeout=600,           # 构建超时秒数
    cpu_count=2,           # 默认 CPU
    memory_mb=4096,        # 默认内存
    start_cmd="python app.py",  # 启动命令
)

print(f"Template ID: {template_info.template_id}")
print(f"Build status: {template_info.build_status.value}")

# 使用构建的模板创建沙箱
sandbox = await Sandbox.create(template=template_info.template_id)
```

### 与 @sandbox 装饰器结合

```python
from easy_sandbox.declarative import sandbox
from easy_sandbox.api.image import Image

image = Image.from_template("python-base").pip_install("flask")

@sandbox(image=image)
def my_app():
    from flask import Flask
    return "Flask ready"
```

`image` 参数优先于 `template` 参数。

---

## Docker 构建流程

Image 构建的内部流程：

1. **生成 Dockerfile**：`image.to_dockerfile()` 将链式调用转换为 Dockerfile
2. **创建 HTTP 客户端**：使用配置的认证凭证
3. **调用 TemplateManager.build()**：上传 Dockerfile 到平台
4. **等待构建完成**：轮询构建状态直到 `ready` 或 `error`
5. **返回 TemplateInfo**：包含 `template_id` 和构建状态

### 构建相关错误

| 错误 | 错误码 | 场景 |
|------|--------|------|
| `TemplateBuildError` | E7010 | 模板构建失败 |
| `TemplateBuildTimeoutError` | E7011 | 构建超时 |
| `DockerBuildError` | E7020 | 本地 Docker 构建失败 |
| `ACRPushError` | E7021 | 推送到 ACR 失败 |
| `ACRLoginError` | E7022 | ACR 登录失败 |

---

## 下一步

- [编写模板](authoring-templates.md) — 通过 template.yaml 定义模板
- [SDK 使用指南](sdk-usage.md) — SDK 完整用法
- [API 参考](../reference/api-reference.md) — Image 类 API 详情
