# Decision: Separate CLI result output from progress and log channels

Status: implemented
Implemented: 2026-09-29
Related: [2026-09-29-init-create-semantics.md](../feature/2026-09-29-init-create-semantics.md), [2026-09-29-nl-create-qwen-code-integration.md](../feature/2026-09-29-nl-create-qwen-code-integration.md)

## Problem

Executing `ebx create` (both the `--template` path and the Qwen Code NL path)
and the shared deploy pipeline produced output that could not be consumed
reliably:

1. **Duplicate warning.** The capability-resolver fallback warning rendered
   twice: once by the SDK's standalone handler
   (`easy_sandbox.utils.logging`, timestamped format, `easy_sandbox` package
   logger) and once by the CLI's root handler (`WARNING: ...`). Two handlers
   rendered the same record.
2. **Garbled live output.** The Rich spinner renders on stderr; warnings and
   log lines written directly to stderr interleaved with the live display into
   unreadable text such as `⠋ Waiting...Warning: ...` and
   `⠋ Waiting...DEBUG: https://...`.
3. **Machine-readable pollution.** In `--json` mode every message
   (`info` / `progress` / `warning` / `debug` / `error`) was emitted as JSON on
   **stdout**, so `ebx create --json | jq` received a sequence of documents
   instead of one. Raw `click.echo` calls bypassed `--quiet` / `--ci` entirely.
4. **Bypassed manager.** `_do_deploy` warned with a bare
   `click.echo(..., err=True)` that ignored quiet/CI suppression and the
   spinner guard; `on_output=click.echo` in verbose mode wrote docker build
   logs to **stdout**, the result channel.
5. **Inconsistent result printing.** `ebx create` printed its result through
   the legacy `OutputFormatter` (`fmt.print_dict` / `fmt.print_success`) while
   the rest of its progress went through `OutputManager`.

## Decision

### Channel policy

| Channel | Content | Consumers |
|---------|---------|-----------|
| **stdout** | final results: `data`, `table`, `success` | humans and scripts (`ebx ... --json \| jq`) |
| **stderr** | progress state and diagnostics: `info`, `progress`, `warning`, `error`, `debug`, plus **every** stdlib `logging` record | humans following a long-running command |

- `--json` keeps stdout a **single JSON document**: the JSON forms of the
  diagnostic methods moved to stderr (`_json(..., err=True)`).
- `success` stays a result (stdout); commands that emit both `data` and
  `success` skip the notice in `--json` mode so the stdout document stays
  single (`ebx create` does this).

### One logging bridge

- `OutputManager.__init__` installs a single `_LogBridgeHandler` (format
  `LEVELNAME: message`, level = CLI level) on the **root** logger and removes
  handlers installed by the SDK or other hosts on both the root and the
  `easy_sandbox` package logger. Exactly one handler renders each record.
- `propagate` stays enabled, so `caplog`-style capture and embedding hosts
  keep seeing records.
- `easy_sandbox.utils.logging._configure_once` keeps setting the package level
  from `SANDBOX_LOG_LEVEL` unconditionally (documented standalone-SDK
  behaviour), but installs its fallback stderr handler only when **neither**
  the root nor the package logger already has one. This makes the
  duplicate-warning regression impossible regardless of initialisation order
  (SDK-first or manager-first).

### Spinner pause / resume

`_spinner_guard` wraps every write (`click.echo`, JSON, Rich table): the live
Rich `Status` objects pushed by `spinner()` / `live_spinner()` are stopped
before a write and restarted afterwards. Spinners already render on stderr and
stay suppressed in verbose/quiet/JSON/non-TTY sessions.

### Log-level precedence during a CLI run

The CLI flags (`--verbose` / `--quiet` / `--log-level` plus CI auto-detection)
own the log level: the manager sets the **root** level and the **bridge**
level. It deliberately does not touch the `easy_sandbox` package logger level,
which keeps honouring `SANDBOX_LOG_LEVEL` for standalone SDK use.

### Deploy/create paths go through the manager

- `_do_deploy`: the `--start-cmd/--ready-cmd` warning uses `out.warning(...)`
  (single stderr line; suppressed by quiet/CI/JSON).
- `_do_deploy`: docker build output (`on_output=out.info if verbose else None`)
  is a diagnostic, never a result.
- `ebx create`: result via `out.data(data)` plus a non-JSON
  `out.success("Sandbox <id> created successfully.")`.

Task 160 invariants are untouched: the top-level `ebx init` stays deleted; the
`ebx config init` / `ebx template init` / `ebx create` boundaries are
unchanged; the DESCRIPTION + `--template` conflict is still rejected before
any config read, AI generation, or network call, and the new test pins it
(`stdout == ""`, codegen and `Sandbox.create` never called).

## API Design

No public library API changes; the CLI output surface changes:

```text
# Before (--json):  stdout = {"level":"info"...}
#                            {"level":"progress"...}
#                            {"ID":...}
#                            {"status":"success"...}
# After  (--json):  stdout = {"ID":...}                       # single document
#                   stderr = {"level":"info"...} {"level":"progress"...} {"level":"warning"...}

# Before: capability fallback warning rendered twice
#         2026-09-29 10:00:00 [WARNING] easy_sandbox.api.capability: Could not resolve ...
#         Warning: Could not resolve ...
# After:  exactly one "WARNING: Could not resolve capabilities ..." line on stderr

# Before: out.warning(...) in quiet mode  -> suppressed (unchanged)
#         raw click.echo(..., err=True)   -> always printed, bypassing quiet/CI
# After:  raw call replaced by out.warning(...) on the shared path
```

