# Easy Sandbox — 完整设计文档

> **版本**：v1.1 | **最后更新**：2026-09-02
>
> 本文档整合了 Easy Sandbox 项目的所有设计决策，是一份可直接交给团队执行的完整技术蓝图。

---

## 一、项目定位与核心理念

### 1.1 项目基本信息

> **更名注记**：本项目已从 Serverless Sandbox 完成全量改名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

| 项目 | 值 |
|------|-----|
| **品牌名称** | Easy Sandbox |
| **GitHub 仓库** | `easy-sandbox` |
| **CLI 命令** | `ebx`（简洁且语义明确） |
| **PyPI 包名** | `easy-sandbox`（`pip install easy-sandbox`），Python 导入名 `easy_sandbox` |
| **npm 包名** | `@easy-sandbox/sdk` |
| **定位** | 面向 AI Agent 的云端 Serverless 代码执行沙箱平台 |

### 1.2 我们要解决什么问题

E2B 是当前 AI Agent 沙箱领域的标杆产品，但在实际使用中存在十大痛点：

| # | 痛点 | 我们的解决方案 |
|---|------|---------------|
| 1 | **配置繁琐** — 需手动拼接 `E2B_API_URL` / `E2B_DOMAIN`，替换地域占位符 | Zero Config — SDK 只需 `region` 参数即可自动推导所有端点 |
| 2 | **资源泄漏** — 忘记 `kill()` 导致沙箱空跑计费 | Context Manager + 自动清理策略 + Session GC |
| 3 | **无复用机制** — 每次都 create → use → kill | SandboxPool 预热池 + Session 自动管理 |
| 4 | **无声明式配置** — 所有配置必须写在代码里 | `sandbox.yaml` + 配置文件 + 环境变量分层覆盖 |
| 5 | **FC Extensions 缺失** — VPC/OSS/域名需额外 SDK | 统一 SDK 覆盖 E2B 兼容 + 阿里云扩展 |
| 6 | **无 Agent 集成** — 缺少 MCP Server 和 Tool Schema | 内置 MCP Server + 一键安装到 IDE |
| 7 | **无 Skills 系统** — 不能封装和分发最佳实践 | Skills 注册/安装/分享生态 |
| 8 | **模板能力有限** — 仅 Dockerfile，无链式构建 | Image 链式构建器 + 模板继承 + GitHub tarball API 按 ref 分发 |
| 9 | **错误信息不友好** — 英文错误，无修复建议 | 结构化错误码 + 中英双语 + 修复建议 |
| 10 | **无结构化输出** — CLI 不支持 JSON | 全命令 `--json` 支持，AI 可直接解析 |

### 1.3 三大设计原则

1. **E2B 协议兼容** — L4 层 API 兼容 E2B 数据面协议，提供迁移辅助层 `from easy_sandbox.compat import Sandbox` 方便迁移用户（注意：需将同步调用改为 async 调用方式）；想用纯 E2B 的用户直接用 E2B SDK 即可
2. **AI-First** — 自然语言创建沙箱、沙箱内置 AI CLI 工具、MCP Server 是一等公民，不是事后补丁
3. **零配置默认** — 开箱即用，从安装到第一个沙箱运行不超过 3 行代码

### 1.4 与 E2B 的关系

Easy Sandbox **兼容 E2B 数据面协议**（Sandbox 生命周期、Commands、Filesystem、Code Interpreter），但**不是 E2B SDK 的替代品**。

**核心差异化价值**：Easy Sandbox 的价值在 E2B 协议之上 —— 装饰器模式（`@sandbox`）、自然语言创建沙箱、Skills 生态、沙箱内置 AI CLI 工具（Codex / Qwen CLI）、MCP Server 深度集成、阿里云 FC Extensions 等，是 E2B SDK 不具备的独有能力。

**迁移路径**：对于已有 E2B 用户，提供迁移辅助层简化迁移（需将同步调用改为 async 调用方式）：

```python
# E2B 原始代码
from e2b_code_interpreter import Sandbox
sb = Sandbox()

# 迁移到 Easy Sandbox — 通过迁移辅助层（需改为 async 调用）
from easy_sandbox.compat import Sandbox
sb = await Sandbox.create(template="code-interpreter")

# 推荐：使用 Easy Sandbox 原生 API，享受全部增强能力
from easy_sandbox import Sandbox
sb = await Sandbox.create(template="code-interpreter")
```

### 1.5 Quick Start — 快速上手

三步开始使用 Easy Sandbox：

**第一步：安装**

```bash
pip install easy-sandbox
```

**第二步：配置认证**

```bash
# 方式一：设置环境变量（推荐）
export SANDBOX_API_KEY=your-api-key

# 方式二：通过 CLI 登录
ebx auth login
```

**第三步：创建第一个沙箱**

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("print('Hello, Easy Sandbox!')")
    print(result.text)
    # 退出时自动销毁沙箱
```

或使用 CLI：

```bash
ebx create --template code-interpreter
ebx exec <sandbox-id> "python -c 'print(1+1)'"
ebx kill <sandbox-id>
```

---

## 二、系统架构

### 2.1 六层分层架构

Easy Sandbox SDK 采用六层分层架构，从底层传输到上层 AI 集成逐层抽象，每层职责单一、边界清晰，用户可在任意层级接入使用。

```mermaid
graph TD
    L6["L6 Agent Integration Layer\nAI 集成层 — 沙箱内置 AI CLI 工具封装 / MCP Server"]
    L5["L5 Declarative API Layer\n声明式 API 层 — @sandbox 装饰器 / sandbox.yaml"]
    L4["L4 High-Level API Layer\n高层便捷 API — Sandbox / SandboxPool / Image"]
    L3["L3 Extension Layer\n阿里云扩展层 — VPC / OSS / 域名 / NAS 挂载"]
    L2["L2 Core Protocol Layer\n核心协议层 — E2B 兼容协议 / HTTP REST + WebSocket"]
    L1["L1 Transport and Auth Layer\n传输与认证层 — HTTP 连接池 / API Key / AK-SK"]
    GW["阿里云 API Gateway"]
    FC["阿里云函数计算 FC 沙箱运行时"]
    L6 --> L5 --> L4 --> L3 --> L2 --> L1
    L1 --> GW
    L1 --> FC
```

### 2.2 各层职责

#### L1 — Transport & Auth Layer（传输与认证层）

| 模块 | 职责 |
|------|------|
| `transport.http` | 基于 httpx 封装 HTTPS 请求，连接池管理，超时/重试策略 |
| `transport.ws` | 基于 websockets 的长连接，心跳保活，自动重连 |
| `auth.api_key` | **API Key 认证（主路径）**：通过 `X-API-KEY` 请求头传递，环境变量 `SANDBOX_API_KEY` |
| `auth.ak_sk` | **AK/SK 认证（扩展）**：通过阿里云 AK/SK 兑换临时 API Key，或用于控制面 OpenAPI 调用 |
| `auth.config` | 多环境配置加载（代码参数 → 环境变量 → .env → config.toml → 默认值） |

**AK/SK 兑换 Token 生命周期**：
- 临时 API Key 有效期：1 小时（TTL=3600s）
- 自动刷新：到期前 5 分钟自动续期
- Token 仅缓存在内存，不持久化到磁盘
- 刷新失败：抛出 `AuthenticationError(E1003)`，提示重新配置凭证
- 支持 STS 临时凭证：企业场景推荐使用 RAM Role + STS

**双认证模式**：

| 认证方式 | 场景 | 传递方式 | 环境变量 |
|----------|------|----------|----------|
| **API Key（主路径）** | 云沙箱数据面操作 | `X-API-KEY` 请求头 | `SANDBOX_API_KEY` |
| **AK/SK（扩展）** | 兑换临时 API Key、控制面 OpenAPI | 阿里云 V4 签名 | `ALICLOUD_ACCESS_KEY_ID` / `ALICLOUD_ACCESS_KEY_SECRET` |

**envdAccessToken 双 Token 认证流**：

```mermaid
sequenceDiagram
    participant User as SDK / User
    participant Platform as Platform API
    participant Envd as Sandbox envd API

    User->>Platform: POST /sandboxes (X-API-KEY)
    Platform-->>User: sandboxId + envdAccessToken
    Note over User: 自动提取 envdAccessToken 并缓存到 Sandbox 实例
    User->>Envd: 进程/文件/代码执行 (X-Access-Token: envdAccessToken)
    Envd-->>User: 执行结果
```

> **说明**：`X-API-KEY` 用于沙箱的创建、管理、销毁等生命周期操作（Platform API）；`envdAccessToken` 用于沙箱内部的进程、文件、代码执行等数据面操作（Sandbox envd API）。两个 Token 的作用域不同，SDK 内部自动管理切换，用户无感知。

**面向用户**：基础设施开发者、需要自定义认证逻辑的高级用户。

#### L2 — Core Protocol Layer（核心协议层）

**自行实现 E2B 兼容协议**，不依赖 E2B SDK，直接基于 httpx + websockets 实现。

**需要明确区分两个 API 层面**：

- **Platform API**（沙箱生命周期管理）：标准 HTTP REST，使用 `X-API-KEY` 认证
  - Sandbox: create, connect, list, getInfo, kill, setTimeout, pause
  - Template: CRUD, build, tags, alias
- **Sandbox envd API**（进程/文件/代码执行）：Connect 协议（gRPC-compatible over HTTP），使用 `X-Access-Token`（envdAccessToken）认证
  - Content-Type: `application/connect+json`
  - 请求路由: RPC 风格（如 `/process.Process/Start`）
  - 支持 Server-Streaming 响应
  - Process: Start(streaming), List, Connect(streaming), SendStdin, Kill
  - Filesystem: List, Exists, GetInfo, Read, Write, MakeDir, Remove, Rename, WatchDir(streaming)
  - Code Interpreter: RunCode(streaming), CreateContext, ListContexts, RestartContext, RemoveContext
  - PTY: WebSocket 双向通道

| 模块 | 职责 |
|------|------|
| `protocol.sandbox` | 沙箱生命周期管理（Platform API — HTTP REST） |
| `protocol.process` | 远程进程管理（Sandbox envd API — Connect 协议 + Server-Streaming） |
| `protocol.filesystem` | 远程文件系统操作（Sandbox envd API — Connect 协议） |
| `protocol.terminal` | 虚拟终端（PTY）复用，WebSocket 双向通信 |
| `protocol.port` | 端口转发与映射管理（Platform API — HTTP REST） |

**面向用户**：协议层开发者、需要细粒度控制的用户。

#### L3 — Extension Layer（阿里云扩展层）

| 模块 | 职责 |
|------|------|
| `extensions.vpc` | VPC 网络配置，安全组规则，ENI 绑定 |
| `extensions.oss` | OSS 挂载，文件同步，大文件传输加速 |
| `extensions.domain` | 自定义域名绑定与 TLS 证书管理 |
| `extensions.nas` | NAS 文件系统挂载（共享存储） |
| `extensions.log` | SLS 日志集成，结构化日志采集 |

**面向用户**：企业用户、需要深度集成阿里云服务的开发者。

#### L4 — High-Level API Layer（高层便捷 API）

| 模块 | 职责 |
|------|------|
| `api.sandbox` | Sandbox 类 — 创建、管理、执行、销毁的统一入口 |
| `api.pool` | SandboxPool — 连接池/预热池，并发管理 |
| `api.image` | Image 构建器 — 链式 API 构建自定义镜像 |
| `api.files` | 高层文件操作 — 上传/下载/监听 |
| `api.code` | 代码执行引擎 — 多语言支持，Rich Output |

**面向用户**：绝大多数开发者，E2B 兼容模式的核心层。

#### L5 — Declarative API Layer（声明式 API 层）

| 模块 | 职责 |
|------|------|
| `declarative.decorator` | `@sandbox` 装饰器 — Modal 风格远程执行 |
| `declarative.config` | `sandbox.yaml` 解析与验证 |
| `declarative.serializer` | 参数/返回值序列化（pickle / cloudpickle / JSON） |
| `declarative.scheduler` | 声明式任务调度与编排 |

**面向用户**：追求极简体验的 Python 开发者、ML 工程师。

#### L6 — Agent Integration Layer（AI 集成层）

| 模块 | 职责 |
|------|------|
| `agent.builtin` | 内置 Agent 封装 — 沙箱模板内预装 AI CLI 工具（Codex / Qwen CLI），SDK 提供语法糖 |
| `agent.tools` | Agent 工具集 — 沙箱操作封装为 OpenAI function calling 格式 |
| `agent.mcp` | MCP Server 实现 — 暴露沙箱能力为 MCP Tools |

**面向用户**：AI 应用开发者、Agent 框架集成者。

> **注意**：SDK 零 LLM 依赖，不内置 LLM Provider 适配层。Agent 能力来自沙箱模板内预装的 AI CLI 工具。

### 2.3 层间依赖关系

```mermaid
graph TD
    L6["L6 Agent Integration"] -->|依赖| L4["L4 High-Level API"]
    L5["L5 Declarative API"] -->|依赖| L4
    L4 -->|依赖| L3["L3 Extensions 可选"]
    L4 -->|依赖| L2["L2 Core Protocol"]
    L2 --> L1["L1 Transport and Auth"]
