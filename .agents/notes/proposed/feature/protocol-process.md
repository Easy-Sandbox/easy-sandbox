# Decision: Process Protocol (L2, Connect)

Status: proposed

## Problem
Process execution uses Connect protocol with Server-Streaming for real-time output. Need typed protocol layer for process management.

## Decision
`protocol/process.py` implements Connect RPC endpoints:
- `start_process(command, args, env, cwd) → AsyncIterator[ProcessEvent]` (streaming)
- `list_processes() → list[ProcessInfo]`
- `connect_process(pid) → AsyncIterator[ProcessEvent]` (streaming, reconnect to running process)
- `send_stdin(pid, data) → None`
- `kill_process(pid, signal) → None`

Uses `application/connect+json` content type with NDJSON streaming frames.

## Alternatives considered
- **gRPC** — E2B uses Connect protocol, not raw gRPC
- **Non-streaming** — Cannot support real-time output for long-running commands

## Dependencies
- `transport/streaming.py` for Connect frame parsing
- `transport/codec.py` for JSON encoding/decoding
- `models/process.py` for ProcessEvent, ProcessInfo models

## Test Strategy
- Streaming output parsing with mock responses
- stdin forwarding verification
- Process lifecycle (start → send stdin → kill)

## Acceptance criteria
- Execute command and receive streaming stdout/stderr in real-time
- stdin forwarding works for interactive processes
- Process kill sends correct signal
