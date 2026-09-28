# MCP Server 设计

> Easy Sandbox MCP Server 将沙箱能力暴露为 MCP (Model Context Protocol) Tools，让 AI Agent（Cursor、Claude Desktop、VS Code 等）可以直接操作云端沙箱。

---

## 1. Tools 定义

### P0 — 核心工具（7 个）

#### create_sandbox

```json
{
  "name": "create_sandbox",
  "description": "创建一个云端沙箱环境。支持自然语言描述自动推断配置。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "description": {
        "type": "string",
        "description": "自然语言描述需要什么环境（如 '运行 Python 数据分析'），或模板名（如 'code-interpreter'）"
      },
      "template": {
        "type": "string",
        "description": "沙箱模板名称。如果提供了 description 且为自然语言，此参数可省略"
      },
      "timeout": {
        "type": "integer",
        "description": "沙箱超时时间（秒），默认 300",
        "default": 300
      },
      "persistent": {
        "type": "boolean",
        "description": "🔮 远期规划 — 是否创建持久沙箱（待底层能力支持）",
        "default": false
      }
    }
  },
  "returns": {
    "sandbox_id": "string — 沙箱 ID",
    "url": "string — 沙箱访问 URL",
    "status": "string — 沙箱状态"
  }
}
```

#### run_code

```json
{
  "name": "run_code",
  "description": "在沙箱中执行代码。支持 Python、JavaScript、Shell 等语言。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "code": {
        "type": "string",
        "description": "要执行的代码"
      },
      "language": {
        "type": "string",
        "description": "编程语言",
        "enum": ["python", "javascript", "shell", "typescript", "r"],
        "default": "python"
      },
      "sandbox_id": {
        "type": "string",
        "description": "沙箱 ID。省略时使用默认沙箱"
      },
      "timeout": {
        "type": "integer",
        "description": "执行超时（秒）",
        "default": 30
      }
    },
    "required": ["code"]
  },
  "returns": {
    "stdout": "string",
    "stderr": "string",
    "exit_code": "integer",
    "output_files": "array — 生成的文件列表"
  }
}
```

#### run_command

```json
{
  "name": "run_command",
  "description": "在沙箱中执行 Shell 命令。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "command": { "type": "string", "description": "Shell 命令" },
      "sandbox_id": { "type": "string", "description": "沙箱 ID" },
      "cwd": { "type": "string", "description": "工作目录", "default": "/app" },
      "timeout": { "type": "integer", "default": 60 }
    },
    "required": ["command"]
  },
  "returns": {
    "stdout": "string",
    "stderr": "string",
    "exit_code": "integer"
  }
}
```

#### read_file

```json
{
  "name": "read_file",
  "description": "读取沙箱中的文件内容。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "文件路径" },
      "sandbox_id": { "type": "string" },
      "encoding": { "type": "string", "default": "utf-8" }
    },
    "required": ["path"]
  },
  "returns": { "content": "string" }
}
```

#### write_file

```json
{
  "name": "write_file",
  "description": "在沙箱中创建或覆写文件。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "description": "文件路径" },
      "content": { "type": "string", "description": "文件内容" },
      "sandbox_id": { "type": "string" }
    },
    "required": ["path", "content"]
  },
  "returns": { "success": "boolean", "size": "integer" }
}
```

#### list_files

```json
{
  "name": "list_files",
  "description": "列出沙箱中指定目录的文件和子目录。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": { "type": "string", "default": "/app" },
      "sandbox_id": { "type": "string" }
    }
  },
  "returns": {
    "files": "array — [{name, path, type, size, modified}]"
  }
}
```

#### kill_sandbox

```json
{
  "name": "kill_sandbox",
  "description": "销毁指定沙箱或默认沙箱。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "sandbox_id": { "type": "string", "description": "省略时销毁默认沙箱" }
    }
  },
  "returns": { "success": "boolean" }
}
```

### P1 — 扩展工具（6 个）

| 工具名 | 描述 | 关键参数 |
|--------|------|----------|
| `upload_file` | 上传本地文件到沙箱 | `local_path`, `remote_path` |
| `download_file` | 从沙箱下载文件 | `remote_path`, `local_path` |
| `list_sandboxes` | 列出所有活跃沙箱 | `status` (running) |
| `sandbox_info` | 获取沙箱详细信息 | `sandbox_id` |
| `get_url` | 获取沙箱端口的公网 URL | `port`, `sandbox_id` |
| `install_packages` | 在沙箱中安装包 | `packages[]`, `manager` (pip/npm/apt) |

### P2 — 高级工具（3 个）

