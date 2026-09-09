# Decision: Sandbox High-Level API (L4)

Status: proposed

## Problem
Users need a convenient, Pythonic Sandbox class that abstracts away protocol details and provides a clean interface for sandbox lifecycle management.

## Decision
`api/sandbox.py` — `Sandbox` class with:
- `Sandbox.create(template, timeout, env_vars, metadata) → Sandbox` (async classmethod)
- `Sandbox.connect(sandbox_id) → Sandbox` (async classmethod)
- `sb.kill() → None`
- `sb.set_timeout(timeout) → None`
- `sb.run_code(code, language) → ExecutionResult`
- Async context manager support (`async with await Sandbox.create() as sb:`)
- Sync variants via `_sync` suffix for non-async users

Sub-modules as `cached_property`:
- `sb.commands` → CommandsModule
- `sb.files` → FilesModule
- `sb.network` → NetworkModule (future)
- `sb.agent` → AgentModule

## Alternatives considered
- **Functional API** — Less discoverable, harder to manage lifecycle
- **Builder pattern** — Over-complex for typical use cases

## Dependencies
- `protocol/*` for all protocol operations
- `models/*` for typed data structures

## Test Strategy
- Full lifecycle mock test (create → use → kill)
- Context manager cleanup verification
- Sub-module lazy initialization

## Acceptance criteria
- `async with await Sandbox.create() as sb: await sb.run_code("print('hello')")` works
- Context manager properly kills sandbox on exit
- Sub-modules initialized on first access only
