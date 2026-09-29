# Decision: Make `name` positional-only in sandbox.custom() and run_command()

Status: implemented
Implemented: 2026-09-28

## Problem
Calling `sandbox.custom("hello", name="World")` raised `TypeError: got multiple
values for argument 'name'` because the first positional parameter was also
named `name`, conflicting with the `**kwargs` pass-through to the custom
command's parameters.

This is a Python semantics issue: when a parameter name collides with a keyword
argument the caller intends to forward, the interpreter cannot disambiguate.

## Decision
Use Python 3.8+ positional-only parameter syntax (`/`) to make `name` accept
only positional binding:

```python
async def custom(self, name: str, /, *, server_port: int = 9000, **kwargs):
    ...

async def run_command(self, name: str, /, **kwargs):
    ...
```

After the `/`, `name` is purely positional. Callers can freely pass
`name="value"` in `**kwargs` without collision.

## Alternatives considered
- **Rename the parameter to `command_name`** — breaks the existing public API
  and reads less naturally. Rejected.
- **Accept `*args` and unpack** — loses type safety and IDE support. Rejected.

## Files changed
- `src/easy_sandbox/api/sandbox.py` — `custom()` and `run_command()` signatures

## Acceptance criteria
- ✅ `sandbox.custom("hello", name="World")` works without TypeError
- ✅ `sandbox.custom("hello")` (no kwargs) still works
- ✅ Type checkers (mypy) pass with the positional-only syntax
