# Decision: Command Source Resolution (Local Cache → Online Metadata Fallback)

Status: implemented

## Problem
To gate capabilities and dispatch named commands, the SDK/CLI must know a sandbox's template capabilities and `custom_commands`. That definition can live in a locally cached template or be served by the backend. We need a resolution order and a graceful path when the backend endpoint is not yet available.

## Decision
Resolve command/capability definitions with a two-tier order, no separate index:
1. **Local cache first**: read from `~/.ebx/templates` (the installed/cached template's `template.yaml`).
2. **Online metadata fallback (Phase 2)**: `GET /templates/{id}` returns template `metadata` (capabilities + custom_commands). Until the backend endpoint is ready, degrade gracefully to `DEFAULT_CAPABILITIES` and emit a `warn` (no hard failure, no custom commands).
3. **No `index.json`**: template volume is small, so a directory walk of `~/.ebx/templates` is sufficient. We do not introduce or maintain an index file.

## API Design
```python
# Resolution (pseudocode):
def resolve_template_metadata(template_id) -> TemplateMetadata:
    # 1. local cache
    local = load_from(~/.ebx/templates/<...>/template.yaml)
    if local:
        return local
    # 2. online (Phase 2)
    if backend_supports("/templates/{id}"):
        return GET(f"/templates/{template_id}").metadata
    # 3. degrade
    warn("template metadata unavailable; using DEFAULT_CAPABILITIES, no custom commands")
    return TemplateMetadata(capabilities=DEFAULT_CAPABILITIES, custom_commands={})
```
Directory discovery uses a plain walk of `~/.ebx/templates` (no index file).

## Alternatives considered
- **`~/.ebx/templates/index.json`** — Extra file to build, keep in sync, and invalidate; unjustified at current template scale. Rejected; see the capability-model-alternatives rejected ADR.
- **Online-only resolution** — Fails when offline or before the backend endpoint exists.
- **Hard error when metadata missing** — Blocks all usage before Phase 2 backend is ready; we prefer degrade + warn.

## Dependencies
- `~/.ebx/templates` cache layout (see minimal-template-repo ADR)
- Platform API `GET /templates/{id}` (Phase 2)
- `2026-09-03-capability-model.md` (`DEFAULT_CAPABILITIES` fallback)

## Test Strategy
- Local cache hit returns declared capabilities/custom_commands.
- Missing local + backend unavailable → returns `DEFAULT_CAPABILITIES`, empty custom_commands, and warns.
- Directory walk discovers templates without any index file.

## Implementation status
- **Implemented (local-first)**: `resolve_capabilities()` parses the declared
  capabilities / custom_commands from the locally cached `template.yaml` under
  `~/.ebx/templates`; when the local copy is missing it falls back to
  `DEFAULT_CAPABILITIES` and emits a `warn`.
- **Online metadata fallback = deferred to Phase 2**: the online metadata fallback
  via `GET /templates/{id}` is not yet wired in and is explicitly deferred to
  Phase 2 (once the backend endpoint is ready). Only the local-first path is active today.

### Known limitation — platform built-in templates
Platform built-in templates (`base` / `code-interpreter`, etc.) **do not ship a
local `template.yaml`**, so `resolve_capabilities()` falls back to
`DEFAULT_CAPABILITIES = {shell, files, code}`. Their `terminal` / `ports`
capabilities are **unavailable** until the Phase 2 online metadata fallback is
ready; scenarios that need `ports` / `terminal` should use a template that
**explicitly declares those capabilities**.

## Acceptance criteria
- A locally cached `template.yaml` resolves its declared capabilities and custom_commands
- Missing local cache with the backend unavailable falls back to `DEFAULT_CAPABILITIES`, empty custom_commands, and a warning
- Template discovery works via directory walk with no `index.json` present

## Consequences
- Works offline and before the backend metadata endpoint lands.
- No index file to maintain or corrupt.
- Degraded mode is observable via a warning, not a silent behavior change.
