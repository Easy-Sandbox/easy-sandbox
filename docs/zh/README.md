# Easy Sandbox SDK — 文档中心

> **更名注记**：本项目已从 Serverless Sandbox 完成全量改名为 **Easy Sandbox**。
> - **PyPI 包名**：`easy-sandbox`（`pip install easy-sandbox`）
> - **Python 导入名**：`easy_sandbox`
> - **CLI 命令**：`ebx`
> - **GitHub 仓库名**：`easy-sandbox`

Easy Sandbox 是基于阿里云函数计算的云端沙箱 SDK，提供 E2B 兼容 API、Modal 风格装饰器和内置 AI Agent 三种使用范式。

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
| 9 | [Server API](design/server-api.md) | 容器内 HTTP Server 端点定义、42 端点、8 个能力组 |
| 10 | [模板目录](design/templates-catalog.md) | 官方模板集合形态契约、发布流程、离线校验 |

## 用户文档

### [`guide/`](guide/) — 使用教程与 How-to 指南

| 文档 | 说明 |
|------|------|
| [快速开始](guide/getting-started.md) | 安装、配置、第一个沙箱 |
| [认证配置](guide/authentication.md) | API Key / AK-SK 双认证模式 |
| [SDK 使用](guide/sdk-usage.md) | Python SDK 完整用法 |
| [CLI 教程](guide/cli-tutorial.md) | 命令行快速上手 |
| [模板使用](guide/using-templates.md) | 官方与社区模板使用 |
| [模板编写](guide/authoring-templates.md) | 自定义模板开发指南 |
| [部署与构建](guide/deploy-and-build.md) | `ebx deploy` 项目部署 |
| [声明式用法](guide/declarative-usage.md) | `@sandbox` 装饰器 |
| [MCP 集成](guide/mcp-integration.md) | Cursor / Claude Desktop 集成 |
| [会话持久化](guide/session-persistence.md) | 本地 / OSS 会话存储 |
| [E2B 迁移](guide/migrate-from-e2b.md) | 从 E2B 迁移指南 |
| [故障排查](guide/troubleshooting.md) | 常见问题与解决方案 |

### [`reference/`](reference/) — CLI / API / 配置参考

| 文档 | 说明 |
|------|------|
| [API 参考](reference/api-reference.md) | SDK 公开 API 完整文档 |
| [CLI 参考](reference/cli-reference.md) | 所有 CLI 命令速查 |
| [配置参考](reference/configuration.md) | 环境变量、配置文件、优先级 |
| [错误码](reference/error-codes.md) | E1xxx–E6xxx 错误码索引 |
| [template.yaml 规范](reference/template-yaml-spec.md) | 模板定义格式 |

### [`explanation/`](explanation/) — 概念解释与架构综述

| 文档 | 说明 |
|------|------|
| [架构综述](explanation/architecture-overview.md) | 六层分层架构概念解释 |
| [E2B 兼容性](explanation/e2b-compatibility.md) | 协议兼容原理与差异 |
| [沙箱生命周期](explanation/sandbox-lifecycle.md) | 创建→运行→休眠→销毁 |

## 项目规划

| 文档 | 说明 |
|------|------|
| [完整设计文档](DESIGN.md) | 所有设计决策汇总 |
| [项目路线图](roadmap.md) | Phase 1-4 交付计划与里程碑 |

---

## 快速导航

### 按角色

- **SDK 用户**：[SDK API 设计](design/sdk-api-design.md) → [沙箱类型](design/sandbox-types.md) → [模板体系](design/template-system.md)
- **CLI 用户**：[CLI 命令体系](design/cli-design.md) → [模板体系](design/template-system.md) → [Skills 系统](design/skills-system.md)
- **AI Agent 开发者**：[内置 Agent](design/built-in-agents.md) → [MCP Server](design/mcp-server.md) → [Skills 系统](design/skills-system.md)
- **架构师**：[系统架构](design/architecture.md) → [Server API](design/server-api.md) → [项目路线图](roadmap.md)

### 按功能

- **自然语言创建沙箱**：[SDK API](design/sdk-api-design.md#核心设计理念自然语言优先) | [CLI](design/cli-design.md#3-自然语言创建) | [InferAgent](design/built-in-agents.md#2-配置推断-agentinferagent)
- **项目直接部署**：[CLI 部署命令](design/cli-design.md#sbox-deploy)（`ebx deploy` 已实现，支持 NL 模式与传统模式）
- **MCP 集成（Cursor/Claude）**：[MCP Server](design/mcp-server.md#5-安装方式)

### 其他资源

- **社区模板索引**：[`awesome-templates.yaml`](../../awesome-templates.yaml) — 官方与社区贡献的沙箱模板统一索引
- **English Documentation**：[English docs](../en/README.md)
