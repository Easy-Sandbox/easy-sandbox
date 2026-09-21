# 部署与构建

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

Easy Sandbox 提供两种构建和部署机制：**NL（自然语言）部署** 和 **Image 链式构建**。

---

## ebx deploy（NL 部署）

`ebx deploy` 使用 qwen-code agent 自动分析项目并完成部署。

### CLI 用法

```bash
ebx deploy <PROJECT_PATH> <DESCRIPTION> [选项]
```

```bash
ebx deploy ./my-flask-app "部署这个 Flask 应用到 8080 端口"
```

Agent 会自动：
1. 创建 `qwen-code` 模板的沙箱（默认 2 CPU / 4096MB 内存）
2. 上传项目目录
3. 分析项目结构和依赖
4. 安装依赖并构建
5. 启动服务

### SDK 用法

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.deploy(
    project_path="./my-flask-app",
    description="部署这个 Flask 应用到 8080 端口",
    max_wall_time="10m",         # agent 最大运行时间（默认 10m）
    max_tool_calls=100,          # agent 最大工具调用次数
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

部署功能依赖 LLM API Key，SDK 按以下顺序查找：

1. `llm_api_key` 参数
2. `BAILIAN_CODING_PLAN_API_KEY` 环境变量
3. `DASHSCOPE_API_KEY` 环境变量
4. `OPENAI_API_KEY` 环境变量
5. `ebx config` 中的 `llm_api_key`

若未找到，抛出 `DeployLLMKeyMissingError`（E7001）。

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
