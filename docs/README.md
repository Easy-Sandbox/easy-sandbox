# Serverless Sandbox SDK — 设计文档

> Serverless Sandbox 是基于阿里云函数计算的云端沙箱 SDK，提供 E2B 兼容 API、Modal 风格装饰器和内置 AI Agent 三种使用范式。

---

## 设计文档

| # | 文档 | 说明 |
|---|------|------|
| 1 | [系统架构设计](design/architecture.md) | 六层分层架构总览、各层职责、目录结构 |
| 2 | [SDK API 设计](design/sdk-api-design.md) | **核心文档** — 三种使用范式、自然语言创建、完整 API 定义 |
| 3 | [CLI 命令体系](design/cli-design.md) | 命令树、自然语言创建、项目直接部署、AI Friendly 原则 |
| 4 | [沙箱类型体系](design/sandbox-types.md) | 临时/持久/休眠三种模式、生命周期状态机、计费模型 |
| 5 | [Skills 系统](design/skills-system.md) | Skill 定义、分类体系、CLI 命令、分发机制 |
| 6 | [MCP Server](design/mcp-server.md) | Tools 定义（P0/P1/P2）、会话绑定、传输方式、IDE 配置 |
| 7 | [模板体系](design/template-system.md) | 官方模板、自定义模板、sandbox.yaml 规范、模板市场 |
| 8 | [内置 Agent](design/built-in-agents.md) | 配置推断 Agent、5 种内置 Agent、自定义 Agent、Agent Chain |

## 项目规划

| 文档 | 说明 |
|------|------|
| [项目路线图](roadmap.md) | Phase 1-4 交付计划与里程碑 |

---

## 快速导航

### 按角色

- **SDK 用户**：[SDK API 设计](design/sdk-api-design.md) → [沙箱类型](design/sandbox-types.md) → [模板体系](design/template-system.md)
- **CLI 用户**：[CLI 命令体系](design/cli-design.md) → [模板体系](design/template-system.md) → [Skills 系统](design/skills-system.md)
- **AI Agent 开发者**：[内置 Agent](design/built-in-agents.md) → [MCP Server](design/mcp-server.md) → [Skills 系统](design/skills-system.md)
- **架构师**：[系统架构](design/architecture.md) → [项目路线图](roadmap.md)

### 按功能

- **自然语言创建沙箱**：[SDK API](design/sdk-api-design.md#核心设计理念自然语言优先) | [CLI](design/cli-design.md#3-自然语言创建) | [InferAgent](design/built-in-agents.md#2-配置推断-agentinferagent)
- **项目直接部署**：[CLI deploy](design/cli-design.md#4-项目直接部署)
- **MCP 集成（Cursor/Claude）**：[MCP Server](design/mcp-server.md#5-安装方式)
