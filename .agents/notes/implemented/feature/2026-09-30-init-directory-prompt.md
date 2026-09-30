# Decision: Ask for a directory on natural-language init

Status: implemented
Implemented: 2026-09-30

## Problem

`ebx init "DESCRIPTION"` has only one positional, and that positional is the
description, so there is no way to pass a directory. The project was always
created as `./<name>/` under the current directory. A long generation then
left the files somewhere the user had not chosen.

## Decision

- On an interactive terminal, natural-language `ebx init` / `ebx template init`
  asks `Directory for the template project` **before** generation. The default
  is `./<name>` (or `./<--name>` when `--name` is set). Enter accepts it.
- Any other answer is the project directory itself, not a parent that grows
  another `<name>` subdirectory. `~` is expanded. The directory is validated
  and not created until the files are copied, so a cancelled run leaves
  nothing behind.
- A path that is a file, or a directory that already contains `Dockerfile`,
  `commands.py`, or `template.yaml`, is rejected before generation.
  `--force` overwrites.
- `--yes`, `--json`, and a non-interactive terminal skip the prompt and keep
  `./<name>/`. The create-path switch to template-only does not ask again; it
  still writes `./<name>/`.
- Scaffold (`-t`), `--from`, and `--adopt` are unchanged: a path token is
  still a directory, and an omitted path still means `./<name>/` without this
  prompt.

## Alternatives considered

- **A second positional** (`ebx init "DESCRIPTION" ./dir`) — rejected: the
  description already occupies the only positional, and a second one is
  refused so a sentence cannot be mistaken for a path.
- **Ask after generation**, once the name is known — rejected: the user would
  wait through the whole run before choosing, which is the delay this prompt
  is meant to avoid. The default `./<name>` stands in for the name that does
  not exist yet.

## Test strategy

- `tests/test_cli/test_create_nl.py`: Enter keeps `./<name>/`, a typed path
  is the project directory, `--yes` does not ask, a file and an existing
  template directory are rejected before generation.

## Files changed

- `src/easy_sandbox/cli/commands/sandbox.py`, `src/easy_sandbox/cli/commands/template.py`
- `docs/{en,zh}/reference/cli-reference.md`, `docs/{en,zh}/design/cli-design.md`,
  `CHANGELOG.md`
