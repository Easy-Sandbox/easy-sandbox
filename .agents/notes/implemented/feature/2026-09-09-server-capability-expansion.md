# Decision: Full expansion of Server module capabilities (6 → 42 endpoints, 8 capability groups)

Status: implemented
Implemented: 2026-09-21

## Problem
The `easy_sandbox.server` module previously exposed only 6 basic endpoints
(health, commands, upload, download, shell, run command), giving limited
capability coverage. To make Server a complete in-sandbox service layer, its
coverage needed to expand to include filesystem CRUD, process management, PTY
terminal, streaming output, system information, environment-variable management,
Git operations, Code Interpreter, and browser automation — while keeping the
architecture controllable: endpoints must be toggleable by capability group so
that unneeded capabilities do not expand the attack surface.

## Decision
Introduce a declarative **RouteTable** + **CapabilityGroup** capability toggle
mechanism, expanding endpoints from 6 to 42 and organizing them into 8 capability
groups.

### 8 capability groups

| Group | Endpoints | Examples | Default state |
|-------|-----------|----------|---------------|
| `CORE` | 2 | `/health`, `/capabilities` | Always enabled, cannot be disabled |
| `COMMANDS` | 2 | `GET /commands`, `POST /commands/{name}` | Enabled |
| `FILE_OPS` | 11 | `/files/list`, `/files/stat`, `/files/mkdir`, `DELETE /files`, `/files/move`, `/files/search`, `/upload`, `/download`, `/files/upload-stream`, `/files/download-stream`, `/files/archive` | Enabled |
| `PROCESS` | 6 | `/shell`, `/shell/stream`, `/process/start`, `/process/list`, `/process/{pid}`, `/process/{pid}/signal` | Enabled |
| `SYSTEM` | 6 | `/system/info`, `GET /env`, `POST /env`, `/ports`, `/packages`, `/system/metrics` | Enabled |
| `TERMINAL` | 3 + WS | `POST /pty/sessions`, `GET /pty/sessions`, `DELETE /pty/sessions/{id}` + WebSocket PTY | Enabled |
| `DEV_TOOLS` | 3 | `/code/run`, `/git/status`, `/git/diff` | Disabled (opt-in) |
| `BROWSER` | 8 | `/browser/navigate`, `/browser/screenshot`, `/browser/content`, `/browser/click`, `/browser/type`, `/browser/evaluate`, `/browser/pdf`, `/browser/console` | Disabled (opt-in) |

### Architectural improvements

1. **Declarative RouteTable**: each route is defined as a `RouteInfo` record with
   `method`, `path pattern` (`{param}` placeholders compiled to regex), handler,
   CapabilityGroup, `auth_required`, `streaming`, and other attributes. At
   startup, routes are auto-registered based on the enabled CapabilityGroups.
   This replaces the current hardcoded if/elif branches for `handle_*` functions
   in `do_GET`/`do_POST`.

2. **Everything except `/health` is toggleable**: `/health` and `/capabilities`
   belong to the CORE group and are always available and non-disable-able. All
   other endpoints can be enabled/disabled through CapabilityGroup. At runtime,
   this can be configured via the `EBX_SERVER_DISABLED_GROUPS` environment
   variable.

3. **Hidden commands (hidden)**: `RegisteredCommand` supports a `hidden=True`
   attribute; hidden commands do not appear in the `GET /commands` discovery
   endpoint but can still be invoked via `POST /commands/{name}`.

4. **Route files split by domain**: route handlers are split into standalone
   modules by domain:
   - `routes.py` — core routes (health/commands/upload/download/shell)
   - `routes_files.py` — FILE_OPS group (9 endpoints)
   - `routes_process.py` — PROCESS group (5 endpoints)
   - `routes_system.py` — SYSTEM group + CORE/capabilities (7 endpoints)
   - `routes_pty.py` — TERMINAL group (3 REST + WebSocket PTY)
   - `routes_browser.py` — BROWSER group (8 endpoints, Playwright-backed)
   - `routes_devtools.py` — DEV_TOOLS group (3 endpoints)