| 工具名 | 描述 | 关键参数 |
|--------|------|----------|
| `agent_code` | 调用沙箱内 AI CLI 执行代码任务 | `task`, `sandbox_id` |
| `agent_browse` | 调用沙箱内 AI CLI 执行浏览器任务 | `task`, `sandbox_id` |
| `deploy_project` | 部署项目到沙箱 | `project_dir`, `name` |

### 🔮 远期规划工具

| 工具名 | 描述 | 说明 |
|--------|------|------|
| `snapshot_sandbox` | 创建沙箱快照 | 待底层 Snapshot 能力支持 |
| `hibernate_sandbox` | 休眠沙箱 | 待底层休眠能力支持 |
| `wake_sandbox` | 唤醒休眠沙箱 | 待底层休眠能力支持 |

---

## 2. 会话绑定设计

### 默认沙箱概念

MCP Server 引入「默认沙箱」概念，简化 Agent 操作：

```mermaid
graph TD
    A["Agent 首次调用 run_code（无 sandbox_id）"] --> B[MCP Server 自动创建默认沙箱]
    B --> C["后续调用自动使用默认沙箱（直到会话结束或手动切换）"]
```

**行为规则**：

1. 首次调用任何需要沙箱的工具时，如未指定 `sandbox_id`，自动创建默认沙箱
2. 默认沙箱使用 `code-interpreter` 模板
3. 默认沙箱在会话结束时自动销毁（STDIO 模式）或超时销毁（HTTP 模式）
4. Agent 可通过 `create_sandbox` 显式创建新沙箱，并通过 `sandbox_id` 切换

```mermaid
sequenceDiagram
    participant Agent
    participant MCP as MCP Server
    participant SB1 as sb-001
    participant SB2 as sb-002

    Note over Agent,MCP: 会话开始
    Agent->>MCP: run_code("print(1)")
    MCP->>SB1: 自动创建默认沙箱 sb-001
    Agent->>MCP: run_code("print(2)")
    MCP->>SB1: 复用 sb-001
    Agent->>MCP: create_sandbox(template=...)
    MCP->>SB2: 创建新沙箱 sb-002
    Agent->>MCP: run_code("...", sandbox=002)
    MCP->>SB2: 使用 sb-002
    Agent->>MCP: run_code("print(3)")
    MCP->>SB1: 仍使用默认 sb-001
    Note over Agent,MCP: 会话结束
    MCP->>SB1: 自动销毁 sb-001
    Note over SB2: sb-002 根据 persistent 配置决定
```

---

## 3. 传输方式

### STDIO — 本地 IDE 集成

```mermaid
graph LR
    IDE["IDE / Agent<br/>Cursor, Claude, VS Code"] <-->|"STDIO stdin/stdout<br/>JSON-RPC over STDIO"| MCP["MCP Server<br/>ebx mcp"]
    MCP --> SM[Sandbox Manager]
    SM --> FC[阿里云 FC]
```

**适用场景**：本地开发，单用户，IDE 直接启动。

**启动方式**：IDE 配置中指定命令，IDE 自动启动进程。

### Streamable HTTP — 远程部署（FC）

> **状态：** Streamable HTTP 传输层 (`mcp_http.py`) 已实现。`ebx mcp deploy` CLI 命令**尚未实现**。

```mermaid
graph LR
    A["Client A - Cursor"] <-->|"Streamable HTTP<br/>POST /mcp"| MCP["MCP Server<br/>FC 函数"]
    B["Client B - Claude"] <-->|"Streamable HTTP<br/>POST /mcp"| MCP
    MCP --> SM["会话管理器<br/>按 Mcp-Session-Id 分派"]
    SM --> FC[阿里云 FC]
```

**适用场景**：远程服务、团队共享、多客户端同时使用。

**协议**：MCP Streamable HTTP（规范 2025-06-18）。通过 `Mcp-Session-Id` 响应头实现会话亲和；阿里云 FC 原生支持 MCP 会话路由。

**启动方式**：通过 `ebx mcp deploy` 部署（规划中），或本地运行 `ebx mcp start --transport http --port 8765`。

> **注意：** 旧版 HTTP+SSE 传输（MCP 规范 2024-11-05）已被 Streamable HTTP 规范取代。现有 SSE 端点仍可运行，但新部署应使用 Streamable HTTP。

---

## 4. Server 架构图

```mermaid
graph TD
    subgraph MCP["MCP Server"]
        TL["Transport Layer\nSTDIO / HTTP"]
        TR["Tool Registry\nP0 Core / P1 Ext / P2 Adv / Skills"]
        SM["Session Manager\nSession A~C / sb-001~003"]
        RR["Request Router\n认证 - 路由 - 执行 - 格式化 - 响应"]
        SC["Sandbox Client\neasy_sandbox SDK"]
    end
    TL --> RR
    TR --> RR
    SM --> RR
    RR --> SC
    SC --> FC["阿里云 FC 沙箱运行时"]
```

