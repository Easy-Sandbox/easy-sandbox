# Decision: Unify the qwen-code session-turns parameter name and semantics

Status: implemented
Proposed: 2026-09-29
Implemented: 2026-09-29

## Problem

The value that caps how long a qwen-code agent run may go on was exposed
under three different names with a wrong semantic label:

| Layer | Old name | Actual behaviour |
| --- | --- | --- |
| CLI `ebx deploy` | `--max-tool-calls` (default 100, help: "tool-call limit") | forwarded to `--max-session-turns` |
| SDK `Sandbox.deploy()` / `DeployModule.deploy_project()` | `max_tool_calls` (default 100, docstring: "number of tool calls") | forwarded to `--max-session-turns` |
| qwen-code template (`template.yaml` arg, `commands.py` signature) | `max_turns` (defaults `100` / `50` — inconsistent) | forwarded to `--max-session-turns` |

Upstream Qwen Code (official headless docs, verified 2026-09-29) defines
`--max-session-turns` (user/model/tool turns, overrun exits with code 53)
and `--max-tool-calls` (cumulative top-level tool calls, overrun exits
with code 55) as **two distinct budgets**. Exposing our session-turns
budget as `--max-tool-calls` therefore collides with a real, different
upstream flag and misleads anyone who knows the upstream CLI.

## Decision

1. **Single public name**: `max_session_turns` everywhere.
   - SDK keyword: `max_session_turns` (`Sandbox.deploy`, `DeployModule.deploy_project`, `DeployModule._build_qwen_command`)
   - CLI option: `--max-session-turns`
   - qwen-code template arg: `max_session_turns` (default unified to `100`)
   - Semantics documented as "user/model/tool session turns; qwen-code
     exits with code 53 when exceeded" (mapped to `turn_limit_exceeded`).
2. **Compatibility strategy**: pre-release rename, no runtime aliases —
   consistent with ADR 2026-09-29 (remove-rename-notices) and ADR
   2026-09-23 (overdesign cleanup): the project has no released users, so
   no deprecation shim is kept. Old names fail loudly:
   - `--max-tool-calls` on the CLI → click usage error ("no such option"),
     locked by `test_max_tool_calls_option_rejected`.
   - `max_tool_calls=` SDK kwarg → `TypeError`, locked by
     `test_build_qwen_command_rejects_legacy_kwarg_name`.
   - `--max-turns` (the flag removed by the earlier task-180 fix; never a
     real upstream flag) must not reappear — locked by
     `test_build_qwen_command_omits_obsolete_flag`.
   No unknown parameter is ever silently ignored.
3. **Stable contract for the NL-create follow-up work (task 168)**: the
   host adapter `run_qwen_code_headless()` / `_build_headless_command()`
   in `agent/qwen_code.py` now accepts keyword-only
   `max_session_turns: int | None = None`. `None` (the default) adds no
   flag, so current `ebx create` NL behaviour is byte-for-byte unchanged;
   future callers (clarification loop, diagnose, etc.) get the unified
   name on the same stable interface.

## Alternatives considered

- **Keep `max_tool_calls` and also expose `max_session_turns`** — two
  names for one value plus a latent semantic trap against the real
  upstream `--max-tool-calls`. Rejected.
- **Deprecation aliases with `DeprecationWarning`** — the project is
  pre-release with no external users; alias machinery is over-design
  (same rationale as the rename-notices removal). Rejected.
- **Expose the upstream `--max-tool-calls` budget too** — no current
  caller needs a tool-call budget; adding it is speculative scope.
  Rejected (can be added later under its own true name).

## Dependencies

- Upstream qwen-code CLI `--max-session-turns` flag (verified against the
  official headless documentation; also live-checked by
  `test_build_qwen_command_flags_accepted_by_cli` when a qwen binary is
  installed).

## Test Strategy

- `tests/test_api/test_deploy.py` — command building uses the new kwarg;
  legacy kwarg raises `TypeError`; obsolete `--max-turns` never reappears.
- `tests/test_cli/test_deploy_commands.py` — `--max-session-turns` is
  forwarded to `Sandbox.deploy(max_session_turns=...)`; legacy
  `--max-tool-calls` produces a usage error.
- `tests/test_agent/test_qwen_code.py` — `_build_headless_command` adds
  no flag by default and forwards `--max-session-turns` when given;
  `run_qwen_code_headless` forwards the budget to the subprocess argv.

## Files changed

- `src/easy_sandbox/api/deploy.py`, `src/easy_sandbox/api/sandbox.py` — SDK rename + docstring semantics
- `src/easy_sandbox/cli/commands/deploy.py` — `--max-session-turns` option, help, examples
- `src/easy_sandbox/agent/qwen_code.py` — optional `max_session_turns` on the host adapter
- `examples/templates/qwen-code/template.yaml`, `commands.py`, `examples/templates/README.md` — template arg rename + default unified to 100
- `tests/test_api/test_deploy.py`, `tests/test_cli/test_deploy_commands.py`, `tests/test_agent/test_qwen_code.py`
- `docs/{en,zh}/reference/api-reference.md`, `docs/{en,zh}/reference/cli-reference.md`, `docs/{en,zh}/design/cli-design.md`, `docs/{en,zh}/guide/deploy-and-build.md`
- `CHANGELOG.md`

## Acceptance criteria

- ✅ `max_session_turns` / `--max-session-turns` is the only public name across CLI, SDK, template, tests, and docs (grep for old names returns nothing outside lock-tests/changelog)
- ✅ Old names fail loudly; nothing is silently ignored
- ✅ `run_qwen_code_headless` default behaviour unchanged (no flag without the new kwarg)
- ✅ Targeted pytest, ruff, mypy pass; CLI evidence golden files unaffected (no deploy help evidence exists)
