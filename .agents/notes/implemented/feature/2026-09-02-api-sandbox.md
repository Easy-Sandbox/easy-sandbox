# Decision: Sandbox High-Level API (L4)

Status: implemented
Implemented: 2026-09-02

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
- `sb.network` → NetworkModule
- `sb.agent` → AgentModule

## API Design
```python
class Sandbox:
    @classmethod
    async def create(cls, template: str, timeout: int = ...,
                     env_vars: dict | None = None,
                     metadata: dict | None = None) -> "Sandbox": ...
    @classmethod
    async def connect(cls, sandbox_id: str) -> "Sandbox": ...
    async def kill(self) -> None: ...
    async def set_timeout(self, timeout: int) -> None: ...
    async def run_code(self, code: str, language: str = "python") -> ExecutionResult: ...

    commands: CommandsModule   # cached_property
    files: FilesModule         # cached_property
    network: NetworkModule     # cached_property
    agent: AgentModule         # cached_property
```
Sync variants are exposed via a `_sync` suffix.

## Implementation
- **Source**: `src/easy_sandbox/api/sandbox.py`
- **Tests**: `tests/test_api/test_sandbox.py`
- **Future extensions**: `deploy()` classmethod (AI-driven deployment), `list_commands()` command discovery

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
- ✅ `async with await Sandbox.create() as sb: await sb.run_code("print('hello')")` works
- ✅ Context manager properly kills sandbox on exit
- ✅ Sub-modules initialized on first access only
