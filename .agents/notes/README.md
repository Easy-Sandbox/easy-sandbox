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

## Template

Each ADR file follows this format:

```markdown
# Decision: <Title>

Status: proposed | implemented | rejected

## Problem
<Motivation, independent of solution>

## Decision
<Technical approach, interfaces, file paths>

## API Design
<Core class/function signatures, input/output types>

## Alternatives considered
- **<Option A>** — <Why rejected>

## Dependencies
<Required modules/packages>

## Test Strategy
<Testing approach and coverage>

## Acceptance criteria
<Measurable acceptance conditions>
```
