# Decision: Session Pluggable Storage Backend

Status: implemented

## Problem
Session data (sandbox mapping, state) needs persistence across CLI invocations. Different deployment scenarios need different storage backends.

## Decision
Define `SessionStore` abstract base class with pluggable backends:
1. **LocalSessionStore** (default) — filelock-based, `~/.sbox/sessions/`
2. **OSSSessionStore** (Phase 2) — Alibaba Cloud OSS for team sharing
3. **DatabaseSessionStore** (Phase 2) — SQL database for enterprise

Interface: `save(session)`, `load(session_id)`, `list()`, `delete(session_id)`, `exists(session_id)`

## Alternatives considered
- **Local-only** — Cannot support team collaboration
- **Database-only** — Over-engineered for single-user CLI
- **Redis** — Additional infrastructure dependency

## Dependencies
- `filelock>=3.12` for LocalSessionStore
- `pydantic` for SessionInfo/SessionConfig models

## Test Strategy
- Unit test each backend independently with mock I/O
- Test concurrent access with filelock
- Test session lifecycle (create → save → load → delete)

## Consequences
- Single-user works out of the box with local storage
- Team/enterprise can upgrade storage without code changes
- Session store selection via config: `session.backend = "local" | "oss" | "database"`
