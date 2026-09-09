# Decision: PTY Terminal Protocol (L2, WebSocket)

Status: proposed

## Problem
Interactive terminal needs bidirectional WebSocket for real-time PTY sessions with resize support.

## Decision
`protocol/terminal.py` manages PTY WebSocket channel:
- `open_terminal(cols, rows, shell) → TerminalSession`
- `TerminalSession.send(data: bytes) → None`
- `TerminalSession.receive() → AsyncIterator[bytes]`
- `TerminalSession.resize(cols, rows) → None`
- `TerminalSession.close() → None`

WebSocket messages are binary frames. Resize commands sent as JSON control frames with a type prefix byte.

## Alternatives considered
- **HTTP long-polling** — Too much latency for interactive terminal
- **SSH** — Additional protocol complexity, E2B uses WebSocket

## Dependencies
- `transport/ws.py` for WebSocket client

## Test Strategy
- Bidirectional message exchange with mock WS
- Resize command formatting and delivery
- Connection close handling

## Acceptance criteria
- Interactive terminal session works with real-time input/output
- Terminal resize updates the PTY dimensions
- Graceful close terminates the PTY session
