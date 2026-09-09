# Decision: Self-implement E2B Protocol Instead of Wrapping SDK

Status: implemented

## Problem
We need to communicate with E2B-compatible sandbox APIs (Platform API + envd API). The choice is between wrapping the official E2B Python SDK or implementing the protocol directly.

## Decision
Self-implement the E2B protocol using httpx + websockets. This gives us full control over:
- Connect protocol (`application/connect+json`) encoding/decoding
- Server-Streaming frame parsing
- Dual token management (API Key for Platform, envdAccessToken for envd)
- HTTP/2 connection pooling and domain partitioning
- Alibaba Cloud-specific extensions (VPC, OSS, domain binding)

## Alternatives considered
- **Wrap E2B SDK** — Version lock to e2b<3.0, cannot customize Connect protocol handling, L1 transport layer becomes a thin passthrough with limited value, Alibaba Cloud extensions require bypassing SDK

## Dependencies
- `httpx[http2]>=0.27` for HTTP client
- `websockets>=12.0` for WebSocket PTY channels

## Test Strategy
- Unit tests with pytest-httpx mocks for all protocol endpoints
- Golden tests with captured real API responses
- Integration tests against real Alibaba Cloud sandbox API

## Consequences
- Full protocol control enables performance optimization (orjson, streaming frame parsing)
- More initial development effort (~3 extra days) but eliminates SDK version dependency risk
- Protocol layer can be reused for future TypeScript SDK
