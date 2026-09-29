# Decision: Allow template.yaml name to differ from directory name for reserved names

Status: implemented
Implemented: 2026-09-28

## Problem
The FC platform reserves certain template names (notably `codex` and
`openclaw`). Attempting to create a template with these names returns a platform
error. However, the community template directories are already established as
`codex/` and `openclaw/` and renaming them would break existing references.

## Decision
Allow a template's `template.yaml` `name` field to differ from its directory
name **when the directory name is platform-reserved**:

| Directory name | `template.yaml` name | Reason                      |
|----------------|----------------------|-----------------------------|
| `codex/`       | `openai-codex`       | "codex" is reserved by FC   |
| `openclaw/`    | `openclaw-agent`     | "openclaw" is reserved by FC|

All other templates continue to use matching directory and YAML names.

### Override mapping
A `_PLATFORM_NAME_OVERRIDES` dict in test helpers maps directory names to their
YAML names for validation:

```python
_PLATFORM_NAME_OVERRIDES = {
    "codex": "openai-codex",
    "openclaw": "openclaw-agent",
}
```

## Alternatives considered
- **Rename the directories** — breaks existing documentation, examples, and
  user expectations. Rejected.
- **Use a prefix convention (e.g., `fc-codex`)** — arbitrary naming convention
  adds cognitive load. Rejected.

## Files changed
- `examples/templates/codex/template.yaml` — `name: openai-codex`
- `examples/templates/openclaw/template.yaml` — `name: openclaw-agent`
- `tests/test_templates/test_template_catalog.py` — `_PLATFORM_NAME_OVERRIDES`
- `tests/test_templates/test_local_install.py` — `_PLATFORM_NAME_OVERRIDES`

## Acceptance criteria
- ✅ `ebx template deploy codex` succeeds with name `openai-codex`
- ✅ Template catalog tests validate the override mapping
- ✅ Non-reserved templates still require directory == YAML name match
