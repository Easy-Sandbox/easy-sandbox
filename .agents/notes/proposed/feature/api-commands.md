# Decision: Commands Module (L4)

Status: proposed

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
- `await sb.commands.run("echo hello")` returns result with stdout
- Streaming mode yields output events in real-time
- Background processes can be listed and killed
