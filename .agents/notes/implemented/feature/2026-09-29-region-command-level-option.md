# Decision: Move --region from a global root option to command-level options

Status: implemented
Implemented: 2026-09-29
Supersedes: the `--region` global option in [2026-09-02-cli-tool.md](2026-09-02-cli-tool.md)

## Problem
`--region`/`-r` was defined as a root-level global option (see
2026-09-02-cli-tool.md), injected via `ctx.obj` into every subcommand. This was
wrong on several counts:

- Region is not a global functional switch like `--json`/`--quiet`/`--verbose`.
  Purely local commands (`sandbox files/process/system`, `template search`,
  `template init`, `mcp install/start/status`) never talk to a regional control
  plane, yet had to accept (and ignore) the flag.
- `ebx mcp deploy` had its **own** `--region` parameter with a hardcoded
  `default="cn-hangzhou"`, creating a double semantic: the command-level flag
  always won and silently bypassed `ebx config set region` / `SANDBOX_REGION`.
- The natural user syntax is `ebx template list --region cn-shanghai`, not
  `ebx --region cn-shanghai template list`.

## Decision
1. **Remove the root `--region`/`-r` option and the `ctx.obj` region injection**
   from `cli/main.py`. `ebx --region ... <cmd>` now fails with the standard
   Click error (exit 2, `No such option: --region`). No compatibility
   deprecation layer: the CLI has not been officially released, so there are no
   existing users to migrate.
2. **Add a local `--region`/`-r` only to commands that talk to a regional
   control plane** (Alibaba Cloud control plane, ACR, FCSandbox, FC deploy):
   - `ebx list` / `ebx sandbox list`
   - `ebx kill --all` / `ebx sandbox kill` (the `--all` path calls the control
     plane; killing one sandbox by ID does not)
   - `ebx template list` / `info` / `create` / `push` / `build` / `install` /
     `delete` (and the `deploy` alias, which inherits `build`'s params)
   - `ebx install` (top-level shortcut, forwards via `ctx.invoke`)
   - `ebx mcp deploy`
   Local commands do not get the option at all — passing `--region` to them is
   a standard Click "no such option" error.
3. **One shared helper** (`src/easy_sandbox/cli/region.py`):
   - `region_option` — the click option decorator (`--region`/`-r`, default
     `None`, metavars aligned with other options).
   - `resolve_region(cli_region)` — returns the final region via
     `load_config(region=cli_region).region`.
   Commands that build a full config call `load_config(region=cli_region)`
   directly; both paths go through the same transport-level override chain, so
   the priority is implemented exactly once:
   **command `--region` > `ebx config set region` / `SANDBOX_REGION` env >
   `cn-hangzhou`**.
4. **`mcp deploy` drops its hardcoded default** and uses the shared
   `region_option` + `resolve_region`, eliminating the double semantic: it now
   honors `ebx config set region` / `SANDBOX_REGION` like every other regional
   command.
5. Shortcut/alias integrity: top-level `list`/`kill`/`install` shortcuts and
   the `template deploy` alias (`params=list(build.params)`) expose and forward
   the option, so `--region` always takes effect at the command that executes.

## Alternatives considered
- **Keep the global option plus per-command overrides** — preserves the old
  syntax but keeps region on commands that never use it and keeps the
  `ctx.obj` injection plumbing. Rejected.
- **One-release deprecation shim** (warn on `ebx --region ...` before removal)
  — unnecessary: no released version exists, so a clean break is the simplest
  correct option. Rejected.
- **Mechanically copy `--region` onto every command** — would hide which
  commands actually hit a regional control plane. Rejected.

## Dependencies
- `src/easy_sandbox/transport/config.py` — `load_config(region=...)` override
  chain (CLI > env > .env > config.toml > default)
- Click `ctx.invoke` forwarding for top-level shortcuts; `params` inheritance
  for the `template deploy` alias

## Test Strategy
`tests/test_cli/test_region_options.py`:
- Root help no longer lists `--region`; old `ebx --region`/`-r` syntax exits 2
- All 14 regional command paths accept `--region`; 16 local commands do not
  expose it, and passing it to local commands exits 2
- `--region` reaches `load_config` as an override; config-file fallback and the
  `cn-hangzhou` default verified through an isolated config env fixture
- `resolve_region` priority matrix (command > config file > env > default)
- `mcp deploy` config.yaml honors the unified priority (no more double
  semantic)
- Shortcut/alias forwarding (`ebx install`, `ebx deploy` alias params, `kill
  --all`)

## Files changed
- `src/easy_sandbox/cli/region.py` — new shared helper
- `src/easy_sandbox/cli/main.py` — root option + `ctx.obj` injection removed
- `src/easy_sandbox/cli/commands/sandbox.py` — `list` / `kill` local option
- `src/easy_sandbox/cli/commands/template.py` — `_do_deploy(region=...)`;
  local options on install/list/info/create/push/build/delete/install shortcut
- `src/easy_sandbox/cli/commands/mcp.py` — shared option + `resolve_region`
- `tests/test_cli/test_region_options.py` — new; `test_mcp_commands.py` pinned
  `resolve_region` for determinism
- `tests/test_cli_evidence/golden/` + `.agents/evidence/` — regenerated
- Docs (en/zh): `cli-reference.md`, `cli-design.md`, `cli-tutorial.md`,
  `authoring-templates.md`, `mcp-server.md`, `configuration.md`

## Acceptance criteria
- ✅ `ebx --help` shows no `--region`; `ebx --region cn-shanghai list` exits 2
- ✅ `ebx list --region cn-shanghai`, `ebx sandbox list --region cn-shanghai`,
  `ebx template build ... --region cn-shanghai`, `ebx mcp deploy --region
  cn-shanghai` all work
- ✅ `ebx config set region cn-shanghai` is honored by every regional command
  without `--region`; default remains `cn-hangzhou`
- ✅ Local commands reject `--region` with the standard Click error
- ✅ `mcp deploy` honors config/env fallback (no hardcoded default semantic)
- ✅ CLI/template/sandbox/mcp/evidence tests, ruff and mypy pass
