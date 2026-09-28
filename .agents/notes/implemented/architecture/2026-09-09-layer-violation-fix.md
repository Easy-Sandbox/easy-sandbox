# Decision: L3→L2 layer-violation fix and error-code reassignment

Status: implemented

## Problem
The project's layered architecture (L0 Models/Utils → L1 Transport → L2 Protocol
→ L3 API) had several violations, causing circular-dependency risk and
architectural erosion:

1. **`session/__init__.py` upward dependency**: the `session` module (same tier as
   L1) imported `api.session_manager.SessionManager` (L3), forming a
   lower→higher reverse dependency.
2. **Error types in the wrong location**: `TemplateBuildError` and
   `TemplateBuildTimeoutError` were defined in `protocol/template.py` (L2), but
   error types are the responsibility of the L0 Models layer.
3. **Error-code collision**: the original codes E7001/E7002 collided with the
   existing `TemplateNotFoundError` (E7001) / `TemplateParseError` (E7002).
4. **Missing CLI command groups**: the `cli/commands/` directory lacked the four
   command modules `session.py`, `secret.py`, `skill.py`, and `auth.py`.

## Decision
### 1. Remove the session upward dependency

Remove the `SessionManager` import from `session/__init__.py`; `__all__` exposes
only the L0/L1-level `SessionStore` (base) and `LocalSessionStore` (local). Users
who need `SessionManager` import it directly from `api.session_manager`.

### 2. Move error classes to models/errors.py

Move `TemplateBuildError` and `TemplateBuildTimeoutError` from
`protocol/template.py` to `models/errors.py` (L0), so that all exception types
are centralized in the errors module.

### 3. Error-code reassignment

- `TemplateBuildError`: E7001 → **E7010**
- `TemplateBuildTimeoutError`: E7002 → **E7011**

The E7010+ range is reserved for Template Build errors and does not collide with
the existing E7000–E7003 (TemplateError/TemplateNotFoundError/TemplateParseError/
TemplateValidationError).

### 4. Fill in the CLI command groups

Add four CLI command modules:
- `cli/commands/auth.py` — authentication management (login/logout/status)
- `cli/commands/session.py` — session management (list/save/restore/delete)
- `cli/commands/secret.py` — secret management (set/get/list/delete)
- `cli/commands/skill.py` — skill management (list/install/remove/run)

## API Design
```python
# session/__init__.py — after the fix
from easy_sandbox.session.base import SessionStore
from easy_sandbox.session.local import LocalSessionStore

__all__ = ["SessionStore", "LocalSessionStore"]
# no longer imports SessionManager (L3)

# models/errors.py — new error-code range
# --- Template Build Errors (E7010+) ---
class TemplateBuildError(SandboxError):
    """Template build failed."""
    code = "E7010"

class TemplateBuildTimeoutError(SandboxError):
    """Template build timed out."""
    code = "E7011"
```

## Alternatives considered
- **Use a TYPE_CHECKING lazy import in session/__init__.py** — still unavailable at
  runtime, and misleads callers into thinking "it can be imported". Rejected.
- **Keep the E7001/E7002 error codes unchanged** — collides with
  `TemplateNotFoundError(E7001)` and `TemplateParseError(E7002)`, breaking
  error-code uniqueness. Rejected.
- **Keep the error definitions in the protocol layer and re-export from models** —
  violates the "all error types belong in models/errors.py" convention and adds
  lookup complexity. Rejected.

## Dependencies
- `models/errors.py` (the unified location for error-class definitions)
- `protocol/template.py` (consumes `TemplateBuildError`/`TemplateBuildTimeoutError`)
- `session/__init__.py` (public API exports)
- `cli/main.py` (registers the new command groups)

## Test Strategy
- Verify `session/__init__.py` contains no `api`-layer imports (Grep check).
- Verify `TemplateBuildError.code == "E7010"` and `TemplateBuildTimeoutError.code == "E7011"`.
- Verify all E7xxx error codes are collision-free (E7000–E7003 + E7010–E7011 + E7020–E7022).
- Verify the four new CLI command groups load correctly via `ebx <group> --help`.

## Acceptance criteria
- `session/__init__` exposes only `SessionStore` and `LocalSessionStore`, with no L3 imports.
- `TemplateBuildError`/`TemplateBuildTimeoutError` are defined in `models/errors.py`,
  with codes E7010/E7011 respectively.
- `cli/commands/` contains the four complete command modules `auth.py`, `session.py`,
  `secret.py`, and `skill.py`.
- Grep for `from easy_sandbox.api` under `session/`, `models/`, and `protocol/` = 0 matches.

## Files changed
- `session/__init__.py` — removed the `SessionManager` import
- `models/errors.py` — added `TemplateBuildError(E7010)`, `TemplateBuildTimeoutError(E7011)`
- `protocol/template.py` — error classes now imported from `models.errors`
- `cli/commands/auth.py` — new
- `cli/commands/session.py` — new
- `cli/commands/secret.py` — new
- `cli/commands/skill.py` — new
