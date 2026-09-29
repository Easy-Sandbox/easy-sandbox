# Decision: Enforce 120s minimum timeout for sandbox creation

Status: implemented
Implemented: 2026-09-28

## Problem
Users who set `http_timeout = 30` in `~/.ebx/config.toml` (a reasonable value
for most API calls) unknowingly override the cold-start protection on sandbox
creation. FC sandbox cold starts can take 60–90s for image pulls, so a 30s
timeout causes `ebx create` to fail silently with a generic timeout error,
leaving users confused about whether the template or the platform is broken.

## Decision
Apply a **floor** of 120 seconds to the HTTP timeout used specifically for
sandbox creation requests:

```python
create_timeout = max(configured_timeout, 120.0)
```

- The user's `http_timeout` config is respected for all other operations.
- For `create` only, the effective timeout is `max(user_value, 120)`.
- If a user explicitly passes `--timeout 180`, that value is used (it exceeds
  the floor).

### Rationale for 120s
- Observed cold starts: 60–90s (image pull + container init).
- 120s provides ~30s headroom above worst-case observed cold starts.
- Matches the platform's own gateway timeout window.

## Alternatives considered
- **Warn but don't override** — users would still hit the timeout and need to
  manually retry with a longer value. Poor UX. Rejected.
- **Set a higher floor (300s)** — unnecessarily long for warm starts; users
  would perceive the CLI as sluggish if creation fails for other reasons.
  Rejected.

## Files changed
- `src/easy_sandbox/cli/commands/sandbox.py` — `create` command timeout logic

## Acceptance criteria
- ✅ `ebx create` with `http_timeout=30` uses 120s for the creation request
- ✅ `ebx create --timeout 180` uses 180s (exceeds floor)
- ✅ Other commands still respect the configured `http_timeout` as-is
