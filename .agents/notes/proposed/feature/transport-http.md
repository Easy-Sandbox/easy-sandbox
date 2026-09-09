# Decision: HTTP Transport Layer

Status: proposed

## Problem
Need an async HTTP client with connection pooling for Platform API and envd API, supporting both HTTP/1.1 and HTTP/2.

## Decision
httpx AsyncClient with HTTP/2 enabled, domain-partitioned connection pools:
- **Platform gateway pool**: single domain, shared across all sandbox operations
- **Per-sandbox envd pool**: unique domain per sandbox instance

Configuration: `max_connections=100`, `keepalive_expiry=30s`, default timeout 30s (configurable).

Transport client is a thin wrapper around httpx providing:
- Automatic header injection (auth, content-type)
- Request/response logging (debug level)
- Retry logic with exponential backoff for 5xx errors

## Alternatives considered
- **aiohttp** — Less ergonomic API, no HTTP/2 support
- **urllib3** — Sync only
- **requests** — Sync only

## Dependencies
- `httpx[http2]>=0.27`
- `models/` for typed request/response

## Test Strategy
- Mock HTTP responses with pytest-httpx
- Connection reuse verification
- Timeout and retry behavior tests

## Acceptance criteria
- Can send authenticated requests to both Platform and envd endpoints
- Connection pooling reduces latency for repeated requests
- HTTP/2 multiplexing works for concurrent requests
