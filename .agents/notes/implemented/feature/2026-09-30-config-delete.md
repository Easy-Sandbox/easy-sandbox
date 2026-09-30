# Decision: `ebx config delete` removes one stored value

Status: implemented
Implemented: 2026-09-30

## Problem

The only way to drop a stored setting was `ebx config set KEY ""`. That works,
but it is easy to miss: `config` had `get`, `set`, `list`, and `init`, and no
command whose name says the value is being removed. `template delete` already
exists for the remote template.

## Decision

- `ebx config delete KEY` removes the value stored by `ebx config set`. The
  key falls back to its built-in default or becomes not set.
- `shortcuts.<name>` removes that one alias. Reserved command names stay
  reserved.
- `ebx config set KEY ""` keeps doing the same removal.
- An environment variable that still overrides the key is not unset. The
  result names the variable and does not print its value.
- There is still no `ebx config reset` and no command that deletes `~/.ebx`.

## Test strategy

`tests/test_cli/test_config_commands.py`: deleting a credential leaves the
other `.env` lines, deleting `region` falls back to `cn-hangzhou`, an unknown
key exits 2, an overriding environment variable is named but not printed, and
`shortcuts.ps` is removed.

## Files changed

- `src/easy_sandbox/cli/commands/config_cmd.py`
- `docs/{en,zh}/reference/cli-reference.md`, `docs/{en,zh}/design/cli-design.md`
- `CHANGELOG.md`
