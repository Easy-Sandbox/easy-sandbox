# Decision: Change envd_inject default from True to False

Status: implemented
Implemented: 2026-09-28

## Problem
When `envd_inject=True`, the FC platform's template build compares `copy.image`
(target image) with the source image. If they match, the platform considers the
build a no-op and **skips the entire build step**, leaving the target image
non-functional. Sandboxes created from such templates fail immediately with
`StreamReset` because the expected runtime (envd) was never injected.

This is a platform-side bug: the image-equality short-circuit ignores the fact
that envd injection is a required transformation even when source == target.

## Decision
Set `envd_inject` to `False` by default in `DockerBuilder.deploy()` and
`fc_template.create_template()`. Templates are deployed with raw ACR images
that include their own CMD/entrypoint.

### Consequence
- SandboxServer (mechanism B custom commands) will **not** auto-start via envd.
  Templates that need custom commands must start the server in their Dockerfile
  `CMD` or `ENTRYPOINT`.
- Once the FC platform fixes the image-equality short-circuit, this default can
  be reverted to `True`.

## Alternatives considered
- **Set `copy.image` to a distinct tag** — would require managing an extra image
  tag per deployment and adds complexity. Rejected as a workaround for a
  platform bug.
- **Keep True and document the workaround** — too fragile; users would silently
  hit StreamReset failures. Rejected.

## Files changed
- `src/easy_sandbox/api/fc_template.py` — default `envd_inject=False`
- `src/easy_sandbox/api/docker_builder.py` — default `envd_inject=False`
- `src/easy_sandbox/cli/commands/template.py` — CLI `--envd-inject` flag default

## Acceptance criteria
- ✅ `ebx template deploy` uses `envd_inject=False` by default
- ✅ Templates deploy successfully and sandboxes start without StreamReset
- ✅ `--envd-inject` flag still allows explicit opt-in
