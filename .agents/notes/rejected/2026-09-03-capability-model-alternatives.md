# Decision: Capability Model — Rejected Alternatives

Status: rejected

## Problem
While designing the command capability model, several alternative approaches were considered for CLI dispatch, SDK dynamic methods, capability defaulting, template discovery, and rollout scope. This record captures the alternatives that were rejected and why, so they are not revisited without new information.

## Decision
The following options were **rejected**. The chosen approaches live in the corresponding `implemented/` ADRs.

- **CLI dynamic template command registration — `ebx <template>:<cmd>`** — Rejected. Registering each template's commands as top-level CLI verbs pollutes the command namespace, causes collisions with built-in verbs, and makes `--help` and completion unpredictable. Chosen instead: explicit `ebx run <sandbox_id> <command_name>` (see `implemented/architecture/2026-09-03-cli-run-vs-exec.md`).

- **SDK `__getattr__` magic-attribute dynamic methods — `sandbox.serve(...)`** — Rejected. Dynamic attributes are invisible to mypy, break the `py.typed` guarantee, provide no autocomplete, and fail in confusing ways. Chosen instead: explicit typed dispatch `sandbox.run("name", **args)` (see `implemented/architecture/2026-09-03-sdk-capability-surface.md`).

- **"Undeclared means everything tightened"** — Rejected. Treating an omitted `capabilities` as "no capabilities" (or otherwise silently restricting) makes the common case fail and surprises template authors. Chosen instead: omitted `capabilities` inherits `DEFAULT_CAPABILITIES = {shell, files, code}` (see `implemented/architecture/2026-09-03-capability-model.md`).

- **`~/.ebx/templates/index.json` index file** — Rejected. An index adds a sync/invalidation surface with no payoff at the current template scale. Chosen instead: directory-walk discovery (see `implemented/architecture/2026-09-03-command-source-resolution.md` and `implemented/feature/2026-09-03-minimal-template-repo.md`).

- **One-shot delivery including full backend implementation** — Rejected. Bundling the backend `GET /templates/{id}` metadata endpoint into the initial change couples client rollout to backend readiness. Chosen instead: phase it — local cache now, online metadata as Phase 2 with graceful degrade + warn (see `implemented/architecture/2026-09-03-command-source-resolution.md`).

## API Design
N/A — this record catalogs rejected alternatives; the accepted API surfaces live in the cross-referenced `implemented/` ADRs.

## Alternatives considered
- (This record *is* the catalog of rejected alternatives; the accepted counterparts are cross-referenced above.)

## Dependencies
- `implemented/architecture/2026-09-03-capability-model.md`
- `implemented/architecture/2026-09-03-cli-run-vs-exec.md`
- `implemented/architecture/2026-09-03-sdk-capability-surface.md`
- `implemented/architecture/2026-09-03-command-source-resolution.md`
- `implemented/feature/2026-09-03-minimal-template-repo.md`

## Consequences
- The chosen designs favor explicitness, static type safety, and minimal infrastructure.
- Revisiting any rejected option requires new evidence (e.g. template count outgrowing directory-walk discovery).

## Test Strategy
N/A — this record only catalogs rejected options; no code artefact is produced by this ADR. Verification that the rejected approaches are absent from the shipped design is covered by the tests of the accepted counterpart ADRs listed under **Dependencies**.

## Acceptance criteria
- Each rejected option is paired with the accepted alternative and its `implemented/` ADR reference.
- None of the rejected approaches appear in the shipped design (no dynamic CLI verbs, no `__getattr__` methods, no `index.json`, no "undeclared means tightened").
- Reopening a rejected option requires new evidence, recorded as a new ADR.
