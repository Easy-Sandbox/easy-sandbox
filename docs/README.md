# Easy Sandbox Documentation

---

## 中文文档 | Chinese

完整文档索引请查看 [中文文档目录](zh/README.md)

### 设计文档

| # | 文档 | 说明 |
|---|------|------|
| 1 | [系统架构设计](zh/design/architecture.md) | 六层分层架构总览、各层职责、目录结构 |
| 2 | [SDK API 设计](zh/design/sdk-api-design.md) | 三种使用范式、自然语言创建、完整 API 定义 |
| 3 | [CLI 命令体系](zh/design/cli-design.md) | 命令树、自然语言创建、项目直接部署 |
| 4 | [沙箱类型体系](zh/design/sandbox-types.md) | 临时/持久/休眠三种模式、生命周期状态机 |
| 5 | [Skills 系统](zh/design/skills-system.md) | Skill 定义、分类体系、CLI 命令、分发机制 |
| 6 | [MCP Server](zh/design/mcp-server.md) | Tools 定义、会话绑定、传输方式、IDE 配置 |
| 7 | [模板体系](zh/design/template-system.md) | 官方模板、自定义模板、sandbox.yaml 规范 |
| 8 | [内置 Agent](zh/design/built-in-agents.md) | 配置推断 Agent、内置 Agent、Agent Chain |
| 9 | [Server API](zh/design/server-api.md) | 容器内 HTTP Server 端点定义 |
| 10 | [模板目录](zh/design/templates-catalog.md) | 官方模板集合形态契约、发布流程 |

### 使用教程

| 文档 | 说明 |
|------|------|
| [快速开始](zh/guide/getting-started.md) | 安装、配置、第一个沙箱 |
| [认证配置](zh/guide/authentication.md) | API Key / AK-SK 双认证模式 |
| [SDK 使用](zh/guide/sdk-usage.md) | Python SDK 完整用法 |
| [CLI 教程](zh/guide/cli-tutorial.md) | 命令行快速上手 |
| [模板使用](zh/guide/using-templates.md) | 官方与社区模板使用 |
| [模板编写](zh/guide/authoring-templates.md) | 自定义模板开发指南 |
| [部署与构建](zh/guide/deploy-and-build.md) | `ebx deploy` 项目部署 |
| [声明式用法](zh/guide/declarative-usage.md) | `@sandbox` 装饰器 |
| [MCP 集成](zh/guide/mcp-integration.md) | Cursor / Claude Desktop 集成 |
| [会话持久化](zh/guide/session-persistence.md) | 本地 / OSS 会话存储 |
| [E2B 迁移](zh/guide/migrate-from-e2b.md) | 从 E2B 迁移指南 |
| [故障排查](zh/guide/troubleshooting.md) | 常见问题与解决方案 |

### 参考手册

| 文档 | 说明 |
|------|------|
| [API 参考](zh/reference/api-reference.md) | SDK 公开 API 完整文档 |
| [CLI 参考](zh/reference/cli-reference.md) | 所有 CLI 命令速查 |
| [配置参考](zh/reference/configuration.md) | 环境变量、配置文件、优先级 |
| [错误码](zh/reference/error-codes.md) | E1xxx–E6xxx 错误码索引 |
| [template.yaml 规范](zh/reference/template-yaml-spec.md) | 模板定义格式 |

### 概念解释

| 文档 | 说明 |
|------|------|
| [架构综述](zh/explanation/architecture-overview.md) | 六层分层架构概念解释 |
| [E2B 兼容性](zh/explanation/e2b-compatibility.md) | 协议兼容原理与差异 |
| [沙箱生命周期](zh/explanation/sandbox-lifecycle.md) | 创建→运行→休眠→销毁 |

### 项目规划

| 文档 | 说明 |
|------|------|
| [完整设计文档](zh/DESIGN.md) | 所有设计决策汇总 |
| [项目路线图](zh/roadmap.md) | Phase 1-4 交付计划与里程碑 |

---

