# Decision: Platform API Protocol (L2)

Status: proposed

## Problem
Need typed wrappers for sandbox lifecycle REST API (create, list, get info, kill, set timeout).

## Decision
`protocol/sandbox.py` wraps Platform API endpoints as async functions:
- `create_sandbox(template, timeout, metadata, env_vars) → SandboxInfo`
- `list_sandboxes() → list[SandboxInfo]`
- `get_sandbox_info(sandbox_id) → SandboxInfo`
- `kill_sandbox(sandbox_id) → None`
- `set_timeout(sandbox_id, timeout) → None`

All functions use Platform API with `X-API-KEY` authentication (standard REST, JSON body).

## Alternatives considered
- **Combined protocol module** — Too large, mixes REST and Connect concerns

## Dependencies
- `transport/http.py` for HTTP client
- `transport/auth.py` for authentication
- `models/sandbox.py` for typed request/response models

## Test Strategy
- Request construction verification with mocked HTTP
- Response parsing with golden response fixtures
- Error response handling (404, 401, 500)

## Acceptance criteria
- Full sandbox lifecycle (create → list → info → kill) works via protocol layer
- All responses are typed Pydantic models
- HTTP errors mapped to appropriate SDK error types
