# Module Specifications & Architecture Decisions

This directory contains Architecture Decision Records (ADRs) and module specifications
following a structured review process.

## Directory Structure

```
notes/
├── proposed/          # Under review
│   ├── architecture/  # System-wide architecture decisions
│   ├── feature/       # Feature module specifications
│   └── process/       # Engineering process decisions
├── implemented/       # Accepted and implemented
│   ├── architecture/
│   ├── feature/
│   └── process/
└── rejected/          # Considered but rejected
```

## Lifecycle

1. **Proposed** → Create in `proposed/<category>/`
2. **Implemented** → Move to `implemented/<category>/`, update Status field
3. **Rejected** → Move to `rejected/`, document reasoning

The `Status:` field value **must** match the state directory the file lives in
(`proposed` / `implemented` / `rejected`). When work is completed, move the file
and update the field together.

## Language

All ADRs **must** be written in English. This keeps the `.agents/` engineering
record internally consistent and reviewable by all contributors and tooling.
(Go-forward convention: every document under `.agents/notes/` is English. Existing
snapshots under `.agents/evidence/` are historical artifacts and are left as-is.)

## Naming & Location

- **File name:** `YYYY-MM-DD-<topic-slug>.md` — ISO date of the decision plus a
  lowercase, hyphenated topic slug (e.g. `2026-09-09-layer-violation-fix.md`).
- **Location:** `<state>/<category>/` where `<state>` is `proposed`,
  `implemented`, or `rejected`, and `<category>` is one of:
  - `architecture/` — system-wide architecture decisions
  - `feature/` — feature module specifications
  - `process/` — engineering process decisions
- **Exception:** `rejected/` is a **flat** directory (no category subfolders).

## Template

Each ADR file follows this format. The title line is always `# Decision: <Title>`,
immediately followed by the `Status:` line.

### Required sections

Every ADR must contain all seven sections below, in this order:

```markdown
# Decision: <Title>

Status: proposed | implemented | rejected

## Problem
<Motivation, independent of solution>

## Decision
<Technical approach, interfaces, file paths>

## API Design
<Core class/function signatures, input/output types.
For decisions that do not involve APIs, state:
"N/A — this decision does not involve API changes.">

## Alternatives considered
- **<Option A>** — <Why rejected>

## Dependencies
<Required modules/packages>

## Test Strategy
<Testing approach and coverage>

## Acceptance criteria
<Measurable acceptance conditions>
```

### Optional sections

The following sections **may** appear after the required sections when useful.
They are registered as recognised optional sections and are not mandatory:

- `## Consequences` — trade-offs and follow-on effects of the decision
- `## Implementation` — implementation notes, phases, or status detail
- `## Evidence` — links to tests, PRs, or captured verification artifacts
- `## Files changed` — the concrete files touched by the decision