`OutputManager` method → channel mapping (unchanged signatures):

| Method | Channel | quiet | JSON |
|--------|---------|-------|------|
| `info` / `progress` / `warning` / `debug` | stderr | suppressed (`debug`: verbose only) | JSON object → stderr |
| `error` | stderr | shown | `{"status":"error",...}` → stderr |
| `success` | stdout | suppressed | `{"status":"success",...}` → stdout |
| `data` | stdout | values only | single JSON document |
| `table` | stdout | tab-separated | list of dicts |

## Alternatives considered

- **Manager also sets the `easy_sandbox` package logger level** (so `-v`
  exposes SDK DEBUG) — rejected: it mutates global logging state across tests;
  `tests/test_utils/test_logging.py::test_respects_env_var` and
  `test_default_level_is_warning` then pass or fail depending on execution
  order in the full suite. Keeping the package level on `SANDBOX_LOG_LEVEL`
  preserves pre-task behaviour exactly.
- **Keep the SDK handler and de-duplicate inside the SDK** — rejected: the SDK
  cannot know about spinner state, the stderr channel choice, or CLI level
  precedence; the CLI must own its output formatting.
- **Keep JSON diagnostics on stdout** — rejected: breaks the single-document
  contract (`json.loads(result.stdout)` must succeed).
- **Move `success` to stderr as well** — rejected: a success notice is the
  human-readable outcome and belongs to the result channel; the JSON/piping
  concern is handled by skipping it in JSON mode where needed.
- **Suppress diagnostics while a spinner is live instead of pause/resume** —
  rejected: hides warnings; pause/resume keeps everything visible in order.

## Dependencies

- Rich `Status` (already a dependency) and Click 8.5 `Result` semantics
  (`stdout` / `stderr` captured separately; `result.output` is the interleaved
  view used by the evidence snapshots).
- No new dependencies.

## Test Strategy

- `tests/test_cli/test_output_channels.py` (new, 18 tests): channel policy
  (result helpers → stdout; diagnostic helpers → stderr; quiet values only;
  JSON single document; debug requires verbose), logging bridge (single root
  handler; SDK-configured-before-manager still renders once; duplicate-warning
  regression count; quiet suppression), spinner guard (white-box
  stop/start/stop/start lifecycle with a fake status), `ebx create`
  end-to-end × {plain, JSON, quiet, CI} plus the task-160 conflict guard, and
  `_do_deploy` diagnostics (one stderr line; suppressed in quiet).
- `tests/test_cli/test_template_commands.py::TestStartReadyWarning` — asserts
  the manager call and that nothing was written to stderr behind its back.
- Evidence: 4 goldens regenerated (`create-nl-*`, expecting the new
  `[stderr]` section); `.agents/evidence/cli/*` regenerated (82 cases) and
  verified byte-identical across two runs.
- Targeted run (final): `pytest tests/test_cli tests/test_utils tests/test_templates
  tests/test_cli_evidence` — 1016 passed; full suite (`-m "not integration"`)
  — 2426 passed, 1 skipped; `ruff check src tests` and
  `mypy src/easy_sandbox/` clean.

## Acceptance criteria

- [x] capability fallback warning rendered exactly once, on stderr
- [x] `ebx create --json` stdout is a single JSON document
  (`json.loads(result.stdout)` succeeds); diagnostics stay JSON but on stderr
- [x] `--quiet` / `--ci` print only values / JSON on stdout; no status text or
  log records leak
- [x] writes pause and resume the live spinner (no `⠋ ... Warning:` interleaving)
- [x] `_do_deploy` warnings follow quiet/CI/JSON suppression rules
- [x] Task 160 semantics unchanged (three init/create boundaries; DESCRIPTION +
  `--template` rejected before any AI or network call)
- [x] targeted tests, ruff, and mypy pass

## Files changed

- `src/easy_sandbox/cli/output.py` — channel policy docstring,
  `_LogBridgeHandler`, `_spinner_guard` / `_pause_spinner` / `_resume_spinner`,
  `_write_stdout` / `_write_stderr` / `_write` / `_json(err=...)`,
  `_configure_logging` / `_apply_log_level`
- `src/easy_sandbox/utils/logging.py` — fallback handler only when nobody else
  owns the output
- `src/easy_sandbox/cli/commands/sandbox.py` — create result via
  `OutputManager` (`out.data` + non-JSON `out.success`)
- `src/easy_sandbox/cli/commands/template.py` — `_do_deploy` warning via
  `out.warning`; `on_output=out.info if verbose else None`
- `tests/test_cli/test_output_channels.py` (new),
  `tests/test_cli/test_template_commands.py`
- `tests/test_cli_evidence/golden/create-nl-{python,nodejs,confirm-required,not-installed}.txt`,
  `.agents/evidence/cli/*`
- `docs/{en,zh}/design/cli-design.md` (§7),
  `docs/{en,zh}/guide/e2e-template-workflow.md`

## Consequences

- Out of scope and deliberately untouched (task 167 boundary): `ebx template
  create`'s own bare `click.echo(..., err=True)` warning (same text, separate
  command path `ebx template create <image>`; stays on stderr and never
  touches JSON stdout); task 166 `envd_stream`; task 181 session turn
  parameter naming; task 168 clarification loop; task 170 diagnose.
- Verbose mode does not expose SDK `DEBUG` records while
  `SANDBOX_LOG_LEVEL` stays at its default: the package logger level is owned
  by the SDK, exactly as before this change.
