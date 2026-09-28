# Decision: CLI Named `ebx`

Status: implemented

## Problem
Need a short, memorable CLI command name that doesn't conflict with existing system tools.

## Decision
CLI command is `ebx`. Config directory is `~/.ebx/`.

## API Design
N/A — this decision does not involve API changes.

## Alternatives considered
- **`ss`** — Conflicts with Linux built-in `ss` (socket statistics)
- **`sb`** — Too short, potential conflicts
- **`sandbox`** — Too long for frequent CLI use

## Dependencies
- `pyproject.toml` entry_points configuration

## Test Strategy
- Verify `ebx --help` works and shows all commands
- Verify startup time < 200ms

## Acceptance criteria
- `ebx --help` runs and lists all commands
- The user config directory resolves to `~/.ebx/`
- The command name does not collide with common system tools (e.g. `ss`)

## Consequences
- Clear, memorable, no known conflicts
- Config at `~/.ebx/` follows XDG-like convention
