# MCP 集成

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

Easy Sandbox 提供 MCP（Model Context Protocol）Server，使 AI IDE 和工具能够直接操作沙箱。

---

## 什么是 MCP

MCP（Model Context Protocol）是一个开放协议，允许 AI 模型与外部工具和服务交互。Easy Sandbox 的 MCP Server 以 STDIO 传输、JSON-RPC 2.0 协议运行，为 AI 助手提供沙箱操作能力。

---

## 安装到 IDE

### Cursor

```bash
ebx mcp install --target cursor
```

此命令会在 Cursor 的 MCP 配置文件中写入 Easy Sandbox Server 配置。

### Claude Desktop

```bash
ebx mcp install --target claude
```

### VS Code

```bash
ebx mcp install --target vscode
```

### 查看安装状态

```bash
ebx mcp status
# 显示：MCP Server 状态、可用工具数量、各 IDE 安装状态
```

---

## 可用工具

MCP Server 提供 7 个工具：

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `create_sandbox` | 创建新沙箱 | `template`（可选，默认 code-interpreter-v1）、`timeout`（可选） |
| `run_code` | 在沙箱中执行代码 | `sandbox_id`、`code`、`language`（可选，默认 python） |
| `run_command` | 在沙箱中执行 Shell 命令 | `sandbox_id`、`command`、`timeout`（可选） |
| `read_file` | 读取沙箱中的文件 | `sandbox_id`、`path` |
| `write_file` | 写入文件到沙箱 | `sandbox_id`、`path`、`content` |
| `list_files` | 列出沙箱中的目录内容 | `sandbox_id`、`path`（可选，默认 /app） |
| `kill_sandbox` | 销毁沙箱 | `sandbox_id` |

> **注意**：`list_files` 省略 `path` 时默认列出 `/app` 目录内容。如需查看根目录，需显式传入 `path="/"`。

---

## 场景示例

### 在 Cursor 中使用

安装 MCP 后，在 Cursor 的 AI 对话中，模型可以自动调用 Easy Sandbox 工具：

1. **代码执行**：「在沙箱中运行这段 Python 代码，看看输出是什么」
2. **环境搭建**：「创建一个沙箱，安装 flask 和 sqlalchemy，然后运行我的项目」
3. **文件操作**：「把这个文件写入沙箱的 /app 目录」
4. **调试辅助**：「在沙箱里执行 pip list 看看装了哪些包」

### 典型工作流

```text
用户: 帮我在沙箱中测试这段代码
  ↓
AI 调用 create_sandbox → 获取 sandbox_id
  ↓
AI 调用 write_file → 写入代码文件
  ↓
AI 调用 run_code → 执行代码
  ↓
AI 调用 read_file → 读取结果
  ↓
AI 调用 kill_sandbox → 清理
```

---

## 手动启动 MCP Server

通常 MCP Server 由 IDE 自动启动。如需手动运行：

```bash
ebx mcp start [选项]
```

| 选项 | 说明 |
|------|------|
| `--template` | 默认模板（默认 code-interpreter-v1） |
| `--api-key` | API Key 覆盖 |
| `--api-url` | API URL 覆盖 |
| `--domain` | Domain 覆盖 |

Server 以 STDIO 模式运行，通过 stdin/stdout 与调用方通信。

---

## 技术细节

- **传输协议**：STDIO（标准输入/输出）
- **消息格式**：JSON-RPC 2.0
- **沙箱管理**：MCP Server 内部维护 `SandboxManager`，管理多个沙箱实例的生命周期
- **默认模板**：`code-interpreter-v1`

---

## 下一步

- [CLI 教程](cli-tutorial.md) — CLI 完整使用教程
- [SDK 使用指南](sdk-usage.md) — 直接使用 SDK
- [CLI 参考](../reference/cli-reference.md) — MCP 命令详细参考
