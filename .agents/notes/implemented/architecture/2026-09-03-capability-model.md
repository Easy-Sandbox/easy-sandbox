# Decision: Command Capability Model (Vocabulary + Default Baseline + Gating)

Status: implemented

## Problem
Not every sandbox exposes the same operations. Previously the SDK assumed all sandboxes support shell/upload/download, so calling a missing operation failed with an opaque protocol error deep in the transport layer. We need a first-class model that lets a template declare which command capabilities it provides, and a well-defined behavior when a caller invokes a capability the sandbox does not have.

## Decision
Introduce a **standard capability vocabulary** and gate every standard-capability call against the sandbox's effective capability set.

1. **Standard capability vocabulary** (extensible): `shell` / `files` / `code` / `terminal` / `ports`. Capabilities are declared by the template, not assumed. New members can be added to the vocabulary later.
2. **System default baseline**: a single constant `DEFAULT_CAPABILITIES = {shell, files, code}`. `terminal` and `ports` are NOT in the baseline and must be declared explicitly by a template. Templates SHOULD follow the baseline but MAY opt out: a template declares its supported capability set via `capabilities:` in `template.yaml` (a subset of the baseline, or the baseline plus `terminal`/`ports`). When a template omits `capabilities`, it inherits `DEFAULT_CAPABILITIES`. Keeping the baseline as one constant makes it trivial to adjust.
3. **Gating always applies**: invoking a standard capability that is not in the sandbox's effective capability set raises `CapabilityNotSupportedError` (E3xxx). The error is explicit — no silent degradation — and its message includes a `suggestion`.

The effective capability set is resolved at sandbox connect time from the template metadata (see command-source-resolution ADR); when metadata is unavailable it falls back to `DEFAULT_CAPABILITIES`.

## API Design
```python
# models/config.py (or a new capability module)
Capability = Literal["shell", "files", "code", "terminal", "ports"]

DEFAULT_CAPABILITIES: frozenset[Capability] = frozenset({"shell", "files", "code"})

class CapabilityNotSupportedError(ExecutionError):
    """Raised when a standard capability is not in the sandbox's effective set."""
    code = "E3004"
    # message includes the missing capability; suggestion lists available capabilities
    # and how to declare it in template.yaml
```

Effective set resolution:
- `template.capabilities` declared → use it (validated against the vocabulary).
- omitted → `DEFAULT_CAPABILITIES`.

## Alternatives considered
- **Assume all sandboxes are fully capable** — Produces opaque, late transport errors when an operation is missing; no way for a template to advertise a reduced surface.
- **Silent degradation (no-op / fallback)** — Hides real misconfiguration and makes debugging harder; violates fail-fast.
- **"Undeclared means everything tightened"** — Rejected; see the capability-model-alternatives rejected ADR.

## Dependencies
- `models/config.py`, `models/errors.py` (extends `ExecutionError`)
- Template parsing (`api/template.py`) to read `capabilities`
- Command source resolution (see `2026-09-03-command-source-resolution.md`)

## Test Strategy
- Unit test `DEFAULT_CAPABILITIES` inheritance when `capabilities` is omitted.
- Unit test declared subset (e.g. `{files}`) and superset (baseline + `terminal`).
- Assert `CapabilityNotSupportedError` (E3004) is raised with a populated `suggestion` when calling a capability outside the effective set.
- Validate declared capabilities against the vocabulary (unknown value rejected).

## Consequences
- Templates gain an explicit, discoverable contract for what a sandbox can do.
- Missing capabilities fail fast at the API boundary with actionable errors.
- The baseline lives in one constant, so tuning it is a one-line change.
- Status is `implemented`: the baseline membership `{shell, files, code}` is realized as the single constant `DEFAULT_CAPABILITIES`; the vocabulary remains extensible, so tuning the baseline is a one-line change.
