# Decision: CLI command reduction (60+ → 43 commands)

Status: implemented
Implemented: 2026-09-23

## Problem
For the sake of feature completeness, the early CLI accumulated more than 60
commands, including four complete subcommand groups: `auth` (login/logout/status/
whoami), `session` (save/load/list/delete), `secret` (set/get/list/delete), and
`skill` (list/install/run). These commands had the following problems:

1. **auth group**: authentication is entirely driven by environment variables /
   config; standalone login/logout/whoami commands are legacy of an OAuth flow
   and have no real use under the current API-Key + AK/SK model.
2. **session group**: session persistence is still at the low-level implementation
   stage of the `session/` module; exposing it via CLI is premature and there are
   no real user scenarios.
3. **secret group**: secret management is done on the FC platform side via
   environment-variable injection; the SDK does not need standalone secret CRUD
   commands.
4. **skill group**: the Skill concept is not yet clearly defined in the current
   version (its boundary with custom commands / templates is blurred); exposing
   empty-shell commands undermines user trust.

Command-count bloat also made `ebx --help` verbose, raised the cognitive load
for new users, and broadened maintenance/testing surface.

## Decision
Remove the four subcommand groups `auth`, `session`, `secret`, and `skill`
(~17 commands total), reducing the CLI's total command count from 60+ to 43.

### Retained command structure (43 commands)

- **Top-level shortcuts** (11): `create`, `list`, `info`, `kill`, `exec`,
  `connect`, `run`, `upload`, `download`, `deploy`, `install`
- **`sandbox` subgroup** (17): core CRUD + `files` (6) + `process` (4) +
  `system` (5) + `capabilities` + `shell-stream`
- **`template` subgroup** (8): `deploy`, `build`, `push`, `create`, `install`,
  `list`, `info`, `delete`, `search`
- **`config` subgroup** (4): `get`, `set`, `list`, `reset`
- **`mcp` subgroup** (4): `install`, `start`, `status`, `deploy`

### Removal principles

- Feature unimplemented or shell-only → remove
- Feature replaceable by existing commands / environment variables / config → remove
- Concept boundary unclear → defer until the concept is clarified

## API Design
N/A — this decision does not involve API changes. It removes CLI subcommand
groups from the `LazyGroup` registration and the commands module directory; no
Python-level SDK APIs are added, removed, or modified.

## Alternatives considered
- **Keep the shell commands with a [WIP] tag** — undermines user trust, makes the
  `--help` page noisy. Rejected.
- **Keep the auth group for credential verification only** — `ebx config list`
  already shows the current credential status, making the auth group redundant.
  Rejected.
- **Hide session/secret but keep the code** — the maintenance cost cannot be
  eliminated; better to remove and reimplement when needed. Rejected.

## Dependencies
- `src/easy_sandbox/cli/main.py` (LazyGroup registry)
- `.agents/design/2026-09-23-cli-final-design.md` (comprehensive CLI/MCP/
  testing design reference; kept outside the ADR lifecycle as a historical
  snapshot)

## Test Strategy
- `ebx --help` output does not include auth/session/secret/skill.
- The `--help` of all 43 retained commands prints correctly.
- CliRunner tests cover the basic invocation of every retained command.

## Acceptance criteria
- ✅ The four command groups `auth`, `session`, `secret`, and `skill` are fully
  removed from the CLI entry point and the commands module.
- ✅ The CLI's total command count is 43.
- ✅ `ebx --help` output is concise and clean, with no empty-shell commands.
- ✅ All retained commands can be invoked normally.

## Implementation
- **CLI entry**: `src/easy_sandbox/cli/main.py` (the `lazy_subcommands` dict no
  longer contains auth/session/secret/skill)
- **Command modules**: no `auth.py`/`session.py`/`secret.py`/`skill.py` under
  `src/easy_sandbox/cli/commands/`
- **Final command tree**: see chapter 1 of
  `.agents/design/2026-09-23-cli-final-design.md` (design-reference snapshot)
