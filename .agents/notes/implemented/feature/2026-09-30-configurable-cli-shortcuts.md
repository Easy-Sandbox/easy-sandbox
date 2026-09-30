# Decision: Configurable CLI Shortcuts via config.toml

Status: implemented
Implemented: 2026-09-30
Supersedes (partial): [2026-09-29-init-restore-and-create-explicit-error.md](2026-09-29-init-restore-and-create-explicit-error.md) — the rejected alternative "**Implement `config.toml [shortcuts]`**" (lines 68–71 of that ADR) is reversed by an explicit project-lead decision. The original design sketch is `.agents/design/2026-09-23-cli-final-design.md` §2.2–§2.4.
Related: [2026-09-30-shortcut-target-hint.md](2026-09-30-shortcut-target-hint.md) — an invalid target is explained in plain language, and a leading `ebx` is answered with the command to retry.

## Problem

Built-in top-level shortcuts (`create`, `list`, `info`, `kill`, `exec`, `connect`,
`run`, `upload`, `download`, `deploy`, `install`, `init`) were hard-coded in the
`LazyGroup(lazy_subcommands=...)` map in `src/easy_sandbox/cli/main.py`. Users had
no supported way to add their own short aliases (e.g. `ebx ps` for
`ebx sandbox process list`) or to see the shortcut set as configuration.

ADR `2026-09-29-init-restore-and-create-explicit-error.md` rejected the
`config.toml [shortcuts]` draft on the grounds that `custom_commands` and the
SandboxServer registry already covered the extension need. That argument conflated
two different layers:

- Template `custom_commands` and `@registry.command` define commands that execute
  **inside a sandbox** and are dispatched per-sandbox via
  `ebx run <SANDBOX_ID> <COMMAND_NAME>`.
- Shortcuts alias **local CLI routing** (`ebx <alias> [args…]` → an existing CLI
  command path). They need no sandbox, no credentials, and no template — they only
  rename/redirect a local command path.

There was therefore no user-facing mechanism at the CLI routing layer at all, while
the demand for one (shorter names for deep subcommand paths) was real.

## Decision

Implement user-configurable CLI command aliases in the `[shortcuts]` section of
`~/.ebx/config.toml`. The project lead decided to proceed; the layering objection
is resolved by scoping: shortcuts stay a pure CLI-routing concern and do not
compete with in-sandbox named commands.

1. **Configuration format** — `[shortcuts]` maps an alias name to a target
   command path (space-separated subcommand path):

   ```toml
   [shortcuts]
   # Factory defaults — every built-in top-level shortcut (see table below)
   create = "sandbox create"
   list   = "sandbox list"
   # …
   install = "template install"
   init    = "template init"

   # User-defined aliases — any existing command path
   ps      = "sandbox process list"
   sysinfo = "sandbox system info"
   files   = "sandbox files list"
   ```

2. **Default aliases enabled out of the box** — all existing top-level shortcuts
   are factory presets, so behaviour is unchanged without any config file:

   | Default alias | Target |
   |---------------|--------|
   | `create` | `sandbox create` |
   | `list` | `sandbox list` |
   | `info` | `sandbox info` |
   | `kill` | `sandbox kill` |
   | `exec` | `sandbox exec` |
   | `connect` | `sandbox connect` |
   | `run` | `sandbox run` |
   | `upload` | `sandbox upload` |
   | `download` | `sandbox download` |
   | `deploy` | `deploy` |
   | `install` | `template install` |
   | `init` | `template init` |

3. **Single-layer resolution** — an alias resolves to exactly one existing command
   path. Aliases never chain to other aliases and never rewrite or inject
   arguments; everything after the alias name is passed through unchanged.

4. **Reserved commands cannot be overridden** — the command group names
   (`sandbox`, `template`, `config`, `mcp`) and other reserved top-level names
   cannot be shadowed, redirected, or deleted by a `[shortcuts]` entry. A conflicting
   entry is reported and ignored rather than silently taking effect.

5. **Corrupt-config fallback** — if `~/.ebx/config.toml` cannot be parsed (TOML
   syntax error, wrong value types), the CLI warns on stderr and disables all
   shortcuts for that session; the core command groups (`sandbox` / `config` /
   `mcp` / `template`) keep working, so a broken shortcuts config never bricks
   the CLI.

