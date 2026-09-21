# Easy Sandbox

<!-- badges — these light up once CI is enabled and the package is published to PyPI -->
[![CI](https://github.com/Easy-Sandbox/easy-sandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/Easy-Sandbox/easy-sandbox/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/easy-sandbox)](https://pypi.org/project/easy-sandbox/)
[![Python 3.10+](https://img.shields.io/pypi/pyversions/easy-sandbox)](https://pypi.org/project/easy-sandbox/)
[![License](https://img.shields.io/github/license/Easy-Sandbox/easy-sandbox)](LICENSE)

> Create, manage, and interact with cloud sandboxes for AI agents.

**Easy Sandbox** is a Python SDK and CLI (`ebx`) for the Alibaba Cloud FC Agent Sandbox service.
It is **E2B-protocol compatible** with extensions for the Alibaba Cloud ecosystem (OSS, VPC, custom domains).

---

## Features

- **Async-first SDK** — `Sandbox.create()`, code execution, file I/O, port forwarding, and WebSocket streaming.
- **Declarative decorator** — `@sandbox` turns a plain function into a remote sandbox execution with automatic serialisation.
- **CLI (`ebx`)** — create, inspect, exec, upload/download, and manage sandboxes from the terminal.
- **Template system** — reusable sandbox images (Python, Node, browser automation, AI agents, …).
- **MCP server** — expose sandbox operations as an MCP tool server for LLM agents.
- **Session persistence** — save and restore sandbox state across runs (local or OSS-backed).
- **Framework integrations** — LangChain, CrewAI, AutoGen adapters (_Coming Soon_).
- **E2B compatibility layer** — drop-in replacement for projects already using the E2B SDK.

## Installation

```bash
# Core SDK only
pip install easy-sandbox

# With the CLI
pip install "easy-sandbox[cli]"

# Everything (CLI + MCP + fast JSON + sessions + declarative)
pip install "easy-sandbox[all]"

# Development (includes test & lint tooling)
pip install -e ".[dev]"
```

## Quick Start — SDK

```python
from easy_sandbox import Sandbox

async def main():
    async with await Sandbox.create(template="python-base") as sb:
        # Run code
        result = await sb.run_code("print('Hello from sandbox!')")
        print(result.text)  # Hello from sandbox!

        # File operations
        await sb.filesystem.write("/tmp/data.txt", b"hello")
        content = await sb.filesystem.read("/tmp/data.txt")

        # Shell commands
        proc = await sb.commands.run("ls -la /tmp")
        print(proc.stdout)
```

## Quick Start — CLI

```bash
# Configure credentials
ebx config set api_key <YOUR_API_KEY>

# Sandbox lifecycle
ebx create --template python-base       # create a sandbox
ebx list                                 # list running sandboxes
ebx info <sandbox-id>                    # inspect a sandbox
ebx exec <sandbox-id> "echo hello"       # run a command
ebx connect <sandbox-id>                 # interactive shell

# File transfer
ebx upload <sandbox-id> ./local.txt /remote/path.txt
ebx download <sandbox-id> /remote/path.txt ./local.txt

# Install community templates
ebx install owner/repo                   # install from GitHub

# Manage templates
ebx template list
ebx template info python-base

# MCP server
ebx mcp start                            # start MCP tool server

# Cleanup
ebx kill <sandbox-id>
```

## Templates

Ready-made sandbox templates live in [`examples/templates/`](examples/templates/):

| Template | Description |
|----------|-------------|
| `python-hello` | Minimal Python sandbox |
| `node-web` | Node.js web application |
| `browser-automation` | Headless browser with Playwright |
| `claude-code` | Claude Code agent harness |
| `codex` | OpenAI Codex agent harness |
| `qoder` | Qoder agent harness |
| `qwen-code` | Qwen-Code agent harness _(WIP — template shell only)_ |
| `deepseek-harness` | DeepSeek agent harness |
| `hermes-agent` | Hermes agent harness |
| `openclaw` | OpenClaw agent harness |

See each template directory for its `Dockerfile`, `template.yaml`, and `README.md`.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  L6  Agent Integration    MCP server, built-in agents      │
│  L5  Declarative API      @sandbox decorator               │
├─────────────────────────────────────────────────────────────┤
│  L4  High-Level API       Sandbox, Pool, Files, Code       │
│  L3  Extensions           OSS, VPC, Custom Domains         │
├─────────────────────────────────────────────────────────────┤
│  L2  Core Protocol        E2B-compat REST + WebSocket      │
│  L1  Transport & Auth     HTTP/2, API Key, AK/SK           │
└────────────────────────────┬────────────────────────────────┘
                             │
                China Region Gateway → Alibaba Cloud FC
```

Lower layers never import upper layers. Full design: [`docs/design/architecture.md`](docs/design/architecture.md).

## Documentation

| Resource | Path |
|----------|------|
| Architecture & design | [`docs/`](docs/) |
| Changelog | [`CHANGELOG.md`](CHANGELOG.md) |
| Contributing guide | [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) |
| License | [`LICENSE`](LICENSE) |

## Contributing

We welcome contributions! Please read the [Contributing Guide](.github/CONTRIBUTING.md) to get started.

## License

[Apache-2.0](LICENSE) — see [`NOTICE`](NOTICE) for copyright information.