```

**依赖规则**：

1. **严格向下依赖**：每层只能依赖其下方的层，禁止反向依赖或跨层依赖
2. **L3 为可选层**：L4 可直接依赖 L2，L3 Extensions 作为增强模块按需引入
3. **L5 依赖 L4**：声明式 API 通过 L4 高层 API 实现，不直接依赖 L2
4. **L6 依赖 L4**：Agent 集成通过 L4 高层 API 实现
5. **L1 为基础层**：所有上层最终依赖 L1 完成网络通信和认证

---

## 三、沙箱类型体系

### 3.1 三种沙箱模式

#### 临时沙箱（Ephemeral）

**定位**：用完即弃的一次性执行环境，最常用的模式。**当前唯一完整支持的沙箱类型。**

```python
from easy_sandbox import Sandbox

# 默认就是临时沙箱
sb = await Sandbox.create(template="code-interpreter")
result = await sb.run_code("print('hello')")
await sb.kill()  # 销毁后数据全部丢失

# Context Manager 自动销毁
async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("print('hello')")
    # 退出即销毁
```

#### 持久沙箱（Persistent）— 🔮 远期规划

> **⚠️ 需底层能力支持，当前为远期规划。** 持久沙箱依赖底层平台的持久化存储能力，需等待阿里云 FC 支持后实现。

**定位**：长期运行的开发/服务环境，状态跨会话保留。

```python
# Future API — 待底层支持
from easy_sandbox import Sandbox

sb = await Sandbox.create(
    template="python-base",
    persistent=True,
    name="my-dev-env",
)

await sb.commands.run("pip install flask sqlalchemy")

# 稍后重新连接
sb = await Sandbox.connect("my-dev-env")
result = await sb.commands.run("pip list")  # flask, sqlalchemy 仍在
```

#### 休眠沙箱（Hibernated）— 🔮 远期规划

> **⚠️ 需底层能力支持，当前为远期规划。** 休眠沙箱依赖底层平台的 Snapshot / CRIU 等能力，需等待底层支持后实现。

**定位**：状态冻结后挂起，唤醒时恢复到冻结时刻，节省计费。

```python
# Future API — 待底层支持
from easy_sandbox import Sandbox

sb = await Sandbox.create(
    template="python-data-science",
    hibernate_after=300,
    on_exit="hibernate",
)

await sb.run_code("import pandas as pd; df = pd.read_csv('data.csv')")

await sb.hibernate()       # 停止计费
sb = await Sandbox.connect("sb-xxx")
await sb.wake_up()         # 恢复到休眠时状态
```

### 3.2 对比矩阵

| 特性 | 临时（Ephemeral） | 持久（Persistent）🔮 | 休眠（Hibernated）🔮 |
|------|-------------------|--------------------|--------------------|
| **实现状态** | **当前可用** | 远期规划 | 远期规划 |
| **生命周期** | 任务结束即销毁 | 持续运行直到手动销毁 | 冻结后可随时唤醒 |
| **状态持久** | 无 | 全量持久化 | 快照式冻结 |
| **文件系统** | tmpfs（内存盘） | 持久化存储 | 冻结时快照 |
| **进程** | 任务完成即停止 | 后台持续运行 | 冻结/恢复 |
| **网络** | 临时端口映射 | 固定域名/端口 | 唤醒后恢复 |
| **启动时间** | 冷启动 ~2s | 已在运行 ~0s | 唤醒 ~3-5s |
| **计费** | 按使用时长 | 持续计费 | 休眠期间低费/免费 |
| **最大时长** | 默认 5 分钟 | 无限制 | 休眠可保持 30 天 |
| **典型场景** | 代码执行、数据分析 | 开发环境、Web 服务 | 间歇性使用的项目 |

### 3.3 生命周期状态机

```mermaid
stateDiagram-v2
    [*] --> Creating : create()
    Creating --> Running : 就绪
    Running --> Dead : kill()
    Running --> Paused : pause() 需白名单
    Paused --> Running : resume()
```

> **说明**：`pause()` / `resume()` 状态转换需白名单权限，当前为受限功能。Snapshot 相关状态转换为远期规划，不在当前状态机中体现。

### 3.4 自动清理策略

#### 临时沙箱

| 触发条件 | 动作 | 默认值 |
|----------|------|--------|
| 达到 `timeout` 时间 | 强制销毁 | 300s |
| Context Manager 退出 | 优雅销毁 | — |
| 客户端断开连接 | 等待 → 销毁 | 等待 30s |

#### 持久沙箱（🔮 远期规划）

| 触发条件 | 动作 | 默认值 |
|----------|------|--------|
| 手动 `kill()` | 销毁 | — |
| CLI `ebx kill` | 销毁 | — |
| 账户欠费 | 冻结 → 7 天后销毁 | — |

#### 休眠沙箱（🔮 远期规划）

| 触发条件 | 动作 | 默认值 |
|----------|------|--------|
| 空闲超过 `hibernate_after` | 自动休眠 | 300s |
| 手动 `hibernate()` | 立即休眠 | — |
| 休眠超过保留期 | 自动销毁 | 30 天 |

### 3.5 计费模型

> **⚠️ 以下费用为估算值，以阿里云官方定价为准。**

```
总费用 = 计算费用 + 存储费用 + 网络费用

计算费用 = CPU 单价 × CPU 核数 × 运行时长
         + 内存单价 × 内存大小 × 运行时长
         + GPU 单价 × GPU 数量 × 运行时长

存储费用 = 持久存储单价 × 存储大小 × 保留时长（🔮远期）

网络费用 = 公网出流量 × 流量单价
```

**费用估算示例**（估算值，以阿里云官方定价为准）：

| 场景 | 配置 | 费用（估算） |
|------|------|------|
| 临时沙箱 5 分钟 | 1C/2G | ≈ ¥0.06 |
| 持久沙箱 24 小时 🔮 | 2C/4G | ≈ ¥36 |
| 休眠沙箱（2h 运行 + 22h 休眠）🔮 | 2C/4G | ≈ ¥3.09（节省 91%） |

---

## 四、SDK API 设计

Easy Sandbox SDK 提供三种使用范式，覆盖从简单脚本到复杂 AI 应用的全部场景，三种范式可混合使用。

### 4.1 配置系统（Zero Config）

SDK 采用零配置理念，按优先级加载配置：

```
代码参数 > 环境变量 > .env 文件 > ~/.ebx/config.toml > 默认值
```

#### 环境变量

```bash
# 认证（主路径 — API Key）
export SANDBOX_API_KEY=your-api-key

# 认证（扩展 — AK/SK，用于兑换临时 API Key 或控制面调用）
# export ALICLOUD_ACCESS_KEY_ID=your-ak
# export ALICLOUD_ACCESS_KEY_SECRET=your-sk

# 可选配置
export SANDBOX_REGION=cn-hangzhou               # 默认区域
export SANDBOX_TIMEOUT=300                       # 默认超时（秒）
export SANDBOX_LOG_LEVEL=INFO                    # 日志级别
```

#### 配置文件

```toml
# ~/.ebx/config.toml
# ⚠️ 安全警告：config.toml 中明文存储 API Key 存在安全风险。
# 推荐使用系统 Keychain（macOS Keychain / Linux Secret Service）存储敏感凭证。
# 参见 `ebx auth login --keychain` 命令。

[default]
region = "cn-hangzhou"
timeout = 300

[default.auth]
api_key = "your-api-key"              # 主认证方式
# access_key_id = "your-ak"          # 扩展认证（AK/SK 兑换）
# access_key_secret = "your-sk"

[profiles.production]
region = "cn-shanghai"
timeout = 600

[profiles.production.auth]
api_key = "your-production-api-key"
```

#### 代码配置

```python
from easy_sandbox import Sandbox, Config

# 全局配置
Config.set(region="cn-hangzhou", timeout=300, log_level="DEBUG")

# 实例级配置（覆盖全局）
sb = await Sandbox.create(template="code-interpreter", region="cn-shanghai", timeout=600)
```

### 4.2 范式一：E2B 兼容模式

兼容 E2B 数据面协议的 API，提供迁移辅助层方便现有 E2B 用户迁移（需将同步调用改为 async 调用方式）。

```python
from easy_sandbox import Sandbox

# 创建沙箱（async 模式）
sb = await Sandbox.create(template="code-interpreter")

# 执行代码
result = await sb.run_code("print('Hello, Easy Sandbox!')")
print(result.text)

# 执行命令
result = await sb.commands.run("ls -la /app")
print(result.stdout)

# 文件操作
await sb.files.write("/app/data.csv", "name,age\nAlice,30\nBob,25")
content = await sb.files.read("/app/data.csv")
files = await sb.files.list("/app")

# 销毁沙箱
await sb.kill()
```

**同步模式**：

```python
from easy_sandbox import Sandbox

sb = Sandbox.create_sync(template="code-interpreter")
result = sb.run_code_sync("print(1+1)")
sb.kill_sync()
```

**Context Manager**：

```python
async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("import sys; print(sys.version)")
    # 退出时自动销毁沙箱
```

**流式输出**：

```python
sb = await Sandbox.create(template="code-interpreter")

async for chunk in sb.commands.stream("pip install pandas && python train.py"):
    if chunk.type == "stdout":
        print(chunk.data, end="")
    elif chunk.type == "stderr":
        print(f"[ERR] {chunk.data}", end="")
    elif chunk.type == "exit":
        print(f"\n退出码: {chunk.exit_code}")
```

### 4.3 范式二：装饰器模式（Modal 风格）

借鉴 Modal 的声明式体验，用装饰器将本地函数透明地在远程沙箱中执行。

```python
from easy_sandbox import sandbox, Image

@sandbox(template="python-data-science", cpu=2, memory=4096)
def analyze(data: str) -> str:
    import pandas as pd
    import io
    df = pd.read_csv(io.StringIO(data))
    summary = df.describe().to_string()
    return f"数据分析结果:\n{summary}"

# 调用时自动：创建沙箱 → 序列化参数 → 远程执行 → 返回结果 → 销毁
result = analyze("name,score\nAlice,95\nBob,87\nCarol,92")
```

**自定义镜像**：

```python
from easy_sandbox import sandbox, Image

