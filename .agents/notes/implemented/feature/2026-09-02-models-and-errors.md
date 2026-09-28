# Decision: Data Models and Error Hierarchy

Status: implemented
Implemented: 2026-09-02

## Problem
SDK needs typed data structures for all API interactions and a structured error system that provides actionable information to users.

## Decision
Pydantic v2 models in `models/` package. Error hierarchy rooted at `SandboxError` with `code`, `message`, `suggestion`, `docs_url` fields. Error codes range E1001-E6xxx, grouped by category:
- E1xxx: Authentication errors
- E2xxx: Sandbox lifecycle / creation errors
- E3xxx: Execution errors
- E4xxx: File operation errors
- E5xxx: Network/transport errors
- E6xxx: Session errors

All models use `model_config = ConfigDict(frozen=True)` for immutability where appropriate.

## API Design
```python
class SandboxError(Exception):
    code: str          # e.g. "E1001"
    message: str
    suggestion: str
    docs_url: str

# Category base classes
class AuthenticationError(SandboxError): ...   # E1xxx
class SandboxCreationError(SandboxError): ...  # E2xxx
class ExecutionError(SandboxError): ...        # E3xxx
class FileOperationError(SandboxError): ...    # E4xxx
class NetworkError(SandboxError): ...          # E5xxx
class SessionError(SandboxError): ...          # E6xxx
```

## Implementation
- **Error hierarchy**: `src/easy_sandbox/models/errors.py`
- **Sandbox model**: `src/easy_sandbox/models/sandbox.py`
- **Filesystem model**: `src/easy_sandbox/models/filesystem.py`
- **Process model**: `src/easy_sandbox/models/process.py`
- **Template model**: `src/easy_sandbox/models/template.py`
- **Config model**: `src/easy_sandbox/models/config.py`
- **Session model**: `src/easy_sandbox/models/session.py`
- **Tests**: `tests/test_models/`

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
- ✅ All models are JSON serializable via `.model_dump_json()`
- ✅ All errors have 4 required fields (code, message, suggestion, docs_url)
- ✅ Error codes are unique across the hierarchy