6. **`config init` generates a complete template** — `ebx config init` writes a
   full `[shortcuts]` block listing all available commands (ready to edit);
   `ebx config init --reset-shortcuts` restores the factory defaults.

Management surface (documented in `docs/*/reference/cli-reference.md`):

```bash
ebx config set shortcuts.<name> "<target>"   # add / modify an alias
ebx config set shortcuts.<name> ""           # delete an alias
ebx config get shortcuts                     # view all aliases
ebx config init --reset-shortcuts            # reset shortcuts to defaults
```

Unknown-command hints (difflib `Did you mean '…'?`, cutoff 0.6; fallback pointing
to `custom_commands` + `ebx run`) keep working on the root group unchanged.

## API Design

N/A — this decision does not involve SDK API changes. The surface is CLI-only:

- Config namespace: `shortcuts.<alias>` → target command path string
  (`"<command> [<subcommand> …]"`), stored in `~/.ebx/config.toml`.
- CLI commands: `ebx config set shortcuts.<alias> "<target>"`,
  `ebx config set shortcuts.<alias> ""`, `ebx config get shortcuts`,
  `ebx config init --reset-shortcuts`.
- Routing: the root `LazyGroup` merges the built-in `lazy_subcommands` map with
  the resolved `[shortcuts]` entries at startup (maintainer registration remains
  the source of built-in commands; user aliases are a config-layer addition).

## Alternatives considered

- **Keep shortcuts hard-coded (the 2026-09-29 rejection)** — reversed: the
  project lead decided to proceed; the earlier rejection conflated CLI routing
  with in-sandbox command extension, which are different layers.
- **`~/.ebx/shortcuts.yaml` as a separate file** — rejected (as in the original
  design draft): an extra file fragments the config surface for no benefit;
  `config.toml` already exists and `ebx config` already manages it.
- **Environment-variable aliases (`EBX_ALIASES`)** — rejected (as in the original
  design draft): poor fit for multi-entry mappings and not persistent.
- **Plugin mechanism** — rejected: over-engineered for name aliasing.

## Dependencies

- Click `LazyGroup` registration in `src/easy_sandbox/cli/main.py`.
- TOML read/write already used by the config subsystem
  (`src/easy_sandbox/cli/commands/config_cmd.py`, `src/easy_sandbox/models/config.py`).

## Test Strategy

- Shortcut resolution: default aliases active without a config file; user alias
  added via `ebx config set shortcuts.<name> "<target>"`; alias deleted via the
  empty value; alias-to-alias chaining rejected; target validated against the
  real command tree.
- Reserved-name protection: `sandbox` / `template` / `config` / `mcp` cannot be
  overridden or deleted.
- Corrupt-config fallback: malformed TOML → warning + all shortcuts disabled,
  the core command groups still work and every `ebx` invocation still works.
- `config init --reset-shortcuts` restores the factory preset; `config get
  shortcuts` prints the effective alias table.
- Docs consistency: cli-design / cli-tutorial / cli-reference (en + zh) describe
  `[shortcuts]` as implemented; no stale "never implemented" annotations remain.

## Consequences

- The "never implemented" annotations in cli-design, cli-tutorial (en + zh), and
  the CHANGELOG note about `[shortcuts]` are superseded; the docs now describe
  `[shortcuts]` as a current capability.
- Users can shorten any command path without waiting for upstream registration.
- `custom_commands` (`template.yaml`) and `@registry.command` (SandboxServer)
  keep their role as in-sandbox named commands invoked via `ebx run`; the
  tutorial's "top-level shortcuts vs your own commands" boundary section now
  describes both layers.

## Acceptance criteria

- All existing top-level shortcuts work with no config file present (factory
  defaults).
- `ebx config set shortcuts.ps "sandbox process list"` makes `ebx ps abc123`
  behave exactly like `ebx sandbox process list abc123`; setting the empty value
  removes the alias.
- `ebx config get shortcuts` lists the effective aliases; `ebx config init`
  generates a complete shortcuts template; `ebx config init --reset-shortcuts`
  restores the defaults.
- Reserved command names cannot be overridden; alias chains are rejected.
- A corrupted `config.toml` disables all shortcuts with a warning while the core
  command groups (`sandbox` / `config` / `mcp` / `template`) keep working, instead
  of the CLI breaking.