## English Documentation

Full documentation index: [English docs](en/README.md)

> **Note:** English translations are in progress. Links below point to placeholder pages that reference the Chinese originals.

### Design

| # | Document | Description |
|---|----------|-------------|
| 1 | [Architecture Design](en/design/architecture.md) | Layered architecture overview *(coming soon)* |
| 2 | [SDK API Design](en/design/sdk-api-design.md) | SDK public API specification *(coming soon)* |
| 3 | [CLI Design](en/design/cli-design.md) | CLI command structure *(coming soon)* |
| 4 | [Sandbox Types](en/design/sandbox-types.md) | Sandbox type taxonomy *(coming soon)* |
| 5 | [Skills System](en/design/skills-system.md) | Pluggable skill system *(coming soon)* |
| 6 | [MCP Server](en/design/mcp-server.md) | MCP tool server design *(coming soon)* |
| 7 | [Template System](en/design/template-system.md) | Template resolution and registry *(coming soon)* |
| 8 | [Built-in Agents](en/design/built-in-agents.md) | Built-in AI agent harness *(coming soon)* |
| 9 | [Server API](en/design/server-api.md) | In-sandbox HTTP server endpoints *(coming soon)* |
| 10 | [Templates Catalog](en/design/templates-catalog.md) | Official template catalog *(coming soon)* |

### Tutorials

| Guide | Description |
|-------|-------------|
| [Getting Started](en/guide/getting-started.md) | Install, configure, first sandbox *(coming soon)* |
| [Authentication](en/guide/authentication.md) | API Key / AK-SK authentication *(coming soon)* |
| [SDK Usage](en/guide/sdk-usage.md) | Python SDK complete usage *(coming soon)* |
| [CLI Tutorial](en/guide/cli-tutorial.md) | CLI quick start *(coming soon)* |
| [Using Templates](en/guide/using-templates.md) | Official and community templates *(coming soon)* |
| [Authoring Templates](en/guide/authoring-templates.md) | Custom template development *(coming soon)* |
| [Deploy & Build](en/guide/deploy-and-build.md) | `ebx deploy` deployment *(coming soon)* |
| [Declarative Usage](en/guide/declarative-usage.md) | `@sandbox` decorator *(coming soon)* |
| [MCP Integration](en/guide/mcp-integration.md) | Cursor / Claude Desktop integration *(coming soon)* |
| [Session Persistence](en/guide/session-persistence.md) | Local / OSS session storage *(coming soon)* |
| [Migrate from E2B](en/guide/migrate-from-e2b.md) | Migration guide from E2B SDK *(coming soon)* |
| [Troubleshooting](en/guide/troubleshooting.md) | Common issues and solutions *(coming soon)* |

### Reference

| Document | Description |
|----------|-------------|
| [API Reference](en/reference/api-reference.md) | Complete SDK API documentation *(coming soon)* |
| [CLI Reference](en/reference/cli-reference.md) | All CLI commands *(coming soon)* |
| [Configuration](en/reference/configuration.md) | Environment variables and config files *(coming soon)* |
| [Error Codes](en/reference/error-codes.md) | E1xxx–E6xxx error code index *(coming soon)* |
| [Template YAML Spec](en/reference/template-yaml-spec.md) | Template definition format *(coming soon)* |

### Explanation

| Document | Description |
|----------|-------------|
| [Architecture Overview](en/explanation/architecture-overview.md) | Layered architecture concepts *(coming soon)* |
| [E2B Compatibility](en/explanation/e2b-compatibility.md) | Protocol compatibility *(coming soon)* |
| [Sandbox Lifecycle](en/explanation/sandbox-lifecycle.md) | Create → Run → Hibernate → Destroy *(coming soon)* |

### Project Planning

| Document | Description |
|----------|-------------|
| [Design Document](en/DESIGN.md) | Consolidated design decisions *(coming soon)* |
| [Roadmap](en/roadmap.md) | Phase 1-4 delivery plan *(coming soon)* |
