# Decision: Command Source Resolution (Local Cache → Online Metadata Fallback)

Status: implemented

## Problem
To gate capabilities and dispatch named commands, the SDK/CLI must know a sandbox's template capabilities and `custom_commands`. That definition can live in a locally cached template or be served by the backend. We need a resolution order and a graceful path when the backend endpoint is not yet available.

## Decision
Resolve command/capability definitions with a two-tier order, no separate index:
1. **Local cache first**: read from `~/.sbox/templates` (the installed/cached template's `template.yaml`).
2. **Online metadata fallback (Phase 2)**: `GET /templates/{id}` returns template `metadata` (capabilities + custom_commands). Until the backend endpoint is ready, degrade gracefully to `DEFAULT_CAPABILITIES` and emit a `warn` (no hard failure, no custom commands).
3. **No `index.json`**: template volume is small, so a directory walk of `~/.sbox/templates` is sufficient. We do not introduce or maintain an index file.

## API Design
```python
# Resolution (pseudocode):
def resolve_template_metadata(template_id) -> TemplateMetadata:
    # 1. local cache
    local = load_from(~/.sbox/templates/<...>/template.yaml)
    if local:
        return local
    # 2. online (Phase 2)
    if backend_supports("/templates/{id}"):
        return GET(f"/templates/{template_id}").metadata
    # 3. degrade
    warn("template metadata unavailable; using DEFAULT_CAPABILITIES, no custom commands")
    return TemplateMetadata(capabilities=DEFAULT_CAPABILITIES, custom_commands={})
```
Directory discovery uses a plain walk of `~/.sbox/templates` (no index file).

## Alternatives considered
- **`~/.sbox/templates/index.json`** — Extra file to build, keep in sync, and invalidate; unjustified at current template scale. Rejected; see the capability-model-alternatives rejected ADR.
- **Online-only resolution** — Fails when offline or before the backend endpoint exists.
- **Hard error when metadata missing** — Blocks all usage before Phase 2 backend is ready; we prefer degrade + warn.

## Dependencies
- `~/.sbox/templates` cache layout (see minimal-template-repo ADR)
- Platform API `GET /templates/{id}` (Phase 2)
- `2026-09-03-capability-model.md` (`DEFAULT_CAPABILITIES` fallback)

## Test Strategy
- Local cache hit returns declared capabilities/custom_commands.
- Missing local + backend unavailable → returns `DEFAULT_CAPABILITIES`, empty custom_commands, and warns.
- Directory walk discovers templates without any index file.

## Implementation status
- **已实现（本地优先）**：`resolve_capabilities()` 从 `~/.sbox/templates` 下本地缓存的
  `template.yaml` 解析声明的 capabilities / custom_commands；本地缺失时回落
  `DEFAULT_CAPABILITIES` 并打 `warn`。
- **线上 metadata 兜底 = Phase 2 延后**：`GET /templates/{id}` 的在线元数据兜底尚未接入，
  明确延后到 Phase 2（等后端 endpoint 就绪）。当前仅本地优先链路生效。

### 已知限制 — 平台内置模板
平台内置模板（`base` / `code-interpreter` 等）**不带本地 `template.yaml`**，因此
`resolve_capabilities()` 回落到 `DEFAULT_CAPABILITIES = {shell, files, code}`。它们的
`terminal` / `ports` 能力在 Phase 2 线上 metadata 兜底就绪前**不可用**；需要 `ports` /
`terminal` 的场景应改用**显式声明这些能力**的模板。

## Consequences
- Works offline and before the backend metadata endpoint lands.
- No index file to maintain or corrupt.
- Degraded mode is observable via a warning, not a silent behavior change.
