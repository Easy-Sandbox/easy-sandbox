# Container-Side HTTP Server API Reference

> Complete API reference for the container-side HTTP Server (`easy_sandbox.server`).
>
> All endpoint methods, paths, parameters, request body fields, and response formats in this document
> are read directly from the implementation code under `src/easy_sandbox/server/`, staying consistent
> with the source code. Where the code does not explicitly define certain behavior, this document
> faithfully notes it rather than speculating.

---

## 1. Overview

### 1.1 Server Positioning

The container-side HTTP Server is a lightweight HTTP service that relies **solely on the Python standard library** (stdlib-only, zero third-party dependencies). It runs inside a Sandbox container and exposes file, process, terminal, system information, development tools, and browser automation capabilities to external consumers (SDK / CLI / Agent).

- Built on [`http.server.ThreadingHTTPServer`](../../../src/easy_sandbox/server/app.py) with a custom `BaseHTTPRequestHandler` subclass.
- Request dispatching is handled by a data-driven [`RouteTable`](../../../src/easy_sandbox/server/router.py), not a hard-coded `if/elif` chain.
- Each route belongs to a **Capability Group** that can be enabled/disabled as a whole.
- Request/response objects are stdlib `dataclass`es ([`types.py`](../../../src/easy_sandbox/server/types.py)), not Pydantic models.

> Note: The "capability groups" described here are **runtime switches in the Server-side RouteTable**, which is an independent mechanism from `STANDARD_CAPABILITIES` in the SDK template layer (`models/template.py` / `api/capability.py`). Do not confuse the two.

### 1.2 Startup

