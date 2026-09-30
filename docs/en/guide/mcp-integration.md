# MCP Integration

Easy Sandbox provides an MCP (Model Context Protocol) Server, enabling AI IDEs and tools to operate sandboxes directly.

---

## What Is MCP

MCP (Model Context Protocol) is an open protocol that allows AI models to interact with external tools and services. The Easy Sandbox MCP Server runs over STDIO transport with JSON-RPC 2.0 protocol, providing sandbox operation capabilities to AI assistants. A Streamable HTTP transport is also available for remote deployments (see below).

### Requirements

```bash
pip install "easy-sandbox[cli]"     # ebx CLI + MCP STDIO server
export E2B_API_KEY=your-api-key     # or: ebx config set sandbox_api_key your-api-key
```

---

## Install to IDE

### Cursor

```bash
ebx mcp install --target cursor
```

Writes an `easy-sandbox` entry into `~/.cursor/mcp.json`, then restart Cursor.

### Claude Desktop

```bash
ebx mcp install --target claude
```

Writes into `claude_desktop_config.json` (location depends on OS), then restart Claude Desktop.

### VS Code

```bash
ebx mcp install --target vscode
```

Writes the workspace `.vscode/mcp.json` `servers` entry (`type: stdio`), then reload the VS Code window. That file is often committed, so the installer does not copy the API key into it; `ebx mcp start` reads the key from the environment or `~/.ebx`.

