# Decision: MCP FC Streamable HTTP Transport

Status: implemented

## Problem

The Easy Sandbox MCP Server currently only supports STDIO transport for local IDE integration (Cursor, Claude Desktop, VS Code). This limits MCP to local use — remote teams, CI/CD pipelines, and cloud-native agent frameworks cannot access sandbox tools via MCP without running a local process. We need a remote-accessible MCP Server deployment option.

## Decision

Implement MCP Streamable HTTP transport (2025-06-18 specification) as a Starlette ASGI application. The new `ebx mcp deploy` command generates an artifact and manual instructions for Alibaba Cloud Function Compute (FC); it does not call an FC deployment API.

### Architecture

- **Transport layer**: `src/easy_sandbox/agent/mcp_http.py` — Starlette ASGI app
  - `POST /mcp` — JSON-RPC 2.0 request/response
  - `GET /mcp` — SSE server notifications (Phase 2 stub, returns 501)
  - `DELETE /mcp` — Session termination and sandbox cleanup
  - `/health` — Health check for FC / load balancers
- **Session management**: In-process `SessionStore` maps `Mcp-Session-Id` → `SandboxMCPServer`, expires idle sessions after a TTL, and enforces a maximum session count
- **Tool reuse**: All 7 P0 tools from `agent/tools.py` are reused via `SandboxMCPServer.handle_request()` — zero code duplication
- **CLI**: `ebx mcp deploy` generates an artifact (`requirements.txt` + `app.py` + `config.yaml`) and prints manual FC deployment steps; `config.yaml` is a provider-neutral manifest, not an FC API payload
- **Authentication**: Dual-layer — Client→MCP via constant-time Bearer token validation, MCP→Sandbox via `E2B_API_KEY`; configured empty Bearer tokens fail closed

### Session Affinity

Session affinity requires an FC runtime that supports `Mcp-Session-Id` header routing. The ASGI app sets `Mcp-Session-Id` on the `initialize` response; operators must configure the platform to route subsequent requests with that header to the same instance. Clients should call `DELETE /mcp` when finished so the server can clean up sandboxes promptly.

### Protocol Version

The HTTP transport uses `MCP_PROTOCOL_VERSION = "2025-06-18"` (Streamable HTTP). The existing STDIO transport retains `"2024-11-05"`. Both coexist without conflict.

**2026-09-29 correction (per-transport version negotiation):** the shared `SandboxMCPServer._handle_initialize()` originally hard-coded the STDIO constant, so HTTP `initialize` responded `2024-11-05` while `GET /health` declared `2025-06-18` (found in real E2E; see `.agents/evidence/2026-09-29-mcp-e2e.md`). Fix: `SandboxMCPServer` now accepts a `supported_protocol_versions` sequence (default `(2024-11-05,)`, preserving STDIO); the HTTP `SessionStore` passes `(2025-06-18,)`. `initialize` echoes a supported requested `protocolVersion` and falls back to the preferred (first) supported version for missing/unsupported requests — the MCP spec rule that the server responds with another version it supports (the client may disconnect). STDIO behavior is unchanged; HTTP health and initialize now report the same version.

## API Design

### ASGI App Factory

```python
def create_mcp_app(
    auth_token: str | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    template: str = "base",
) -> Starlette:
    """Create the MCP Streamable HTTP Starlette application."""
```

### CLI Command

```
ebx mcp deploy \
  --name easy-sandbox-mcp \
  --region cn-hangzhou \
  --template python-base \
  --memory 512 --timeout 600 \
  --generate-token \
  --api-key $E2B_API_KEY \
  --output-dir ./deploy-artifact \
  [--custom-domain mcp.example.com]
```

### Module-Level ASGI Entry Point

```python
# For: uvicorn easy_sandbox.agent.mcp_http:asgi_app
asgi_app: Any = _LazyApp()
```

## Alternatives considered

- **HTTP+SSE (deprecated MCP 2024-11-05)** — Rejected: specification deprecated, client ecosystem moving to Streamable HTTP.
- **WebSocket transport** — Rejected: not part of MCP standard, client compatibility gap.
- **Stateless HTTP (recreate sandbox per request)** — Rejected: unacceptable latency for sandbox creation on every call.
- **Embed Starlette as hard dependency** — Rejected: added to `mcp` optional extra to keep base install lightweight.

## Dependencies

- `starlette>=0.37` — ASGI framework (optional, `mcp` extra)
- `uvicorn>=0.29` — ASGI server (optional, `mcp` extra)
- Reuses: `easy_sandbox.agent.mcp.SandboxMCPServer`, `easy_sandbox.agent.tools`

## Test Strategy

- **Unit tests** (`tests/test_agent/test_mcp_http.py`):
  - JSON-RPC helper tests
  - Bearer token validation
  - SessionStore lifecycle (create, get, destroy, shutdown_all)
  - Full ASGI integration via Starlette TestClient:
    - Initialize → session creation
    - tools/list with session header
    - Notification → 202 response
    - Auth enforcement (POST, GET, DELETE)
    - DELETE session cleanup
    - Invalid JSON, invalid session, missing header error cases
  - Protocol version negotiation (`TestProtocolVersionNegotiation`, `TestHttpProtocolVersionNegotiation`):
    - HTTP health/initialize consistency (both report 2025-06-18)
    - STDIO unchanged: default server always negotiates 2024-11-05 for supported, unsupported, and missing requested versions
    - Supported requested versions are echoed; unsupported/missing ones fall back to the transport's preferred version
    - Empty `supported_protocol_versions` is rejected with `ValueError`
- **CLI tests** (`tests/test_cli/test_mcp_commands.py`):
  - `deploy --help` output
  - `--output-dir` artifact generation
  - Custom `--name`, `--region`, `--memory`, `--timeout`
  - `--auth-token-file` and `--generate-token`
  - `--enable-session-affinity` flag
  - `--custom-domain` propagation
  - No API key warning

## Acceptance criteria

### Completed

1. `POST /mcp` with `initialize` creates a bounded, expiring session and returns `Mcp-Session-Id`
2. Subsequent `POST /mcp` with the session header routes to the correct MCP server
3. `DELETE /mcp` terminates the session and cleans up sandboxes
4. Bearer token auth uses constant-time comparison; missing or configured-empty credentials fail closed with 401
5. All 7 existing tools are delegated through `SandboxMCPServer.handle_request()` over HTTP
6. `ebx mcp deploy --output-dir` generates `requirements.txt`, `app.py`, and `config.yaml`, plus manual FC deployment steps
7. Existing STDIO mode (`ebx mcp start`) retains its transport behavior; malformed non-object JSON is now rejected with a JSON-RPC error instead of crashing
8. `GET /mcp` explicitly returns 501 until Phase 2 SSE notifications are implemented
9. (2026-09-29) HTTP `initialize` negotiates `2025-06-18`, consistent with `GET /health`; STDIO retains `2024-11-05`; supported requested versions are echoed, missing/unsupported ones fall back to the transport's preferred version

### Follow-up

1. Integrate an official, verified Alibaba Cloud FC function and HTTP Trigger SDK workflow for automatic deployment
2. Implement SSE server notifications for `GET /mcp`
3. Validate session-affinity configuration against the selected FC runtime before enabling it
