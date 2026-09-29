# Decision: Converge `init`/`create` command semantics (remove top-level `ebx init`, make create routing explicit)

Status: implemented — **partially superseded (2026-09-29)** by [2026-09-29-init-restore-and-create-explicit-error.md](2026-09-29-init-restore-and-create-explicit-error.md): decision item 1 (delete top-level `ebx init`) is reversed — the shortcut is restored as the same command object; the create routing row "`ebx create` → `base` template, direct create" is replaced by an explicit no-argument usage error. Items on DESCRIPTION + `--template` mutual exclusion and help-surface structure stand.
Implemented: 2026-09-29
Supersedes: the `ebx create` routing row "`--template` wins over a description" in [2026-09-29-nl-create-qwen-code-integration.md](2026-09-29-nl-create-qwen-code-integration.md)

## Problem

Four entry points competed for the "get started" slot:

- top-level `ebx init` — a pure alias of `ebx template init` implemented with
  `ctx.invoke`; it had no independent semantics and was not described in the
  design docs.
- `ebx template init` — scaffolds a local template project (files only).
- `ebx config init` — interactive guided credentials wizard.
- `ebx create` — creates a cloud sandbox (base / `--template` / NL → Qwen Code).

Two concrete defects followed:

1. **Naming ambiguity.** Three commands containing `init` plus `create` made it
   impossible to tell from the command name what each one does. `ebx init` in
   particular sounded like "initialise everything" but only scaffolded files.
2. **Silent input dropping.** `ebx create "DESCRIPTION" --template NAME`
   accepted both inputs and silently ignored the description (`--template` won).
   Every other path in the CLI (Qwen Code install/credential failures, missing
   template, invalid `--env` format) fails loudly with an actionable message, so
   silently discarding user input was inconsistent and surprising.

Pre-release status: the CLI has not been officially released, so there are no
external users to migrate — the same reasoning that justified the clean break in
`2026-09-29-region-command-level-option.md`.

## Decision

1. **Delete the top-level `ebx init` shortcut.**
   - `src/easy_sandbox/cli/main.py`: remove `"init":
     "easy_sandbox.cli.commands.template:init_shortcut"` from
     `lazy_subcommands`.
   - `src/easy_sandbox/cli/commands/template.py`: delete the `init_shortcut`
     command.
   - `ebx init ...` now fails with the standard Click error: exit code 2,
     `No such command 'init'.`
   - Repo-wide verification found no dependency on the alias: no imports, no
     automation/scripts/examples usage, only tests/docs/CHANGELOG mentions (all
     updated).

2. **Keep exactly three distinct entry points**, each named after what it
   initialises:

   | Goal | Command | Cloud? |
   | --- | --- | --- |
   | Store credentials / endpoints (first run) | `ebx config init` | No |
   | Create a cloud sandbox | `ebx create [DESCRIPTION]` | Yes |
   | Scaffold a local template project | `ebx template init [DIRECTORY]` | No |

3. **Make `ebx create` routing explicit and total:**

   | Invocation | Path |
   | --- | --- |
   | `ebx create` | `base` template, direct create |
   | `ebx create --template NAME` | direct template path (no AI generation) |
   | `ebx create "DESCRIPTION"` | AI path: Qwen Code generates → build & deploy → create |
   | `ebx create "DESCRIPTION" --template NAME` | **rejected** (usage error, exit code 1) |

   The guard runs in `create()` before any config read, AI generation, or
   network call:

   ```python
   if description and template:
       raise click.UsageError(
           "DESCRIPTION and --template cannot be combined. Drop --template to "
           "generate a template from the description, or drop DESCRIPTION to "
           "launch an existing template directly."
       )
   ```

   `handle_errors` maps the `UsageError` to exit code 1 with the message on
   stderr — matching the mutual-exclusion precedent already used by
   `ebx template init` (`--template` vs `--from`).

4. **Help surfaces updated:**
   - Root `ebx --help` gains a "Setup, create, or scaffold:" block listing
     `ebx config init`, `ebx create [DESCRIPTION]`, `ebx template init [DIR]`.
   - `ebx create` docstring rewritten as the routing table;
     `--template/-T` help now states "Cannot be combined with DESCRIPTION."
   - `Commands:` list in the root help no longer contains `init`.

