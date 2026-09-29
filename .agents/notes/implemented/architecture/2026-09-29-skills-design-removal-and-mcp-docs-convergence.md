# Decision: Skills Design Removal and MCP Docs Convergence

Status: implemented

## Problem

An implementation audit found that the Skills documentation and parts of the MCP
documentation described features that do not exist anywhere in the code:

1. **skills-system.md was a pure design draft** — the Chinese and English
   `design/skills-system.md` described a `ebx skill` CLI command, SDK Skills
   classes, a Skills registry, and a `skills` field in template specs. None of
   these exist: `cli/main.py` has no `skill` command group, the SDK has no
   skills API, `agent/tools.py` registers no skill tools, and template parsing
   (`models/template.py`) rejects unknown fields.
2. **Stale Skills references across docs** — `README`, `DESIGN`,
   `template-system`, `architecture-overview`, `e2b-compatibility`, and
   `architecture` linked to the deleted design or listed skills as a runtime
   capability.
3. **MCP docs drifted from code** — the MCP design docs listed 9 unimplemented
   P1/P2 roadmap tools, a Skills registry integration, a `--skills` start
   option, `--transport http`, a `qoder` install target, and "auto-deploy to
   FC" wording, none of which match `cli/commands/mcp.py`, `agent/mcp.py`,
   `agent/mcp_http.py`, or `agent/tools.py`.
4. **deploy artifact format mismatch** — `ebx mcp deploy` wrote a file named
   `config.yaml` whose content was produced by `json.dumps` (JSON body under a
   YAML filename), misleading both users and downstream tooling.

## Decision

Remove the unimplemented Skills design entirely and converge all MCP
documentation onto the audited implementation. Do not preserve future roadmap
content on the user's behalf.

### Skills cleanup

- Deleted `docs/en/design/skills-system.md` and `docs/zh/design/skills-system.md`.
- Removed Skills links/capability rows from: `README(.zh-CN)`, `docs/*/README.md`,
  `docs/*/DESIGN.md`, `docs/*/design/template-system.md`,
  `docs/*/design/architecture.md`, `docs/*/explanation/architecture-overview.md`,
  `docs/*/explanation/e2b-compatibility.md`, `docs/*/design/cli-design.md`,
  `llms.txt`.
- Corrected the command-group inventory in `architecture-overview.md` to the
  real `cli/main.py` subcommands (config, template, mcp, sandbox groups plus
  top-level shortcuts); removed the phantom `skill.py` line from the
  `architecture.md` source trees.
- Preserved the qwen-code template's own `/root/.qwen/skills/` concept in
  `template-system.md` only as an external tool capability (SKILL.md → noted as
  consumed by the bundled agent tool, not an Easy Sandbox feature).

### MCP docs convergence

- Rewrote `docs/*/design/mcp-server.md` against code: exactly the 7 P0 tools
  with their real parameters/defaults/return fields (`size` → `bytes_written`,
  no `description`/`persistent` params), STDIO protocol details, Streamable
  HTTP ASGI endpoints (`POST/DELETE /mcp`, `GET /mcp` → 501, `GET /health`),
  session TTL/capacity behavior, Bearer token fail-closed semantics, the real
  environment variables, real `install` targets (cursor/claude/vscode), and
  "generates an artifact; automatic FC deployment is not implemented".
- Removed all P1/P2 roadmap tool tables, the Skills registry section, and
  non-existent CLI flags from `mcp-server.md` and `cli-design.md`.
- Rewrote `docs/*/guide/mcp-integration.md` as a runnable guide: IDE install,
  STDIO start with smoke test, `status`, uvicorn + `create_mcp_app` HTTP usage,
  Bearer token, `ebx mcp deploy` artifact walkthrough, client config snippets,
  curl three-step workflow, and a troubleshooting table.
- Fixed `llms.txt`: `ebx mcp serve` (non-existent) → `ebx mcp start`.

### deploy artifact format fix

`config.yaml` now contains real YAML, using the existing `pyyaml` dependency
(already required by the `cli` extra and used by `cli/commands/template.py`):

```python
import yaml  # provided by the cli extra, same as cli/commands/template.py

(artifact_dir / "config.yaml").write_text(
    yaml.safe_dump(fc_config, default_flow_style=False, sort_keys=False, allow_unicode=True)
)
```

Keys keep insertion order; nested FC settings render as block mappings.

## API Design

```python
# Behavior change (artifact only): config.yaml content is YAML, not JSON.
# Before: json.dumps(fc_config, indent=2, ensure_ascii=False)
# After:  yaml.safe_dump(fc_config, default_flow_style=False, sort_keys=False,
#                        allow_unicode=True)
# No CLI flags, tool schemas, endpoints, or env vars changed.
```

## Alternatives considered

- **Rename the artifact to `config.json`** — Rejected: keeps the filename/format
  honest but churns help text, docs, and tests to describe the same payload;
  YAML is the native manifest format for the FC deployment workflow the
  artifact targets, and `pyyaml` was already a dependency, so emitting real
  YAML is the smaller, more useful fix.
- **Keep skills-system.md with an "unimplemented" banner** — Rejected: the
  audit directive says not to preserve future planning on the user's behalf;
  the design had no code counterpart and its removal matches the earlier
  overdesign-cleanup precedent.
- **Retain P1/P2 roadmap tables in MCP docs** — Rejected for the same reason:
  unverified planning content was indistinguishable from shipped behavior.

## Dependencies

No new dependencies. `pyyaml` was already declared in the `cli` extra in
`pyproject.toml` (and imported by `cli/commands/template.py`), so the YAML
artifact output adds no install requirements.

## Test Strategy

- `tests/test_cli/test_mcp_commands.py`: all `config.yaml` assertions switched
  from `json.loads` to `yaml.safe_load` — 23 passed.
- Regenerated MCP CLI evidence via
  `scripts/capture_cli_evidence.py --command mcp`; golden help files
  (`help-mcp*.txt`, 5 files) updated to the new deploy docstring.
- Combined run of MCP CLI, evidence snapshot, agent MCP, and MCP HTTP tests:
  169 passed.
- `ruff check` and `ruff format --check` clean on the two changed Python
  files; `mypy` reports only the pre-existing `no-untyped-def` errors in the
  test file (verified identical before/after via `git stash`).

## Acceptance criteria

- [x] `skills-system.md` deleted in both languages; no Skills links remain in
      docs (qwen-code template's external skills directory excepted and
      labeled as external tool capability)
- [x] MCP design docs match code for tools, params, returns, transports,
      install targets, deploy semantics, env vars, default template
- [x] MCP usage guides (en/zh) cover install/start/status/HTTP/token/deploy/
      client config/troubleshooting with runnable examples
- [x] `config.yaml` artifact contains real YAML; tests and golden evidence
      updated
- [x] MCP/CLI tests, ruff, and mypy verified with no new failures
