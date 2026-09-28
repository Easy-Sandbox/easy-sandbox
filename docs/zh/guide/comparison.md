# 与其他沙箱工具的对比

本文档客观对比 Easy Sandbox (ebx) 与其他主流沙箱及远程执行平台：E2B、Modal、Docker Sandbox。

---

## 定位与场景

| 平台 | 核心定位 | 主要使用场景 |
|------|---------|-------------|
| **Easy Sandbox (ebx)** | 基于阿里云 FC 的 E2B 兼容云沙箱 SDK | AI Agent 代码执行、云端开发环境、模板驱动沙箱 |
| **E2B** | 为 AI 应用构建的云沙箱 | AI Agent 工具调用、代码解释器、LLM 工作流中的数据分析 |
| **Modal** | 面向数据/ML 流水线的 Serverless 计算 | GPU 工作负载、批处理、模型推理、定时任务 |
| **Docker Sandbox** | 基于容器的本地/远程隔离 | 本地开发、CI/CD、可复现环境 |

---

## SDK 对比

| 维度 | Easy Sandbox | E2B | Modal |
|------|-------------|-----|-------|
| **语言** | Python | Python, JS/TS, Kotlin, Go | Python |
| **安装** | `pip install easy-sandbox` | `pip install e2b` | `pip install modal` |
| **沙箱创建** | `await Sandbox.create()` | `await Sandbox.create()` | `@app.function()` 装饰器 |
| **同步支持** | `Sandbox.create_sync()` | `Sandbox()`（同步类） | N/A（原生异步） |
| **命令执行** | `sandbox.commands.run()` | `sandbox.commands.run()` | 远程函数调用 |
| **文件操作** | `sandbox.files.read/write/list` | `sandbox.files.read/write/list` | `modal.Volume` 挂载 |
| **代码执行** | `sandbox.run_code()` | `sandbox.run_code()` | 远程函数执行 |
| **自定义命令** | `sandbox.custom(name, **kwargs)` | N/A | N/A |
| **网络访问** | `sandbox.network.get_host()` | `sandbox.get_host()` | 内置 URL 路由 |
| **终端 (PTY)** | `sandbox.get_terminal()` | `sandbox.terminal.start()` | `modal shell` |
| **E2B 兼容层** | `from easy_sandbox.compat import Sandbox` | 原生 | N/A |
| **认证方式** | API Key、阿里云 AK/SK | API Key | Token |

### 代码示例

**Easy Sandbox：**

```python
from easy_sandbox.api.sandbox import Sandbox

async with await Sandbox.create(template="python-hello") as sb:
    result = await sb.run_code("print('hello')")
    print(result.text)
```

**E2B：**

```python
from e2b import Sandbox

sandbox = Sandbox()
result = sandbox.run_code("print('hello')")
print(result.text)
sandbox.kill()
```

**Modal：**

```python
import modal
app = modal.App("example")

@app.function()
def hello():
    print("hello")
```

### 使用风格对比

Easy Sandbox 同时支持 **命令式**（E2B 风格）和 **声明式**（Modal 风格）两种编程范式：

| 维度 | E2B 风格（命令式） | Modal 风格（声明式） |
|------|-------------------|---------------------|
| **创建** | 手动 `Sandbox.create()` | 自动（`@sandbox` 装饰器） |
| **依赖安装** | `sb.run("pip install ...")` | 装饰器参数 `packages=[...]` |
| **数据传输** | `files.write()` + `files.read()` | 函数参数和返回值自动序列化 |
| **执行** | `sb.run()` / `sb.run_code()` | 直接调用函数 |
| **结果获取** | 解析 stdout / 读取文件 | 函数返回值 |
| **生命周期** | 手动 `kill()` 或 `async with` | 自动管理 |
| **适用场景** | 细粒度控制、长时间交互、多步骤流程 | 简单计算任务、批处理、函数即服务 |

**E2B 风格（命令式）— 细粒度控制：**

```python
from easy_sandbox.api.sandbox import Sandbox

async with await Sandbox.create() as sb:
    await sb.run("pip install pandas")
    await sb.files.write("/app/data.csv", csv_content)
    result = await sb.run("python3 /app/analyze.py")
    report = await sb.files.read("/app/report.txt")
```

**Modal 风格（声明式）— 像调本地函数：**

```python
from easy_sandbox.declarative import sandbox

@sandbox(packages=["pandas"])
def analyze(data: list[dict]) -> dict:
    import pandas as pd
    df = pd.DataFrame(data)
    return {"mean": df["value"].mean(), "count": len(df)}

# 调用方式和本地函数一样，自动在远程沙箱中执行
result = analyze(my_data)
```

> 完整示例参见 [`examples/compat-demos/comparison.py`](../../examples/compat-demos/comparison.py)

---

## CLI 对比

