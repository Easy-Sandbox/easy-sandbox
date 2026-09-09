# Decision: CLI Tool (sbox)

Status: proposed

## Problem
Users need command-line access to sandbox management for scripting, CI/CD, and interactive use.

## Decision
`cli/` package with Click + Rich:
- Lazy subcommand loading for < 200ms startup time
- Commands: `create`, `list`, `info`, `kill`, `exec`, `shell` + `auth` + `config`
- Output formats: `--format table|json|quiet` (table default for TTY, json for pipes)
- Exit codes: 0 (success), 1 (general error), 2 (auth error), 3 (not found), 4 (timeout), 5 (connection error), 6 (user interrupt)

CLI entry point: `sbox` (configured in pyproject.toml `[project.scripts]`).

## Alternatives considered
- **argparse** — Less ergonomic, no built-in rich output
- **typer** — Additional dependency, less mature than Click
- **Fire** — Auto-generates CLI from functions, less control

## Dependencies
- `click>=8.0` for CLI framework
- `rich>=13.0` for terminal output formatting
- `api/*` for sandbox operations

## Test Strategy
- Click CliRunner tests for all commands
- Output format verification (table, json, quiet)
- Exit code verification for error scenarios

## Acceptance criteria
- `sbox create → exec → kill` flow works end-to-end
- Startup time < 200ms (lazy imports)
- All output formats work correctly
