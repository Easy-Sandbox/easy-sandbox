# 架构概览

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

本文档简述 Easy Sandbox 的整体架构，帮助理解 SDK、CLI、Server 之间的关系。

---

## 三层架构

Easy Sandbox 由三个核心层组成：

```
┌─────────────────────────────────────────┐
│              用户代码 / AI IDE           │
├───────────┬────────────┬────────────────┤
│  SDK API  │    CLI     │ @sandbox 装饰器 │
│ (Python)  │  (ebx)   │  (declarative)  │
├───────────┴────────────┴────────────────┤
│          Transport 层（HTTP/WS）         │
├─────────────────────────────────────────┤
│      平台 API          │    envd        │
│  (控制平面)            │  (数据平面)    │
├─────────────────────────────────────────┤
│          沙箱容器（Server）              │
└─────────────────────────────────────────┘
```

### SDK 层（客户端）

- **Sandbox 类**：核心入口，管理沙箱生命周期
- **子模块**：`commands`（命令）、`files`（文件）、`network`（网络）、`code`（代码解释器）
- **Image 构建器**：链式 API 构建 Docker 镜像
- **声明式装饰器**：`@sandbox` 远程执行函数

### CLI 层

- **ebx 命令**：基于 Click 的 CLI 工具
- **LazyGroup**：延迟加载子命令，加速 `--help` 响应
- **命令组**：auth、config、session、secret、template、mcp、deploy、skill、sandbox

### Server 层（沙箱内部）

- **HTTP Server**：运行在沙箱内，端口 9000
- **能力组**：8 个能力组控制端点访问
- **自定义命令**：通过 `@sandbox.register` 注册并通过 HTTP 路由暴露

---

## 通信架构

### 控制平面（Platform API）

客户端通过 HTTPS 与平台 API 通信，用于：
- 创建/列出/销毁沙箱
- 模板管理（构建/查询）
- 认证（API Key / AK/SK token 交换）

URL 格式：`https://api.{region}.e2b.fc.aliyuncs.com`

### 数据平面（envd）

沙箱创建后，SDK 通过 HTTPS/WSS 直接与沙箱内的 envd 服务通信：
- 执行命令（HTTP POST）
- 文件操作（HTTP）
- 代码执行（RPC over HTTP）
- 终端会话（WebSocket）

URL 格式：`https://49983-{sandbox_id}.{domain}`

其中 `49983` 是 envd 的固定端口。

### 认证流程

```
客户端                  平台 API              沙箱 envd
  │                       │                     │
  │── API Key/AK/SK ─────→│                     │
  │← sandbox_id + token ──│                     │
  │                       │                     │
  │── envd token ──────────────────────────────→│
  │← 操作结果 ─────────────────────────────────│
```

---

## Server 端能力组

沙箱内 Server 的 42 个端点分为 8 个能力组：

| 能力组 | 默认状态 | 说明 |
|--------|----------|------|
| CORE | 始终启用 | 基础端点（健康检查等） |
| COMMANDS | 启用 | 自定义命令路由 |
| FILE_OPS | 启用 | 文件 CRUD 操作 |
| PROCESS | 启用 | 进程管理 |
| TERMINAL | **启用** | PTY 终端 |
| SYSTEM | 启用 | 系统信息查询 |
| DEV_TOOLS | **禁用** | 开发者工具 |
| BROWSER | **禁用** | 浏览器自动化 |

通过环境变量 `EBX_SERVER_DISABLED_GROUPS` 控制禁用的组，默认值为 `DEV_TOOLS,BROWSER`。

---

## SDK 内部分层

```
api/          ← L4 高层 API（用户直接使用）
  sandbox.py, files.py, commands.py, network.py, code.py, image.py

protocol/     ← L3 协议层（HTTP/RPC 请求构建）
  sandbox.py, process.py, filesystem.py, code_interpreter.py, terminal.py

transport/    ← L2 传输层（HTTP 客户端、认证、配置）
  http.py, auth.py, config.py, streaming.py

models/       ← L1 数据模型（Pydantic 模型）
  sandbox.py, process.py, errors.py, template.py, session.py, filesystem.py

declarative/  ← 声明式远程执行
  decorator.py, serializer.py, config.py

agent/        ← AI Agent 集成
  mcp.py, tools.py, infer.py

session/      ← 会话管理
  local.py, base.py

compat/       ← E2B 兼容层
  sandbox.py

cli/          ← CLI 命令
  main.py, commands/
```

---

## 下一步

- [沙箱生命周期](sandbox-lifecycle.md) — 状态转换和超时机制
- [E2B 兼容性](e2b-compatibility.md) — 设计决策
- [API 参考](../reference/api-reference.md) — 完整 API 文档
