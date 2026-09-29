# Decision: Restore the top-level `ebx init` shortcut, make bare `ebx create` an explicit error, and add unknown-command hints

Status: implemented
Implemented: 2026-09-29
Supersedes (partial): [2026-09-29-init-create-semantics.md](2026-09-29-init-create-semantics.md) — decision item 1 (delete `ebx init`) is reversed; the create routing row "`ebx create` → `base` template, direct create" is replaced by an explicit usage error.

## Problem

The earlier init/create convergence (ADR `2026-09-29-init-create-semantics.md`) removed the top-level `ebx init` alias and let bare `ebx create` silently launch the `base` template. Follow-up review (tasks 206/210/211/218) surfaced three issues:

1. **The alias removal hurt real usage patterns.** `ebx init` maps naturally to
   "scaffold my project", the most common first action after install. The alias
   costs nothing (it is the same click command object) and its earlier confusion
   is better solved by help text than by removal.
2. **Bare `ebx create` still silently chose a path.** The convergence made
   DESCRIPTION + `--template` explicit but kept the implicit `base` default for
   the no-argument case — inconsistent with the fail-loud convention.
3. **Unknown top-level commands gave no guidance.** Typos produced a bare
   `No such command 'x'.`, and users who expected `ebx <their-command>` to work
   (template `custom_commands`, SandboxServer registry commands) were not
   pointed at `ebx run`.

## Decision

1. **Restore the top-level `ebx init` shortcut.**
   - `src/easy_sandbox/cli/main.py`: register `"init":
     "easy_sandbox.cli.commands.template:init"` in `lazy_subcommands`.
   - It is the *same command object* as `ebx template init` — option surface,
     TTY picker, and scaffolding logic are shared; nothing is duplicated.
   - The three entry points stay distinct: `ebx config init` (credentials),
     `ebx create` (cloud sandbox), `ebx init` / `ebx template init` (scaffold).

2. **Bare `ebx create` is now an explicit usage error** (exit code 2) listing
   the three valid routes: `--template base`, `--template <NAME>`,
   `"<DESCRIPTION>"`. No config read, AI generation, or network call happens.

3. **Unknown top-level commands get targeted hints** (root group only):
   `difflib.get_close_matches` (cutoff 0.6) over root commands yields a
   `Did you mean '…'?` suggestion; with no plausible candidate the error points
   to template `custom_commands` (declared in `template.yaml`) invoked via
   `ebx run COMMAND`. Click `UsageError` semantics are preserved: exit code 2,
   message on stderr; nested groups keep the stock message.

4. **Registration semantics clarified (docs, not code change):**
   - The `LazyGroup(lazy_subcommands=...)` map in `main.py` is the
     **project-maintainer registration point** for built-in top-level
     shortcuts. It is not a user-facing extension mechanism.
   - User-defined commands live in `template.yaml` `custom_commands` or the
     SandboxServer `@registry.command` registry and run via `ebx run`.
   - The `config.toml [shortcuts]` section from the original CLI design draft
     (`.agents/design/2026-09-23-cli-final-design.md` §2.2) was **never
     implemented**; it must not be described as a current capability.

5. **Evidence / docs sync:** `error-init-removed` evidence case replaced by
   `error-create-noargs`, `error-unknown-suggestion`,
   `error-unknown-custom-hint`, and `help-init-alias`; golden snapshots and
   `.agents/evidence/cli/*` regenerated; cli-reference, cli-design,
   cli-tutorial (incl. new bilingual "top-level shortcuts vs custom commands"
   advanced-usage section), e2e-template-workflow and CHANGELOG updated (en+zh).

## Alternatives considered

- **Keep the alias removed and rely on `ebx template init`** — rejected: the
  alias is free (same command object) and matches user intuition.
- **Keep bare `ebx create` → `base` for quick start** — rejected: silent
  defaults contradict the CLI-wide fail-loud convention and hide the routing
  model; `ebx create --template base` is one flag away.
- **Implement `config.toml [shortcuts]`** — rejected (still): two competing
  extension mechanisms (`custom_commands` + Server registry already cover the
  need); a third, config-file-based mechanism would split where commands are
  discovered.

## Dependencies

- Click `LazyGroup` registration and `resolve_command` override in
  `src/easy_sandbox/cli/main.py`.
- `handle_errors` exit-code mapping (UsageError → exit 1/2 preserved).

## Test Strategy

- `tests/test_cli/test_main.py` — init present again, delegating to the same
  command object; unknown-command suggestion and custom-command hint cases.
- `tests/test_cli/test_create_nl.py` / `test_sandbox_commands.py` — bare create
  rejected before any side effect.
- `tests/test_cli/test_template_commands.py` — TTY arrow-key picker vs
  non-TTY/CI/JSON fail-fast behaviour unchanged.
- Evidence: registry cases above; `capture_cli_evidence.py` + golden snapshots
  regenerated (98 cases).

## Files changed

- `scripts/evidence_cases.py`; `tests/test_cli_evidence/golden/*`;
  `.agents/evidence/cli/*`
- Docs (en/zh): `reference/cli-reference.md`, `design/cli-design.md`,
  `guide/cli-tutorial.md`, `guide/e2e-template-workflow.md`; `CHANGELOG.md`
- This ADR + supersede annotation on
  `2026-09-29-init-create-semantics.md`

## Acceptance criteria

- ✅ `ebx init --help` renders the `template init` help; `ebx init -t python`
  scaffolds identically to `ebx template init -t python`
- ✅ Bare `ebx create` exits 2 with the three-route hint; no side effects
- ✅ `ebx crate` exits 2 with `Did you mean 'create'?`; `ebx frobnicate` exits 2
  pointing to `custom_commands` + `ebx run`; both hints on stderr only
- ✅ TTY arrow-key case picker; non-TTY/CI/JSON never block
- ✅ Docs state `lazy_subcommands` is the maintainer registration point and
  mark `config.toml [shortcuts]` as never-implemented
- ✅ Evidence tests, ruff pass; stale goldens removed
