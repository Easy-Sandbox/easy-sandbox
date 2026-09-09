# Decision: SDK Capability Surface (Capability-Driven, Type-Safe Dynamic)

Status: implemented

## Problem
The SDK must expose two kinds of commands: (a) standard capabilities with well-known signatures (`commands.run`, `files.upload`, ...) and (b) template-declared custom commands whose names are only known at runtime. We need dynamic dispatch for (b) without sacrificing the static type safety promised by `py.typed` + mypy.

## Decision
Keep standard capabilities as **typed methods**, and route custom commands through **explicit dynamic dispatch** — no `__getattr__` magic.

1. **Standard capabilities** keep their typed methods (`sandbox.commands.run(...)`, `sandbox.files.upload(...)`, etc.). Each is subject to capability gating (raises `CapabilityNotSupportedError` when the capability is absent — see capability-model ADR).
2. **Custom commands** are invoked via one explicit method: `sandbox.run("name", **args)`. This is a normal, typed method — arguments are passed through a `**kwargs` mapping and validated against the template's `custom_commands` schema at call time. We deliberately do **not** use `__getattr__`/magic attributes (e.g. `sandbox.serve(...)`), which would be invisible to mypy and break `py.typed`.
3. **Discovery API**: `sandbox.capabilities` returns the effective capability set (`frozenset[str]`); `sandbox.list_commands()` returns the template's declared custom commands as a **list of plain dicts** (not objects) — each dict carries `name` + `description` + `args`. These let users and Agents introspect what a sandbox can do.

## API Design
```python
class Sandbox:
    @property
    def capabilities(self) -> frozenset[Capability]:
        """Effective standard-capability set for this sandbox."""
        ...

    def list_commands(self) -> list[dict[str, Any]]:
        """Template-declared custom commands as a list of plain dicts:
        {"name": str, "description": str,
         "args": [{"name": str, "required": bool,
                   "default": str | None, "description": str}]}
        """
        ...

    async def run(self, name: str, **args: str) -> ProcessResult:
        """Dispatch a template-declared custom command by name.
        Raises if `name` is unknown or a required arg is missing.
        Values are shlex.quote()-escaped before substitution.
        """
        ...

# Standard, typed, gated as before:
#   await sandbox.commands.run("ls -la")     # requires "shell"
#   await sandbox.files.upload(local, remote) # requires "files"
```

> **MCP 工具按 capabilities 过滤 = Phase 2 延后**：当前 MCP Server 暴露的 7 个 P0 工具
> 仅依赖默认能力（shell / files / code），**不**按 `capabilities` 动态过滤工具列表。
> 当沙箱能力受限时，由 `dispatch_tool` 捕获 `CapabilityNotSupportedError` 并返回结构化
> error（而非崩溃或静默缺失）。按 capabilities 动态过滤 MCP 工具集留待 Phase 2。

## Alternatives considered
- **`__getattr__` magic methods** (`sandbox.serve(port=9000)`) — Invisible to static type checkers, breaks `py.typed`, no autocomplete, surprising failure modes. Rejected; see the capability-model-alternatives rejected ADR.
- **Only dynamic dispatch (drop typed standard methods)** — Loses type safety and discoverability for the common path.
- **Codegen typed stubs per template** — Too heavy; templates are resolved at runtime.

## Dependencies
- `2026-09-03-capability-model.md` (gating on standard methods)
- `2026-09-03-custom-commands-schema.md` (schema for `run` / `list_commands`)
- `api/sandbox.py`, `models/template.py`

## Test Strategy
- `sandbox.capabilities` reflects the effective set (declared vs default baseline).
- `sandbox.list_commands()` returns declared custom commands with args.
- `sandbox.run("unknown")` raises a clear error; `run("serve", port="9000")` builds the quoted command.
- mypy check: `sandbox.run` and standard methods type-check; no reliance on dynamic attributes.

## Acceptance criteria
- Standard capabilities remain typed and gated.
- Custom commands are reachable only via `sandbox.run("name", **args)`.
- `mypy --strict` passes with `py.typed` intact (no `__getattr__`-based dispatch).
