# Decision: Commands Module (L4)

Status: implemented
Implemented: 2026-09-02

## Problem
Users need to run commands in sandboxes with both blocking and streaming output modes.

## Decision
`api/commands.py` — `CommandsModule` with:
- `run(command, args, env, cwd, timeout) → ExecutionResult` (blocking, waits for completion)
- `stream(command, args, env, cwd) → AsyncIterator[OutputEvent]` (streaming output)
- `start(command, args, env, cwd) → ProcessHandle` (background, returns immediately)
- `list() → list[ProcessInfo]` (list running processes)
- `kill(pid, signal) → None` (kill a running process)

`ExecutionResult` contains: `exit_code`, `stdout`, `stderr`, `text` (combined output).

## API Design
```python
class CommandsModule:
    async def run(self, command: str, args: list[str] | None = None,
                  env: dict | None = None, cwd: str | None = None,
                  timeout: int | None = None) -> ExecutionResult: ...
    def stream(self, command: str, args: list[str] | None = None,
               env: dict | None = None, cwd: str | None = None) -> AsyncIterator[OutputEvent]: ...
    async def start(self, command: str, args: list[str] | None = None,
                    env: dict | None = None, cwd: str | None = None) -> ProcessHandle: ...
    async def list(self) -> list[ProcessInfo]: ...
    async def kill(self, pid: int, signal: int = ...) -> None: ...

# ExecutionResult: exit_code: int, stdout: str, stderr: str, text: str
```

## Implementation
- **Source**: `src/easy_sandbox/api/commands.py`
- **Tests**: `tests/test_api/test_commands.py`
- **Protocol dependency**: `src/easy_sandbox/protocol/process.py`

## Alternatives considered
- **Single run method with mode parameter** — Less discoverable, confusing API
- **Separate Process class** — Over-abstraction for simple command execution

## Dependencies
- `protocol/process.py` for Connect protocol process operations

## Test Strategy
- Command execution with mock protocol responses
- Streaming output accumulation
- Background process lifecycle

## Acceptance criteria
- ✅ `await sb.commands.run("echo hello")` returns result with stdout
- ✅ Streaming mode yields output events in real-time
- ✅ Background processes can be listed and killed
