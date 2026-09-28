# Decision: Restore Fail-Closed Capability Gate for CodeContextModule Only

Status: implemented

## Problem

Issue #140 identified that the blanket removal of all runtime `check_capability()` call-sites in the P0+P1 overdesign cleanup (see `2026-09-23-overdesign-cleanup.md`) was over-broad for the `code` capability. The cleanup correctly removed gates from `commands`, `files`, and `network` modules — those gates added overhead without protecting against real misuse — but removing the gate from `CodeContextModule` created a security gap:

**Threat model — arbitrary code execution.** `CodeContextModule` exposes `run()`, `create_context()`, `list_contexts()`, `restart_context()`, and `remove_context()` which execute arbitrary user-supplied code inside the sandbox. A template that deliberately omits `code` from its capability declaration (e.g. a web-only or file-server template) must *never* allow code execution, even when the underlying CodeInterpreter service or shell fallback happens to be technically reachable. Without the gate, such a template could be tricked into executing arbitrary code through the code module.

The `code` capability gate is fundamentally different from the removed `shell`/`files`/`network` gates:
- **shell/files/network** — low-risk operations already authorized by the sandbox's existence; the removed gates only caught template-level misconfiguration, not real threats.
- **code** — high-risk: arbitrary code execution is the one operation a restricted template might intentionally disallow; the gate is a security boundary, not a misconfiguration guard.

## Decision

Restore `check_capability(self._capabilities, "code")` in `CodeContextModule` for **all five public entrypoints**: `run()`, `create_context()`, `list_contexts()`, `restart_context()`, and `remove_context()`. This is a deliberate, scoped partial reversal of `2026-09-23-overdesign-cleanup.md` item #4.

### Key design rules

1. **Gate precedes CI availability and 404→shell fallback.** The `check_capability()` call is the first statement in `run()`, *before* the `_ci_available` fast-path check and before any attempt to call the CodeInterpreter RPC. This ensures a template without `code` never reaches either the interpreter or the shell fallback (fail-closed).

2. **When `code` is declared, the 404→shell fallback is preserved.** The gate only blocks when `code` is absent. Templates that declare `code` continue to enjoy transparent fallback from CodeInterpreter to shell execution when the CI service is unavailable.

3. **No other runtime gates are restored.** The `commands`, `files`, and `network` modules remain gate-free as decided in the overdesign cleanup. The threat model does not justify runtime gating for those capabilities.

4. **`check_capability()` and `CapabilityNotSupportedError` (E3004) are preserved infrastructure.** The overdesign cleanup intentionally preserved these — this decision uses them, not re-introduces them.

### Relationship to prior ADRs

| ADR | Relationship |
|-----|-------------|
| `2026-09-03-capability-model.md` | **Foundational.** Defines the capability vocabulary and `check_capability()` semantics. This decision restores the model's original intent for `code` specifically. |
| `2026-09-03-no-backward-compat-capability.md` | **Still valid.** No backward-compat shim is added. |
| `2026-09-03-sdk-capability-surface.md` | **Still valid.** Standard capabilities remain typed and gated (now: `code` re-gated; others remain un-gated per cleanup). |
| `2026-09-23-overdesign-cleanup.md` | **Partially reversed** for item #4 only (`check_capability` gating). The cleanup removed all 14 call-sites; this decision restores 5 of them — exclusively in `CodeContextModule`. The other 9 removed sites (in `commands.py`, `files.py`, `network.py`, `sandbox.py`) remain deleted. |

### Applicability and expiry conditions

- **Applies as long as** `CodeContextModule` offers arbitrary code execution (which is its core purpose).
- **Expiry:** If the SDK adopts a different authorization layer (e.g. per-sandbox RBAC or policy engine) that subsumes capability gating at a higher level, these call-site gates can be removed in favor of the new mechanism.
- **Scope boundary:** This decision covers only `api/code.py`. If future modules expose similarly dangerous operations (e.g. a hypothetical `eval` module), they should independently assess whether a capability gate is warranted — not automatically inherit this decision.

## API Design

```python
# api/code.py — CodeContextModule
# Each public entrypoint starts with the gate:

from easy_sandbox.api.capability import check_capability

class CodeContextModule:
    async def run(self, code: str, ...) -> CodeResult:
        check_capability(self._capabilities, "code")  # MUST be first
        # ... CI availability check, RPC call, 404→shell fallback ...

    async def create_context(self, ...) -> dict[str, Any]:
        check_capability(self._capabilities, "code")  # MUST be first
        self._check_ci_available("create_context")
        ...

    async def list_contexts(self) -> list[dict[str, Any]]:
        check_capability(self._capabilities, "code")
        ...

    async def restart_context(self, context_id: str) -> dict[str, Any]:
        check_capability(self._capabilities, "code")
        ...

    async def remove_context(self, context_id: str) -> None:
        check_capability(self._capabilities, "code")
        ...
```