custom_image = (
    Image.from_template("python-data-science")
    .pip_install("scikit-learn", "xgboost", "lightgbm")
    .apt_install("libgomp1")
    .copy_local("./models/", "/app/models/")
    .env(MODEL_PATH="/app/models/latest.pkl")
)

@sandbox(image=custom_image, cpu=4, memory=8192, timeout=300)
def train_model(dataset_path: str) -> dict:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    model = RandomForestClassifier(n_estimators=100)
    # ... 训练逻辑
    return {"accuracy": 0.95, "model_path": "/app/output/model.pkl"}
```

**Async 装饰器**：

```python
from easy_sandbox import sandbox

@sandbox(template="node-web", async_mode=True)
async def run_lighthouse(url: str) -> dict:
    import subprocess, json
    result = subprocess.run(
        ["npx", "lighthouse", url, "--output=json", "--quiet"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

import asyncio
results = await asyncio.gather(
    run_lighthouse("https://example.com"),
    run_lighthouse("https://test.com"),
)
```

> **说明**：资源规格参数（`cpu`/`memory`/`gpu`）当前通过模板决定，SDK 内部实现为“查找匹配模板 / 创建匹配模板”的两步操作。用户指定的 cpu/memory 值将映射到最接近的可用模板规格。

#### 序列化限制与风险

装饰器模式使用 `cloudpickle` 进行函数序列化，存在以下已知限制：

**类型限制**：
- 支持：基本类型（int/float/str/bool）、list、dict、dataclass、Pydantic Model
- 不支持：数据库连接、文件句柄、C 扩展对象、线程/进程对象
- 引用不可序列化对象的闭包将在运行时失败

**安全风险**：
- pickle 反序列化可执行任意代码，SDK 对返回值使用受限反序列化器
- 建议在可信网络环境下使用装饰器模式

**跨版本兼容性**：
- 本地和沙箱的 Python 主版本必须一致（如均为 3.10.x 或 3.11.x）
- 不同 Python 版本间的 cloudpickle 产物不保证兼容

**大小限制**：
- 函数参数和返回值序列化后不超过 10MB
- 超过限制时 SDK 抛出 `SerializationError`

**MVP 阶段替代方案**：
装饰器 MVP 版本可仅支持 JSON 序列化（限制参数类型为 JSON-compatible），后续迭代增加 cloudpickle 支持。

### 4.4 范式三：内置 Agent 模式

SDK 内置 AI Agent 能力封装。**核心思路**：沙箱模板内预装 AI CLI 工具（Codex、Qwen CLI 等），SDK Agent API 只是 `commands.run()` 的语法糖。

```python
from easy_sandbox import Sandbox

# 代码 Agent — 实质执行 sb.commands.run("codex 'fix bug in main.py'")
sb = await Sandbox.create(template="codex")
result = await sb.agent.code("fix bug in main.py")
print(result.output)

# 浏览器 Agent — 实质执行 sb.commands.run("qwen-cli browse '打开百度并截图'")
sb = await Sandbox.create(template="qwen-browser")
result = await sb.agent.browse("打开百度并截图首页")
print(result.output)

# Shell 自动化 — 实质执行 sb.commands.run("codex 'install nginx and configure...'")
sb = await Sandbox.create(template="codex")
result = await sb.agent.shell("安装 nginx 并配置反向代理到 8080 端口")
print(result.output)
```

> **设计理念**：SDK 零 LLM 依赖，保持轻量。AI 工具的认证在沙箱模板内预配置，用户无需额外 API Key。可通过升级模板内 AI CLI 版本实现热更新。用户可选择不同模板（Codex 模板 / Qwen 模板 / 自定义模板）。

### 4.5 自然语言创建

> **用户不需要知道模板名、资源规格、配置参数，只需要描述想做什么，SDK 自动搞定一切。**

```python
from easy_sandbox import Sandbox

# 自然语言描述 → 自动推断模板 + 资源配置
sb = await Sandbox.create("运行 python 数据分析环境，需要 GPU")
# 推断结果：template=python-data-science, gpu=auto, memory=8192

sb = await Sandbox.create("启动一个 Node.js Web 服务，开放 3000 端口")
# 推断结果：template=node-web, expose=[3000]

sb = await Sandbox.create("用 playwright 爬取网页并截图")
# 推断结果：template=browser-automation, memory=4096
```

**推断实现策略**（三级 Fallback）：

```mermaid
flowchart TD
    A["自然语言描述"] --> B{"Server 端 AI 推断接口"}
    B -- 可用 --> R1["返回推断结果（最优精度）"]
    B -- 不可用/超时 --> C{"本地 Qwen CLI / DashScope API"}
    C -- 可用 --> R2["返回推断结果（本地 Fallback）"]
    C -- 不可用/超时 --> D["关键词规则匹配（完全离线）"]
    D --> R3["返回推断结果（最终兜底）"]
```

**Fallback 控制策略**：
- Server 端 AI 超时：3 秒，超时后立即 fallback（不重试）
- Qwen CLI/DashScope 超时：5 秒，未安装或认证失败立即 fallback
- 关键词规则匹配：本地执行，无超时
- confidence 阈值：< 0.6 时提示用户确认而非直接创建
- 三级全部失败：提示用户手动指定模板名，显示可用模板列表

**推断透明化**：

```python
# 查看推断结果（不实际创建）
plan = await Sandbox.plan("需要一个能跑 TensorFlow 的环境，数据集 50GB")
print(plan)
# SandboxPlan(
#   template='ml-gpu',
#   cpu=4, memory=16384, disk=65536,
#   gpu='A10',                    # ⚠️ GPU 支持取决于底层平台能力，当前为远期规划
#   confidence=0.92,
#   reasoning='检测到 TensorFlow + 大数据集需求，选择 GPU 模板并扩容磁盘'
# )

# 用户可选择接受或覆盖
sb = await Sandbox.create(plan)                     # 直接使用推断结果
sb = await Sandbox.create(plan, memory=32768)        # 覆盖部分参数
```

**向后兼容**：`create()` 智能判断第一个参数，匹配已知模板名则按模板创建，否则触发推断流程。

### 4.6 Sandbox 核心 API

```python
class Sandbox:
    """沙箱核心类 — 所有操作的统一入口"""

    # ── 生命周期 ──────────────────────────────────────
    @classmethod
    async def create(
        cls,
        description: str | None = None,      # 自然语言描述（AI-First）
        *,
        template: str = "base",
        timeout: int = 300,
        metadata: dict | None = None,
        env: dict[str, str] | None = None,
        cpu: int | None = None,               # 通过模板决定，SDK 查找匹配模板
        memory: int | None = None,            # MB，同上
        disk: int | None = None,              # MB
        gpu: str | None = None,               # GPU 型号或 "auto"
        region: str | None = None,
        vpc: VPCConfig | None = None,
        upload: list[str] | None = None,
        project_dir: str | None = None,
        # 🔮 远期参数 — 待底层支持
        # persistent: bool = False,
        # name: str | None = None,
        # hibernate_after: int | None = None,
        # on_exit: Literal["destroy", "hibernate", "keep"] = "destroy",
    ) -> "Sandbox": ...

    @classmethod
    async def plan(cls, description: str, **kwargs) -> "SandboxPlan": ...
    @classmethod
    async def connect(cls, sandbox_id: str) -> "Sandbox": ...
    @classmethod
    async def last(cls) -> "Sandbox": ...

    async def kill(self) -> None: ...
    async def keep_alive(self, duration: int) -> None: ...
    async def set_timeout(self, timeout: int) -> None: ...
    @property
    def is_running(self) -> bool: ...

    # Future API — 待底层支持
    # async def hibernate(self) -> None: ...
    # async def wake_up(self) -> "Sandbox": ...
    # async def snapshot(self, name: str) -> str: ...

    # ── 属性 ──────────────────────────────────────────
    @property
    def id(self) -> str: ...
    @property
    def status(self) -> SandboxStatus: ...
    @property
    def url(self) -> str: ...

    # ── 代码执行 ──────────────────────────────────────
    async def run_code(self, code: str, *, language: str = "python", timeout: int = 30) -> CodeResult: ...

    # ── 子模块 ────────────────────────────────────────
    @property
    def commands(self) -> CommandsModule: ...
    @property
    def files(self) -> FilesModule: ...
    @property
    def agent(self) -> AgentModule: ...
    @property
    def network(self) -> NetworkModule: ...

    # ── E2B 兼容方法 ─────────────────────────────────
    def get_host(self, port: int) -> str: ...
    async def upload_url(self, path: str) -> str: ...
    async def download_url(self, path: str) -> str: ...
```

**CommandsModule**：

```python
class CommandsModule:
    async def run(self, cmd: str, *, timeout: int = 60, env: dict | None = None, cwd: str = "/app") -> ProcessResult: ...
    async def stream(self, cmd: str, **kwargs) -> AsyncIterator[ProcessChunk]: ...
    async def start(self, cmd: str, **kwargs) -> Process: ...
    async def list(self) -> list[ProcessInfo]: ...
    async def kill(self, pid: int) -> None: ...
```

**FilesModule**：

```python
class FilesModule:
    async def read(self, path: str, *, encoding: str = "utf-8") -> str: ...
    async def read_bytes(self, path: str) -> bytes: ...
    async def write(self, path: str, content: str | bytes) -> None: ...
    async def list(self, path: str = "/") -> list[FileInfo]: ...
    async def remove(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def upload(self, local_path: str, remote_path: str) -> None: ...
    async def download(self, remote_path: str, local_path: str) -> None: ...
    async def watch(self, path: str) -> AsyncIterator[WatchEvent]: ...
    async def make_dir(self, path: str) -> None: ...
```

**NetworkModule**：

```python
class NetworkModule:
    async def get_url(self, port: int) -> str: ...
    async def expose(self, port: int, *, public: bool = False) -> str: ...
    async def forward(self, remote_port: int, local_port: int) -> None: ...
    async def list_ports(self) -> list[PortInfo]: ...
    # ⚠️ 当前不进行实际网络变更，仅记录配置
    async def update_config(self, config: NetworkConfig) -> None: ...
```

**CodeContextModule（E2B 兼容）**：

```python
class CodeContextModule:
    """E2B Code Context 兼容 API"""
    async def create(self, *, cwd: str = "/app", language: str = "python") -> "CodeContext": ...
    async def list(self) -> list["CodeContext"]: ...
    async def restart(self, context_id: str) -> None: ...
    async def remove(self, context_id: str) -> None: ...
```

### 4.7 链式 Image 构建

```python
from easy_sandbox import Image

image = (
    Image.from_template("python-base")
    .python_version("3.11")
    .pip_install("pandas", "numpy", "matplotlib")
    .pip_install_from_requirements("./requirements.txt")
    .apt_install("ffmpeg", "libsm6")
    .copy_local("./src/", "/app/src/")
    .run_command("chmod +x /app/src/entrypoint.sh")
    .env(MODEL_PATH="/app/models/latest.pkl", DATA_DIR="/app/data")
    .workdir("/app")
    .expose(8080)
    .entrypoint("python /app/src/main.py")
)

sb = await Sandbox.create(image=image)

# 构建并推送为模板
template_id = await image.build_and_push(name="my-ml-env", tag="v1.0")
```

**从 Dockerfile 构建**：

```python
image = Image.from_dockerfile("./Dockerfile")
image = Image.from_dockerfile_string("""
FROM python:3.11-slim
RUN pip install flask
COPY . /app
CMD ["python", "app.py"]
""")
```

### 4.8 SandboxPool 沙箱池

```python
from easy_sandbox import SandboxPool

pool = SandboxPool(
    template="code-interpreter",
    min_ready=3,           # 最小预热数量
    max_size=20,           # 最大沙箱数量
    idle_timeout=300,      # 空闲超时（秒）
    scale_policy="auto",   # 自动扩缩容
)

await pool.start()

# 从池中获取沙箱（毫秒级）
async with pool.acquire() as sb:
    result = await sb.run_code("print('instant!')")

# 批量执行
tasks = ["print(i)" for i in range(100)]
results = await pool.map(lambda sb, code: sb.run_code(code), tasks)

# 池状态
status = pool.status()
print(f"就绪: {status.ready}, 使用中: {status.in_use}, 总计: {status.total}")

await pool.shutdown()
```

### 4.9 FC Extensions

#### VPC 网络配置

```python
from easy_sandbox import Sandbox
from easy_sandbox.extensions import VPCConfig

sb = await Sandbox.create(
    template="base",
    vpc=VPCConfig(vpc_id="vpc-xxx", vswitch_ids=["vsw-xxx"], security_group_id="sg-xxx"),
)
result = await sb.commands.run("curl http://10.0.1.100:3306")
```

#### OSS 挂载

```python
from easy_sandbox.extensions import OSSMount

sb = await Sandbox.create(
    template="python-data-science",
    mounts=[
        OSSMount(bucket="my-data-bucket", remote_path="datasets/", mount_point="/data", read_only=True),
        OSSMount(bucket="my-output-bucket", remote_path="results/", mount_point="/output", read_only=False),
    ],
)
```

#### 自定义域名

```python
from easy_sandbox.extensions import DomainConfig

sb = await Sandbox.create(
    template="node-web",
    domain=DomainConfig(domain="sandbox.example.com", port=3000, tls=True, cors=["https://myapp.com"]),
)
print(sb.network.public_url)  # https://sandbox.example.com
```

### 4.10 错误处理体系

#### 异常类层次

```mermaid
classDiagram
    class SandboxError {
        <<基类>>
    }
    class AuthenticationError {
        认证失败
    }
    class InvalidAPIKeyError {
        E1001 API Key 无效
    }
    class InvalidCredentialsError {
        E1003 AK/SK 无效
    }
    class TokenExpiredError {
        E1002 Token 过期
    }
    class SandboxCreationError {
        创建失败
    }
    class TemplateNotFoundError {
        E2001 模板不存在
    }
    class QuotaExceededError {
        E2002 配额超限
    }
    class RegionUnavailableError {
        E2003 区域不可用
    }
    class ExecutionError {
        执行失败
    }
    class TimeoutError {
        E3001 执行超时
    }
    class ProcessError {
        E3002 进程异常退出
    }
    class CodeExecutionError {
        E3003 代码执行错误
    }
    class FileOperationError {
        E4001 文件操作失败
    }
    class NetworkError {
        网络错误
    }
    class ConnectionLostError {
        E5002 网络断开
    }
    class ReconnectFailedError {
        重连失败
    }
    class AgentError {
        Agent 错误
    }
    class ToolExecutionError {
        工具执行失败
    }

    SandboxError <|-- AuthenticationError
    SandboxError <|-- SandboxCreationError
    SandboxError <|-- ExecutionError
    SandboxError <|-- FileOperationError
    SandboxError <|-- NetworkError
    SandboxError <|-- AgentError
    AuthenticationError <|-- InvalidAPIKeyError
    AuthenticationError <|-- InvalidCredentialsError
    AuthenticationError <|-- TokenExpiredError
    SandboxCreationError <|-- TemplateNotFoundError
    SandboxCreationError <|-- QuotaExceededError
    SandboxCreationError <|-- RegionUnavailableError
    ExecutionError <|-- TimeoutError
    ExecutionError <|-- ProcessError
    ExecutionError <|-- CodeExecutionError
    NetworkError <|-- ConnectionLostError
    NetworkError <|-- ReconnectFailedError
    AgentError <|-- ToolExecutionError
```

#### 错误码体系

| 错误码 | 类别 | 含义 | 修复建议 |
|--------|------|------|----------|
| `E1001` | 认证 | API Key 无效 | 检查 SANDBOX_API_KEY 环境变量 |
| `E1002` | 认证 | Token 过期 | SDK 将自动刷新，若持续请检查时钟同步 |
| `E1003` | 认证 | AK/SK 无效 | 检查 ALICLOUD_ACCESS_KEY_ID / SECRET 环境变量 |
| `E2001` | 创建 | 模板不存在 | 运行 `ebx template list` 查看可用模板 |
| `E2002` | 创建 | 配额超限 | 联系管理员提升配额或销毁闲置沙箱 |
| `E3001` | 执行 | 命令超时 | 增大 timeout 参数 |
| `E4001` | 文件 | 文件不存在 | 使用 `files.list()` 检查路径 |
| `E5001` | 网络 | 连接失败 | 检查网络和防火墙 |
| `E5002` | 网络 | 连接断开 | SDK 将自动重连，若持续请检查网络环境 |

#### 错误处理示例

```python
from easy_sandbox import Sandbox
from easy_sandbox.errors import (
    SandboxError, QuotaExceededError, TimeoutError, TemplateNotFoundError,
)

try:
    sb = await Sandbox.create(template="code-interpreter")
    result = await sb.run_code("import time; time.sleep(100)", timeout=5)
except TemplateNotFoundError as e:
    print(f"模板不存在: {e.template}")
    print(f"可用模板: {e.available_templates}")
except QuotaExceededError as e:
    print(f"配额超限: {e.current}/{e.limit}")
except TimeoutError as e:
    print(f"执行超时: {e.timeout}s, 已执行输出: {e.partial_output}")
except SandboxError as e:
    print(f"[{e.code}] {e.message}")
    print(f"修复建议: {e.suggestion}")
```

#### 错误场景用户体验设计

| 错误场景 | 用户感知 | SDK 行为 |
|----------|---------|---------|
| **网络断开** | CLI 显示 "⚠ 网络中断，正在重连..." | 自动重连 3 次（指数退避 1s/2s/4s），超限后抛出 `ConnectionLostError` 并保留部分输出 |
| **认证过期** | CLI 显示 "🔑 认证已过期，正在刷新..." | API Key 模式自动续期；AK/SK 模式自动重新兑换；全部失败后抛出 `TokenExpiredError` 并引导重新登录 |
| **沙箱崩溃** | CLI 显示 "💥 沙箱异常退出 (OOM/Timeout)" | 收集崩溃前日志，返回 `SandboxCrashedError` 含 `last_output`/`exit_reason`/`suggestion`（如 "内存不足，建议增大 memory 参数"） |
| **API 限流** | CLI 显示 "⏳ 请求过于频繁，等待重试..." | 自动退避重试（尊重 `Retry-After` 头），超过 30s 后抛出 `RateLimitError` |

---

## 五、CLI 设计

`ebx` CLI 是 Easy Sandbox 的命令行入口，兼顾人类开发者和 AI Agent 两种使用场景。

### 5.1 命令体系

```mermaid
graph TB
    ebx["ebx"]

    ebx --- create["create - 创建沙箱（支持自然语言）"]
    ebx --- list["list - 列出所有沙箱"]
    ebx --- info["info - 查看沙箱详情"]
    ebx --- kill["kill - 销毁沙箱 / --all"]
    ebx --- exec["exec - 在沙箱中执行命令"]
    ebx --- run["run - 执行代码文件"]
    ebx --- shell["shell - 交互式 Shell"]
    ebx --- logs["logs - 查看沙箱日志"]
    ebx --- upload["upload - 上传文件"]
    ebx --- download["download - 下载文件"]
    ebx --- start["start - 启动命名 Session"]
    ebx --- connect["connect - 连接已有 Session"]
    ebx --- sessions["sessions"]
    ebx --- build["build - 从目录构建镜像"]
    ebx --- deploy["deploy - 直接部署项目"]
    ebx --- template["template"]
    ebx --- skill["skill"]
    ebx --- secret["secret"]
    ebx --- mcp["mcp"]
    ebx --- pool["pool"]
    ebx --- auth["auth"]
    ebx --- config["config"]
    ebx --- version["version - 版本信息"]

    sessions --- sess_list["list"]
    sessions --- sess_info["info"]
    sessions --- sess_rename["rename"]
    sessions --- sess_export["export"]
    sessions --- sess_clean["clean"]
    sessions --- sess_import["import"]

    template --- tpl_list["list"]
    template --- tpl_info["info"]
    template --- tpl_build["build"]
    template --- tpl_push["push"]
    template --- tpl_pull["pull"]
    template --- tpl_init["init"]
    template --- tpl_cache["cache"]

    skill --- sk_search["search"]
    skill --- sk_install["install"]
    skill --- sk_update["update"]
    skill --- sk_list["list"]
    skill --- sk_create["create"]
    skill --- sk_publish["publish"]
    skill --- sk_uninstall["uninstall"]

    secret --- sec_create["create"]
    secret --- sec_list["list"]
    secret --- sec_delete["delete"]
    secret --- sec_inject["inject"]

    mcp --- mcp_install["install"]
    mcp --- mcp_start["start"]
    mcp --- mcp_status["status"]
    mcp --- mcp_config["config"]

    pool --- pool_create["create"]
    pool --- pool_list["list"]
    pool --- pool_status["status"]
    pool --- pool_scale["scale"]
    pool --- pool_destroy["destroy"]

    auth --- auth_login["login"]
    auth --- auth_logout["logout"]
    auth --- auth_status["status"]
    auth --- auth_switch["switch"]

    config --- cfg_get["get"]
    config --- cfg_set["set"]
    config --- cfg_list["list"]
    config --- cfg_reset["reset"]
```

#### 全局选项

| 选项 | 缩写 | 说明 | 默认值 |
|------|------|------|--------|
| `--json` | `-j` | 输出 JSON 格式（AI 友好） | `false` |
| `--quiet` | `-q` | 静默模式，仅输出关键结果 | `false` |
| `--yes` | `-y` | 跳过所有确认提示 | `false` |
| `--profile` | `-p` | 指定配置档案 | `default` |
| `--region` | `-r` | 指定区域 | `cn-hangzhou` |
| `--verbose` | `-v` | 详细输出 | `false` |
| `--no-color` | | 禁用颜色 | `false` |
| `--timeout` | `-t` | 超时时间（秒） | `300` |

### 5.2 自然语言创建

```bash
# 自然语言描述 → 自动推断模板和配置
ebx create "运行 python，运行 codex"
# ✓ 推断结果：
#   模板: code-interpreter
#   CPU: 2 核  |  内存: 4096 MB
#   置信度: 0.95
#   推断来源: Server 端 AI / Qwen CLI / 规则匹配
# → 创建中... 完成！sandbox-id: sb-a1b2c3d4

ebx create "启动一个 Node.js Web 服务"
# ✓ 推断结果：模板: node-web, CPU: 1 核, 内存: 2048 MB, 端口: 3000

# 只看推断结果，不实际创建
ebx create "需要 TensorFlow GPU 环境" --dry-run

# 自然语言推断 + 手动覆盖
ebx create "python 数据分析" --memory 8192 --region cn-shanghai

# 传统模板模式 — 100% 向后兼容
ebx create --template code-interpreter
```

### 5.3 项目直接部署（ebx build / ebx deploy）

```bash
# 从当前目录构建镜像
ebx build . --name my-app --tag v1.0

# 直接部署项目到运行中的沙箱
ebx deploy ./my-flask-app --name api-server
# ✓ 检测项目类型: Python (requirements.txt + app.py)
# ✓ 检测框架: Flask
# ✓ 选择模板: python-base
# ✓ 创建沙箱: sb-x7y8z9
# ✓ 上传源码: 42 个文件, 1.2MB
# ✓ 安装依赖: pip install -r requirements.txt
# ✓ 启动服务: python app.py
# ✓ 服务就绪: https://api-server.sandbox.alicloud.com

# 开发模式：本地文件变更自动同步到沙箱
ebx deploy . --watch
```

**自动项目检测**：

| 特征文件 | 检测为 | 选择模板 |
|----------|--------|---------|
| `package.json` + `next.config` | Next.js | node-web |
| `package.json` + `vite.config` | Vite | node-web |
| `requirements.txt` + `manage.py` | Django | python-base |
| `requirements.txt` + `app.py` | Flask | python-base |
| `go.mod` | Go | go-dev |
| `pom.xml` / `build.gradle` | Java | java-dev |
| `Dockerfile` | Docker | 直接使用 |
| `sandbox.yaml` | 声明式配置 | 优先级最高 |

### 5.4 核心工作流

#### 工作流 1：快速实验

```bash
ebx create "python 数据分析，需要 pandas 和 matplotlib"
# → sb-abc123
ebx exec sb-abc123 "python -c 'import pandas; print(pandas.__version__)'"
ebx kill sb-abc123
```

#### 工作流 2：项目开发

```bash
ebx deploy ./my-api --name api-dev --watch --expose 8080
ebx logs api-dev --follow        # 另一个终端（⚠️ 实验性）
ebx exec api-dev "pytest tests/ -v"
ebx kill api-dev
```

#### 工作流 3：AI Agent 集成

```bash
ebx mcp install --target cursor
ebx create "全栈开发环境" --name agent-env
# AI Agent 通过 MCP 自动使用沙箱
```

#### 工作流 4：模板定制

```bash
ebx template build ./my-template --name my-ml-env
ebx create --template my-ml-env
ebx template push my-ml-env --tag v1.0
```

### 5.5 AI Friendly 设计原则

1. **结构化输出** — 所有命令支持 `--json`，输出严格 JSON
2. **幂等操作** — 重复创建同名沙箱返回已有的，重复销毁静默成功
3. **确定性退出码** — `0` 成功，`1` 一般错误，`2` 参数错误，`3` 认证失败，`4` 资源不存在，`5` 超时，`6` 配额超限
4. **无交互模式** — `--yes` 跳过确认，`--quiet` 最小化输出
5. **可组合管道** — `ID=$(ebx create "python" --quiet)` 直接获取 ID
6. **自描述帮助** — 错误信息包含修复建议
7. **进度反馈** — 人类模式有进度条，AI 模式（`--json`）输出结构化事件
8. **自然语言容错** — 模糊描述尽力推断，失败给出引导


---

## 六、Session 管理 ★增强★

### 6.1 Session 概念

Session 是用户与沙箱交互的上下文。一个 Session 将沙箱实例引用、执行历史、文件状态、环境变量等绑定在一起，形成一个有名字、可恢复、可管理的工作单元。

Session 与沙箱的关系：
- 一个 Session 对应一个沙箱实例
- Session 是沙箱的"客户端引用" — 记录了如何找到、连接、恢复一个沙箱
- 沙箱可能因为超时/销毁而消失，Session 记录了足够的信息来重建

### 6.2 SDK 自动 Session 管理

```python
from easy_sandbox import Sandbox

# SDK 自动追踪 session
sb = await Sandbox.create(template="python", name="my-work")
# Session 自动创建，ID 保存到 ~/.ebx/sessions/

# 下次可以直接恢复
sb = await Sandbox.connect("my-work")  # 通过名字连接
sb = await Sandbox.last()              # 连接最近的 session
```

Session 在 SDK 中是透明的 — 用户不需要显式管理 Session，SDK 在 `create()`、`connect()` 时自动维护 Session 状态。

> **增强**：`Sandbox.connect()` 前会先向云端验证沙箱是否仍然存活，避免连接到已不存在的沙箱导致状态不一致。

```python
# 查看所有活跃 session
sessions = await Sandbox.sessions.list()
for s in sessions:
    print(f"{s.name}: {s.state} (sandbox={s.sandbox_id})")

# 按状态过滤
running = await Sandbox.sessions.list(state="running")
```

### 6.3 CLI Session 命令

```bash
# 启动一个命名 session（创建沙箱 + 注册 session）
ebx start my-project
ebx start my-project --template python-data-science --cpu 2

# 列出所有活跃 session
ebx sessions list
ebx sessions list --all  # 包含已断开的

# 连接到已有 session
ebx connect my-project
ebx connect _            # 最近的 session（快捷方式）

# Session 信息
ebx sessions info my-project
# ╭─── Session: my-project ──────────────────────╮
# │  Sandbox ID:  sbx-abc123                     │
# │  Template:    python-data-science            │
# │  State:       running                        │
# │  Created:     2026-09-01 10:00:00            │
# │  Last Access: 2026-09-01 15:00:00            │
# │  Ports:       8080, 3000                     │
# ╰──────────────────────────────────────────────╯

# Session 操作
ebx sessions rename old-name new-name     # 重命名
ebx sessions export my-project            # 导出 Session 配置信息（JSON 格式，可分享）
ebx sessions import session-config.json   # 从配置文件恢复 Session
ebx sessions clean                        # 清理过期 session
ebx sessions clean --dry-run              # 预览清理
```

> **说明**：`sessions export/import` 导出的是 Session 配置信息（模板、资源规格、环境变量等），而非沙箱状态快照。这确保了在任何环境下都能根据配置重建相同的沙箱。

### 6.4 存储后端（可插拔设计）

Session 元信息存储采用可插拔设计，支持多种存储后端：

```python
from easy_sandbox.session import (
    SessionStore,          # 抽象基类
    LocalSessionStore,     # 本地文件（默认）
    OSSSessionStore,       # 阿里云 OSS
    DatabaseSessionStore,  # 数据库（Redis/MySQL）
)

# 默认：本地文件存储
# Session 数据存储在 ~/.ebx/sessions/

# 多机器共享：OSS 存储
from easy_sandbox import Config
Config.set(session_store=OSSSessionStore(
    bucket="my-team-sessions",
    prefix="sandbox-sessions/",
))

# 团队协作：数据库存储
Config.set(session_store=DatabaseSessionStore(
    url="redis://localhost:6379/0",
    # 或 url="mysql://user:pass@host/db",
))

# 自定义实现
class MySessionStore(SessionStore):
    async def save(self, session: SessionInfo) -> None: ...
    async def load(self, name: str) -> SessionInfo | None: ...
    async def list(self, **filters) -> list[SessionInfo]: ...
    async def delete(self, name: str) -> None: ...
```

**并发控制**：
- `SessionStore` 接口增加可选的乐观锁语义：`save(session, expected_version=None)`
- `LocalSessionStore`：使用 `filelock` 库实现文件级别锁
- `OSSSessionStore`：利用 OSS 条件写入（If-Match ETag）实现乐观锁
- `DatabaseSessionStore`：使用数据库事务 + 版本号字段
- GC 操作采用“先标记后删除”两阶段流程，避免误删活跃 Session

#### 本地存储目录结构（默认）

```
~/.ebx/sessions/
├── my-project.toml          # Session 元信息
├── my-project.history       # 命令历史
└── my-project.env           # 环境变量快照
```

**Session TOML 格式**：

```toml
# ~/.ebx/sessions/my-project.toml
sandbox_id = "sbx-abc123"
template = "python-data-science"
created_at = "2026-09-01T10:00:00Z"
last_accessed = "2026-09-01T15:00:00Z"
state = "running"            # running / dead
region = "cn-hangzhou"

[resources]
cpu = 2
memory = 4096

[ports]
exposed = [8080, 3000]

[tags]
project = "my-project"
team = "data-science"
```

**命令历史**（`.history` 文件）：

```
# ~/.ebx/sessions/my-project.history
2026-09-01T10:00:05Z  pip install pandas numpy
2026-09-01T10:01:00Z  python train.py
2026-09-01T10:15:00Z  python evaluate.py --model /app/model.pkl
```

### 6.5 生命周期配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `session_ttl` | Session 过期时间 | `7d` |
| `auto_cleanup` | 自动清理过期 Session | `true` |
| `sync_interval` | 与云端状态同步间隔 | `300s` |
| `on_orphan` | 孤儿 Session 处理策略 | `warn` |

```bash
# 配置 session 策略
ebx config set session.session_ttl 7d            # 7 天后过期
ebx config set session.auto_cleanup true          # 开启自动清理
ebx config set session.sync_interval 300          # 每 300 秒同步云端状态
ebx config set session.on_orphan warn             # 孤儿 Session：warn/cleanup/ignore
```

**孤儿 Session 处理**：当本地 Session 引用的沙箱在云端已不存在时：
- `warn`（默认）：标记为 dead 并在下次 `sessions list` 时提示
- `cleanup`：自动删除本地 Session 文件
- `ignore`：不做任何处理

### 6.6 自动管理策略

| 策略 | 说明 | 配置 |
|------|------|------|
| **自动命名** | 不指定名字时使用 `sbox-{timestamp}` 格式 | 默认开启 |
| **自动清理** | `ebx sessions clean` 清理超过 `session_ttl` 的死亡 session | `session_ttl = 7d` |
| **云端验证** | `connect` 前先验证沙箱是否存活 | 默认开启 |
| **GC 策略** | 定期清理本地 session 文件中引用的已不存在的沙箱 | `sync_interval = 300s` |

**GC 流程**：

```mermaid
flowchart TD
    A["定时触发 / ebx sessions clean"] --> B["读取 Session 存储中所有 Session"]
    B --> C{"遍历每个 Session"}
    C --> D["查询远端沙箱状态"]
    D --> E{"沙箱是否存在?"}
    E -- 不存在 --> F["标记 state = dead"]
    E -- 存在 --> H["更新 last_checked 时间戳"]
    F --> G{"state = dead 且超过 session_ttl?"}
    G -- 是 --> I["按 on_orphan 策略处理"]
    G -- 否 --> H
    I --> H
    H --> J{"还有更多 Session?"}
    J -- 是 --> C
    J -- 否 --> K["输出清理报告"]
```

### 6.7 多 Session 并发

```python
import asyncio
from easy_sandbox import Sandbox

# 同时管理多个 session
sessions = await Sandbox.sessions.list()
for s in sessions:
    print(f"{s.name}: {s.state}")

# 并发执行任务
async def run_task(name: str, code: str):
    sb = await Sandbox.connect(name)
    return await sb.run_code(code)

results = await asyncio.gather(
    run_task("worker-1", "process_batch_1()"),
    run_task("worker-2", "process_batch_2()"),
    run_task("worker-3", "process_batch_3()"),
)
```

```bash
# CLI 并发管理
ebx start worker-1 --template python-base
ebx start worker-2 --template python-base
ebx start worker-3 --template python-base

ebx sessions list
#   NAME       TEMPLATE       STATE     CREATED
#   worker-1   python-base    running   2 min ago
#   worker-2   python-base    running   1 min ago
#   worker-3   python-base    running   30s ago

# 批量操作
ebx kill worker-1 worker-2 worker-3
```

---

## 七、模板体系

### 7.1 模板来源（GitHub tarball API 为核心）

模板的核心分发机制基于 **GitHub tarball API（按 tag/branch/sha 拉取，无需发布 Release）**，类似 Go modules / GitHub Actions 的引用方式。SDK 按优先级依次解析模板来源：

```
模板来源优先级：
1. 内置模板（SDK 自带的 Tier 1 模板）
2. GitHub tarball 模板（owner/repo 格式；GitHub tarball API 按 tag/branch/sha 拉取，无需 Release）
3. 本地模板（文件路径）
4. 阿里云 ACR 镜像（registry URL）
```

**模板名解析规则**：

```python
"python"                → 内置 python 模板
"code-interpreter"      → 内置 code-interpreter 模板
"hello/world"           → github.com/hello/world 默认分支
"hello/world@v1.0"      → github.com/hello/world ref v1.0（tag/branch/sha）
"./my-template"         → 当前目录下的 my-template
"acr://registry.cn-hangzhou.aliyuncs.com/ns/image:tag" → 阿里云容器镜像
```

> **安全说明**：从远程拉取模板时，SDK 会校验模板包的 checksum（SHA-256），防止中间人篡改。`ebx template info <template>` 可查看模板 checksum 信息。checksum 校验失败时默认中止下载并报错，提供 `--skip-verify` 标志用于开发环境跳过校验。

### 7.2 官方核心模板

#### Tier 1 — 首发模板（5 个）

| 模板名 | 描述 | 基础 | 资源默认值 |
|--------|------|------|-----------|
| `base` | 最小化 Linux 环境 | debian:bookworm-slim | 1C/2G/10G |
| `python-base` | Python 开发环境 | base + pip/venv/poetry | 1C/2G/10G |
| `python-data-science` | 数据科学全套 | python-base + pandas/numpy/matplotlib/sklearn | 2C/4G/20G |
| `node-web` | Node.js Web 开发 | base + node20/npm/yarn/pnpm | 1C/2G/10G |
| `code-interpreter` | 多语言代码解释器 | python-data-science + node/go/rust + Rich Output | 2C/4G/20G |

#### Tier 2 — 扩展模板（5 个）

| 模板名 | 描述 | 资源默认值 |
|--------|------|-----------|
| `browser-automation` | Playwright + Chromium 浏览器自动化 | 2C/4G/15G |
| `full-stack` | 前后端 + PostgreSQL + Redis + Nginx | 4C/8G/30G |
| `go-dev` | Go 1.22 + golangci-lint + dlv + air | 2C/4G/15G |
| `java-dev` | JDK 21 + Maven 3.9 + Gradle 8.x | 2C/4G/20G |
| `ml-gpu` | CUDA 12.1 + PyTorch + TensorFlow | 4C/16G/50G + GPU | 

> **注意**：GPU 支持取决于底层平台能力，`ml-gpu` 模板当前为远期规划。

#### Agent 模板（AI CLI 预装）

| 模板名 | 描述 | 预装工具 | 资源默认值 |
|--------|------|---------|-----------|
| `codex` | Codex CLI 代码 Agent | OpenAI Codex CLI | 2C/4G/20G |
| `qwen-browser` | Qwen 浏览器 Agent | Qwen CLI + Playwright | 2C/4G/15G |
| `qwen-code` | Qwen 代码 Agent | Qwen CLI + 多语言运行时 | 2C/4G/20G |

> **说明**：Agent 模板内的 AI CLI 工具认证已预配置（通过沙箱环境变量注入），用户无需额外配置 API Key。

### 7.3 模板规范（template.yaml）

`template.yaml` 是模板的标准化声明文件，定义了模板的完整规范。

```yaml
# template.yaml — 模板规范 v1
version: "1"

metadata:
  name: python-data-science
  display_name: "Python 数据科学"
  description: "预装 pandas/numpy/matplotlib 的数据分析环境"
  version: "1.2.0"
  author: "easy-sandbox"
  tags: ["python", "data-science", "jupyter"]
  category: "data-science"
  checksum: "sha256:a1b2c3..."     # 模板包完整性校验

base:
  image: "ubuntu:22.04"               # 与 from 二选一
  # from: "owner/repo@tag"            # 继承另一个模板

build:
  apt_install: [build-essential, libpq-dev]
  pip_install: ["pandas>=2.0", numpy, matplotlib]
  npm_install: [typescript]
  env:
    PYTHONUNBUFFERED: "1"
  run: ["jupyter notebook --generate-config"]
  copy:
    - src: "./config/"
      dest: "/app/config/"

resources:
  cpu: 2
  memory: 4096
  disk: 15360
  gpu: null
  timeout: 600
  idle_timeout: 300

network:
  ports: [8888]
  public: false

sandbox:
  mode: "ephemeral"
  workdir: "/workspace"
  user: "sandbox"
  shell: "/bin/bash"
  readiness_probe:
    type: "tcp"
    port: 8888
    timeout: 30

skills:
  bundled: ["jupyter", "pandas-stack"]
  recommended: ["matplotlib-extra"]

agent:
  description: "适用于数据分析、CSV 处理、统计计算、图表生成场景"
  triggers: ["数据分析", "pandas", "CSV", "图表"]
  instructions: |
    1. 数据文件放在 /workspace/data/
    2. 输出文件放在 /workspace/output/
    3. 使用 matplotlib 生成图表时，保存为 PNG

healthcheck:
  command: "python3 -c 'import pandas'"
  interval: 30
  timeout: 5
  retries: 3
```

### 7.4 自定义模板

**方式一：SDK 编程式**

```python
from easy_sandbox import Image

image = (
    Image.from_template("python-base")
    .pip_install("flask", "sqlalchemy", "celery")
    .apt_install("postgresql-client", "redis-tools")
    .copy_local("./config/", "/app/config/")
    .env(FLASK_ENV="production")
    .expose(5000, 6379)
    .entrypoint("python /app/main.py")
)

template_id = await image.build_and_push(name="my-flask-app", tag="v1.0")
```

**方式二：CLI + Dockerfile**

```bash
ebx template build . --name my-flask-app --tag v1.0
ebx template push my-flask-app:v1.0
```

**方式三：sandbox.yaml 声明式**

```yaml
name: my-flask-app
version: "1.0"
base: python-base
packages:
  pip: [flask==3.0, sqlalchemy==2.0, celery==5.3]
  apt: [postgresql-client, redis-tools]
env:
  FLASK_ENV: production
ports: [5000, 6379]
resources: {cpu: 2, memory: 4096}
entrypoint: python /app/main.py
```

**方式四：发布到 GitHub（按 tag/branch/sha 拉取，无需发 Release）**

```bash
ebx template init my-template          # 初始化脚手架
ebx create ./my-template               # 本地测试
cd my-template && git tag v1.0.0
git push origin v1.0.0                 # 推 git tag 即可，无需发 Release
# 其他人：ebx create yourname/my-template（默认分支）或 ebx create yourname/my-template@v1.0.0
```

### 7.5 模板缓存管理

```
~/.ebx/templates/
├── hello/
│   └── world/
│       ├── v1.0.0/
│       │   ├── template.yaml
│       │   └── Dockerfile
│       └── v1.2.0/
│           └── ...
└── myorg/
    └── python-ml/
        └── latest/
```

```bash
ebx template cache list                      # 查看缓存
ebx template cache clean                     # 清理所有缓存
ebx template cache clean hello/world         # 清理指定
ebx create hello/world --no-cache            # 跳过缓存
```

---

## 八、Skills 系统

### 8.1 Skill 定义与结构

Skills 是 Easy Sandbox 的可复用能力包，将「沙箱环境配置 + Agent 使用说明 + MCP Tools 扩展」封装为一个可分发的单元。

```
Skill = 沙箱环境配置 + Agent 使用说明 + MCP Tools 扩展
        ─────────────   ─────────────   ───────────────
        sandbox.yaml     SKILL.md        mcp-tools.json
        Dockerfile       (结构化文档)     (工具定义)
        scripts/
```

**Skill 目录结构**：

```
my-skill/
├── SKILL.md              # Skill 说明文档（AI 可读）
├── sandbox.yaml          # 沙箱环境配置
├── Dockerfile            # 可选：自定义镜像
├── scripts/              # 可选：工具脚本
│   ├── setup.sh
│   └── tools/
│       ├── analyze.py
│       └── visualize.py
├── mcp-tools.json        # 可选：MCP 工具定义
├── examples/             # 使用示例
├── tests/                # 测试
└── skill.lock            # 依赖锁定（自动生成）
```

### 8.2 分类体系

| 类别 | Skills | 说明 |
|------|--------|------|
| **语言运行时** | `python-base`, `node-base`, `go-base`, `java-base`, `rust-base` | 基础开发环境 |
| **数据科学** | `data-analysis`, `ml-sklearn`, `ml-pytorch`, `ml-tensorflow`, `jupyter` | 数据分析与机器学习 |
| **Web 开发** | `nextjs`, `vue`, `flask-api`, `fastapi`, `express` | 前后端框架 |
| **浏览器自动化** | `playwright`, `puppeteer`, `web-scraper`, `screenshot` | 爬虫与自动化 |
| **AI/ML** | `llm-inference`, `embedding`, `image-gen`, `speech`, `ocr` | AI 能力 |
| **数据库** | `postgres`, `mysql`, `redis`, `sqlite`, `mongodb` | 数据存储 |
| **DevOps** | `docker-in-sandbox`, `k8s-tools`, `terraform`, `ansible` | 运维工具 |
| **安全** | `code-audit`, `pentest`, `vulnerability-scan` | 安全审计 |

### 8.3 CLI 命令

```bash
# 搜索 Skill
ebx skill search "data science"
ebx skill search python --category ai-ml

# 安装 Skill
ebx skill install data-analysis                     # 安装到项目
ebx skill install data-analysis --global            # 安装到全局
ebx skill install data-analysis --target cursor     # 安装到 Cursor
ebx skill install data-analysis@1.2.0               # 指定版本
ebx skill install https://github.com/user/my-skill  # 从 Git 安装
ebx skill install ./my-local-skill --link           # 本地开发模式

# 列出已安装
ebx skill list
ebx skill list --target cursor

# 创建和发布
ebx skill create my-awesome-skill
ebx skill publish ./my-skill
ebx skill publish ./my-skill --dry-run
```

### 8.4 安装目标

| 目标 | 命令 | 效果 |
|------|------|------|
| 项目 | `--scope project` | 写入 `sandbox.yaml`，项目级生效 |
| 全局 | `--global` | 写入 `~/.ebx/skills/`，全局生效 |
| Cursor | `--target cursor` | 写入 Cursor MCP 配置 |
| Claude Desktop | `--target claude` | 写入 Claude Desktop 配置 |
| VS Code | `--target vscode` | 写入 VS Code settings |
| Qoder | `--target qoder` | 写入 Qoder 配置 |

### 8.5 与 MCP/Agent 联动

当 AI Agent 通过 MCP 连接到 Easy Sandbox 时，已安装的 Skills 会自动注册为 MCP Tools：

```
Agent（Cursor/Claude）
  │
  ▼
MCP Server
  │
  ├── 内置 Tools（create_sandbox, run_code, ...）
  │
  └── Skill Tools（自动注册）
      ├── data-analysis → analyze_data(), create_chart()
      ├── playwright   → browse_url(), screenshot()
      └── code-audit   → audit_code(), scan_vulnerabilities()
```

---

## 九、MCP Server

### 9.1 Tools 定义

#### P0 — 核心工具（7 个）

| 工具名 | 描述 | 关键参数 |
|--------|------|----------|
| `create_sandbox` | 创建沙箱（支持自然语言） | `description`, `template`, `timeout` |
| `run_code` | 执行代码 | `code`, `language`, `sandbox_id`, `timeout` |
| `run_command` | 执行 Shell 命令 | `command`, `sandbox_id`, `cwd` |
| `read_file` | 读取文件 | `path`, `sandbox_id` |
| `write_file` | 写入文件 | `path`, `content`, `sandbox_id` |
| `list_files` | 列出目录 | `path`, `sandbox_id` |
| `kill_sandbox` | 销毁沙箱 | `sandbox_id` |

#### P1 — 扩展工具（6 个）

| 工具名 | 描述 |
|--------|------|
| `upload_file` | 上传本地文件到沙箱 |
| `download_file` | 从沙箱下载文件 |
| `list_sandboxes` | 列出所有活跃沙箱 |
| `sandbox_info` | 获取沙箱详细信息 |
| `get_url` | 获取沙箱端口的公网 URL |
| `install_packages` | 安装包（pip/npm/apt） |

#### P2 — 高级工具（3 个）

| 工具名 | 描述 |
|--------|------|
| `agent_code` | 调用沙箱内 AI CLI 执行代码任务 |
| `agent_browse` | 调用沙箱内 AI CLI 执行浏览器任务 |
| `deploy_project` | 部署项目到沙箱 |

#### 🔮 远期规划工具

| 工具名 | 描述 | 说明 |
|--------|------|------|
| `snapshot_sandbox` | 创建沙箱快照 | 待底层 Snapshot 能力支持 |
| `hibernate_sandbox` | 休眠沙箱 | 待底层休眠能力支持 |
| `wake_sandbox` | 唤醒休眠沙箱 | 待底层休眠能力支持 |

### 9.2 会话绑定

MCP Server 引入「默认沙箱」概念：

1. 首次调用任何需要沙箱的工具时，如未指定 `sandbox_id`，自动创建默认沙箱
2. 默认沙箱使用 `code-interpreter` 模板
3. 后续调用自动复用默认沙箱
4. 会话结束时自动销毁默认沙箱

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant MCP as MCP Server
    participant SB1 as "默认沙箱 sb-001"
    participant SB2 as "新沙箱 sb-002"

    Note over Client,MCP: 会话开始
    Client->>MCP: run_code("print(1)")
    MCP->>SB1: 自动创建默认沙箱
    SB1-->>Client: 执行结果
    Client->>MCP: run_code("print(2)")
    MCP->>SB1: 复用默认沙箱
    SB1-->>Client: 执行结果
    Client->>MCP: create_sandbox(template=...)
    MCP->>SB2: 创建新沙箱
    Client->>MCP: run_code("...", sandbox=002)
    MCP->>SB2: 使用指定沙箱
    SB2-->>Client: 执行结果
    Client->>MCP: run_code("print(3)")
    MCP->>SB1: 仍使用默认沙箱
    SB1-->>Client: 执行结果
    Note over Client,MCP: 会话结束
    MCP->>SB1: 自动销毁默认沙箱
```

**传输方式**：

| 方式 | 适用场景 | 启动方式 |
|------|---------|---------|
| STDIO | 本地 IDE（Cursor/Claude/VS Code） | IDE 配置自动启动 |
| HTTP + SSE | 远程服务、多客户端共享 | `ebx mcp start --transport http --port 8765` |

> **⚠️ 安全要求**：HTTP 传输模式必须配置 Bearer Token 认证。通过 `--auth-token` 参数或 `SANDBOX_MCP_AUTH_TOKEN` 环境变量设置。STDIO 模式因在本地运行，无需额外认证。

### 9.3 安装方式

```bash
# 一键安装到 IDE
ebx mcp install --target cursor
ebx mcp install --target claude
ebx mcp install --target vscode
ebx mcp install --target qoder

# 安装并指定 Skills
ebx mcp install --target cursor --skills data-analysis,playwright
```

**生成的配置示例**（Cursor）：

```json
{
  "mcpServers": {
    "easy-sandbox": {
      "command": "ebx",
      "args": ["mcp", "start"],
      "env": {
        "SANDBOX_API_KEY": "your-api-key"
      }
    }
  }
}
```

---

## 十、内置 Agent

### 10.1 设计理念

内置 Agent 采用**极简架构**：沙箱模板内预装 AI CLI 工具（Codex、Qwen CLI 等），SDK Agent API 只是 `commands.run()` 的语法糖封装。

**核心优势**：
- **SDK 零 LLM 依赖**：保持轻量，不引入任何 LLM 客户端库
- **用户无需额外 API Key**：AI 工具的认证在沙箱模板内预配置
- **可热更新**：升级模板内的 AI CLI 版本即可获得新能力，无需升级 SDK
- **用户可选择**：Codex 模板 / Qwen 模板 / 自定义模板，灵活切换

### 10.2 Agent 类型与实现映射

| Agent 方法 | 实质执行 | 使用模板 |
|-----------|---------|---------|
| `sb.agent.code("fix bug")` | `sb.commands.run("codex 'fix bug'")` | `codex` |
| `sb.agent.browse("打开百度")` | `sb.commands.run("qwen-cli browse '打开百度'")` | `qwen-browser` |
| `sb.agent.shell("安装 nginx")` | `sb.commands.run("codex 'install nginx and configure'")` | `codex` |
| `sb.agent.analyze("分析数据")` | `sb.commands.run("qwen-cli analyze '分析数据'")` | `qwen-code` |

### 10.3 使用示例

```python
from easy_sandbox import Sandbox

# === 代码 Agent ===
sb = await Sandbox.create(template="codex")
result = await sb.agent.code("分析这段代码的复杂度并给出优化建议", context={"file": "/app/main.py"})
print(result.output)

# === 浏览器 Agent ===
sb = await Sandbox.create(template="qwen-browser")
result = await sb.agent.browse("访问 https://example.com 并截图首页")
print(result.output)

# === Shell 自动化 ===
sb = await Sandbox.create(template="codex")
result = await sb.agent.shell("安装 nginx 并配置反向代理到 8080 端口")
print(result.output)

# === 数据分析 ===
sb = await Sandbox.create(template="qwen-code")
await sb.files.write("/app/data.csv", csv_content)
result = await sb.agent.analyze("对这个 CSV 做趋势分析并生成图表")
print(result.output)
```

### 10.4 AgentModule SDK API

```python
class AgentModule:
    """Agent 语法糖 — 底层调用 commands.run()"""

    async def code(self, task: str, *, context: dict | None = None, timeout: int = 120) -> AgentResult:
        """代码分析/生成/修复"""
        cmd = self._build_command("code", task, context)
        return await self._execute(cmd, timeout)

    async def browse(self, task: str, *, timeout: int = 120) -> AgentResult:
        """浏览器自动化"""
        cmd = self._build_command("browse", task)
        return await self._execute(cmd, timeout)

    async def shell(self, task: str, *, timeout: int = 120) -> AgentResult:
        """Shell 自动化"""
        cmd = self._build_command("shell", task)
        return await self._execute(cmd, timeout)

    async def analyze(self, task: str, *, timeout: int = 120) -> AgentResult:
        """数据分析"""
        cmd = self._build_command("analyze", task)
        return await self._execute(cmd, timeout)

    def _build_command(self, action: str, task: str, context: dict | None = None) -> str:
        """根据模板类型构建 CLI 命令

        ⚠️ 安全要求：防止命令注入
        - 所有用户输入必须通过 shlex.quote() 转义后拼接
        - 或使用参数列表模式（非 shell 字符串）传递给 commands.run()
        """
        import shlex
        # 根据沙箱模板判断使用 codex / qwen-cli / 其他
        # 示例：sb.commands.run(f"codex {shlex.quote(task)}")
        # 而非：sb.commands.run(f"codex '{task}'")  ← 存在注入风险
        ...

    async def _execute(self, cmd: str, timeout: int) -> AgentResult:
        """执行命令并解析结果"""
        result = await self._sandbox.commands.run(cmd, timeout=timeout)
        return AgentResult(output=result.stdout, exit_code=result.exit_code)
```

### 10.5 自然语言推断（简化实现）

自然语言创建沙箱的推断逻辑不再由 SDK 内部的 InferAgent 实现，而是通过外部调用：

```mermaid
flowchart TD
    A["自然语言描述"] --> B{"Server 端 AI 推断接口"}
    B -- 可用 --> P["SandboxPlan(template, cpu, memory, gpu, confidence, reasoning)"]
    B -- 不可用/超时 --> C{"本地 Qwen CLI / DashScope API"}
    C -- 可用 --> P
    C -- 不可用/超时 --> D["关键词规则匹配（完全离线）"]
    D --> P
```

**规则匹配示例**（离线兜底）：

| 关键词 | 推断模板 | 推断资源 |
|--------|---------|---------|
| python, pandas, 数据分析, CSV | python-data-science | 2C/4G |
| node, web, 前端, react, vue | node-web | 1C/2G |
| playwright, 浏览器, 爬虫, 截图 | browser-automation | 2C/4G |
| GPU, CUDA, tensorflow, pytorch | ml-gpu | 4C/16G+GPU |
| codex, 代码生成, fix bug | codex | 2C/4G |

---

## 十一、Agent 框架集成

### Tool Schema 导出

沙箱操作工具遵循 OpenAI function calling 格式，可直接导出为 LangChain / CrewAI / AutoGen 等框架的 Tool Schema：

```python
from easy_sandbox.agent import get_tool_schema

# 导出为 OpenAI 格式
tools = get_tool_schema(format="openai")

# 导出为 LangChain 格式
tools = get_tool_schema(format="langchain")
```

### LangChain 适配器

```python
from easy_sandbox.integrations import LangChainToolkit

toolkit = LangChainToolkit(sandbox_config={"template": "code-interpreter"})
tools = toolkit.get_tools()

# 在 LangChain Agent 中使用
from langchain.agents import AgentExecutor
agent = AgentExecutor(tools=tools, llm=llm)
```

### CrewAI 适配器

```python
from easy_sandbox.integrations import CrewAIToolkit

toolkit = CrewAIToolkit()
tools = toolkit.get_tools()
```

> **说明**：框架集成层仅导出 Tool Schema 和提供适配器，不包含 LLM Provider 适配。LLM 的选择和配置由用户在各自的 Agent 框架中完成。


---

## 十二、技术选型

| 领域 | 选型 | 理由 |
|------|------|------|
| HTTP 客户端 | `httpx` | 原生 async 支持，HTTP/2，E2B 兼容协议实现的核心 |
| WebSocket | `websockets` | 成熟稳定，async 原生，用于 PTY/流式场景 |
| CLI 框架 | `click` + `rich` | 丰富的 UI 组件，表格/进度条 |
| 序列化 | `cloudpickle` + `msgpack` | Python 对象序列化 + 高性能二进制 |
| 配置管理 | `pydantic` | 类型安全的配置验证 |
| 测试 | `pytest` + `pytest-asyncio` | 异步测试标准方案 |
| 包管理 | `hatch` / `pdm` | 现代 Python 项目管理 |

> **注意**：不依赖 `e2b` SDK。L2 Core Protocol 层自行实现 E2B 兼容协议，直接基于 httpx + websockets。

---

## 十三、项目结构

```
src/easy_sandbox/
├── __init__.py                    # 顶层导出：Sandbox, Image, sandbox
├── _version.py                    # 版本号
│
├── transport/                     # L1 — 传输与认证层
│   ├── __init__.py
│   ├── http.py                    #   httpx HTTPS 客户端，连接池
│   ├── ws.py                      #   websockets 长连接，心跳保活
│   ├── auth.py                    #   API Key 认证 + AK/SK 兑换
│   └── config.py                  #   配置加载（代码参数→环境变量→.env→config.toml→默认值）
│
├── protocol/                      # L2 — 核心协议层（自行实现 E2B 兼容）
│   ├── __init__.py
│   ├── sandbox.py                 #   沙箱生命周期 API（HTTP REST）
│   ├── process.py                 #   远程进程管理（HTTP + WebSocket 流式）
│   ├── filesystem.py              #   远程文件系统操作（HTTP REST）
│   ├── terminal.py                #   PTY 终端复用（WebSocket）
│   └── port.py                    #   端口转发管理（HTTP REST）
│
├── extensions/                    # L3 — 阿里云扩展层
│   ├── __init__.py
│   ├── vpc.py                     #   VPC 网络配置
│   ├── oss.py                     #   OSS 挂载与文件同步
│   ├── domain.py                  #   自定义域名绑定
│   ├── nas.py                     #   NAS 文件系统挂载
│   └── log.py                     #   SLS 日志集成
│
├── api/                           # L4 — 高层便捷 API
│   ├── __init__.py
│   ├── sandbox.py                 #   Sandbox 核心类
│   ├── pool.py                    #   SandboxPool 沙箱池
│   ├── image.py                   #   Image 链式构建器
│   ├── files.py                   #   高层文件操作
│   ├── code.py                    #   代码执行引擎
│   └── session.py                 #   Session 管理
│
├── declarative/                   # L5 — 声明式 API 层
│   ├── __init__.py
│   ├── decorator.py               #   @sandbox 装饰器
│   ├── config.py                  #   sandbox.yaml 解析
│   ├── serializer.py              #   参数序列化
│   └── scheduler.py               #   任务调度
│
├── agent/                         # L6 — AI 集成层（轻量封装）
│   ├── __init__.py
│   ├── builtin.py                 #   AgentModule — commands.run() 语法糖
│   ├── tools.py                   #   Agent 工具集（OpenAI function calling 格式）
│   ├── infer.py                   #   自然语言推断（外部调用 Server/Qwen CLI/规则匹配）
│   └── mcp.py                     #   MCP Server 实现
│
├── session/                       # Session 存储后端
│   ├── __init__.py
│   ├── base.py                    #   SessionStore 抽象基类
│   ├── local.py                   #   LocalSessionStore — 本地文件
│   ├── oss.py                     #   OSSSessionStore — 阿里云 OSS
│   └── database.py                #   DatabaseSessionStore — Redis/MySQL
│
├── compat/                        # E2B 迁移辅助层（非透明兼容，需调整 async 调用方式）
│   ├── __init__.py                #   from easy_sandbox.compat import Sandbox
│   └── sandbox.py                 #   E2B 兼容的 Sandbox 封装
│
├── integrations/                  # Agent 框架集成
│   ├── __init__.py
│   ├── langchain.py               #   LangChain 适配器
│   ├── crewai.py                  #   CrewAI 适配器
│   └── autogen.py                 #   AutoGen 适配器
│
├── cli/                           # CLI 命令行工具
│   ├── __init__.py
│   ├── main.py                    #   CLI 入口（ebx 命令）
│   ├── commands/                  #   子命令实现
│   │   ├── sandbox.py             #     create/list/kill/...
│   │   ├── session.py             #     sessions/start/connect
│   │   ├── template.py            #     template build/push/list/...
│   │   ├── skill.py               #     skill search/install/...
│   │   ├── secret.py              #     secret create/list/delete/inject
│   │   ├── mcp.py                 #     mcp install/start/...
│   │   └── deploy.py              #     build/deploy
│   └── formatters.py              #   输出格式化（table/json/quiet）
│
├── models/                        # 数据模型
│   ├── __init__.py
│   ├── sandbox.py                 #   SandboxInfo, SandboxConfig
│   ├── session.py                 #   SessionInfo, SessionConfig
│   ├── process.py                 #   ProcessResult, ProcessConfig
│   ├── filesystem.py              #   FileInfo, WatchEvent
│   └── errors.py                  #   异常类层次
│
└── utils/                         # 工具函数
    ├── __init__.py
    ├── retry.py                   #   重试策略
    ├── logging.py                 #   日志工具
    └── keychain.py                #   系统 Keychain 集成（macOS/Linux）
```

---

## 十四、分阶段路线图

```mermaid
graph LR
    P1["Phase 1 MVP\n6周\n核心 SDK / CLI 基础命令\n临时沙箱 / E2B 兼容协议\nSession 基础 / Tier 1 模板"]
    P2["Phase 2 增强\n6周\nFC Extensions / MCP Server\n自然语言创建 / Session 完整\n沙箱池 / Tier 2 模板"]
    P3["Phase 3 生态\n8周\nSkills 系统 / Agent 模板集成\n模板市场 / 项目部署\n社区生态 / Agent 模板"]
    P4["Phase 4 高级\n持续\nGPU 支持 / 企业特性\n持久/休眠沙箱 / Snapshot\n多区域 / Web Console"]
    P1 --> P2 --> P3 --> P4
```

### Phase 1 — MVP（6 周）

**目标**：可用的核心 SDK + CLI，支持临时沙箱，E2B 兼容协议。

| 周次 | 交付物 |
|------|--------|
| 1-2 | L1 Transport & Auth（API Key + AK/SK 双认证）、L2 Core Protocol 最小子集（Sandbox 生命周期 + Process run + Filesystem read/write，约 8-10 个端点）、项目脚手架、CI/CD |
| 3-4 | L2 完整协议实现（剩余端点）、`Sandbox.create()`、`kill()`、`run_code()`、`commands.*`、`files.*`、Context Manager、同步 API |
| 5-6 | CLI `ebx create/exec/list/kill/shell`、Tier 1 模板 ×5、Session 基础管理、E2B 迁移辅助层、PyPI 发布、文档站点 |

**里程碑**：

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("import pandas as pd; print(pd.__version__)")
    print(result.text)
```

### Phase 2 — 增强（6 周）

**目标**：MCP Server、自然语言创建、完整 Session 管理、FC Extensions。

| 周次 | 交付物 |
|------|--------|
| 7-8 | VPC/OSS/域名 Extensions、SandboxPool、Image 构建器 |
| 9-10 | Session 完整功能（可插拔存储、生命周期管理）、Secret 管理 |
| 11-12 | MCP Server P0 Tools、STDIO 传输、`ebx mcp install`、自然语言创建（三级 Fallback）、Tier 2 ×3 |

**里程碑**：

```bash
ebx create "运行 Python 数据分析，需要 pandas"
ebx mcp install --target cursor
ebx start my-project
ebx sessions list
```

### Phase 3 — 生态（8 周）

**目标**：Skills 系统、Agent 模板集成、模板市场、项目直接部署。

| 周次 | 交付物 |
|------|--------|
| 13-15 | Skill 规范、`ebx skill` CLI、官方 Skills ×10、安装目标、Skill Registry |
| 16-17 | `@sandbox` 装饰器、Agent 模板（codex/qwen-browser/qwen-code）、AgentModule SDK API |
| 18-20 | 模板市场、`ebx build/deploy`、热重载、MCP P1 Tools、HTTP+SSE（含 Bearer Token 认证）、Tier 2 补全 |

### Phase 4 — 高级（持续）

| 交付物 | 预期时间 |
|--------|---------|
| GPU 模板（A10/V100/A100） | 第 21-22 周 |
| 持久沙箱 🔮（需底层支持） | 第 23-24 周 |
| 休眠/Snapshot 🔮（需底层支持） | 第 25-26 周 |
| 企业 SSO（SAML/OIDC） | 第 27-28 周 |
| 多区域（cn-shanghai, cn-shenzhen） | 第 29-30 周 |
| 审计日志 + 团队管理 | 第 31-32 周 |
| MCP P2 Tools + NAS 挂载 | 第 33-34 周 |
| Web Console | 第 35-38 周 |
| Terraform Provider | 第 39-40 周 |

### 关键度量

| 指标 | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|
| SDK 下载量 | 1,000/月 | 5,000/月 | 20,000/月 |
| MCP 安装数 | — | 500 | 3,000 |
| Skills 数量 | — | — | 30+ |
| 社区模板 | — | — | 20+ |
| 沙箱创建量 | 10,000/月 | 50,000/月 | 200,000/月 |
| P95 冷启动 | < 3s | < 2s | < 1.5s |
| API 可用性 | 99.5% | 99.9% | 99.95% |

---

## 十五、Secrets 管理

### 15.1 设计概述

Secrets 管理提供安全的敏感信息存储与注入机制，避免在代码、配置文件中明文存储 API Key、数据库密码等敏感数据。

### 15.2 存储方式

| 存储方式 | 安全级别 | 场景 |
|----------|---------|------|
| **系统 Keychain**（推荐） | 高 | macOS Keychain / Linux Secret Service，本地开发 |
| **加密文件** | 中 | `~/.ebx/secrets.enc`（AES-256 加密，需 master password） |
| **环境变量** | 低 | CI/CD 场景，通过 `SANDBOX_SECRET_*` 前缀注入 |

### 15.3 CLI 命令

```bash
# 创建 Secret
ebx secret create DB_PASSWORD "my-secret-password"
ebx secret create API_KEY "sk-xxx" --store keychain

# 列出 Secrets（仅显示名称，不显示值）
ebx secret list
#   NAME          STORE      CREATED
#   DB_PASSWORD   keychain   2 days ago
#   API_KEY       keychain   1 hour ago

# 删除 Secret
ebx secret delete DB_PASSWORD

# 将 Secrets 注入沙箱
ebx secret inject sb-abc123 --names DB_PASSWORD,API_KEY
```

### 15.4 SDK 集成

```python
from easy_sandbox import Sandbox

# 创建沙箱时注入 Secrets
sb = await Sandbox.create(
    template="python-base",
    secrets=["DB_PASSWORD", "API_KEY"],  # 从 Secrets 存储中读取并注入
)

# 沙箱内通过环境变量访问
result = await sb.commands.run("echo $DB_PASSWORD")
```

---

## 十六、被否决方案

| 方案 | 否决理由 |
|------|---------|
| 自建模板 Registry（类似 npm registry） | 运营成本高，GitHub tarball API（按 tag/branch/sha 拉取，无需 Release）是零运维方案，社区熟悉 |
| CLI 命令用 `sandbox`（全称） | 太长，日常使用效率低 |
| CLI 命令用 `ss`（两字母） | 与系统命令/常见缩写冲突风险大，`ebx` 语义更明确 |
| 仅支持 Dockerfile 构建模板 | 不够声明式，链式 Image API + template.yaml 更友好 |
| 不兼容 E2B API | 放弃 E2B 生态会流失潜在用户，兼容优先 |
| 封装 E2B SDK 作为 L2 核心实现 | 引入不必要的依赖和版本耦合，自行实现协议更可控 |
| 声称"零修改迁移"替代 E2B SDK | 产品定位不清，应强调自身独有价值而非替代竞品 |
| SDK 内置 LLM Provider 适配（OpenAI/Anthropic/Qwen） | 增加包体积和依赖复杂度，Agent 能力改为沙箱内预装 CLI 工具 |
| 复杂 Agent 编排（AgentChain/FanOut/DAG） | 过度设计，90% 场景用单 Agent 就够 |
| Session 信息存储在云端 | 增加服务端复杂度和延迟，改为可插拔设计（本地/OSS/数据库） |
| 使用 gRPC 替代 WebSocket | 浏览器兼容性差，WebSocket 更通用 |

---

## 十七、未来愿景

### `ebx start <anything>` — 云端万物启动器

Easy Sandbox 的终极形态：**一条命令启动任何东西**。

```bash
# 启动应用
ebx start openclaw              # 启动名为 openclaw 的应用
ebx start redis                 # 启动一个 Redis 实例
ebx start jupyter               # 启动 Jupyter Notebook
ebx start postgres              # 启动一个 PostgreSQL 数据库
ebx start nginx                 # 启动一个 Nginx 服务器

# 自然语言启动
ebx start "我需要一个 ML 训练环境"
ebx start "帮我搭建一个 Flask + Redis + PostgreSQL 的后端"
ebx start "运行这个 GitHub 仓库: https://github.com/user/repo"

# 一切都是 Serverless
# - 按需创建，按秒计费
# - 不用关心服务器、容器、镜像
# - 用完即走，或者休眠等待下次唤醒
```

**愿景**：开发者不再需要理解 Docker、Kubernetes、云服务器。他们只需要告诉 `ebx` 自己想要什么，Easy Sandbox 负责把一切跑起来。从一个代码片段到一个完整的分布式应用，从一个临时实验到一个长期运行的服务 — 一切都是 `ebx start`。
