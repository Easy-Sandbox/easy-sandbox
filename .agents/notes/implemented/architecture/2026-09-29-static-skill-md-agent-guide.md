# Decision: Static SKILL.md Agent Guide at the Repository Root

Status: implemented

Date: 2026-09-29

## Problem

AI coding tools and agents working in *other* projects (not this repository) need a
portable, tool-neutral description of how to operate Easy Sandbox: which interface to
pick (MCP vs Python SDK vs `ebx` CLI), how to install, how to keep credentials safe,
how to run the sandbox lifecycle, and how to diagnose common errors.

Prior to this decision the repository had only research conclusions — the skills
*system* design (`docs/*/design/skills-system.md`) had been deleted as unimplemented
(ADR 2026-09-29 skills-design-removal), and the `ebx skill` CLI command group had
been removed (ADR 2026-09-23 CLI command reduction). Nothing shippable existed for
external agents to consume, and `llms.txt` contained API drift: a non-existent
`sb.filesystem` attribute, a non-existent `python-base` template, and six dead
`docs/design/` links.

## Decision

Add a **static `SKILL.md` at the repository root** following the common Agent Skills
convention (YAML frontmatter `name` + `description`, Markdown instructions — the same
format the qwen-code template writes into `/root/.qwen/skills/`).

Scope boundaries, made explicit inside the file:

1. **Static guide only.** The file is not executed, parsed, or registered by Easy
   Sandbox at runtime.
2. **No restoration** of the removed `ebx skill` command group, Skills registry,
   skill runtime, or template skill configuration.
3. **Tool-neutral.** It documents one shared surface (CLI / SDK / MCP) and briefly
   explains how MCP-capable tools (Cursor, Claude, VS Code, Qoder, …),
   skills-aware tools, and AGENTS.md/rules-based tools (Codex, …) each consume the
   same guide or MCP server — without binding to any single vendor.
4. **Content floor** (all verified against code before writing): when to use,
   install, credential security with explicit never-leak rules, MCP vs SDK vs CLI
   selection rules, create / execute / files / destroy workflows with real commands,
   and an error-diagnosis table using real error codes (E1001, E1003, E2001, E2002,
   E2003, E3001, E3004, E5003) and CLI exit codes.

Supporting changes:

- `llms.txt`: added the SKILL.md reference (purpose note + Links entry) and fixed
  the pre-existing drift (`sb.filesystem` → `sb.files`, `python-base` →
  `python-hello`, `docs/design/` → `docs/en/design/`).
- `pyproject.toml`: `SKILL.md` added to the **sdist** include list.

### Packaging decision (with test evidence)

- **sdist: include.** SKILL.md is a top-level distribution document like README.md;
  source-distribution consumers (including AI tooling unpacking the tarball) get it.
- **wheel: exclude.** The wheel ships only the `easy_sandbox` Python package; a
  repo-root usage guide does not belong in `site-packages`.
- Evidence: `tests/test_packaging.py` builds both artifacts with the real backend
  (hatchling, `python -m hatchling build`) in a temporary repo copy and asserts
  SKILL.md is present in the sdist and absent from the wheel. A third test pins the
  include-list decision itself (SKILL.md in, llms.txt deliberately out).

### Guide/code consistency (with test evidence)

`tests/test_agent_guide.py` asserts: frontmatter format and size limits, the
required topic coverage, the static-guide/no-restore disclaimer, that `ebx skill`
mentions appear only as removal disclaimers, that the MCP tool names cited match
`agent/tools.py` `TOOL_SCHEMAS`, that cited error codes exist in `models/errors.py`
(or CLI HTTP mappings), that repo paths cited in SKILL.md exist, that `llms.txt`
references SKILL.md, that `llms.txt` Links resolve on disk, and that every `ebx …`
example in `llms.txt` names a command registered in `cli/main.py`.

## Alternatives considered

- **Restore `ebx skill search/install/...`** — Rejected: re-introduces the
  unimplemented skills system removed by ADR 2026-09-23; a static file delivers the
  value (teaching agents) without any runtime surface.
- **Put the guide only under `docs/`** — Rejected: agents in other repositories
  discover repo-root artifacts (`llms.txt`, `SKILL.md`) far more readily than nested
  docs; `docs/` remains the deep-dive layer the guide links to.
- **Include SKILL.md in the wheel** — Rejected: wheels install into
  `site-packages`; a usage guide is not an importable asset and would pollute every
  environment that installs the package.
- **Vendor-specific skill packages** (e.g. only a Claude-flavoured skill) —
  Rejected: the Agent Skills frontmatter format is already vendor-neutral, and MCP
  provides an identical tool surface to every client; per-vendor forks would drift.

## Dependencies

None. No new runtime dependencies; `pyyaml` (already a `cli` extra) is used by the
consistency test for frontmatter parsing; `hatchling` (already the build backend in
the dev environment) is used by the packaging test, with `importorskip` guards so
minimal environments can still run the suite.

## Test Strategy

- `pytest tests/test_packaging.py tests/test_agent_guide.py` — 15 passed.
- Real-build evidence: sdist tar listing contains `SKILL.md`; wheel zip listing does
  not; wheel still contains `easy_sandbox/…`.
- llms.txt link/command checks caught and now guard the six previously dead
  `docs/design/` links and any future command drift.

## Acceptance criteria

- [x] `SKILL.md` exists at the repository root in Agent Skills frontmatter format
- [x] Covers: when to use, install, credential safety, MCP/SDK selection rules,
      create, execute, file operations, destroy, error diagnosis, never-leak rules
- [x] States it is a static guide and does not restore the removed skills system
- [x] Tool-neutral consumption notes (MCP / skills-aware / AGENTS.md-based tools)
- [x] `llms.txt` references SKILL.md; its examples and links are code-accurate
- [x] sdist include / wheel exclude decision covered by real-build tests
- [x] CHANGELOG entry added; full test suite, ruff, and mypy run clean