5. **WebSocket PTY terminal**: uses the Python stdlib `pty` module plus the
   existing core dependency `websockets` (already required by the SDK) to
   provide an interactive terminal capability. The REST API manages sessions
   (create/list/delete) and WebSocket carries I/O. Supports input/resize/signal
   message types.

6. **Streaming shell (SSE)**: `POST /shell/stream` returns a Server-Sent Events
   stream, delivering the shell command's stdout/stderr in real time and
   emitting an `exit` event when the command exits.

7. **Browser automation (BROWSER group)**: 8 Playwright-backed endpoints
   supporting page navigation, screenshots, DOM-content retrieval, element
   clicks, text input, JavaScript execution, PDF generation, and console-log
   collection. Playwright is lazy-loaded and returns 503 when not installed.

### File safety

- `_resolve_safe_path()` prevents path traversal; all file-op paths are confined
  under `EBX_SERVER_BASE_DIR` (default `/home/user`).
- Sensitive environment-variable fields (TOKEN/SECRET/KEY/PASSWORD) are masked automatically.
- Protected variables (PATH/HOME/USER/SHELL) cannot be overridden via `POST /env`.
- Process signals are restricted to an allow list (SIGINT/SIGKILL/SIGTERM, etc.);
  signals to PID 1 or the server's own process are rejected.

## API Design
```python
# startup configuration
server = SandboxServer(
    port=8080,
    enabled_groups={"core", "commands", "file_ops", "process", "system", "terminal"},
    # dev_tools and browser must be explicitly enabled
)
```

## Alternatives considered
- **Keep the if/elif hardcoded route dispatch** — an if/elif chain over 42
  endpoints is extremely unreadable, and adding endpoints requires modifying the
  core dispatch logic. Rejected.
- **Switch to the FastAPI framework** — introduces a third-party dependency,
  violating the server module's stdlib-only principle. Rejected.
- **Share the same port between PTY and HTTP (HTTP Upgrade)** — `http.server`
  does not support WebSocket upgrade, requiring extra protocol-upgrade logic.
  Using the `websockets` library on a separate port for PTY is simpler. Rejected
  (the same-port scheme).
- **Trie-based router** — the benefit of a trie is limited at 42 endpoints;
  regex matching + dict lookup is sufficient. Rejected (over-engineering).

## Dependencies
- `server/registry.py` (the existing command registry)
- `server/routes.py` (existing route handlers, now split)
- `server/app.py` (`SandboxServer` accepts an `enabled_groups` argument)
- `server/types.py` (`RouteEntry`, `RouteTable` definitions)
- `websockets` (existing core SDK dependency, used for the PTY terminal)
- `2026-09-09-server-command-registry.md` (CommandRegistry decoupling)
- `2026-09-05-sandbox-server-module.md` (overall server-module architecture)

## Test Strategy
- RouteTable: registration → match → 404 on no match; route reachability changes
  after enabling/disabling a group.
- file_ops: write→read round-trip consistency; list recursive/non-recursive;
  delete then read errors; mkdir is idempotent.
- process: after start, list contains the PID; after kill, the process is gone.
- terminal: WebSocket connect → send command → receive output → disconnect.
- system: info returns correct OS/arch; env/set then env contains the new variable.
- browser: navigate → screenshot → content chained operations.
- Capability toggles: after disabling file_ops, `/files/read` returns 403/404.
- Hidden commands: `GET /commands` does not include hidden commands, but
  `POST /commands/{name}` can invoke them.

## Acceptance criteria
- ✅ The RouteTable + CapabilityGroup framework replaces the if/elif hardcoding.
- ✅ 8 capability groups (including BROWSER), 42 endpoints, all toggleable except CORE.
- ✅ The WebSocket PTY terminal uses the `websockets` core dependency; no new third-party package is introduced.
- ✅ The 8 Playwright endpoints of the BROWSER group are implemented.
- ✅ Routes are split into 7 module files by domain.
- ✅ This ADR has been moved from `proposed/` to `implemented/`.

## Evidence
- Source: all route modules under the `src/easy_sandbox/server/` directory.
- Test coverage: corresponding test files under the `tests/test_server/` directory.
