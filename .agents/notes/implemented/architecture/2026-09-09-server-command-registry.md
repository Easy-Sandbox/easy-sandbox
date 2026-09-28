# Decision: Server CommandRegistry standalone command registry

Status: implemented

## Problem
`server/routes.py` previously depended on the `declarative` layer's `_registry`
dict (an attribute of a `_SandboxFactory` instance) and dynamically executed the
source code of user-registered functions via `exec(source)`. This caused two
problems:

1. **Layer violation**: the `server` module (a stdlib-only in-container module)
   had a reverse dependency on the `declarative` layer, breaking the server
   module's zero-external-dependency design principle.
2. **Security risk**: `exec()` dynamically executing source strings carries a
   code-injection risk and is hard to debug.

A standalone, zero-external-dependency command-registration mechanism was needed
so the server module can manage command registration on its own while remaining
compatible with the declarative layer's `@sandbox.register` decorator.

## Decision
Create a standalone `CommandRegistry` class in `server/registry.py`, using stdlib
`dataclasses` for the data model, with no dependency on Pydantic or any other SDK
layer.

### Key design

1. **`CommandArg` type validation**: defined with `@dataclasses.dataclass`;
   `__post_init__` validates that the `type` field is one of the four scalar
   types `{"string", "integer", "float", "boolean"}`.

2. **`RegisteredCommand` direct function reference**: the `fn` field holds a
   direct reference to the callable and no longer stores a source string. This
   eliminates the use of `exec()`.

3. **`freeze()` locking mechanism**: `CommandRegistry.freeze()` marks the
   registry read-only; `register()` raises `RuntimeError` while frozen. This
   ensures the command set is immutable after the server starts.

4. **`default_registry` singleton**: the module-level `_default_registry`
   instance is exposed via the `default_registry()` function; both `routes.py`
   and `app.py` reference the same instance.

5. **declarative → server one-way bridge**: `_RegisterProxy.__call__` in
   `declarative/decorator.py`, after registering a command into
   `_factory._registry`, synchronously registers it into
   `server.registry.default_registry()` inside a `try/except ImportError`,
   forming a one-way bridge. The server module is unaware of the declarative
   layer's existence.

## API Design
```python
# server/registry.py — stdlib dataclasses, zero external dependencies

@dataclasses.dataclass
class CommandArg:
    name: str
    type: str = "string"          # {"string", "integer", "float", "boolean"}
    required: bool = False
    default: str | None = None
    description: str = ""

@dataclasses.dataclass
class RegisteredCommand:
    name: str
    fn: Any                       # direct function reference, not a source string
    args: list[CommandArg] = field(default_factory=list)
    description: str = ""

class CommandRegistry:
    def register(self, name: str, fn: Any, *, args=None, description=""): ...
    def command(self, name: str | None = None, **kwargs): ...  # decorator
    def freeze(self) -> None: ...
    def get(self, name: str) -> RegisteredCommand | None: ...
    def list_all(self) -> dict[str, RegisteredCommand]: ...

def default_registry() -> CommandRegistry: ...  # module-level singleton
```

```python
# declarative/decorator.py — bridge snippet
self._factory._registry[name] = cmd

# Bridge to server registry (effective only inside a container)
try:
    from easy_sandbox.server.registry import CommandArg as ServerCommandArg
    from easy_sandbox.server.registry import default_registry
    server_registry = default_registry()
    server_registry.register(name=cmd.name, fn=func, args=server_args, ...)
except ImportError:
    pass  # server module not installed
except RuntimeError:
    pass  # registry already frozen
```

## Alternatives considered
- **Keep the `exec()` + source-delivery mechanism** — high security risk (code
  injection), hard to debug (no line-number info), and cannot retain the
  function's closure state. Rejected.
- **Expose `declarative._registry` as a public interface for server to reference
  directly** — introduces a server→declarative reverse dependency, violating the
  zero-dependency principle. Rejected.
- **Use a Pydantic model for `CommandArg`** — the server module must be
  stdlib-only to run inside a container with no pip environment, and Pydantic is
  a third-party dependency. Rejected.

## Dependencies
- `server/routes.py` (consumes commands from `default_registry()` for route dispatch)
- `server/app.py` (`SandboxServer.__init__` accepts an optional `registry` argument)
- `declarative/decorator.py` (the bridge layer, with an optional dependency on the server registry)
- `2026-09-05-sandbox-server-module.md` (overall server-module architecture)

## Test Strategy
- After registering a command, `registry.get(name)` returns the correct `RegisteredCommand`.
- `CommandArg` rejects invalid `type` values (e.g. `"list"`).
- After `freeze()`, `register()` raises `RuntimeError`.
- The `command()` decorator infers argument types and defaults from the function signature.
- `default_registry()` returns the same singleton instance.
- declarative bridge: a command registered via `@sandbox.register` appears in both registries.

## Acceptance criteria
- `server/registry.py` uses only the Python standard library (`dataclasses`, `inspect`), with zero third-party dependencies.
- `routes.py` and `app.py` no longer import any symbol from the `declarative` layer.
- `exec()` is no longer used anywhere in the server module.
- The declarative → server bridge is optional (`try/except ImportError`); the server can run standalone.

## Files changed
- `server/registry.py` — new, 288 lines
- `server/routes.py` — refactored to obtain commands from `default_registry`
- `server/app.py` — refactored; `SandboxServer` accepts a `registry` argument
- `declarative/decorator.py` — added the bridge logic
