# Decision: easy_sandbox.server — User Opt-in In-Container HTTP Server Module

Status: implemented
Implemented: 2026-09-21
Task: #118

## Problem
Users need to register and execute custom commands inside the sandbox container. The original approach (source-delivery execution: `files.write` to deliver a script + `commands.run` to execute it) requires the full chain on every call, with high latency, no persistent state, and no concurrency support. A persistent in-container HTTP server is needed to carry custom commands, while introducing no third-party dependencies (the container may have no pip package-management environment).

## Decision
Add an `easy_sandbox.server` module: a stdlib-only, zero-dependency in-container HTTP server that the user opt-in starts.

### Core design principles

1. **stdlib-only, zero dependencies**: uses only the Python standard library (`http.server`, `json`, `subprocess`, `os`, `shutil`) with no third-party packages. Reason: the in-container environment is uncontrolled and may have no pip/virtualenv; we cannot assume the user image pre-installs any Python package.

2. **User opt-in, not a fallback agent**: the server module is never auto-deployed or auto-started. The user must explicitly call `sandbox.server.start()`, which delivers the server source into the container via `files.write` and starts it in the background via `commands.start`. envd remains the base carrier for standard capabilities (files/process/code/PTY); the server module does not replace envd.

3. **Operates directly on the local filesystem, not bound to envd**: the built-in commands (upload/download/runshell) call the Python standard library directly to operate on the container's local filesystem and processes, without going through the envd API. Reasons: (a) it avoids an extra server→envd network hop; (b) the server runs inside the container and has direct filesystem and process access.

4. **ports capability gating**: the server module requires the template to declare `capabilities: [..., ports]`. `ports` ∉ `DEFAULT_CAPABILITIES = {shell, files, code}`. The client reaches the server via `https://{port}-{sandbox_id}.{domain}`, relying on the Gateway's `routeDynamic` dynamic port routing.

### Final implementation scale

The server module ultimately expanded to **42 endpoints**, managed in **8 CapabilityGroups** (CORE, COMMANDS, FILE_OPS, PROCESS, SYSTEM, TERMINAL, DEV_TOOLS, BROWSER). It uses a declarative `RouteTable` + `CapabilityGroup` mechanism instead of hard-coded if/elif routing.

### Built-in commands

5. **upload**: upload a file to the container. The request body carries the file content and target path.
6. **download**: download a file from the container. The request body carries the source path; the response carries the file content.
7. **runshell**: run a shell command. The request body carries the command string; the response carries stdout/stderr/exit_code.

### WIRE CONTRACT (client↔server communication protocol)

