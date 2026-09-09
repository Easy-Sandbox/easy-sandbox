# Decision: Minimal Template Repository Shape

Status: implemented

## Problem
Templates need a distribution form that is trivial to author, review, and (later) extract into its own repository, without heavyweight registry infrastructure.

## Decision
Keep the template repository maximally simple: **one `README` plus a set of template folders**. Each template folder contains its `template.yaml` (and optional `Dockerfile`, `scripts/`, `files/`, `examples/`). No index file, no registry service.

- The whole collection can be extracted wholesale into a standalone GitHub repository when it grows.
- The main project repository links to it from docs rather than vendoring it.
- Discovery is a directory walk (consistent with the command-source-resolution ADR — no `index.json`).

```
sandbox-templates/
├── README.md                 # what's here + how to install
├── python-base/
│   └── template.yaml
├── node-web/
│   ├── template.yaml
│   └── Dockerfile
└── code-interpreter/
    └── template.yaml
```

## Alternatives considered
- **Registry service + database** — Overkill for the current template count; adds infra and ops burden.
- **Index/manifest file at repo root** — Extra sync surface; a directory walk suffices (see command-source-resolution ADR).
- **Vendor templates inside the main repo permanently** — Couples release cadence; harder to extract later.

## Dependencies
- `2026-09-03-command-source-resolution.md` (directory-walk discovery)
- `2026-09-03-release-publish-flow.md` (how the repo gets published)
- `docs/design/template-system.md` (template packaging + `template.yaml`)

## Test Strategy
- A repo with N template folders is discoverable by directory walk.
- Each folder's `template.yaml` parses (including `capabilities` + `custom_commands`).
- The collection can be `sbox install`-ed from a local path and from GitHub.

## Acceptance criteria
- Repository is just `README` + template folders — no index or registry component.
- Templates are discoverable and installable via directory walk / GitHub.
- Collection is self-contained enough to extract into a standalone repo, with the main repo linking to it.
