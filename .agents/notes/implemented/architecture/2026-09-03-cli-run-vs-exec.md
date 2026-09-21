# Decision: `ebx run` (Named Commands) vs `ebx exec` (Raw Shell)

Status: implemented

## Problem
Users need to invoke template-declared named commands from the CLI, but the existing `ebx exec` runs an arbitrary raw shell string. We need a clear division of labor between running a raw command and dispatching a template's named, parameterized command.

## Decision
Add a new top-level command `ebx run` and keep `ebx exec`:
- **`ebx run <sandbox_id> <command_name> [--arg k=v ...]`** — template-aware dispatch of a named command declared in the sandbox's template `custom_commands`. Arguments are supplied as repeatable `--arg key=value` pairs, validated against the command's `args` schema, and `shlex.quote()`-escaped.
- **`ebx exec <sandbox_id> <command>`** — unchanged; runs a raw shell command string (requires the `shell` capability).

Semantic split: `exec` = raw shell; `run` = template-declared named command.

## API Design
```bash
ebx run <sandbox_id> <command_name> [选项]

选项：
  --arg, -a <KEY=VALUE>     命名命令参数（可多次使用）
  --timeout, -t <seconds>   覆盖命令声明的超时
  --json, -j                结构化输出

示例：
  ebx run sb-abc123 serve --arg port=9000
  ebx run sb-abc123 migrate --arg target=head --json
```
- Unknown `command_name` → error listing available commands (`ebx run <id> --help` / discovery).
- Missing a `required` arg → error before execution.
- If the sandbox lacks the capability the command needs → `CapabilityNotSupportedError` (E3xxx) surfaced with its suggestion.

## Alternatives considered
- **Overload `ebx exec` to also resolve named commands** — Ambiguous: a command name could collide with a real binary; blurs raw-vs-named semantics.
- **`ebx <template>:<cmd>` dynamic registration** — Rejected; see the capability-model-alternatives rejected ADR.

## Dependencies
- `cli/commands/` (new `run` command)
- `2026-09-03-custom-commands-schema.md` (command definitions)
- `2026-09-03-sdk-capability-surface.md` (`sandbox.run` under the hood)

## Test Strategy
- Click CliRunner: `ebx run` with valid args, repeated `--arg`, and `--json` output.
- Unknown command name and missing required arg produce non-zero exit codes with helpful messages.
- `ebx exec` behavior unchanged (regression).

## Acceptance criteria
- `ebx run <id> <name> --arg k=v` dispatches the named command and propagates its exit code.
- `ebx exec` continues to run raw shell commands.
- Errors for unknown command / missing arg / missing capability are clear and actionable.