8. **Command execution**: `POST /commands/{name}`
   - Request Content-Type: `application/json`
   - Request Body: `{"key": "value", ...}` (the command's kwargs)
   - Success Response: `200 OK`, `{"result": <return_value>}`
   - Error Response: `4xx/5xx`, `{"error": "<message>", "type": "<exception_class>"}`

9. **Command discovery**: `GET /commands`
   - Response: `200 OK`, `{"commands": [{"name": "upload", "args": [...]}, ...]}`
   > Note: an early ADR showed a bare-array format in its example; the actual implementation wraps it in a `{"commands": [...]}` object.

10. **Health check**: `GET /health`
    - Response: `200 OK`, `{"status": "ok"}`

### Client API

11. **`sandbox.server.start(port=8080)`**: deliver the server source into the container + start it in the background + wait for the health check to pass.
12. **`sandbox.server.call(command_name, **kwargs)`**: send a `POST /commands/{name}` request and parse the JSON response.
13. **`sandbox.server.discover()`**: send a `GET /commands` request and return the command list.

## API Design
```python
# Client side
from easy_sandbox import Sandbox

sandbox = await Sandbox.create(template="my-template")

# Start the in-container server (opt-in)
await sandbox.server.start(port=8080)

# Call a built-in command
result = await sandbox.server.call("runshell", cmd="ls -la /home/user")
# → POST https://8080-{sandbox_id}.{domain}/commands/runshell
# → Body: {"cmd": "ls -la /home/user"}
# ← {"result": {"stdout": "...", "stderr": "", "exit_code": 0}}

# Upload a file
await sandbox.server.call("upload", path="/home/user/script.py", content="print('hello')")

# Download a file
result = await sandbox.server.call("download", path="/home/user/output.txt")

# Discover all commands
commands = await sandbox.server.discover()
# → GET https://8080-{sandbox_id}.{domain}/commands
# ← [{"name": "upload", ...}, {"name": "download", ...}, {"name": "runshell", ...}]
```

```python
# In-container server module (easy_sandbox/server/)
# Pure stdlib, zero dependencies

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, subprocess, os, shutil

class SandboxHandler(BaseHTTPRequestHandler):
    """Handles /commands/{name}, /commands, and /health requests"""
    ...

class SandboxServer:
    """Command registration + HTTP server lifecycle management"""
    def register(self, name: str, handler: Callable) -> None: ...
    def start(self, host: str = "0.0.0.0", port: int = 8080) -> None: ...
```

## Alternatives considered
- **FastAPI / Flask as the server framework** — Introduces third-party dependencies; the container may have no pip environment, making deployment costly. Rejected.
- **Reuse the envd files/process API (server as an envd client)** — Adds an extra network hop (server→envd→local filesystem), and since the server runs in the container with direct filesystem access, going through envd is pointless. Rejected.
- **Keep source-delivery execution (no server)** — Every call requires the full files.write + commands.run chain, with high latency, no persistent state, and no concurrency. Rejected.
- **Build directly `FROM` the official image (which contains envd, no server needed)** — envd's endpoint surface is closed and non-extensible (controlled by the image); the user cannot register custom commands into envd. The server module solves the "user-defined command" carrier problem — complementary to envd, not a replacement. Rejected as the sole solution.
- **gRPC / Connect protocol as the communication protocol** — Requires a protobuf toolchain and runtime library, violating the zero-dependency principle. Rejected.

## Dependencies
- `api/sandbox.py` (the `Sandbox` class, mounting the `server` attribute)
- `api/network.py` (`NetworkModule.get_url(port)` builds the access URL)
- `api/files.py` (`files.write` delivers the server source into the container)
- `api/commands.py` (`commands.start` starts the server process in the background)
- `transport/auth.py` (`EnvdTokenManager` obtains the `X-Access-Token`)
- `2026-09-03-capability-model.md` (`ports` capability gating)
- `2026-09-04-envd-container-service-model.md` (two-layer model: envd base layer + server opt-in layer)
- `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md` (confirms Gateway routeDynamic supports dynamic port routing, the basis of server reachability)

## Test Strategy
- Unit tests: the server module's command registration, request routing, JSON serialization/deserialization.
- Integration test: `sandbox.server.start()` → health check → `call("runshell", cmd="echo ok")` → verify the response.
- Built-in commands: upload + download round-trip consistency; runshell returns correct stdout/stderr/exit_code.
- Capability gating: when a template does not declare `ports`, `sandbox.server.start()` should raise `CapabilityNotSupportedError(E3004)`.
- Discovery endpoint: `GET /commands` returns the full schema of all built-in commands + user-registered commands.
- Error handling: invalid command name → 404; command execution exception → `{"error", "type"}` response.
- Zero-dependency validation: the server module source imports no third-party package.

## Acceptance criteria
- ✅ The `easy_sandbox.server` module uses only the Python standard library, with zero third-party dependencies.
- ✅ Built-in upload/download/runshell commands operate directly on the local filesystem.
- ✅ Stable WIRE CONTRACT: `POST /commands/{name}` + JSON body → `{"result"}` or `{"error","type"}`.
- ✅ The `GET /commands` discovery endpoint returns all registered commands and their argument schemas.
- ✅ `ports` capability gating: `start()` errors when `ports` is not declared.
- ✅ Client API: `sandbox.server.start()` / `.call()` / `.discover()` are functionally complete.
- ✅ The server expanded from 6 endpoints to 42 endpoints across 8 capability groups (including BROWSER).
- ✅ This ADR has been moved from `proposed/` to `implemented/`.

## Evidence
- `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md` (Gateway routeDynamic confirms dynamic port routing is feasible)
- `.agents/evidence/research/2026-09-04-fc-sandbox-official-docs.md` (confirms the port URL format `{port}-{sandbox_id}.{domain}`)
