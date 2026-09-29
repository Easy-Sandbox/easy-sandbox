# Decision: BYO agent integration — dedicated templates + custom_commands contract, no in-SDK agent runtime

Status: implemented
Proposed: 2026-09-29
Implemented: 2026-09-29
Related: [2026-09-29-pluggable-coding-agent-backend.md](2026-09-29-pluggable-coding-agent-backend.md), [2026-09-29-template-catalog-single-source-of-truth.md](2026-09-29-template-catalog-single-source-of-truth.md), [2026-09-29-skills-design-removal-and-mcp-docs-convergence.md](2026-09-29-skills-design-removal-and-mcp-docs-convergence.md)

## Problem

Task 195 evaluated whether Easy Sandbox should ship a pluggable sandbox-embedded
agent (e.g. a bundled Qwen Code CLI) instead of leaving agents to the user. The
evaluation covered Qwen Code CLI, Qoder CLI, Codex CLI, Claude Code, and
user-defined agent commands: install channels, real headless CLI behaviour,
runtime and system dependencies, auth modes, licenses, image size, startup
cost, version locking, security boundaries, and network/credential
requirements.

Two integration axes were being conflated in the docs:

1. **Host-side generation** — `ebx create "<description>"` runs Qwen Code *on
   the host* to generate `Dockerfile` + `template.yaml` (already covered by the
   pluggable-backend ADR; Qwen Code is the default host backend).
2. **In-sandbox agents** — a coding-agent CLI running *inside* the sandbox to
   do the actual work.

Without an explicit decision, the pressure was to (a) preinstall every agent
into the default base image, (b) add an `agent` capability / SDK orchestration
layer duplicating agent planning loops, (c) download agents on first sandbox
run, or (d) redistribute proprietary binaries (Claude Code, Qoder CLI) in
official templates. Each option fails a licensing, reliability, or layering
constraint.

## Decision

**Bring Your Own Agent (BYO).** Easy Sandbox provides the isolated runtime and
the operational surface; the agent CLI provides planning, reasoning, code
generation, and its tool loop. Concretely:

### Responsibility split

- Easy Sandbox owns: sandbox CRUD + lifecycle (TTL, kill), files, shell
  commands, network/ports, the MCP server, credential injection
  (`ebx create --env KEY=...`), and the template build/deploy pipeline.
- The agent CLI owns: model calls, planning, task decomposition, code
  generation, and its internal tool loop.
- The SDK adds **no LLM client dependency** and no agent runtime (no planner,
  no orchestration). The existing `AgentModule` stays sugar over
  `commands.run()`; the Skills runtime is not restored.

### Packaging: dedicated templates, not the base image

- **The default base image ships no agent CLI.** General-purpose templates stay
  small, auditable, and license-clean.
- The main path is a **dedicated template per agent** in the
  awesome-templates catalog (SSOT), plus this repository's BYO guide.
- Official catalog templates only ship agents whose license permits
  redistribution **and** whose install can be version-pinned:
  Qwen Code (Apache-2.0) and Codex CLI (Apache-2.0) are eligible;
  Claude Code and Qoder CLI are proprietary and are documented for self-built
  or community templates only — **no binary is redistributed** by this
  repository.
- On-demand install is acceptable only for host-side helper tooling; never as
  a first-run download inside the sandbox.

### The minimal contract = existing `custom_commands`

No new capability, template schema, or SDK API. A BYO agent template maps the
contract onto the `CustomCommand` model that already exists
(`src/easy_sandbox/models/template.py`):

| Contract element | Mechanism |
| --- | --- |
| Install / probe | `Dockerfile` build-time install + a probe command (`agent_probe`) |
| Headless startup | `custom_commands.<name>.cmd` with `{placeholder}` tokens |
| Prompt input | required `args[]` entry (filled after `shlex.quote()`) |
| JSON output | flags in `cmd`; format documented in `description`; stdout parsed by the caller |
| Auth env whitelist | `env` names in `template.yaml` + values via `ebx create --env` |
| Working directory | `custom_commands.<name>.cwd` (`/workspace` convention) |
| Timeout | `custom_commands.<name>.timeout` per turn; sandbox TTL separate |
| Resource limits | `resources.cpu` / `resources.memory`; `Sandbox.create(cpu=, memory=)` overrides |
| Lifecycle | `ebx create --timeout`, `ebx kill <id>` |
| Error mapping | non-zero exit code + stderr on `CommandResult` |
| Version locking | exact versions in the `Dockerfile` (+ SHA256 for archives) |
| License boundary | official (Apache-2.0) vs proprietary (BYO/community only) |

Per-CLI dialects are preserved (Codex uses `codex exec --json`; the rest use
`-p`; permission/output flags differ) — templates adapt to the CLI, the
contract does not force uniformity.

### Docs and verification

- New bilingual guide: `docs/en/guide/byo-agent-integration.md` +
  `docs/zh/guide/byo-agent-integration.md`, linked from both docs indexes and
  both DESIGN indexes.
- The guide explicitly separates host-side generation (Axis A) from in-sandbox
  agents (Axis B) and states the no-preinstall base-image rule.
- No unverified install pipelines: the guide documents pinning + hash
  verification and does not recommend `curl … | sh`; proprietary agents are
  never distributed as official binaries.

