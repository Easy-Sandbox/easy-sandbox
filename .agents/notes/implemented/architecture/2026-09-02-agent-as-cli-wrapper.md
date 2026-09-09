# Decision: Built-in Agent as CLI Syntax Sugar

Status: implemented

## Problem
Users want AI agent capabilities (code generation, debugging, browsing) inside sandboxes. The question is whether to embed LLM clients in the SDK or use a lighter approach.

## Decision
Built-in Agent is a thin CLI wrapper — sandbox templates pre-install Codex/Qwen CLI tools, and `AgentModule` methods map to `commands.run()` calls:
- `sb.agent.code(task)` → `commands.run("codex --task {shlex.quote(task)}")`
- `sb.agent.shell(task)` → `commands.run("qwen-cli shell {shlex.quote(task)}")`

Zero LLM dependencies in the SDK. Users who need advanced agent orchestration use standard Python with the commands API.

## Alternatives considered
- **Embed LLM client** — SDK becomes heavy, requires additional API keys, overlaps with Alibaba Cloud Agent & Skills
- **Full agent framework** — AgentChain/DAG orchestration too complex for SDK scope

## Dependencies
- `api/commands.py` (CommandsModule)
- Sandbox templates with pre-installed CLI tools

## Test Strategy
- Unit test command mapping and shlex.quote escaping
- Integration test with agent-enabled template

## Consequences
- SDK stays lightweight (zero LLM dependencies)
- Agent capabilities depend on template having CLI tools installed
- Command injection prevented via shlex.quote()
