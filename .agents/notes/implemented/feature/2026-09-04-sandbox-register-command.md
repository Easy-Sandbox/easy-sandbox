# Decision: @sandbox.register decorator-based command (registered on the persistent HTTP server endpoint)

Status: implemented
Implemented: 2026-09-09
Task: #98, #105, #118

## Problem
Users need to register Python functions as named commands invokable through
`ebx run`. Currently custom commands can only be declared via YAML (the
`custom_commands:` section of `template.yaml`); there is no way to register them
directly from Python code. A decorator API is needed that maps a function name
to a command name and the function signature to CLI options.

## Decision
Add the `@sandbox.register` decorator. Commands are registered on the endpoints
of the persistent in-container HTTP server, and the client invokes them over
HTTP.

> **⚠ Key change (2026-09-05)**: the original ADR used a "source-delivery
> execution" mechanism (`files.write` to deliver a script + `commands.run` to
> execute it) and explicitly did not introduce a new in-container server. That
> decision has been reversed. Reasons: (1) every invocation required the full
> files.write + commands.run chain, with high latency; (2) it could not support
> persistent state; (3) the new `easy_sandbox.server` module (see
> `2026-09-05-sandbox-server-module.md`) has been added and provides a
> persistent HTTP server to host registered commands.

### Core design

1. **Commands are registered as persistent HTTP server endpoints**: functions
   decorated with `@sandbox.register` are registered as HTTP endpoints on the
   `easy_sandbox.server` module. Clients invoke them via
   `POST /commands/{name}` with a JSON kwargs body; the response is
   `{"result": ...}` or `{"error": ..., "type": ...}`.

2. **Function name → command name**: for a function decorated with
   `@sandbox.register`, `func.__name__` becomes the command name, isomorphic to
   the keys of YAML `custom_commands:`. The final output is a `CustomCommand`
   object, identical to what YAML parsing produces, so **all downstream
   consumers** (`Sandbox.run` placeholder substitution, `list_commands` discovery
   output, CLI `--arg` parsing) **can be reused with zero changes**.

3. **Function signature → CLI options**: at **import time**, the decorator runs
   `inspect.signature(fn)` and converts parameter name / type annotation /
   default value into `CustomCommandArg` (including a `type` field).

4. **Parameter-type restriction**: V1 supports only the four scalars
   `str`/`int`/`float`/`bool`.

### WIRE CONTRACT (client → server communication protocol)

5. **Request format**: `POST https://{port}-{sandbox_id}.{domain}/commands/{name}`
6. **Success response**: `200 OK`, `{"result": <return_value>}`
7. **Failure response**: `4xx/5xx`, `{"error": "<message>", "type": "<exception_class>"}`
8. **Discovery endpoint**: `GET /commands` → returns all registered commands and their argument schemas.

### O7 naming decision: keep @sandbox.register

9. **Naming-conflict resolution**: by changing `sandbox` into a `_SandboxFactory`
   callable — it simultaneously supports `__call__` (the `@sandbox(template=...)`
   semantics) and a `register` method.

## API Design
```python
@sandbox.register
def demo(x: int, y: str = "hello") -> str:
    """Run a demo command."""
    return f"{x}: {y}"

# SDK: await sandbox.server.call("demo", x=42, y="world")
# CLI: ebx run <sandbox_id> demo -a x=42 -a y="world"
# Discovery: GET /commands
```

## Alternatives considered
- **Source-delivery execution (files.write + commands.run)** — Rejected in favor of a persistent HTTP server.
- **cloudpickle-serialize the function body** — high deployment cost. Rejected.
- **Route through envd Code Interpreter primitives** — not empirically tested. Rejected.
- **`@remote.register` naming** — adds mental overhead. Rejected.

## Dependencies
- `declarative/decorator.py`
- `models/template.py` (`CustomCommand`, `CustomCommandArg`)
- `2026-09-05-sandbox-server-module.md` (server-module architecture)

## Test Strategy
- After `@sandbox.register`, the function name becomes a discoverable command name.
- `inspect.signature` correctly extracts parameter names, types, and defaults.
- Unsupported parameter types cause an immediate error at decoration time.
- End-to-end: `POST /commands/demo` invocation → returns the correct JSON response.

## Acceptance criteria
- ✅ `@sandbox.register`-decorated functions are registered as HTTP server endpoints.
- ✅ YAML-declared commands and Python-registered commands converge on the same `CustomCommand` model.
- ✅ `sandbox` is both a callable decorator and has a `.register` method.
- ✅ WIRE CONTRACT: the `POST /commands/{name}` + JSON body protocol is in effect.

## Implementation
- **Decorator**: `src/easy_sandbox/declarative/decorator.py` (`_SandboxFactory` class + `register` method)
- **Server routes**: `src/easy_sandbox/server/routes.py` (`GET /commands`, `POST /commands/{name}`)
- **Command registry**: `src/easy_sandbox/server/registry.py` (`CommandRegistry`, `RegisteredCommand`)
- **CLI integration**: `src/easy_sandbox/cli/commands/sandbox.py` (`ebx run` auto-scans `@sandbox.register`)
- **Model**: `src/easy_sandbox/models/template.py` (`CustomCommand`, `CustomCommandArg` include a `type` field)

## Evidence
- `.agents/evidence/research/2026-09-04-container-serve-boundary.md` §5, §6.1–§6.3, §7 O7
