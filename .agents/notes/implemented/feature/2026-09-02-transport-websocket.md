# Decision: WebSocket Transport

Status: implemented
Implemented: 2026-09-02

## Problem
PTY terminal requires bidirectional WebSocket communication for interactive shell sessions.

## Decision
websockets library with:
- Heartbeat: 30s ping interval
- Auto-reconnect: exponential backoff (1s/2s/4s), max 3 retries
- Binary and text frame support
- Graceful shutdown with close frame

WebSocket URL constructed from sandbox domain: `wss://{sandbox_domain}/ws/pty`

## API Design
```python
class WebSocketTransport:
    def __init__(self, url: str, *, ping_interval: float = 30.0,
                 max_retries: int = 3): ...
    async def connect(self) -> None: ...
    async def send(self, data: bytes | str) -> None: ...
    def __aiter__(self) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...
# URL: wss://{sandbox_domain}/ws/pty ; auto-reconnect with backoff 1s/2s/4s.
```

## Implementation
- **Source**: `src/easy_sandbox/transport/ws.py`
- **Tests**: `tests/test_transport/test_ws.py`
- **Server PTY side**: `src/easy_sandbox/server/routes_pty.py` (WebSocket PTY terminal)

## Alternatives considered
- **aiohttp WebSocket** — Would require adding aiohttp as dependency
- **websocket-client** — Sync only, not suitable for async SDK

## Dependencies
- `websockets>=12.0`

## Test Strategy
- Mock WebSocket server for unit tests
- Heartbeat verification (ping/pong)
- Reconnect on unexpected disconnect
- Graceful close handling

## Acceptance criteria
- ✅ Bidirectional message exchange works
- ✅ Auto-reconnect recovers from transient failures
- ✅ Heartbeat keeps connection alive through proxies