No new public API is introduced. `check_capability()` and `CapabilityNotSupportedError` already exist in `api/capability.py` and `models/errors.py`.

## Alternatives considered

- **Restore gates for all modules (full reversal of cleanup item #4)** — Rejected: the shell/files/network gates were correctly identified as overdesign; they protect against misconfiguration, not security threats. Restoring them would undo the cleanup's valid simplification.
- **Gate only `run()`, not context management methods** — Rejected: `create_context()` and `restart_context()` establish execution environments that will eventually run code. Gating only `run()` leaves an inconsistent security boundary (contexts created but code blocked).
- **Move the gate after the CI availability check** — Rejected: this would allow a template without `code` to probe CI availability (information leak) and, if CI is unavailable, would rely on the shell fallback code path to independently refuse execution — violating fail-closed.
- **Use a decorator instead of inline call** — Considered but rejected for readability: an inline `check_capability()` call at the top of each method makes the security boundary visible to reviewers without indirection.

## Dependencies

- `api/capability.py` — `check_capability()` function (already exists, preserved by cleanup)
- `models/errors.py` — `CapabilityNotSupportedError` / E3004 (already exists, preserved by cleanup)
- `models/template.py` — `DEFAULT_CAPABILITIES` constant (already exists)
- `2026-09-23-overdesign-cleanup.md` — parent decision being partially reversed

## Test Strategy

Comprehensive test coverage in `tests/test_api/test_code.py`, class `TestCodeCapabilityGating`:

1. **`test_run_without_code_capability_raises`** — Module with `{shell, files}` (no `code`): `run()` raises `CapabilityNotSupportedError`; neither CI protocol nor shell process protocol is touched.
2. **`test_run_gate_precedes_404_fallback`** — CI configured to return 404, but `code` is absent: gate fires first, shell fallback never reached.
3. **`test_run_gate_precedes_cached_fallback`** — `_ci_available=False` (prior 404 cached), `code` absent: gate fires first, shell fast-path never reached.
4. **`test_run_with_code_capability_works`** — Module with `{code}`: `run()` proceeds normally through CI.
5. **`test_ci_404_fallback_still_works_with_code`** — Module with `{code}`, CI returns 404: fallback works, proving the gate does not break the fallback.
6. **`test_context_methods_gated_without_code`** — Parametrized over all four context methods (`create_context`, `list_contexts`, `restart_context`, `remove_context`): each raises `CapabilityNotSupportedError` when `code` is absent.
7. **`test_context_methods_work_with_code`** — All four context methods work when `code` is declared.
8. **`test_resolved_capabilities_without_code_gates_run`** — End-to-end: a template YAML declaring `{shell, files}` resolves without `code`; passing those capabilities to `CodeContextModule` blocks `run()`.
9. **`test_malformed_template_never_grants_code`** — Fail-closed resolution: a matched-but-malformed template raises `TemplateParseError` rather than silently granting `DEFAULT_CAPABILITIES` (which includes `code`).

All tests pass. No regressions introduced in the broader test suite.

## Acceptance criteria

- [x] `check_capability(self._capabilities, "code")` is the first statement in all five `CodeContextModule` public methods
- [x] Gate fires before CI availability check and before 404→shell fallback
- [x] Templates with `code` declared continue to enjoy 404→shell fallback
- [x] No `check_capability` call-sites restored in `commands.py`, `files.py`, `network.py`, or `sandbox.py`
- [x] `CapabilityNotSupportedError` (E3004) raised with `.capability == "code"` when gate triggers
- [x] 9 targeted tests in `TestCodeCapabilityGating` all pass
- [x] Full test suite passes with no new regressions

## Consequences

- `CodeContextModule` is the only API module with runtime capability gating; this asymmetry is intentional and documented.
- Templates that omit `code` from their capability declaration are now protected against code execution through any path (CI or shell fallback).
- The security boundary is visible in source code (explicit `check_capability` call, not hidden in middleware or decorator).
- Future modules exposing dangerous operations should evaluate whether they warrant a similar gate, using this ADR as a reference pattern.

## Files changed

- `src/easy_sandbox/api/code.py` — Added `check_capability(self._capabilities, "code")` to 5 methods, added import of `check_capability`
- `tests/test_api/test_code.py` — Added `TestCodeCapabilityGating` class with 9 test methods
