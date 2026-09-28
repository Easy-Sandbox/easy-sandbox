# Decision: Server SDK 42-endpoint capability audit and retention decision

Status: implemented
Implemented: 2026-09-23

## Problem
The Server module was expanded from 6 to 42 endpoints (see
`2026-09-09-server-capability-expansion.md`), covering 8 capability groups. After
the expansion, a systematic audit was required to confirm:
1. Whether each endpoint has a clear use case and a real caller.
2. Whether the default enable/disable policy for the 8 capability groups is reasonable.
3. Whether any endpoints are redundant and can be merged or should be removed.

This ADR records the audit conclusions and retention decisions; it does not
repeat the design details in `server-capability-expansion.md`.

## Decision
**All 42 endpoints are retained.** Audit conclusions are as follows:

### Capability-group decisions

| Group | Endpoints | Decision | Rationale |
|-------|-----------|----------|-----------|
| CORE | 2 | Always enabled, not disable-able | `/health` and `/capabilities` are infrastructure endpoints |
| COMMANDS | 2 | Enabled by default | The core WIRE CONTRACT of `@sandbox.register` |
| FILE_OPS | 11 | Enabled by default | Backend for the CLI `sandbox files` subgroup; covers full CRUD + search + archive |
| PROCESS | 6 | Enabled by default | Backend for the CLI `sandbox process` subgroup; includes SSE streaming shell |
| SYSTEM | 6 | Enabled by default | Backend for the CLI `sandbox system` subgroup; includes env management and metrics |
| TERMINAL | 3 + WS | Enabled by default | The PTY terminal is a core capability for interactive debugging |
| DEV_TOOLS | 3 | **Disabled by default** | code/run and git operations are not general-purpose; opt-in |
| BROWSER | 8 | **Disabled by default** | Heavy Playwright dependency; only the browser-automation template needs it |

### Security decisions

- All file-op paths are protected by `_resolve_safe_path()` and confined under
  `EBX_SERVER_BASE_DIR` (default `/home/user`).
- Sensitive env-var fields are masked automatically (TOKEN/SECRET/KEY/PASSWORD).
- Protected variables (PATH/HOME/USER/SHELL) cannot be overridden.
- Process signals are restricted to a safe list; signals to PID 1 are refused.

### No redundant endpoints

- `/upload` and `/files/upload-stream` look similar but use different protocols:
  the former is simple multipart upload, the latter is chunked streaming upload
  (for large files); both are kept.
- `/shell` and `/shell/stream` correspond to blocking execution and SSE streaming
  execution respectively; their scenarios differ, and both are kept.

## API Design
N/A — this decision does not involve API changes. It is an audit/retention
decision on the existing 42 endpoints; endpoint contracts remain as defined in
`2026-09-09-server-capability-expansion.md`.

## Alternatives considered
- **Remove the BROWSER group to reduce code size** — browser automation is a
  differentiating capability (the browser-automation template depends on it);
  disabling it by default already isolates the risk. Rejected.
- **Merge `/upload` and `/files/upload-stream`** — would break the existing WIRE
  CONTRACT; multipart suits small files and streaming suits large files.
  Rejected.
- **Enable DEV_TOOLS by default** — the security isolation of code/run is not yet
  robust (arbitrary code execution); keep it disabled by default. Rejected.

## Dependencies
- `2026-09-09-server-capability-expansion.md` (the 42-endpoint expansion decision;
  this ADR only adds the audit-decision conclusions)
- `src/easy_sandbox/server/` (all route modules)

## Test Strategy
- Enable/disable each capability group: after disabling, endpoints return 404;
  after enabling, endpoints are reachable normally.
- Security: path-traversal attacks are intercepted by `_resolve_safe_path()`.
- Signal safety: signals to PID 1 are refused.

## Acceptance criteria
- ✅ All 42 endpoints are retained; no redundant removals.
- ✅ DEV_TOOLS and BROWSER are disabled by default; the rest are enabled by default.
- ✅ Security decisions are enforced in code (path protection, env masking, signal restriction).
- ✅ The `EBX_SERVER_DISABLED_GROUPS` environment variable configures capability groups at runtime.
