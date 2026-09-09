# Decision: No Backward Compatibility for the Capability Model

Status: implemented

## Problem
Introducing the command capability model (vocabulary + gating) changes runtime behavior: some calls that previously reached the transport layer now raise `CapabilityNotSupportedError`. We must decide whether to preserve the old "everything is available" behavior for existing callers and templates.

## Decision
Do **not** preserve backward compatibility. The project is not released and there are currently zero published templates, so there is no installed base or prior behavior to protect. The capability model is adopted as the canonical behavior:
- No compatibility shim, feature flag, or "legacy mode" is added.
- Existing tests are adjusted to the new model rather than the model being bent to keep old tests green.
- Any test that implicitly assumed unconditional shell/upload/download is updated to declare or assume `DEFAULT_CAPABILITIES` explicitly.

## Alternatives considered
- **Add a compatibility flag (e.g. `strict_capabilities=False`)** — Carries legacy behavior forever for a codebase that has no legacy users; increases branching and test surface for zero benefit.
- **Grandfather existing tests** — Would force the model to encode the old "all capable" assumption, defeating the purpose of the redesign.

## Dependencies
- `2026-09-03-capability-model.md` (the model this decision commits to)
- `tests/` — updated to the new model (owned by the implementation task, not this ADR)

## Test Strategy
- Existing command/file tests are updated to reflect gating: assume `DEFAULT_CAPABILITIES` or declare capabilities per case.
- Add regression tests asserting there is no hidden "compat mode" that bypasses gating.

## Consequences
- Cleaner implementation with a single behavior path and no legacy branches.
- Test suite reflects the intended final model.
- Acceptable precisely because the project is pre-release; this decision would not hold once real templates exist.
