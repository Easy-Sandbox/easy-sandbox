# Decision: Remove legacy declarative build fields from template.yaml

Status: implemented
Implemented: 2026-09-29

## Problem
`template.yaml` contained declarative build fields (`python_packages`,
`system_packages`, `node_packages`, `commands`, `base`, `copy_files`) and a
`to_dockerfile()` method that were never used in the actual CLI build flow.
The real build pipeline always uses a `Dockerfile` directly. These fields:

- Misled contributors into thinking declarative builds were supported.
- Added dead code and model complexity to the `TemplateConfig` model.
- Contradicted the industry standard of Dockerfile + language-native dependency
  files (requirements.txt, package.json, etc.).

## Decision
Remove all legacy declarative build fields and the `to_dockerfile()` method:

- Delete fields: `python_packages`, `system_packages`, `node_packages`,
  `commands`, `base`, `copy_files` from the `TemplateConfig` Pydantic model.
- Delete the `to_dockerfile()` method entirely.
- The build pipeline continues to use `Dockerfile` as the single source of
  truth for image construction.

## API Design
N/A — this decision removes unused internal fields. No public API changes.

## Alternatives considered
- **Keep fields but mark as deprecated** — adds warnings without removing dead
  code; users would still be confused by their presence. Rejected.
- **Implement declarative builds** — duplicates Dockerfile functionality with
  inferior flexibility; goes against industry convention. Rejected.

## Dependencies
- `src/easy_sandbox/models/template.py` — `TemplateConfig` model

## Test Strategy
- Verify existing template YAML files parse without the removed fields.
- Ensure `ebx template deploy` still works with Dockerfile-based builds.

## Files changed
- `src/easy_sandbox/models/template.py` — removed legacy fields and `to_dockerfile()`

## Acceptance criteria
- ✅ `TemplateConfig` no longer accepts `python_packages`, `system_packages`,
  `node_packages`, `commands`, `base`, or `copy_files`
- ✅ `to_dockerfile()` method removed
- ✅ All existing template.yaml files load without errors
- ✅ Build pipeline unchanged (still uses Dockerfile)