5. **Docs / evidence / changelog updated (en + zh):**
   `cli-reference.md` (overview count 12→11, config 4→5, comparison table,
   create routing table, `ebx init (shortcut)` section removed), `cli-design.md`
   (command tree gains `tpl_init`/`cfg_init`, routing table, new
   `#### template init` subsection), `cli-tutorial.md` (quick-orientation table,
   scaffold section), `e2e-template-workflow.md` (alias mentions removed),
   `CHANGELOG.md` (breaking-changes entry + migration note), CLI evidence
   regenerated (82 cases incl. `help-template-init`, `create-nl-conflict`,
   `error-init-removed`).

## API Design

N/A — this decision does not involve library API changes; it only reshapes the
CLI surface:

```text
ebx init                       # REMOVED — exit 2, "No such command 'init'."
ebx template init [DIRECTORY] [-t CASE] [--from REF] [--name NAME] [--list] [--force]
ebx config init [--yes]
ebx create [DESCRIPTION] [-T NAME] [...]
```

## Alternatives considered

- **Keep the alias with clearer help** ("shortcut for `ebx template init`") —
  rejected: still three `init` forms; no code or automation relies on the
  alias; pre-release removal costs nothing.
- **Keep it but stop documenting it** — rejected: a hidden command is worse than
  an absent one, and `ebx --help` already advertised it in `Commands:`.
- **When both DESCRIPTION and `--template` are given, keep `--template` and
  warn** — rejected: still ships a silently dropped user input and contradicts
  the fail-loud convention used everywhere else in create.
- **When both are given, prefer DESCRIPTION (AI) and ignore `--template`** —
  rejected for the same reason; it also makes an explicit flag meaningless.

## Dependencies

- Click `LazyGroup` registration in `src/easy_sandbox/cli/main.py`
- `handle_errors` exit-code mapping (`UsageError` → exit 1; unknown command →
  Click's exit 2)
- The Qwen Code codegen kernel, clarification loop, output mixing, diagnose,
  MCP, and shell-stream code paths are untouched.

## Test Strategy

- `tests/test_cli/test_main.py::TestTopLevelInitRemoved` — command absence
  (`cli.get_command(ctx, "init") is None`), `ebx init` / `ebx init --help` exit
  2, root-help contents (no `init` row; the three setup entries present).
- `tests/test_cli/test_create_nl.py` — parametrized `--template`/`-T` conflict
  rejection: exit 1, message contains "cannot be combined", and
  codegen/deploy/`Sandbox.create` are never called; argument-order independence.
- `tests/test_cli/test_template_commands.py` — top-level shortcut gone;
  `ebx template init` still scaffolds.
- `tests/test_cli/test_region_options.py` — `init` removed from the local
  command lists.
- Evidence: new registry cases `help-template-init`, `create-nl-conflict`,
  `error-init-removed`; `capture_cli_evidence.py` + golden snapshots
  regenerated.

## Files changed

- `src/easy_sandbox/cli/main.py` — `init` lazy registration removed; root epilog
  block added
- `src/easy_sandbox/cli/commands/template.py` — `init_shortcut` deleted
- `src/easy_sandbox/cli/commands/sandbox.py` — create docstring, `--template`
  help, routing guard
- `tests/test_cli/test_main.py`, `test_create_nl.py`, `test_template_commands.py`,
  `test_region_options.py`
- `scripts/evidence_cases.py`; `.agents/evidence/cli/*`;
  `tests/test_cli_evidence/golden/*`
- Docs (en/zh): `reference/cli-reference.md`, `design/cli-design.md`,
  `guide/cli-tutorial.md`, `guide/e2e-template-workflow.md`; `CHANGELOG.md`

## Acceptance criteria

- ✅ `ebx init` exits 2 with `No such command 'init'.`; `init` is absent from
  `ebx --help` `Commands:`
- ✅ Root help shows the "Setup, create, or scaffold:" block naming
  `ebx config init`, `ebx create [DESCRIPTION]`, `ebx template init [DIR]`
- ✅ `ebx create` / `--template` / DESCRIPTION routes behave as before;
  `DESCRIPTION` + `--template` exits 1 with an explicit conflict message and no
  codegen/deploy/network call
- ✅ `ebx template init --help` and `ebx config init --help` describe their
  distinct responsibilities
- ✅ EN/ZH docs carry the comparison table and real examples; no doc references
  the removed alias (except the CHANGELOG migration note)
- ✅ CLI/create/template/config/evidence tests, ruff, and mypy pass
