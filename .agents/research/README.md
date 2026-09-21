# 云沙箱调研文档索引

> 最后更新：2026-09-01

---

本目录包含阿里云云沙箱（FC Agent Sandbox）SDK 设计前的技术调研文档。

## 文档清单

| # | 文档 | 说明 |
|---|------|------|
| 1 | [E2B 云沙箱现状分析与痛点](./e2b-analysis.md) | E2B 兼容 API 清单、兼容边界、十大痛点分析、阿里云差异化能力 |
| 2 | [Modal.com 设计模式深度分析](./modal-analysis.md) | 装饰器 API 体系、Image 链式构建、Sandbox 功能、Skills 系统 |
| 3 | [云沙箱竞品深度对比](./competitor-comparison.md) | Modal vs E2B vs Daytona 功能矩阵、SDK 设计、差异化竞争点 |
| 4 | [云沙箱用户场景全景调研](./user-scenarios.md) | 10 大使用场景、沙箱模式映射、用户需求缺口分析 |
| 5 | [MCP 与 AI Agent 集成调研](./mcp-and-agent-integration.md) | MCP 协议、现有实现、Tool 分级设计、Agent 框架集成模式、Skills 系统 |

## 阅读顺序建议

1. 先阅读 **E2B 分析** 了解现状和痛点
2. 再阅读 **Modal 分析** 学习先进设计模式
3. 通过 **竞品对比** 明确差异化方向
4. 结合 **用户场景** 确认需求优先级
5. 最后阅读 **MCP 与 Agent 集成** 规划集成架构