## API Design

N/A — this decision does not involve API changes. The contract reuses the
existing `CustomCommand` / `custom_commands` mechanism and the existing CLI
(`ebx run <id> <name>`) and SDK (`sandbox.custom(name, **kwargs)`) entry
points.

## Alternatives considered

- **Preinstall all agents in the default base image** — rejected: multi-GB
  images, license contamination (proprietary binaries), version collisions,
  and every user paying for agents they do not use.
- **Add an `agent` capability token / SDK orchestration layer** — rejected:
  duplicates planning/reasoning that belongs to the agent, violates the
  zero-LLM-dependency principle, and reopens the deleted Skills-runtime
  surface.
- **First-run on-demand install inside the sandbox** — rejected: slow,
  unrepeatable, not version-locked, and a supply-chain risk on every sandbox
  start.
- **Redistribute proprietary binaries in official templates** — rejected:
  license violation and unverifiable provenance; proprietary agents stay
  BYO/community documentation only.
- **Force a single uniform headless invocation across vendors** — rejected:
  vendor CLIs have different subcommands and flags (`codex exec` vs `-p`);
  the contract standardises the *interface* (probe, named run command,
  prompt arg, output format, whitelist), not the dialect.
- **Document nothing and let users improvise** — rejected: users would paste
  credentials into images, skip version pinning, and misuse permission-bypass
  flags (the highest-risk mistakes the guide now prevents).

## Dependencies

None new. Documentation and tests only; no SDK, CLI, or template-schema
changes. The contract depends on the existing `custom_commands` model and the
existing template pipeline.

## Test Strategy

- New `tests/test_byo_agent_docs.py` keeps the guide honest and bilingual:
  both guides exist and are substantial; every relative link resolves; in-guide
  anchors match headings; shared commands / flags / environment-variable names
  / paths stay identical across languages; the responsibility split, the
  two-axes explanation, the no-preinstall rule, the credential whitelist, the
  version-locking rules, and the license boundaries are all present in both
  languages; neither guide demonstrates `curl | sh` in code blocks while both
  warn against it; the docs indexes (both READMEs and both DESIGN indexes)
  link the guides.
- Template-level contract tests and minimal E2E live with the template
  convergence work in the awesome-templates repository (separate task), so
  this repository keeps no duplicated template content.

## Acceptance criteria

- [x] Bilingual BYO guide exists, covering: install/probe, headless startup,
      prompt input, JSON output, auth env whitelist, working directory,
      timeout, resource limits, lifecycle, error mapping, version locking,
      and license boundaries
- [x] The guide states the base image ships no agent CLI, recommends dedicated
      templates + BYO docs, and separates host-side generation from in-sandbox
      agents
- [x] Official (Apache-2.0) vs proprietary distribution boundaries are
      explicit; no proprietary binary distribution; no unverified
      `curl | sh` recommendation
- [x] Both docs indexes (README + DESIGN, EN/ZH) link the guide
- [x] Consistency tests land in this repository; existing suites stay green

## Consequences

- Users get a checkable contract instead of ad-hoc agent templates; the
  highest-risk mistakes (credentials baked into images, unpinned downloads,
  host-side permission bypass, proprietary redistribution) are addressed in
  one place.
- Per-agent headless dialects remain the template author's responsibility;
  the guide documents verified 2026-09-29 behaviour and will need periodic
  re-verification as vendor CLIs evolve.
- The awesome-templates catalog remains the single source of truth for template
  content; this repository adds documentation and tests only.

## Evidence

- `tests/test_byo_agent_docs.py` — bilingual/link consistency suite (see
  Verification section of the task evidence).
- Guide facts verified 2026-09-29 against vendor documentation / CLI
  behaviour: Qwen Code (Apache-2.0; standalone/npm/Homebrew; `qwen -p`,
  `--output-format json`, `--max-session-turns`; `DASHSCOPE_API_KEY` /
  `BAILIAN_CODING_PLAN_API_KEY` / `OPENAI_API_KEY` + `OPENAI_BASE_URL`),
  Codex CLI (Apache-2.0; `codex exec --json`, `--sandbox workspace-write`;
  `OPENAI_API_KEY`), Claude Code (proprietary; `claude -p`, `--allowedTools`,
  `--output-format json`/`stream-json`, `--bare`; `ANTHROPIC_API_KEY`),
  Qoder CLI (proprietary; `qoder -p`, `--output-format json`/`stream-json`,
  `--max-turns`, `--permission-mode bypass_permissions`;
  `QODER_PERSONAL_ACCESS_TOKEN`).

## Files changed

- New: `docs/en/guide/byo-agent-integration.md`,
  `docs/zh/guide/byo-agent-integration.md`, `tests/test_byo_agent_docs.py`,
  this ADR.
- Changed: `docs/en/README.md`, `docs/zh/README.md`, `docs/en/DESIGN.md`,
  `docs/zh/DESIGN.md` (index entries; the stale "Built-in Agents" summaries
  now describe `AgentModule` + dedicated templates and link the BYO guide).
- Untouched by design: `src/easy_sandbox/**` (no SDK/CLI changes), external
  awesome-templates repository (template convergence is a separate task), and
  the verified Agent Skill installation commands (task 193 scope).