| 维度 | ebx | e2b CLI | modal CLI |
|------|-----|---------|-----------|
| **安装** | `pip install easy-sandbox[cli]` | `npm i -g @e2b/cli` | `pip install modal` |
| **运行时** | Python (Click) | Node.js | Python (Typer) |
| **创建沙箱** | `ebx create` | `e2b sandbox create` | N/A（代码驱动） |
| **列出沙箱** | `ebx sandbox list` | `e2b sandbox list` | `modal container list` |
| **连接沙箱** | `ebx connect <id>` | `e2b sandbox connect` | `modal shell` |
| **模板构建** | `ebx template build` | `e2b template build` | N/A |
| **模板部署** | `ebx template deploy` | `e2b template build --push` | N/A |
| **认证设置** | 通过环境变量（`.env`）| `e2b auth login` | `modal token set` |
| **MCP 集成** | `ebx mcp install` | N/A | N/A |
| **密钥管理** | 通过环境变量（`.env`）| N/A | `modal secret create` |

---

## 基础设施

| 维度 | Easy Sandbox | E2B | Modal | Docker Sandbox |
|------|-------------|-----|-------|----------------|
| **隔离技术** | 容器（阿里云 FC） | Firecracker MicroVM | 容器（gVisor） | 容器（runc/containerd） |
| **启动时间** | 秒级 | ~150ms（MicroVM） | 秒级（冷启动）/ 毫秒级（热启动） | 秒级 |
| **部署区域** | 阿里云区域（cn-hangzhou 等） | 美国、欧洲 | 美国（aws-us-east-1 等） | 自托管 |
| **平台类型** | 托管（阿里云） | 托管（E2B Cloud） | 托管（Modal Cloud） | 自托管 / Docker Desktop |
| **GPU 支持** | 通过模板配置 | N/A | 原生（A10G, A100, H100） | 通过 NVIDIA Container Toolkit |
| **最大生命周期** | 可配置（最长 86400 秒） | 可配置 | 按调用计 | 无限制 |
| **计费** | 阿里云 FC 计费 | 按沙箱秒计费 | 按秒计费 | 基础设施成本 |

---

## Easy Sandbox 的独特能力

### E2B 协议兼容

Easy Sandbox 在 API 层面与 E2B Python SDK 保持兼容。现有 E2B 代码仅需极少改动即可迁移：

```python
# 最小迁移——只需改变导入
from easy_sandbox.compat import Sandbox  # 可替代 e2b.Sandbox
```

完整迁移指南参见[从 E2B 迁移](migrate-from-e2b.md)。

### 阿里云生态集成

| 扩展 | 说明 |
|------|------|
| **AK/SK 认证** | 原生阿里云 AccessKey 认证 |
| **OSS 挂载** | 将阿里云 OSS Bucket 挂载到沙箱文件系统 |
| **VPC** | 将沙箱接入阿里云 VPC 网络 |
| **自定义域名** | 为沙箱服务绑定自定义域名 |
| **ACR** | 构建并推送模板镜像到阿里云容器镜像服务 |

### 自定义命令

模板可以在 `template.yaml` 中定义自定义命令，并通过容器内 Server SDK 实现。SDK 通过统一 API 暴露这些命令：

```python
result = await sandbox.custom("analyze", data="input.csv")
```

此能力在 E2B 和 Modal 中不可用。

### MCP Server 集成

Easy Sandbox 内置 MCP (Model Context Protocol) Server，使 AI IDE（Cursor、Claude Desktop、VS Code）可以直接操作沙箱：

```bash
ebx mcp install --target cursor
```

提供 7 个工具：`create_sandbox`、`run_code`、`run_command`、`read_file`、`write_file`、`list_files`、`kill_sandbox`。

### 声明式沙箱装饰器

```python
from easy_sandbox import sandbox

@sandbox(template="python-hello", timeout=60)
async def my_task():
    ...
```

---

## 其他平台（简要）

| 平台 | 说明 |
|------|------|
| **Daytona** | 云开发环境平台。2026 年转为闭源，此前提供开源自托管方案。 |
| **Google Gemini Sandbox** | Google Cloud Gemini Enterprise Agent Platform（原 Vertex AI）中的代码执行沙箱。托管服务，与 Google Cloud 生态紧密耦合。 |
| **Cloudflare Workers** | 使用 V8 Isolates 进行进程内隔离，亚毫秒级冷启动。侧重边缘计算，非通用沙箱。 |
| **Fly.io Machines** | 基于 Firecracker 的临时 VM，支持完整 Linux 环境和快速启动。API 驱动，无专用沙箱 SDK。 |

---

## 总结

| 考量因素 | 推荐平台 |
|---------|---------|
| 从 E2B 迁移到阿里云 | **Easy Sandbox**——协议兼容，代码改动最小 |
| AI Agent 代码执行需求 | **Easy Sandbox** 或 **E2B**——专为沙箱构建的 SDK |
| GPU 密集型 ML/推理工作负载 | **Modal**——原生 GPU 支持和 Serverless 弹性 |
| 本地开发隔离 | **Docker**——行业标准，自托管 |
| 阿里云生态集成 | **Easy Sandbox**——原生 OSS、VPC、ACR、AK/SK 支持 |
| 基于 MCP 的 AI IDE 集成 | **Easy Sandbox**——内置 MCP Server |

---

## 延伸阅读

- [从 E2B 迁移](migrate-from-e2b.md)
- [SDK 使用指南](sdk-usage.md)
- [CLI 教程](cli-tutorial.md)
- [MCP 集成](mcp-integration.md)
- [认证详解](authentication.md)
