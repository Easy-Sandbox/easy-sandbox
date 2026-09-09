# Decision: CLI Named `sbox`

Status: implemented

## Problem
Need a short, memorable CLI command name that doesn't conflict with existing system tools.

## Decision
CLI command is `sbox`. Config directory is `~/.sbox/`.

## Alternatives considered
- **`ss`** — Conflicts with Linux built-in `ss` (socket statistics)
- **`sb`** — Too short, potential conflicts
- **`sandbox`** — Too long for frequent CLI use

## Dependencies
- `pyproject.toml` entry_points configuration

## Test Strategy
- Verify `sbox --help` works and shows all commands
- Verify startup time < 200ms

## Consequences
- Clear, memorable, no known conflicts
- Config at `~/.sbox/` follows XDG-like convention