---

## 5. 安装方式

### 一键安装

```bash
# 安装到 Cursor
ebx mcp install --target cursor

# 安装到 Claude Desktop
ebx mcp install --target claude

# 安装到 VS Code (Copilot)
ebx mcp install --target vscode

# 安装到 Qoder
ebx mcp install --target qoder

# 安装并指定 Skills
ebx mcp install --target cursor --skills data-analysis,playwright

# 安装 HTTP 模式（远程服务器）
ebx mcp install --transport http --port 8765
```

### 安装过程

```bash
$ ebx mcp install --target cursor

✓ 检测 Cursor 配置目录: ~/.cursor/
✓ 写入 MCP 配置: ~/.cursor/mcp.json
✓ 验证认证信息: API Key 已配置
✓ 安装完成！

请重启 Cursor 以生效。MCP Server 将在 Cursor 启动时自动运行。

已注册工具:
  • create_sandbox  — 创建云端沙箱
  • run_code        — 执行代码
  • run_command     — 执行命令
  • read_file       — 读取文件
  • write_file      — 写入文件
  • list_files      — 列出文件
  • kill_sandbox    — 销毁沙箱
```

---

## 6. 配置示例

### Claude Desktop 配置

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "easy-sandbox": {
      "command": "ebx",
      "args": ["mcp", "start", "--transport", "stdio"],
      "env": {
        "SANDBOX_API_KEY": "your-api-key",
        "SANDBOX_REGION": "cn-hangzhou"
      }
    }
  }
}
```

### Cursor 配置

```json
// ~/.cursor/mcp.json
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

### VS Code 配置

```json
// .vscode/settings.json
{
  "mcp.servers": {
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

### HTTP 模式配置（远程服务）

```bash
# 本地启动 Streamable HTTP MCP Server
ebx mcp start --transport http --port 8765 --host 0.0.0.0

# 客户端连接
# Streamable HTTP 端点: http://server:8765/mcp
```

```json
// 远程 MCP 配置 (Streamable HTTP)
{
  "mcpServers": {
    "easy-sandbox-remote": {
      "url": "http://your-server:8765/mcp"
    }
  }
}
```

---

## 7. FC 部署

> **状态：** Streamable HTTP 传输层 (`mcp_http.py`) 已实现。`ebx mcp deploy` CLI 命令**尚未实现**。

### 架构

MCP Server 可部署到阿里云函数计算 (FC) 作为 Streamable HTTP 端点，利用 FC 原生的 MCP 会话亲和路由。

```mermaid
graph TB
    CLI["ebx mcp deploy → 打包 → FC CreateFunction + CreateTrigger"]
    FC["FC 函数: easy-sandbox-mcp-server"]
    Sandbox["Envd 沙箱（另一个 FC 实例）"]

    CLI --> FC
    FC --> Sandbox

    subgraph FC_Function ["FC 函数"]
        ASGI["easy_sandbox.agent.mcp_http:asgi_app"]
        Trigger["HTTP 触发器: POST/GET/DELETE /mcp"]
        Session["会话亲和: Mcp-Session-Id"]
        Env["环境变量: EBX_API_KEY / EBX_API_URL / EBX_TEMPLATE"]
    end
```

### 关键设计要点

- **协议**：Streamable HTTP（MCP 规范 2025-06-18）
- **会话亲和**：委托 FC 平台层通过 `Mcp-Session-Id` 头实现 — 无需应用层粘性路由
- **认证**：双层 — 客户端→MCP 使用 `Authorization: Bearer <token>`；MCP→沙箱使用 FC 环境变量中的 `E2B_API_KEY`
- **生命周期**：沙箱按 MCP 会话懒创建；`DELETE /mcp` 触发清理；idle timer 作为安全网
- **冷启动**：FC 冷启动 (~1–3s) 可能与 MCP initialize 超时冲突；生产环境建议使用预留实例

### CLI 命令（规划中）

```bash
ebx mcp deploy \
  --name easy-sandbox-mcp \
  --region cn-hangzhou \
  --template python-base \
  --memory 512 --timeout 600 \
  --generate-token \
  --enable-session-affinity
```

产出：FC 函数 ARN、HTTP 触发器 URL 和 IDE 配置片段。

详见 [CLI 设计 — mcp deploy](cli-design.md#mcp-deploy) 获取完整参数参考。
```
