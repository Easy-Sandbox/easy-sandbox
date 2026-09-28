# Decision: Discovery API two-layer model (local static + remote authenticated)

Status: proposed
Task: #103, #105, #118

## Problem
The SDK's `Sandbox.list_commands()` already implements basic command discovery
(`api/sandbox.py` returns plain dicts), but there are three gaps: (1) it can only
discover commands declared in local YAML and cannot see Python commands
registered in-project via `@sandbox.register`; (2) zero authentication, zero
gating (one of only two public APIs across the whole repo that skips
`check_capability`); (3) argument entries are missing a `type` field. A clean
two-layer discovery model needs to be defined.

## Decision
Adopt a **two-layer discovery model**: Layer 1 local static discovery + Layer 2
server remote discovery.

### Layer 1: local static discovery (no auth, no server needed)

1. **YAML branch (already implemented)**: `_find_local_template()` in
   `api/capability.py` scans `~/.ebx/templates/**/template.yaml` and parses
   `custom_commands:` + `capabilities:`. Triggered by `resolve_capabilities()`
   during `Sandbox.create()` / `Sandbox.connect()`.
2. **Python command module introspection (gap, filled by @sandbox.register)**:
   the decorator produces `CustomCommand` objects at import time and injects
   them into the same `custom_commands` dict. CLI introspection only needs to
   `import` the user module to discover them.
3. **Permissions**: purely local — only reads the `~/.ebx/templates` directory
   or imports Python modules. Auth is neither required nor desirable.

### Layer 2: server remote discovery (runtime-registered commands)

> **⚠ Key change (2026-09-05)**: the original ADR considered only the platform's
> `GET /templates/{id}` as a remote discovery source and listed "user-built server
> exposing a discovery endpoint" as Rejected. That decision has been overturned.
> The new `easy_sandbox.server` module (see `2026-09-05-sandbox-server-module.md`)
> provides a `GET /commands` discovery endpoint and becomes the primary source
> for Layer 2.

4. **The server module provides a `GET /commands` discovery endpoint**: once
   `easy_sandbox.server` is up, `GET https://{port}-{sandbox_id}.{domain}/commands`
   returns every registered command with its argument schema. This is the
   standard discovery path for runtime-registered commands.
5. **Platform template discovery (auxiliary)**: `GET /templates/{id}` in
   `protocol/template.py` plus `auth_headers = await self._auth.get_headers()`
   at `transport/http.py:84` injects L1 credentials automatically. `ebx template
   info` is a live end-to-end proof point. The wiring gap: `api/capability.py:196`
   is a one-liner `# 3. TODO(Phase2): online fallback`.
6. **Auth reuse**:
   - Platform plane → `AuthProvider.get_headers()` (`ApiKeyAuth` or `AkSkAuth`
     in `transport/auth.py`).
   - envd plane → `EnvdTokenManager.get_headers()` (4 headers).
   - Server module discovery endpoint → shares the same transport auth as
     command execution (`X-Access-Token`).
   - **Not** `NetworkModule.get_access_headers()`. That one is gated by the
     `ports` capability (`api/network.py:63`), and `ports` ∉
     `DEFAULT_CAPABILITIES`. Using it for discovery auth would impose a
     capability prerequisite that most sandboxes lack, **directly violating the
     "discovery permission ⊆ execution permission" principle**.

### Auth principle

