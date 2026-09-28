# Decision: PTY Terminal Protocol (L2, WebSocket)

Status: implemented
Implemented: 2026-09-02

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

## API Design
```python
async def open_terminal(cols: int, rows: int, shell: str) -> TerminalSession: ...

class TerminalSession:
    async def send(self, data: bytes) -> None: ...
    def receive(self) -> AsyncIterator[bytes]: ...
    async def resize(self, cols: int, rows: int) -> None: ...
    async def close(self) -> None: ...
# Binary WebSocket frames; resize sent as JSON control frames with a type-prefix byte.
```

## Implementation
- **Source**: `src/easy_sandbox/protocol/terminal.py`
- **Tests**: `tests/test_protocol/test_terminal.py`
- **Server side**: `src/easy_sandbox/server/routes_pty.py` (WebSocket PTY terminal service)

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
- ✅ Interactive terminal session works with real-time input/output
- ✅ Terminal resize updates the PTY dimensions
- ✅ Graceful close terminates the PTY session
