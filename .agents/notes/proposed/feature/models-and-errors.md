# Decision: Data Models and Error Hierarchy

Status: proposed

## Problem
SDK needs typed data structures for all API interactions and a structured error system that provides actionable information to users.

## Decision
Pydantic v2 models in `models/` package. Error hierarchy rooted at `SandboxError` with `code`, `message`, `suggestion`, `docs_url` fields. Error codes range E1001-E5002, grouped by category:
- E1xxx: Authentication errors
- E2xxx: Sandbox lifecycle errors
- E3xxx: Execution errors
- E4xxx: File operation errors
- E5xxx: Network/transport errors

All models use `model_config = ConfigDict(frozen=True)` for immutability where appropriate.

## Alternatives considered
- **dataclasses** — Less validation, no JSON schema generation
- **TypedDict** — No runtime validation
- **attrs** — Less ecosystem adoption than Pydantic v2

## Dependencies
- `pydantic>=2.0`

## Test Strategy
- Serialization roundtrip tests for all models
- Error instantiation and field access tests
- Error code uniqueness validation

## Acceptance criteria
- All models are JSON serializable via `.model_dump_json()`
- All errors have 4 required fields (code, message, suggestion, docs_url)
- Error codes are unique across the hierarchy