7. **Discovery permission ⊆ execution permission**:
   - **Identity-level**: **automatically holds** once Layer 2 is wired. Discovery
     and execution share the same L1 identity; an invalid token causes
     `platform_request`'s `raise_for_status()` to trip first.
   - **Command-level (fine-grained)**: does not hold today and we **cannot**
     unilaterally make it hold. The platform returns a template-level manifest;
     fine-grained filtering requires the server to filter by caller identity
     (outside the protocol client's control). V1 explicitly states "only
     identity-level auth is guaranteed; per-command least-visibility is not".
   - **Current state** (Layer 1 only): zero auth, leak surface confined to local
     `~/.ebx/templates`, direction is safe (discovery broader than execution).

### Current list_commands() defects

8. **Missing argument `type` field**: `CustomCommandArg` (`models/template.py`)
   has no `type`; `list_commands()` outputs args with only `name/required/
   default/description`. To be completed by the M1 milestone of the
   `@sandbox.register` ADR.
9. **Zero auth is the correct design (Layer 1)**: it is a sync method reading a
   local dict without any network call — auth neither should nor can be added.
   Once Layer 2 is wired, `platform_request` handles auth automatically.

### O5 platform custom_commands carriage

10. **Whether `GET /templates/{id}` responses carry `custom_commands` is TBD**.
    `TemplateInfo` in `models/template.py` has no such field, only a generic
    `metadata: dict[str, Any]`. `custom_commands` is a client-side YAML
    extension in this repo, not part of the E2B/FC template model. **Real E2E
    verification is required (#103)**: run `ebx template info <id> --json` and
    inspect whether the response contains `metadata` / `customCommands`. This
    validation directly determines whether M6b (remote discovery wiring) is
    "one function call" or "requires platform-side support".

## API Design
```python
# Layer 1: local discovery (implemented, to be enhanced)
commands = sandbox.list_commands()
# → [{"name": "demo", "description": "...",
#     "args": [{"name": "x", "type": "int", "required": True,
#               "default": None, "description": "..."}]}]

capabilities = sandbox.capabilities
# → frozenset({"shell", "files", "code"})

# Layer 2: remote discovery (to be wired)
# resolve_capabilities() 3rd fallback:
#   template_info = await template_protocol.get(template_id)  # GET /templates/{id}
#   # auth_headers auto-injected by platform_request (Authorization: Bearer)
#   return parse_metadata(template_info.metadata)
```

## Alternatives considered
- **Expose a command-list endpoint on envd** — structurally infeasible. envd's
  endpoint surface is closed and fully enumerated (Process / Filesystem /
  CodeInterpreter / File / Terminal); the `Envd` tag in the E2B OpenAPI only
  covers health / stats / envs; envd's version is controlled by the image.
  Rejected.
- **Use `process.Process/List` as the discovery API** — semantic mismatch: it
  returns "currently running OS processes" (PID-level runtime state), not
  "which named commands are supported and their argument schema". Rejected.
- **User-built server exposing a discovery endpoint** — ~~originally
  Rejected~~. **Adopted (2026-09-05)**: the `easy_sandbox.server` module
  provides a `GET /commands` discovery endpoint, gated by the `ports`
  capability. This becomes the primary way of Layer 2 runtime discovery.
- **Use `NetworkModule.get_access_headers()` for auth** — gated by `ports`
  and returns an empty dict when `secure=False`, which would make discovery
  permission narrower than execution permission. Rejected.

## Dependencies
- `api/capability.py` (`resolve_capabilities`, `_find_local_template`)
- `protocol/template.py` (`TemplateProtocol.get()`)
- `transport/auth.py` (`AuthProvider`, `EnvdTokenManager`)
- `transport/http.py` (`platform_request` auto-injects L1)
- `2026-09-03-sdk-capability-surface.md` (Discovery API definition)
- `2026-09-03-command-source-resolution.md` (resolution order + Phase 2 TODO)
- `2026-09-04-sandbox-register-command.md` (M1 adds the `type` field)
- `2026-09-05-sandbox-server-module.md` (server module provides `GET /commands`)

## Test Strategy
- Layer 1: local YAML discovery, `list_commands()` returns args including `type`.
- Layer 1: commands registered via `@sandbox.register` are visible in
  `list_commands()`.
- Layer 2 (once wired): missing L1 credentials → `resolve_capabilities` falls
  back to `DEFAULT_CAPABILITIES` with a warning, no exception raised.
- Layer 2: with valid credentials, remote template capabilities + custom_commands
  are retrieved.
- Auth: Layer 2 must go through `platform_request` (which auto-injects
  `Authorization: Bearer`); creating a separate `httpx.AsyncClient` is forbidden.

## Acceptance criteria
- `list_commands()` output args include the `type` field.
- Layer 1 local discovery is auth-free and works offline.
- Once Layer 2 is wired, auth is supplied by `AuthProvider.get_headers()` /
  `EnvdTokenManager.get_headers()` (not `get_access_headers`).
- After the O5 verification is completed, update this ADR's Layer 2 status.
- Once implemented, move this ADR from `proposed/` to `implemented/`.

## Evidence
- `.agents/evidence/research/2026-09-04-container-serve-boundary.md` §6.4
- `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`
  (confirms Gateway routeDynamic supports dynamic port routing)
