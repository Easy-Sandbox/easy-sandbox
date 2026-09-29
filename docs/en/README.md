# Easy Sandbox SDK — Documentation

> **Note:** English translations are in progress. Each page below links back to the Chinese original until translation is complete.

Easy Sandbox is a cloud sandbox SDK built on Alibaba Cloud Function Compute, providing E2B-compatible APIs, Modal-style decorators, and built-in AI Agent paradigms.

---

## Design Documents

| # | Document | Description |
|---|----------|-------------|
| 1 | [Architecture Design](design/architecture.md) | Layered architecture overview *(coming soon)* |
| 2 | [SDK API Design](design/sdk-api-design.md) | SDK public API specification *(coming soon)* |
| 3 | [CLI Design](design/cli-design.md) | CLI command structure *(coming soon)* |
| 4 | [Sandbox Types](design/sandbox-types.md) | Sandbox type taxonomy *(coming soon)* |
| 5 | [MCP Server](design/mcp-server.md) | MCP tool server design *(coming soon)* |
| 6 | [Template System](design/template-system.md) | Template resolution and registry *(coming soon)* |
| 7 | [Built-in Agents](design/built-in-agents.md) | Agent module (`commands.run()` sugar) and per-Agent dedicated templates (BYO) |
| 8 | [Server API](design/server-api.md) | In-sandbox HTTP server endpoints *(coming soon)* |
| 9 | [Templates Catalog](design/templates-catalog.md) | Official template catalog *(coming soon)* |

## User Guides

### [`guide/`](guide/) — Tutorials & How-to Guides

| Guide | Description |
|-------|-------------|
| [Getting Started](guide/getting-started.md) | Install, configure, first sandbox *(coming soon)* |
| [Authentication](guide/authentication.md) | API Key / AK-SK authentication *(coming soon)* |
| [SDK Usage](guide/sdk-usage.md) | Python SDK complete usage *(coming soon)* |
| [CLI Tutorial](guide/cli-tutorial.md) | CLI quick start *(coming soon)* |
| [Using Templates](guide/using-templates.md) | Official and community templates *(coming soon)* |
| [Authoring Templates](guide/authoring-templates.md) | Custom template development *(coming soon)* |
| [Deploy & Build](guide/deploy-and-build.md) | `ebx deploy` deployment *(coming soon)* |
| [Declarative Usage](guide/declarative-usage.md) | `@sandbox` decorator *(coming soon)* |
| [MCP Integration](guide/mcp-integration.md) | Cursor / Claude Desktop integration *(coming soon)* |
| [Session Persistence](guide/session-persistence.md) | Local / OSS session storage *(coming soon)* |
| [Migrate from E2B](guide/migrate-from-e2b.md) | Migration guide from E2B SDK *(coming soon)* |
| [Environment Variables](guide/environment-variables.md) | Sandbox env var scopes, injection, and direct-exec semantics |
| [Troubleshooting](guide/troubleshooting.md) | Common issues and solutions *(coming soon)* |
| [E2E Template Workflow](guide/e2e-template-workflow.md) | Complete guide from building a template to using sandboxes |
| [Agent Skill Installation](guide/agent-skill-installation.md) | Install the static SKILL.md agent guide into Qoder / Claude Code / Cursor / Qwen Code / Codex |
| [BYO Agent Integration](guide/byo-agent-integration.md) | Bring your own agent CLI inside a sandbox: responsibility boundary, `custom_commands` contract, credential whitelist, version locking, license boundaries |

### [`reference/`](reference/) — CLI / API / Configuration Reference

| Document | Description |
|----------|-------------|
| [API Reference](reference/api-reference.md) | Complete SDK API documentation *(coming soon)* |
| [CLI Reference](reference/cli-reference.md) | All CLI commands quick reference |
| [Configuration](reference/configuration.md) | Environment variables and config files *(coming soon)* |
| [Error Codes](reference/error-codes.md) | E1xxx–E6xxx error code index *(coming soon)* |
| [Template YAML Spec](reference/template-yaml-spec.md) | Template definition format *(coming soon)* |

### [`explanation/`](explanation/) — Concepts & Architecture

| Document | Description |
|----------|-------------|
| [Architecture Overview](explanation/architecture-overview.md) | Layered architecture concepts *(coming soon)* |
| [E2B Compatibility](explanation/e2b-compatibility.md) | Protocol compatibility *(coming soon)* |
| [Sandbox Lifecycle](explanation/sandbox-lifecycle.md) | Create → Run → Hibernate → Destroy *(coming soon)* |

## Project Planning

| Document | Description |
|----------|-------------|
| [Design Document](DESIGN.md) | Consolidated design decisions *(coming soon)* |

---

## Other Resources

- **Template source of truth (awesome-templates):** [Easy-Sandbox/awesome-templates](https://github.com/Easy-Sandbox/awesome-templates) — the single source of truth for official & community template content, the index (`awesome-templates.yaml`), and publishing; consumed via `ebx template search` / `ebx template install`
- **中文文档**：[Chinese docs](../zh/README.md)