All targets register the same STDIO command: `ebx mcp start`. The command is the absolute `ebx` next to the current interpreter (or `python -m easy_sandbox.cli.main` when `ebx` cannot be found), so an IDE with a minimal PATH can still start the server. The installer merges into existing config files — other MCP servers you have configured are preserved. A config file that is not strict JSON (comments or trailing commas) is left untouched. Cursor and Claude user-level configs embed the API key in `env` when one is available. That key follows [Credential resolution](../reference/configuration.md#credential-resolution): the process environment, then `./.env`, then `~/.ebx`. `E2B_API_URL` and `SANDBOX_REGION` are copied only when the process environment sets them; a region saved with `ebx config set region` is read again when `ebx mcp start` runs.

### Check Installation Status

```bash
ebx mcp status
# server, transport, tool list, auth_configured, installed_<ide> flags

ebx --json mcp status
```

---

## Available Tools

The MCP Server provides 7 tools:

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_sandbox` | Create a sandbox and make it the default | `template` (optional; omitted means the server template), `timeout` (optional, default 300), `envs` (optional) |
| `run_code` | Execute code in the sandbox | `code` (required), `sandbox_id` (optional), `language` (optional, default python), `timeout` (optional, default 30) |
| `run_command` | Run a command via `sh -c` (pipes, `&&`, `$VAR`, `cd`) | `command` (required), `sandbox_id` (optional), `cwd` (optional; omitted uses the image workdir), `timeout` (optional, default 60; a non-zero exit is a tool error) |
| `read_file` | Read a file from the sandbox | `path` (required), `sandbox_id` (optional), `encoding` (optional, default utf-8) |
| `write_file` | Write a file to the sandbox | `path`, `content` (required), `sandbox_id` (optional) |
| `list_files` | List directory contents in the sandbox | `path` (optional, default `/`), `sandbox_id` (optional) |
| `kill_sandbox` | Destroy a sandbox | `sandbox_id` (optional; destroys the default sandbox when omitted. An error is returned when there is no default) |

> **Naming clarification**: The MCP tool `run_command` runs the command via `sh -c` (`sandbox.commands.run(..., shell=True)` in the SDK). It is unrelated to the deprecated SDK method `Sandbox.run_command()`, which dispatches named custom commands — use `Sandbox.custom()` for that purpose.
>
> **Default sandbox**: `create_sandbox` makes that sandbox the default, so a later `write_file` / `run_code` / `kill_sandbox` that omits `sandbox_id` uses the sandbox just created. If there is no default yet, the first tool call that omits `sandbox_id` lazily creates one. An omitted `template` uses the server template (`code-interpreter-v1` for `ebx mcp start`). Each use extends the sandbox lifetime by the timeout it was created with. Every sandbox in the session is destroyed when the IDE closes the server (STDIO) or on `DELETE /mcp` / idle timeout (HTTP).

---

## Manually Start the MCP Server (STDIO)

The MCP Server is usually started automatically by the IDE. A manual process sits on stdin waiting for JSON-RPC; that wait is the running state. On startup it writes the transport, protocol, template, whether an API key is configured, the tool list, and how to stop to **stderr** (stdout stays JSON-RPC, and the secret itself is not printed):

```bash
ebx mcp start
```

Stop it from another terminal:

```bash
ebx mcp stop
```

`ebx mcp stop` sends SIGTERM to the recorded pid. A foreground STDIO process also stops on Ctrl-C. The pid file and log live under `~/.ebx/run/` (`mcp-server.json`, `mcp-server.log`); tests can point `EBX_MCP_RUNTIME_DIR` somewhere else. `ebx mcp status` reports `mcp_running` for this local process.

| Option | Description |
|--------|-------------|
| `--template` | Default template (default code-interpreter-v1) |
| `--api-key` | API Key override (env: `E2B_API_KEY`) |
| `--api-url` | API URL override (env: `E2B_API_URL`) |
| `--domain` | Domain override (env: `E2B_DOMAIN`) |
| `--http` | Serve Streamable HTTP instead (default `127.0.0.1:9000`) |
| `--host` / `--port` | HTTP bind address and port. A non-loopback host requires a non-empty `--auth-token` |
| `--auth-token` | HTTP Bearer token (env: `EBX_MCP_AUTH_TOKEN`) |
| `--background` | Detach the HTTP server. STDIO would see EOF after detach and exit, so this option forces HTTP |

Background HTTP:

```bash
ebx mcp start --http --background
ebx mcp stop
```

The parent prints the pid, `http://127.0.0.1:9000/mcp`, and the log path, then returns. The API key and token go into the child environment, not its argv. `--quiet` skips these notes.

In STDIO mode the server speaks newline-delimited JSON-RPC 2.0 on stdin/stdout. You can smoke-test it without an IDE (the notes stay on stderr, so the pipe is still JSON):

```bash
# initialize + tools/list over a pipe; the server replies on stdout
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | ebx mcp start | head -n 2
```

---

## Remote Server (Streamable HTTP)

For team sharing or remote access, run the MCP Server as a Streamable HTTP service instead of STDIO.

### Run Locally with uvicorn

```bash
pip install "easy-sandbox[mcp]"

export EBX_MCP_AUTH_TOKEN=replace_me   # Bearer token (omit to disable auth)
export E2B_API_KEY=your-api-key

uvicorn easy_sandbox.agent.mcp_http:asgi_app --host 0.0.0.0 --port 9000
```

Endpoints: `POST /mcp` (JSON-RPC), `DELETE /mcp` (session termination), `GET /health` (health check). `GET /mcp` returns 405 (SSE notifications are not implemented; the Streamable HTTP spec uses 405 rather than 501). A request that sends `Origin` from anywhere other than localhost or `EBX_MCP_ALLOWED_ORIGINS` is rejected with 403.

You can also build the app programmatically:

```python
from easy_sandbox.agent.mcp_http import create_mcp_app

app = create_mcp_app(
    auth_token="replace_me",   # None disables client auth
    api_key="your-api-key",
    template="base",
)
```

### Bearer Token Authentication

The three entry points use different credentials:

| Entry | Client authentication | How to configure |
|-------|----------------------|------------------|
| `ebx mcp start` (STDIO) | No Bearer token. The IDE starts a local process; it does not listen on the network | Sandbox calls use `E2B_API_KEY` / `ebx config set sandbox_api_key` |
| `ebx mcp start --http` | Bearer token. Loopback may omit it (the process warns). A non-loopback `--host` requires a non-empty `--auth-token` | `--auth-token` or `EBX_MCP_AUTH_TOKEN` |
| Remote function on Alibaba Cloud FC | Bearer token is required. The artifact `app.py` refuses to start when the token is empty, so a remote process cannot boot with authentication disabled | `ebx mcp deploy --generate-token` writes `EBX_MCP_AUTH_TOKEN` into the function environment. The FC HTTP trigger uses `anonymous` so an MCP client does not need an Alibaba Cloud signature; the application Bearer token is the check. `GET /health` returns status and protocol only, with no token check and no secrets |

When `EBX_MCP_AUTH_TOKEN` (or `auth_token`) is set, every `/mcp` request must carry:

```
Authorization: Bearer <token>
```

- Loopback with the token unset → authentication disabled, and the process warns
- Token set but empty → **fails closed**: every request is rejected with 401
- FC artifact with the token unset or empty → the process refuses to start

Tokens are compared with constant-time comparison. Generate one with `openssl rand -base64 32` or let `ebx mcp deploy --generate-token` create one.

### Client Configuration (Remote)

```json
{
  "mcpServers": {
    "easy-sandbox-remote": {
      "url": "http://your-server:9000/mcp",
      "headers": {
        "Authorization": "Bearer replace_me"
      }
    }
  }
}
```

---

## Generate an FC Deployment Artifact

`ebx mcp deploy` produces a ready-to-package artifact for Alibaba Cloud Function Compute. It does **not** call the FC API — you create the function manually via the console or SDK.

```bash
ebx mcp deploy \
  --generate-token \
  --api-key $E2B_API_KEY \
  --output-dir ./mcp-artifact
```

The artifact directory contains:

| File | Content |
|------|---------|
| `requirements.txt` | `easy-sandbox[mcp]`, `uvicorn>=0.29` |
| `app.py` | ASGI entry point reading FC env vars (`EBX_MCP_AUTH_TOKEN`, `E2B_API_KEY`, `E2B_API_URL`, `E2B_DOMAIN`, `EBX_TEMPLATE`) |
| `config.yaml` | YAML manifest with function name, region, runtime `python3.10`, handler `app.app`, memory/timeout, env vars, HTTP trigger (POST/GET/DELETE), session affinity |

The command prints: manual FC deployment steps (package → create function → create HTTP trigger → enable `Mcp-Session-Id` affinity if supported) and an IDE config template pointing at `<FC_HTTP_TRIGGER_URL>/mcp` with a masked Bearer token.

> **Security**: `config.yaml` contains your API key and Bearer token. Do not commit it to version control.

After deployment, configure clients with the trigger URL:

```json
{
  "mcpServers": {
    "easy-sandbox-remote": {
      "url": "https://<FC_HTTP_TRIGGER_URL>/mcp",
      "headers": { "Authorization": "Bearer <BEARER_TOKEN>" }
    }
  }
}
```

---

## Usage Examples

### Using in Cursor

After installing MCP, the model can automatically invoke Easy Sandbox tools in Cursor's AI chat:

1. **Code execution**: "Run this Python code in a sandbox and show me the output"
2. **Environment setup**: "Create a sandbox, install flask and sqlalchemy, then run my project"
3. **File operations**: "Write this file to the /app directory in the sandbox"
4. **Debug assistance**: "Run pip list in the sandbox to see what packages are installed"

### Typical Workflow

```mermaid
sequenceDiagram
    participant User as User
    participant AI as AI Assistant
    participant MCP as MCP Server / Sandbox

    User->>AI: Help me test this code in a sandbox
    AI->>MCP: create_sandbox
    MCP-->>AI: sandbox_id
    AI->>MCP: write_file — write code file
    AI->>MCP: run_code — execute code
    MCP-->>AI: execution result
    AI->>MCP: read_file — read result
    AI->>MCP: kill_sandbox — cleanup
    AI-->>User: return test result
```

### Run a Quick Code Snippet (HTTP, curl)

```bash
# 1. initialize (creates a session; capture Mcp-Session-Id)
curl -s http://localhost:9000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer replace_me" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'

# 2. call a tool with the session header
curl -s http://localhost:9000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer replace_me" \
  -H "Mcp-Session-Id: <SESSION_ID_FROM_STEP_1>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"run_code","arguments":{"code":"print(1+1)"}}}'

# 3. terminate the session (destroys its sandboxes)
curl -s -X DELETE http://localhost:9000/mcp \
  -H "Authorization: Bearer replace_me" \
  -H "Mcp-Session-Id: <SESSION_ID_FROM_STEP_1>"
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| IDE shows the server as failed / no tools | `ebx` not on the IDE's `PATH` | Use an absolute command path in the IDE config, e.g. `/Users/you/.venv/bin/ebx` |
| Tools list works but every call errors | API key missing or invalid | `ebx mcp status` → `auth_configured`; set `E2B_API_KEY` or `ebx config set sandbox_api_key` |
| `create_sandbox` fails after IDE restart | Backend API URL/region mismatch | Pass `--api-url` (or set `E2B_API_URL`) in the server args/env block |
| HTTP 401 on every request | Empty `EBX_MCP_AUTH_TOKEN` (fails closed) | Set a non-empty token. A local loopback server can omit the variable to disable auth. The FC artifact will not start without a token |
| HTTP 404 Unknown session | `Mcp-Session-Id` expired (idle TTL 3600 s) or instance restarted | Re-send `initialize` to create a new session |
| HTTP 503 session limit | More than 100 concurrent sessions in the process | Close idle sessions (`DELETE /mcp`) or raise `max_sessions` via `create_mcp_app()` |
| HTTP 405 on `GET /mcp` | SSE notifications not implemented | Expected — use `POST /mcp` only |

More general issues: see the [Troubleshooting guide](troubleshooting.md) and [error codes](../reference/error-codes.md).

---

## Technical Details

- **Transport protocols**: STDIO (newline-delimited JSON-RPC 2.0, protocol version 2024-11-05) and Streamable HTTP (spec 2025-06-18). `initialize` negotiates each transport's supported version — a supported requested `protocolVersion` is echoed back; missing or unsupported requests fall back to the transport's own version (so HTTP health and initialize both report 2025-06-18)
- **Sandbox management**: the server internally maintains a `SandboxManager` per session that manages the lifecycle of multiple sandbox instances
- **Default template**: `code-interpreter-v1` via `ebx mcp start`; `base` for the HTTP app and `ebx mcp deploy` artifacts. `create_sandbox` uses that server template when `template` is omitted
- **STDIO**: one message may be up to 8 MiB. A longer line is rejected and the process keeps serving. `ping` is answered while a tool call is still running
- **HTTP sessions**: idle TTL 3600 s, max 100 concurrent sessions per process, capacity exhaustion returns 503

---

## Next Steps

- [CLI Tutorial](cli-tutorial.md) — Complete CLI tutorial
- [SDK Usage Guide](sdk-usage.md) — Use the SDK directly
- [CLI Reference](../reference/cli-reference.md) — Detailed MCP command reference
- [MCP Server Design](../design/mcp-server.md) — Tools, transports, and FC deployment architecture