**Convenience function** —
[`start()`](../../../src/easy_sandbox/server/app.py#L320-L334):

```python
from easy_sandbox.server import start

start(9000)  # Listen on 0.0.0.0:9000, blocking
```

**Class interface** —
[`SandboxServer`](../../../src/easy_sandbox/server/app.py#L215-L317) (accepts custom `registry` / `route_table`):

```python
from easy_sandbox.server import SandboxServer, CommandRegistry

registry = CommandRegistry()
# ... register custom commands ...
server = SandboxServer(host="0.0.0.0", registry=registry)
server.serve(port=9000)  # Blocks until KeyboardInterrupt / shutdown()
```

`serve()` calls `registry.freeze()` at startup to freeze the command registry, then begins accepting requests.

### 1.3 Dual-Port Architecture

The Server uses two ports:

| Port | Protocol | Purpose | Default | Override Variable |
|------|----------|---------|---------|-------------------|
| HTTP Port | HTTP/1.1 | All REST / SSE endpoints | `9000` (`serve(port=...)` parameter) | — |
| PTY Port | WebSocket | Interactive terminal (PTY) | `9001` | `EBX_PTY_PORT` |

The PTY WebSocket service starts in a background daemon thread only when the `TERMINAL` capability group is enabled (see
[`SandboxServer.serve`](../../../src/easy_sandbox/server/app.py#L254-L280)). `TERMINAL` is enabled by default, so the PTY service starts alongside the main service by default.

---

## 2. Capability Groups

Capability groups are defined in the enum
[`CapabilityGroup`](../../../src/easy_sandbox/server/router.py#L50-L64),
totaling **8 groups**. Each group is a set of endpoints that can be enabled/disabled as a unit.

| Capability Group | Enum Value | Endpoints | Default State | Description |
|------------------|------------|:---------:|:-------------:|-------------|
| `CORE` | `core` | 2 | **Always enabled** (cannot be disabled) | Health check, capability query |
| `COMMANDS` | `commands` | 2 | Enabled | Custom command listing and execution |
| `FILE_OPS` | `file_ops` | 11 | Enabled | File upload/download/listing/search/archive etc. |
| `PROCESS` | `process` | 6 | Enabled | Shell execution, SSE streaming shell, background process management |
| `TERMINAL` | `terminal` | 3 REST + WS | Enabled | PTY session management + WebSocket interactive terminal |
| `SYSTEM` | `system` | 6 | Enabled | System info, environment variables, ports, packages, metrics |
| `DEV_TOOLS` | `dev_tools` | 3 | **Disabled by default** | Code execution, Git inspection |
| `BROWSER` | `browser` | 8 | **Disabled by default** | Playwright browser automation |

### 2.1 Default Disabled Set

From the definition in [`router.py`](../../../src/easy_sandbox/server/router.py#L68):

```python
_DEFAULT_DISABLED = frozenset({CapabilityGroup.DEV_TOOLS, CapabilityGroup.BROWSER})
```

> **Accuracy note**: Only `DEV_TOOLS` and `BROWSER` are disabled by default in the source code. `TERMINAL` **is enabled by default** (thus the PTY WebSocket service starts by default). The statement "TERMINAL is disabled by default" in the task outline does not match the current code; this document follows the code.

`CORE` is always enabled; calling `disable_group(CapabilityGroup.CORE)` raises `ValueError`;
`enable_group(CapabilityGroup.CORE)` is a no-op.

### 2.2 Environment Variable Control

`RouteTable` reads the environment variable
[`EBX_SERVER_DISABLED_GROUPS`](../../../src/easy_sandbox/server/router.py#L112-L126)
at instantiation time. Its value is a comma-separated list of capability group enum values (e.g., `system,process`), used to additionally disable groups at process startup:

```bash
# Disable system and process groups in addition to the defaults (dev_tools, browser)
export EBX_SERVER_DISABLED_GROUPS="system,process"
```

Parsing rules:

- Each item is `strip()`-ed then matched against enum values; unrecognized values are silently ignored.
- `core` is explicitly skipped (CORE cannot be disabled via environment variable).

### 2.3 Runtime Toggle API

`RouteTable` provides runtime switches (see
[`router.py`](../../../src/easy_sandbox/server/router.py#L240-L265)):

| Method | Description |
|--------|-------------|
| `enable_group(group)` | Enable a capability group (no-op for `CORE`) |
| `disable_group(group)` | Disable a capability group (raises `ValueError` for `CORE`) |
| `is_group_enabled(group) -> bool` | Query whether a capability group is enabled |
| `list_groups() -> dict[str, bool]` | Return `{enum_value: is_enabled}` mapping |

Template author example (from
[`python-hello/commands.py`](../../../examples/templates/python-hello/commands.py#L23-L26)):

```python
from easy_sandbox.server import CapabilityGroup, default_table

table = default_table()
table.enable_group(CapabilityGroup.FILE_OPS)
table.enable_group(CapabilityGroup.PROCESS)
table.enable_group(CapabilityGroup.SYSTEM)
```

> Compatibility layer: The legacy API `enable_builtin("upload"|"download"|"shell")` /
> `disable_builtin(...)` is still available, internally mapping to corresponding capability groups
> (`upload`/`download` → `FILE_OPS`, `shell` → `PROCESS`), see
> [`_compat.py`](../../../src/easy_sandbox/server/_compat.py#L30-L34).

---

## 3. Authentication

Authentication logic resides in
[`SandboxRequestHandler._check_auth`](../../../src/easy_sandbox/server/app.py#L66-L81).

- The Server reads the environment variable `EBX_SERVER_TOKEN` at startup (`os.environ.get("EBX_SERVER_TOKEN") or None`).
- **Token not set**: `auth_token is None`, treated as local mode — **all requests bypass authentication**.
- **Token set**: Requests must include an `X-Access-Token` header, compared against the configured value using `hmac.compare_digest` (constant-time comparison).
  - Missing or mismatched → `401`, response body `{"error": "unauthorized", "type": "AuthError"}`.

### 3.1 Auth-Exempt Endpoints

The following routes are registered with `auth_required=False`, so they do not require authentication even when a token is configured:

| Endpoint | Capability Group | Source |
|----------|------------------|--------|
| `GET /health` | `CORE` | [routes.py#L442-L445](../../../src/easy_sandbox/server/routes.py#L442-L445) |
| `GET /capabilities` | `CORE` | [routes_system.py#L411-L414](../../../src/easy_sandbox/server/routes_system.py#L411-L414) |

Example request with token:

```bash
curl -H "X-Access-Token: $EBX_SERVER_TOKEN" http://localhost:9000/system/info
```

### 3.2 Dispatch Order

The processing order in [`_dispatch`](../../../src/easy_sandbox/server/app.py#L134-L179):

1. Path normalization: `urlparse` followed by `path.rstrip("/") or "/"` (strip trailing slash).
2. `RouteTable.match(method, path)`: no match → `404 {"error": "Not found: <path>", "type": "ValueError"}`.
3. If `route.auth_required` and authentication fails → `401` (this step occurs **before** the capability group gate).
4. Capability group gate: if `route.group` is disabled → `404 {"error": "Built-in route '<name>' is disabled", "type": "ValueError"}`.
5. For `POST/PUT/PATCH/DELETE`, read JSON request body (parse failure → `400`).
6. Invoke handler; `streaming=True` takes the SSE dispatch path.

> Only `do_GET` / `do_POST` / `do_DELETE` are implemented. `PUT` / `PATCH` have no corresponding entry points; stdlib returns `501`.

---

## 3.3 Request/Response Data Models

Route handler inputs and outputs use stdlib `dataclass` definitions (not Pydantic), located in
[`types.py`](../../../src/easy_sandbox/server/types.py).

#### `ServerRequest`

The request object passed to handlers after parsing by `_dispatch`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `method` | `str` | — | HTTP method (uppercase, e.g., `"GET"`, `"POST"`) |
| `path` | `str` | — | URL path (e.g., `"/commands/greet"`) |
| `query` | `dict[str, list[str]]` | `{}` | Query parameters, each key maps to a value list (supports duplicate keys) |
| `headers` | `dict[str, str]` | `{}` | Request headers (single-value) |
| `body` | `dict[str, Any] \| None` | `None` | Parsed JSON request body; `None` when absent or non-JSON |
| `path_params` | `dict[str, str]` | `{}` | Path parameters extracted from `{param}` route templates |
| `context` | `dict[str, Any]` | `{}` | Request context injected by the dispatcher (e.g., `CommandRegistry` under the `"registry"` key) |

#### `ServerResponse`

Return type for normal (non-streaming) handlers.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | `int` | — | HTTP status code (e.g., `200`, `404`) |
| `body` | `dict[str, Any]` | `{}` | JSON-serializable response body |
| `headers` | `dict[str, str]` | `{}` | Additional response headers |

Factory methods:

| Method | Returns | Description |
|--------|---------|-------------|
| `ServerResponse.ok(data)` | `ServerResponse(200, data)` | Success response |
| `ServerResponse.error(status, message, error_type="ValueError")` | `ServerResponse(status, {"error": message, "type": error_type})` | Error response |

#### `SSEResponse`

Return type for SSE streaming handlers (`streaming=True` routes).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | `int` | `200` | HTTP status code |
| `headers` | `dict[str, str]` | `{"Content-Type": "text/event-stream"}` | Response headers |
| `event_iterator` | `Any` | `None` | Iterator yielding SSE event payloads (`str` or `bytes`), flushed to the client one by one |

---

## 4. Endpoint Reference

Response bodies are uniformly JSON. Success generally returns `200`; error bodies follow the format
`{"error": "<message>", "type": "<ExceptionName>"}` (see
[`ServerResponse.error`](../../../src/easy_sandbox/server/types.py#L70-L88)).

### 4.1 CORE (2)

#### `GET /health`

Health check, always returns `200`, no authentication required.

Response:

```json
{"status": "ok"}
```

```bash
curl http://localhost:9000/health
```

#### `GET /capabilities`

Lists all capability groups and their enabled status, no authentication required.

Response (`groups` is `{enum_value: bool}`):

```json
{
  "groups": {
    "core": true,
    "commands": true,
    "file_ops": true,
    "process": true,
    "terminal": true,
    "system": true,
    "dev_tools": false,
    "browser": false
  }
}
```

---

### 4.2 COMMANDS (2)

#### `GET /commands`

Lists **visible** (non-`hidden`) commands in the registry along with their parameter definitions.

Response:

```json
{
  "commands": [
    {
      "name": "hello",
      "args": [
        {"name": "name", "type": "string", "required": false, "default": "World", "description": ""}
      ]
    }
  ]
}
```

Parameter fields from
[`handle_list_commands`](../../../src/easy_sandbox/server/routes.py#L96-L119):
`name` / `type` / `required` / `default` / `description`.

#### `POST /commands/{name}`

Execute a registered command. The request body contains the command's keyword arguments (kwargs).

Request body example:

```json
{"name": "Qoder"}
```

Processing flow (see
[`handle_run_command`](../../../src/easy_sandbox/server/routes.py#L229-L269)):

1. Command does not exist → `404 {"error": "Unknown command '<name>'; available: ...", "type": "ValueError"}`.
2. Parameter validation/type coercion failure → `400` (missing required parameter, unknown parameter, type conversion failure).
3. Command function raises exception → `500 {"error": "...", "type": "<ExceptionName>"}`.
4. Success → `200 {"result": <return_value>}`.

Type coercion supports `string` / `integer` / `float` / `boolean`; boolean accepts
`true/false/yes/no/1/0` (see
[`_parse_boolean`](../../../src/easy_sandbox/server/routes.py#L130-L152)).

```bash
curl -X POST http://localhost:9000/commands/hello \
  -H "Content-Type: application/json" \
  -d '{"name": "Qoder"}'
# -> {"result": "Hello, Qoder!"}
```

---

### 4.3 FILE_OPS (11)

Includes 2 "legacy" upload/download endpoints (`/upload`, `/download`, registered in
[`routes.py`](../../../src/easy_sandbox/server/routes.py#L454-L461)) and 9 extended file operation endpoints (registered in
[`routes_files.py`](../../../src/easy_sandbox/server/routes_files.py#L528-L565)). All paths go through
[`_resolve_safe_path`](../../../src/easy_sandbox/server/routes.py#L58-L84) path traversal protection (see §8.1).

#### `POST /upload`

Writes base64-encoded content to a local file.

Request body:

```json
{"path": "/home/user/file.txt", "content_base64": "<base64>"}
```

Response: `{"path": "<resolved_absolute_path>", "bytes": <byte_count>}`.

Errors: missing/invalid `path` or `content_base64` → `400`; invalid base64 → `400`; write failure → `500`;
path escaping base directory → `400 {"error": "Path escapes base directory", ...}`.

#### `GET /download?path=...`

Reads a file and returns base64 content.

Response:

```json
{"path": "/home/user/file.txt", "content_base64": "<base64>"}
```

Errors: missing `path` → `400`; file not found → `404 {"type": "FileNotFoundError"}`; read failure → `500`.

#### `GET /files/list?path=...`

Lists directory contents. Query parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `path` | (required) | Directory path |
| `recursive` | `false` | `true/yes/1` for recursive; max recursive depth `3` (`_DEFAULT_MAX_DEPTH`) |
| `max_entries` | `1000` | Upper limit clamped to `1000` (`_DEFAULT_MAX_ENTRIES`) |

Response:

```json
{
  "entries": [
    {"name": "a.txt", "type": "file", "size": 12, "modified": "2026-09-21T00:00:00+00:00"}
  ]
}
```

`type` is `file` or `directory`; `modified` is ISO 8601 UTC. Symlinks pointing outside the base directory are skipped.
Directory not found → `404`.

#### `GET /files/stat?path=...`

Returns metadata for a single file/directory. When the file does not exist, still returns `200` with `exists=false`:

```json
{"name": "x", "path": "/home/user/x", "type": "unknown", "size": 0, "permissions": "", "modified": "", "exists": false}
```

When present: `type` is `file`/`directory`/`symlink`, `permissions` is the last three octal digits (e.g., `"644"`),
`modified` is ISO 8601 UTC, `exists=true`.

#### `POST /files/mkdir`

Creates a directory (including parents, `exist_ok=True`). Request body `{"path": "..."}`;
success `{"path": "...", "created": true}`.

#### `DELETE /files?path=...`

Deletes a file or directory (directories use `shutil.rmtree`). Success `{"path": "...", "deleted": true}`;
not found → `404`.

#### `POST /files/move`

Move/rename. Request body:

```json
{"source": "/home/user/a.txt", "destination": "/home/user/b.txt"}
```

Response `{"source": "...", "destination": "..."}`; source not found → `404`; `source`/`destination`
path escape errors are prefixed with `source: ` / `destination: ` respectively.

#### `POST /files/search`

Searches files by glob pattern (`fnmatch`). Request body:

| Field | Default | Description |
|-------|---------|-------------|
| `path` | (required) | Search root directory |
| `pattern` | (required) | Glob pattern, e.g., `*.py` |
| `max_depth` | `5` (`_SEARCH_MAX_DEPTH`) | Maximum recursion depth |
| `max_results` | `100` (`_SEARCH_MAX_RESULTS`) | Maximum result count |

Timeout upper limit `10` seconds (`_SEARCH_TIMEOUT_SECONDS`, implemented via a timer thread). Response:

```json
{"results": [{"name": "app.py", "path": "/home/user/app.py"}], "timed_out": false}
```

#### `POST /files/upload-stream`

Chunked (64 KB) base64 upload with size limit. Request body
`{"path": "...", "content_base64": "..."}`. Exceeding the limit (default 100 MB, overridable via
`EBX_MAX_UPLOAD_SIZE`) → `413`. Success `{"path": "...", "bytes": N}`.

#### `GET /files/download-stream?path=...`

Chunked read returning base64, with an additional `bytes` field:

```json
{"path": "...", "content_base64": "<base64>", "bytes": 1024}
```

File not found → `404`.

#### `POST /files/archive`

Archives multiple paths and returns base64. Request body:

```json
{"paths": ["/home/user/dir", "/home/user/a.txt"], "format": "tar.gz"}
```

`format` supports `tar.gz` (default) or `zip`; other values → `400`. Limits: total file count
`10000` (`_ARCHIVE_MAX_FILES`), archive size `100 MB` (`_ARCHIVE_MAX_SIZE`, exceeding → `413`).
Path not found → `404`. Response:

```json
{"content_base64": "<base64>", "format": "tar.gz", "bytes": 2048}
```

---

### 4.4 PROCESS (6)

Includes `/shell` (registered in [routes.py](../../../src/easy_sandbox/server/routes.py#L462-L465)) and SSE streaming shell with background process management (registered in
[routes_process.py](../../../src/easy_sandbox/server/routes_process.py#L268-L288)).

#### `POST /shell`

Synchronous shell command execution (`shlex.split` + `shell=False`), 300-second timeout. Request body:

```json
{"command": "ls -la /tmp"}
```

Response:

```json
{"stdout": "...", "stderr": "...", "exit_code": 0}
```

Missing/invalid `command` → `400`; timeout → `500 {"type": "TimeoutError"}`.

#### `POST /shell/stream`

Executes a command and streams output via **SSE** (`streaming=True`). Request body:

| Field | Default | Description |
|-------|---------|-------------|
| `command` | (required) | Command string |
| `timeout` | `300` | Seconds; `<=0` or invalid falls back to `300` |
| `cwd` | (empty) | Working directory; empty means `None` |

SSE event format described in §6. Missing/invalid `command` or `shlex` parsing failure → `400` (plain JSON response).

#### `POST /process/start`

Starts a background process (`subprocess.Popen`). Request body `{"command": "...", "cwd": "..."}`.
Process limit `100` (`_MAX_PROCESSES`, exceeding → `429 {"type": "ResourceError"}`). Success:

```json
{"pid": 12345, "command": "sleep 60"}
```

#### `GET /process/list`

Lists managed background processes (cleans up exited processes before listing). Response:

```json
{"processes": [{"pid": 12345, "command": "sleep 60", "state": "running", "started_at": 1758412800.0}]}
```

`state` is `running` or `exited`.

#### `GET /process/{pid}`

Single process details. `pid` not an integer → `400`; unmanaged → `404 {"type": "NotFoundError"}`. Response:

```json
{"pid": 12345, "command": "sleep 60", "state": "exited", "started_at": 1758412800.0, "exit_code": 0}
```

`state=running` has `exit_code` as `null`.

#### `POST /process/{pid}/signal`

Sends a signal to a managed process. Request body `{"signal": 15}`.

- Allowed signal whitelist `_ALLOWED_SIGNALS = {2, 9, 15, 18, 20}` (SIGINT/SIGKILL/SIGTERM/SIGCONT/SIGTSTP);
  others → `400`.
- Sending signals to `pid == 1` or the Server's own process is denied → `403 {"type": "PermissionError"}`.
- `pid` not an integer or missing `signal` → `400`; unmanaged → `404`.

Success `{"pid": 12345, "signal": 15}`.

---

### 4.5 TERMINAL (3 REST + WebSocket)

PTY session management endpoints (registered in
[routes_pty.py](../../../src/easy_sandbox/server/routes_pty.py#L398-L410)). WebSocket interaction protocol described in §5.

> PTY depends on the Unix `pty` module; creating sessions on non-Unix platforms raises `OSError` (→ `500`). Session limit
> `MAX_SESSIONS = 10`, idle timeout `IDLE_TIMEOUT = 1800` seconds.

#### `POST /pty/sessions`

Creates a PTY session. Request body (all optional):

| Field | Default | Description |
|-------|---------|-------------|
| `shell` | `/bin/bash` | Shell executable |
| `cols` | `80` | Terminal columns |
| `rows` | `24` | Terminal rows |
| `env` | `null` | Additional environment variable mapping |

Response:

```json
{"session_id": "a1b2c3d4e5f6", "ws_url": "ws://localhost:9001/pty?session_id=a1b2c3d4e5f6", "pid": 4321}
```

`cols`/`rows` not integer → `400`; session limit reached → `429 {"type": "RuntimeError"}`; PTY creation failure →
`500 {"type": "OSError"}`. The port in `ws_url` comes from `EBX_PTY_PORT` (default `9001`).

#### `GET /pty/sessions`

Lists active sessions (reaps dead sessions first). Response:

```json
{
  "sessions": [
    {"id": "a1b2c3d4e5f6", "pid": 4321, "created_at": 1758412800.0, "cols": 80, "rows": 24, "alive": true}
  ]
}
```

#### `DELETE /pty/sessions/{id}`

Closes and destroys a session. Success `{"status": "closed", "session_id": "<id>"}`; missing id → `400`;
not found → `404`.

---

### 4.6 SYSTEM (6)

System information endpoints (registered in
[routes_system.py](../../../src/easy_sandbox/server/routes_system.py#L416-L440)). All implemented using only the standard library (no `psutil`).

#### `GET /system/info`

OS / CPU / memory / disk / Python version:

```json
{
  "os": "Linux",
  "arch": "x86_64",
  "cpu_count": 4,
  "memory_total_mb": 8192,
  "memory_available_mb": 4096,
  "disk_total_gb": 40.0,
  "disk_free_gb": 25.5,
  "python_version": "3.11.5",
  "hostname": "sandbox-01"
}
```

Memory is preferentially parsed from `/proc/meminfo`; falls back to the `resource` module on non-Linux (less precise).

#### `GET /env`

Lists environment variables. Query parameter `filter` is a comma-separated whitelist (returns only those variables). **Variables whose names contain sensitive tokens (`TOKEN`/`SECRET`/`KEY`/`PASSWORD`/`CREDENTIAL`) are always excluded** (see §8.3).

```json
{"variables": {"LANG": "C.UTF-8", "PWD": "/home/user"}}
```

#### `POST /env`

Sets environment variables. Request body `{"vars": {"KEY": "value"}}`. **Protected variables**
(`PATH`/`HOME`/`USER`/`SHELL`/`EBX_SERVER_TOKEN`) cannot be overwritten → `403 {"type": "PermissionError"}`;
`vars` not an object → `400`. Success `{"updated": ["KEY1", "KEY2"]}` (sorted).

#### `GET /ports`

Lists listening TCP ports. Preferentially parses `/proc/net/tcp` and `/proc/net/tcp6` (state `0A` = LISTEN),
falls back to `ss -tlnp` when empty. Response:

```json
{"listening": [{"port": 8080, "protocol": "tcp", "address": "0.0.0.0", "pid": null}]}
```

> `pid` is usually `null` without root privileges.

#### `GET /packages`

Lists installed packages. Query parameter `manager` is `pip` (default) or `npm`; other values → `400`.
When the command is not found (`FileNotFoundError`), returns an empty list instead of an error; timeout → `500 {"type": "TimeoutError"}`.

```json
{"manager": "pip", "packages": [{"name": "requests", "version": "2.32.0"}]}
```

#### `GET /system/metrics`

Real-time resource metrics:

```json
{
  "cpu_load_1m": 0.15, "cpu_load_5m": 0.10, "cpu_load_15m": 0.05,
  "memory_used_mb": 2048, "memory_total_mb": 8192, "memory_percent": 25.0,
  "disk_used_gb": 14.5, "disk_total_gb": 40.0, "disk_percent": 36.3,
  "uptime_seconds": 123.4
}
```

`uptime_seconds` is relative to the process import time (`_BOOT_TIME`).

---

### 4.7 DEV_TOOLS (3) — Disabled by Default

Code execution and Git inspection (registered in
[routes_devtools.py](../../../src/easy_sandbox/server/routes_devtools.py#L385-L397)). Must
`default_table().enable_group(CapabilityGroup.DEV_TOOLS)` before use, otherwise requests return `404` (group disabled).

#### `POST /code/run`

Executes code in a subprocess. Request body:

| Field | Default | Description |
|-------|---------|-------------|
| `code` | (required) | Source code string |
| `language` | `python` | `python` / `node` / `bash`; others → `400` |
| `timeout` | `30` | Seconds; upper limit `300` (`_MAX_TIMEOUT`), `<=0` falls back to `30` |

Language mapping: `python`→`python3 -c`, `node`→`node -e`, `bash`→`bash -c`. Response:

```json
{"stdout": "hello\n", "stderr": "", "exit_code": 0, "language": "python", "execution_time_ms": 42.5}
```

Timeout → `408 {"type": "TimeoutError"}`; runtime not found → `500 {"type": "FileNotFoundError"}`.

#### `GET /git/status?path=...`

Parses `git status --porcelain -b`. Query parameter `path` (default `.`). Path containing `..` segment → `400`.
git not installed → `500`; timeout → `408`; git returns non-zero → `400 {"type": "GitError"}`. Response:

```json
{"branch": "main", "clean": false, "files": [{"path": "app.py", "status": "modified"}]}
```

`status` values: `modified`/`added`/`deleted`/`renamed`/`untracked`/`copied`/`unmerged`.

#### `GET /git/diff?path=...`

Returns `git diff` text and statistics. Query parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `path` | `.` | Working directory (containing `..` → `400`) |
| `staged` | `false` | Uses `--staged` when `true` |
| `file` | (empty) | Restrict to a single file (containing `..` → `400`) |

Diff text exceeding 1 MB (`_MAX_DIFF_BYTES`) is truncated with `... (truncated at 1MB)` appended. Response:

```json
{"diff": "diff --git ...", "stats": {"files_changed": 3, "insertions": 10, "deletions": 2}}
```

---

### 4.8 BROWSER (8) — Disabled by Default

Playwright headless browser control (registered in
[routes_browser.py](../../../src/easy_sandbox/server/routes_browser.py#L484-L516)). Must
`default_table().enable_group(CapabilityGroup.BROWSER)` before use.

> **Playwright lazy loading and 503 degradation**: Playwright is imported and started only on first use
> ([`_get_playwright`](../../../src/easy_sandbox/server/routes_browser.py#L60-L96)).
> If `playwright` is not installed, all browser endpoints return
> `503 {"error": "Playwright is not installed. ...", "type": "RuntimeError"}`.
> The page is a process-wide shared singleton (same `page`), and operations are serialized by `_browser_lock`.

#### `POST /browser/navigate`

Navigates to a URL. Request body:

| Field | Default | Description |
|-------|---------|-------------|
| `url` | (required) | Target URL |
| `wait_until` | `networkidle` | Playwright wait condition |
| `timeout` | `30000` | Milliseconds; `<=0` falls back to `30000` |

Response `{"url": "...", "title": "...", "status": 200}`.

#### `POST /browser/screenshot`

Takes a screenshot. Request body:

| Field | Default | Description |
|-------|---------|-------------|
| `selector` | `null` | If specified, captures that element; element not found → `404` |
| `full_page` | `true` | Full-page screenshot (when no selector) |
| `format` | `png` | `png` or `jpeg` (others fall back to `png`) |

Response `{"image_base64": "...", "width": 1280, "height": 720}`.

#### `GET /browser/content?type=...`

Gets page content. Query parameter `type`: `html` (default, `page.content()`) or `text`
(`page.inner_text("body")`). Response `{"content": "...", "url": "...", "title": "..."}`.

#### `POST /browser/click`

Clicks an element. Request body `{"selector": "#btn", "timeout": 5000}` (`timeout` in milliseconds, `<=0` falls back to `5000`).
Response `{"clicked": true, "selector": "#btn"}`.

#### `POST /browser/type`

Types text into an element. Request body:

| Field | Default | Description |
|-------|---------|-------------|
| `selector` | (required) | Target selector |
| `text` | (required) | Input text |
| `delay` | `50` | Per-character delay (milliseconds), `<0` falls back to `50` |
| `clear` | `false` | Whether to clear before typing (`page.fill("")`) |

Response `{"typed": true, "selector": "...", "text": "..."}`.

#### `POST /browser/evaluate`

Executes JavaScript. Request body `{"script": "document.title", "timeout": 10000}`
(`timeout` in milliseconds, used as default timeout, `<=0` falls back to `10000`). Response `{"result": <JS_return_value>}`.

#### `POST /browser/pdf`

Generates a PDF. Request body `{"format": "A4", "landscape": false}`. Response
`{"pdf_base64": "...", "pages": 1}` (`pages` is a rough count based on `/Type /Page` occurrences, at least `1`).

#### `GET /browser/console`

Returns collected console logs and **clears the buffer**. Response:

```json
{"logs": [{"type": "log", "text": "hello", "timestamp": 1758412800.0}]}
```

Log buffer limit `1000` entries (`_MAX_CONSOLE_LOGS`).

---

## 5. WebSocket PTY Terminal Protocol

Implementation in
[`pty_ws_handler`](../../../src/easy_sandbox/server/routes_pty.py#L426-L503)
and [`start_pty_server`](../../../src/easy_sandbox/server/routes_pty.py#L546-L571).
The WebSocket service depends on the `websockets` library and runs on a separate port (default `9001`).

### 5.1 Connection URL

```
ws://<host>:<pty_port>/pty?session_id=<session_id>
```

`session_id` must come from a prior `POST /pty/sessions`. Missing `session_id` → server closes with code
`1008` and message `"Missing session_id parameter"`; unknown session → `1008` + `"Unknown session: <id>"`.

### 5.2 Client → Server Messages (JSON Text Frames)

| `type` | Fields | Description |
|--------|--------|-------------|
| `input` | `data` (string) | Input to write to the shell (UTF-8 encoded) |
| `resize` | `cols`, `rows` (integers) | Resize terminal; non-integer values cause the message to be ignored |
| `signal` | `signal` (string) | Send signal to the shell process group |

`signal` value mapping (`_SIGNAL_MAP`): `SIGINT` / `SIGTERM` / `SIGKILL` / `SIGHUP` / `SIGQUIT`;
unrecognized signal names are ignored. Invalid JSON frames are silently discarded.

```json
{"type": "input",  "data": "ls -la\n"}
{"type": "resize", "cols": 120, "rows": 40}
{"type": "signal", "signal": "SIGINT"}
```

### 5.3 Server → Client Messages (JSON Text Frames)

| `type` | Fields | Description |
|--------|--------|-------------|
| `output` | `data` (string) | PTY output (UTF-8, `errors="replace"`) |
| `event` | `event`, `session_id`, `pid`? | Lifecycle events |

`event` values:

- `started`: Sent immediately after connection, includes `session_id` and `pid`.
- `exited`: Sent after shell process ends, includes `session_id`.

```json
{"type": "output", "data": "total 0\n"}
{"type": "event",  "event": "started", "session_id": "a1b2c3d4e5f6", "pid": 4321}
{"type": "event",  "event": "exited",  "session_id": "a1b2c3d4e5f6"}
```

### 5.4 Session Lifecycle

1. `POST /pty/sessions` creates a session, returning `session_id` and `ws_url`.
2. Connect to `ws_url`; server pushes `started` event, then the background read loop continuously forwards `output`.
3. Client sends `input`/`resize`/`signal` messages.
4. Shell exit triggers `exited` push; or call `DELETE /pty/sessions/{id}` to actively destroy.

---

## 6. SSE Streaming Shell

Endpoint: `POST /shell/stream` (PROCESS group). Implementation in
[`_handle_shell_stream`](../../../src/easy_sandbox/server/routes_process.py#L64-L121).
Response `Content-Type: text/event-stream` ([`SSEResponse`](../../../src/easy_sandbox/server/types.py#L91-L107)),
events flushed one by one as standard SSE frames `event: <name>\ndata: <json>\n\n`.

### 6.1 Event Types (Confirmed from Code)

| `event` | `data` Structure | Trigger |
|---------|------------------|---------|
| `stdout` | `{"data": "<line_text>"}` | Each line read from standard output (trailing `\n` stripped) |
| `stderr` | `{"data": "<line_text>"}` | After stdout is fully read, lines from standard error |
| `error` | `{"error": "<message>"}` | Process startup failure, or timeout (`{"error": "timeout"}`) |
| `exit` | `{"exit_code": <int>}` | Process ended (an `exit` event is also sent after timeout) |

> Implementation note: stdout and stderr are read **sequentially — all stdout lines first, then stderr** — not interleaved in real time.
> Timeout detection is based on `time.monotonic()` within the stdout read loop.

### 6.2 Example

```bash
curl -N -X POST http://localhost:9000/shell/stream \
  -H "Content-Type: application/json" \
  -d '{"command": "echo hello && echo err >&2", "timeout": 30}'
```

```
event: stdout
data: {"data": "hello"}

event: stderr
data: {"data": "err"}

event: exit
data: {"exit_code": 0}

```

---

## 7. Extensibility (Template Author Guide)

The Server's routes and commands can be extended by template `commands.py` without modifying SDK source code. See the complete example at
[`examples/templates/python-hello/commands.py`](../../../examples/templates/python-hello/commands.py).

### 7.1 Registering Custom HTTP Routes

Use the [`RouteTable.route()`](../../../src/easy_sandbox/server/router.py#L175-L204) decorator (or `register()`).
Path templates support `{param}` placeholders, compiled to named capture groups `(?P<param>[^/]+)`, accessible via
`request.path_params`:

```python
from easy_sandbox.server import CapabilityGroup, ServerResponse, default_table

table = default_table()

@table.route("GET", "/hello/{name}", group=CapabilityGroup.COMMANDS)
def hello_route(request) -> ServerResponse:
    name = getattr(request, "path_params", {}).get("name", "World")
    return ServerResponse.ok({"greeting": f"Hello, {name}!"})
```

`route()` / `register()` keyword arguments: `group` (required), `auth_required` (default `True`),
`streaming` (default `False`), `name` (default `"<METHOD> <path>"`). Routes match in registration order.

#### Custom SSE Streaming Endpoints

When a route is registered with `streaming=True`, the handler should return an
[`SSEResponse`](../../../src/easy_sandbox/server/types.py#L91-L107) whose
`event_iterator` yields standard SSE frame format strings (refer to the implementation in
[`routes_process.py`](../../../src/easy_sandbox/server/routes_process.py#L64-L121)):

```python
import json
from easy_sandbox.server import CapabilityGroup, default_table
from easy_sandbox.server.types import SSEResponse, ServerResponse

table = default_table()

@table.route("POST", "/my/stream", group=CapabilityGroup.COMMANDS, streaming=True)
def my_stream(request) -> SSEResponse | ServerResponse:
    body = request.body or {}
    count = body.get("count", 3)
    if not isinstance(count, int) or count <= 0:
        return ServerResponse.error(400, "Invalid 'count'", "ValueError")

    def event_gen():
        for i in range(count):
            yield f"event: progress\ndata: {json.dumps({'step': i + 1})}\n\n"
        yield f"event: done\ndata: {json.dumps({'total': count})}\n\n"

    return SSEResponse(event_iterator=event_gen())
```

The client will receive a `Content-Type: text/event-stream` response with events flushed one by one.

#### Auth-Exempt Endpoints

Setting `auth_required=False` makes an endpoint bypass authentication even when `EBX_SERVER_TOKEN` is configured (the built-in
`GET /health` and `GET /capabilities` use this mode):

```python
from easy_sandbox.server import CapabilityGroup, ServerResponse, default_table

table = default_table()

@table.route("GET", "/public/status", group=CapabilityGroup.COMMANDS, auth_required=False)
def public_status(request) -> ServerResponse:
    return ServerResponse.ok({"status": "running", "public": True})
```

> Note: Auth-exempt endpoints are still subject to capability group gating; if their capability group is disabled, they return `404`.

### 7.2 Registering Custom Commands

Use the [`CommandRegistry.command()`](../../../src/easy_sandbox/server/registry.py#L163-L234) decorator;
when `args` is not explicitly provided, parameter types are **inferred from the function signature** (`int`→`integer`, `float`→`float`,
`bool`→`boolean`, others→`string`) along with required status (no default value means required):

```python
from easy_sandbox.server import CommandRegistry, SandboxServer

registry = CommandRegistry()

@registry.command("hello", description="Say hello.")
def hello(name: str = "World") -> str:
    return f"Hello, {name}!"

@registry.command(hidden=True)          # Executable but not listed in GET /commands
def _debug_info() -> dict:
    import platform
    return {"python": platform.python_version()}

registry.freeze()                        # Registering after freeze raises RuntimeError
server = SandboxServer(registry=registry)
server.serve(port=9000)
```

- `hidden=True`: The command can still be executed via `POST /commands/{name}`, but is excluded from the `GET /commands` listing by
  [`list_visible`](../../../src/easy_sandbox/server/registry.py#L268-L276).
- `freeze()`: Locks the registry to prevent modifications after startup; `serve()` also calls this internally.
- Programmatic registration is also available via `registry.register(name, fn, args=[CommandArg(...)], description=..., hidden=...)`.

`CommandArg`'s `type` must be one of `string`/`integer`/`float`/`boolean`, otherwise the constructor raises
`ValueError`.

---

## 8. Security Model

### 8.1 Path Traversal Protection

[`_resolve_safe_path`](../../../src/easy_sandbox/server/routes.py#L58-L84)
normalizes paths for all file endpoints (`os.path.realpath` + `normpath`) and verifies the resolved result must equal
the base directory or reside under it (`resolved == base_dir or resolved.startswith(base_dir + os.sep)`),
otherwise raises `ValueError` (→ `400 {"error": "Path escapes base directory"}`).

- Base directory comes from `EBX_SERVER_BASE_DIR`, default `/home/user`.
- `/files/list` additionally skips symlinks pointing outside the base directory.
- Git endpoints (`/git/status`, `/git/diff`) use a separate `..` segment rejection check
  ([`_validate_git_path`](../../../src/easy_sandbox/server/routes_devtools.py#L62-L70)),
  rather than `_resolve_safe_path`.

### 8.2 Signal Whitelist

- `POST /process/{pid}/signal` only allows `_ALLOWED_SIGNALS = {2, 9, 15, 18, 20}`;
  and denies signals to `pid == 1` or the Server's own process (`403`).
- WebSocket PTY `signal` messages only accept `_SIGNAL_MAP` entries:
  `SIGINT`/`SIGTERM`/`SIGKILL`/`SIGHUP`/`SIGQUIT`, targeting the shell process group.

### 8.3 Environment Variable Protection and Redaction

- **Redaction (`GET /env`)**: Variables whose names contain `_ENV_BLACKLIST_TOKENS`
  (`TOKEN`/`SECRET`/`KEY`/`PASSWORD`/`CREDENTIAL`, case-insensitive) are always excluded from the response.
- **Protection (`POST /env`)**: `_PROTECTED_ENV_VARS`
  (`PATH`/`HOME`/`USER`/`SHELL`/`EBX_SERVER_TOKEN`) cannot be overwritten; matching triggers `403`.

### 8.4 Other Limits

| Limit | Value | Location |
|-------|-------|----------|
| shell / code / git commands | `shell=False` + argument vector execution | Various handlers |
| `/shell` timeout | 300s | routes.py |
| `/code/run` timeout | Default 30s, max 300s | routes_devtools.py |
| Upload size limit | 100 MB (`EBX_MAX_UPLOAD_SIZE` adjustable) | routes_files.py |
| Archive file count/size | 10000 / 100 MB | routes_files.py |
| Background process limit | 100 | routes_process.py |
| PTY session limit / idle timeout | 10 / 1800s | routes_pty.py |
| Authentication comparison | `hmac.compare_digest` (constant-time) | app.py |

---

## 9. Configuration Reference (Environment Variable Summary)

| Environment Variable | Default | Purpose | Read Location |
|---------------------|---------|---------|---------------|
| `EBX_SERVER_TOKEN` | (unset = no auth) | Authentication token; when set, requires matching `X-Access-Token` header | [app.py#L43](../../../src/easy_sandbox/server/app.py#L43) |
| `EBX_SERVER_BASE_DIR` | `/home/user` | File endpoint path safety root directory | [routes.py#L54-L55](../../../src/easy_sandbox/server/routes.py#L54-L55) |
| `EBX_SERVER_DISABLED_GROUPS` | (empty) | Comma-separated, additionally disables capability groups beyond the defaults | [router.py#L71](../../../src/easy_sandbox/server/router.py#L71) |
| `EBX_PTY_PORT` | `9001` | PTY WebSocket port, also written into `ws_url` | [app.py#L247](../../../src/easy_sandbox/server/app.py#L247) / [routes_pty.py#L362](../../../src/easy_sandbox/server/routes_pty.py#L362) |
| `EBX_MAX_UPLOAD_SIZE` | `104857600` (100 MB) | `/files/upload-stream` upload byte limit | [routes_files.py#L39](../../../src/easy_sandbox/server/routes_files.py#L39) |

> The HTTP port is not controlled by an environment variable; it is a `start(port=...)` / `SandboxServer.serve(port=...)` parameter (default `9000`).

---

## Appendix: Endpoint Count Verification

| Capability Group | Endpoints | Endpoint List |
|------------------|:---------:|---------------|
| CORE | 2 | `GET /health`, `GET /capabilities` |
| COMMANDS | 2 | `GET /commands`, `POST /commands/{name}` |
| FILE_OPS | 11 | `POST /upload`, `GET /download`, `GET /files/list`, `GET /files/stat`, `POST /files/mkdir`, `DELETE /files`, `POST /files/move`, `POST /files/search`, `POST /files/upload-stream`, `GET /files/download-stream`, `POST /files/archive` |
| PROCESS | 6 | `POST /shell`, `POST /shell/stream`, `POST /process/start`, `GET /process/list`, `GET /process/{pid}`, `POST /process/{pid}/signal` |
| TERMINAL | 3 REST | `POST /pty/sessions`, `GET /pty/sessions`, `DELETE /pty/sessions/{id}` |
| SYSTEM | 6 | `GET /system/info`, `GET /env`, `POST /env`, `GET /ports`, `GET /packages`, `GET /system/metrics` |
| DEV_TOOLS | 3 | `POST /code/run`, `GET /git/status`, `GET /git/diff` |
| BROWSER | 8 | `POST /browser/navigate`, `POST /browser/screenshot`, `GET /browser/content`, `POST /browser/click`, `POST /browser/type`, `POST /browser/evaluate`, `POST /browser/pdf`, `GET /browser/console` |
| **HTTP Total** | **41** | |
| WebSocket | 1 | `ws://host:9001/pty?session_id=...` |
| **Grand Total** | **42** | |

> 41 HTTP routes match the total count of `_table.register(...)` calls in the source code (`CORE 2 + COMMANDS 2 +
> FILE_OPS 11 + PROCESS 6 + TERMINAL 3 + SYSTEM 6 + DEV_TOOLS 3 + BROWSER 8 = 41`), plus 1
> PTY WebSocket endpoint for a total of **42 endpoints**.
