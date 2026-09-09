# Decision: WebSocket Transport

Status: proposed

## Problem
PTY terminal requires bidirectional WebSocket communication for interactive shell sessions.

## Decision
websockets library with:
- Heartbeat: 30s ping interval
- Auto-reconnect: exponential backoff (1s/2s/4s), max 3 retries
- Binary and text frame support
- Graceful shutdown with close frame

WebSocket URL constructed from sandbox domain: `wss://{sandbox_domain}/ws/pty`

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
- Bidirectional message exchange works
- Auto-reconnect recovers from transient failures
- Heartbeat keeps connection alive through proxies
