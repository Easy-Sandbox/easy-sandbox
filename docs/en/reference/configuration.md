# Configuration Reference

This document lists all Easy Sandbox configuration options, environment variables, default values, and priority rules.

---

## Configuration Priority

Configuration is loaded in the following priority order (highest to lowest):

```text
1. Code parameters (api_key=, api_url=, etc.)        ← Highest
2. Environment variables (E2B_* takes priority over SANDBOX_*)
3. .env files (./.env or ~/.ebx/.env)
4. ~/.ebx/config.toml
5. Built-in defaults                                  ← Lowest
```

Within the same priority level, E2B-prefixed variables take priority over SANDBOX-prefixed variables.

`.env` files are merged **per key**. `./.env` overrides `~/.ebx/.env` when both set the same key. A key that the project file does not set still comes from `~/.ebx/.env`.

A blank or whitespace-only value does not count. It does not hide the next layer.

## Credential resolution

Every credential uses that order at the moment it is needed. `ebx config list` shows the winner and labels it `(env)`, `(user)`, `(default)`, or `(not set)`.

| What you need | 1. Explicit argument | 2. Process environment | 3. `./.env` | 4. `~/.ebx` | 5. Default |
|---|---|---|---|---|---|
| Sandbox API key | `api_key=` | `E2B_API_KEY`, then `SANDBOX_API_KEY` | same names | `~/.ebx/.env` (`ebx config set sandbox_api_key`) | none |
| Alibaba Cloud AK/SK | `access_key_id=` / `access_key_secret=` | `ALICLOUD_ACCESS_KEY_ID` / `ALICLOUD_ACCESS_KEY_SECRET`, then `AccessKey` / `AccessSecret` | same names | `~/.ebx/.env` | none |
| ACR namespace | `--acr-namespace` | `ACR_NAMESPACE` | `ACR_NAMESPACE` | `~/.ebx/.env` (`ebx config set acr_namespace`) | none |
| GitHub token | `--token` | `GITHUB_TOKEN` | `GITHUB_TOKEN` | `~/.ebx/.env` (`ebx config set github_token`) | none |
| LLM API key | `llm_api_key=` | `EBX_LLM_API_KEY`, then `BAILIAN_CODING_PLAN_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY` | same names | `~/.ebx/.env` (`ebx config set llm_api_key`) | none |
| LLM base URL | `openai_base_url=` | `EBX_LLM_BASE_URL`, then `OPENAI_BASE_URL` | same names | `llm_base_url` in `~/.ebx/config.toml` | DashScope compatible-mode |
| LLM model | `openai_model=` | `EBX_LLM_MODEL`, then `OPENAI_MODEL` | same names | `llm_model` in `~/.ebx/config.toml` | `qwen3-coder-plus` |
| Region | command `--region` | `SANDBOX_REGION` | `SANDBOX_REGION` | `region` in `~/.ebx/config.toml` | `cn-hangzhou` |

The same chain is what these calls read:

- `Sandbox.create` and the other SDK clients (`load_config`)
- `Sandbox.deploy` (`resolve_llm_env`)
- natural-language `ebx create` (the coding agent)
- `ebx template install` / `ebx template search` (GitHub token)
- `ebx mcp install` (the sandbox API key copied into the editor config)

An older `EBX_QWEN_CODE_API_KEY` is still accepted as `llm_api_key` when the `llm_*` value is unset. In the process environment it sits after `OPENAI_API_KEY`. In `~/.ebx` it is used only after `EBX_LLM_API_KEY` and a legacy `llm_api_key` in `config.toml`.

`ebx mcp install` writes that sandbox API key into the Cursor and Claude config. `E2B_API_URL` and `SANDBOX_REGION` are copied into the same file only when the process environment sets them. `ebx mcp start` loads `~/.ebx` again, so a region saved with `ebx config set region` still applies when the editor starts the server.

`ebx config list` marks a process variable as `(env)` and either file as `(user)`. The value in the table is the one the command will use.

---

## Environment Variables

### SDK/CLI Common

| Environment Variable | Config Field | Series | Description |
|---------------------|-------------|--------|-------------|
| `E2B_API_KEY` | `api_key` | E2B | API Key (most common) |
| `E2B_API_URL` | `api_url` | E2B | Platform API URL |
| `E2B_DOMAIN` | `domain` | E2B | Data plane domain |
| `SANDBOX_API_KEY` | `api_key` | Sandbox | API Key (fallback) |
| `SANDBOX_API_BASE_URL` | `api_url` | Sandbox | Platform API URL (fallback) |
| `SANDBOX_REGION` | `region` | Sandbox | Region |
| `SANDBOX_HTTP_TIMEOUT` | `http_timeout` | Sandbox | HTTP timeout in seconds |
| `ALICLOUD_ACCESS_KEY_ID` | `access_key_id` | AK/SK | Alibaba Cloud AK |
| `ALICLOUD_ACCESS_KEY_SECRET` | `access_key_secret` | AK/SK | Alibaba Cloud SK |
| `ACR_NAMESPACE` | `acr_namespace` | ACR | ACR namespace (`ebx config set acr_namespace`, or `ebx config init`) |
| `GITHUB_TOKEN` | `github_token` | GitHub | GitHub token for template downloads (store with `ebx config set github_token`; CI: inject as a secret) |
| `EBX_LLM_API_KEY` | `llm_api_key` | LLM | LLM API key (store with `ebx config set llm_api_key`) |
| `BAILIAN_CODING_PLAN_API_KEY` | `llm_api_key` | LLM | LLM API key fallback |
| `DASHSCOPE_API_KEY` | `llm_api_key` | LLM | LLM API key fallback |
| `OPENAI_API_KEY` | `llm_api_key` | LLM | LLM API key fallback |
| `EBX_LLM_BASE_URL` | `llm_base_url` | LLM | LLM base URL |
| `OPENAI_BASE_URL` | `llm_base_url` | LLM | LLM base URL fallback |
| `EBX_LLM_MODEL` | `llm_model` | LLM | LLM model name |
| `OPENAI_MODEL` | `llm_model` | LLM | LLM model name fallback |

When both `E2B_API_KEY` and `SANDBOX_API_KEY` are present, `E2B_API_KEY` takes priority. The CLI lists that key as `sandbox_api_key`; the SDK field stays `api_key`.

For the LLM API key the environment order is `EBX_LLM_API_KEY`, then `BAILIAN_CODING_PLAN_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`. Any of those wins over `./.env`, which wins over `~/.ebx/.env`. Base URL order is `EBX_LLM_BASE_URL` then `OPENAI_BASE_URL`, then the same names in `./.env`, then the stored `llm_base_url`. Model order is `EBX_LLM_MODEL` then `OPENAI_MODEL`, then `./.env`, then the stored `llm_model`. The full chain is in [Credential resolution](#credential-resolution).

### CLI display

These variables change what a terminal shows. They are not stored by `ebx config`.

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `EBX_ACTIVITY_LINES` | `4` | How many grey lines sit under a `message... 12s` header (integer 1–10). Used by deploy, create, upload, download, template fetch, image registration, the coding-agent install, and `ebx kill --all`. |

`--json`, `--quiet`, `--ci`, `TERM=dumb`, and a non-TTY do not draw that header. See [While a command is running](../guide/cli-tutorial.md#while-a-command-is-running).

### Server-Side Environment Variables

The following environment variables are used for in-sandbox Server configuration:

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `EBX_SERVER_TOKEN` | — | Server authentication token |
| `EBX_SERVER_BASE_DIR` | — | Server working base directory |
| `EBX_SERVER_DISABLED_GROUPS` | `DEV_TOOLS,BROWSER` | Disabled capability groups (comma-separated) |
| `EBX_PTY_PORT` | — | PTY terminal WebSocket port |
| `EBX_MAX_UPLOAD_SIZE` | — | Maximum upload file size |

### Deployment Related

| Environment Variable | Description |
|---------------------|-------------|
| `BAILIAN_CODING_PLAN_API_KEY` | Bailian Coding Agent API Key (for deploy) |
| `DASHSCOPE_API_KEY` | DashScope API Key (for deploy) |
| `OPENAI_API_KEY` | OpenAI-compatible API Key (for deploy) |

---

## config.toml Configuration

Config file path: `~/.ebx/config.toml`

```toml
[transport]
api_key = "your-api-key"
api_url = "https://api.cn-hangzhou.e2b.fc.aliyuncs.com"
domain = "cn-hangzhou.e2b.fc.aliyuncs.com"
region = "cn-hangzhou"
http_timeout = 30.0
max_retries = 3

[shortcuts]
init = "template init"          # command path, not "ebx template init"
ps   = "sandbox process list"
```

`[shortcuts]` maps a top-level alias to a command path. The value does not include the `ebx` prefix. `ebx config set shortcuts.ps "ebx sandbox process list"` is rejected; use `"sandbox process list"`. A bad line already in the file is skipped at the next startup and the other aliases keep working. See [Shortcut aliases](cli-reference.md#shortcut-aliases-shortcutsalias).

---

## TransportConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `api_url` | `str` | `"https://api.cn-hangzhou.e2b.fc.aliyuncs.com"` | Platform API URL |
| `domain` | `str` | `"cn-hangzhou.e2b.fc.aliyuncs.com"` | Data plane domain |
| `region` | `str` | `"cn-hangzhou"` | Region |
| `api_key` | `str \| None` | `None` | API Key |
| `access_key_id` | `str \| None` | `None` | Alibaba Cloud AK |
| `access_key_secret` | `str \| None` | `None` | Alibaba Cloud SK |
| `http_timeout` | `float` | `30.0` | HTTP request timeout (seconds, ≥1.0) |
| `max_connections` | `int` | `100` | Maximum connections |
| `max_keepalive_connections` | `int` | `20` | Maximum keep-alive connections |
| `keepalive_expiry` | `float` | `30.0` | Keep-alive connection expiry (seconds) |
| `http2` | `bool` | `True` | Whether to enable HTTP/2 |
| `ws_ping_interval` | `float` | `30.0` | WebSocket ping interval (seconds) |
| `max_retries` | `int` | `3` | Maximum retry count |
| `retry_base_delay` | `float` | `1.0` | Retry base delay (seconds) |

### Automatic Region Derivation

When `api_url` and `domain` are not explicitly set but `region` is, the SDK automatically derives:

```text
api_url = "https://api.{region}.e2b.fc.aliyuncs.com"
domain  = "{region}.e2b.fc.aliyuncs.com"
```

---

## CLI Configuration Commands

Manage configuration via `ebx config`:

```bash
# View all configuration (with source annotations)
ebx config list

# Get a single value
ebx config get sandbox_api_key

# Set a value
ebx config set sandbox_api_key your-new-key
ebx config set region cn-beijing
ebx config set http_timeout 60

# GitHub token for template downloads (VALUE omitted → masked asterisk prompt)
ebx config set github_token
ebx config set github_token ghp_xxxxxxxxxxxx

# Clear a single stored value (returns to default / not set)
ebx config set region ""
ebx config set github_token ""
```

The `region` key set here is the **persistent default** for regional commands. A single invocation can override it with the command-level `--region`/`-r` option (accepted by `ebx list`, `ebx kill --all`, the template control-plane commands, and `ebx mcp deploy`). Resolution priority: command `--region` > `SANDBOX_REGION` > `ebx config set region` > `cn-hangzhou`.

### Keys Configurable via ebx config

| Config Key | Description |
|-----------|-------------|
| `sandbox_api_key` | Sandbox service API key (stored as `E2B_API_KEY`; `api_key` is a get/set alias) |
| `api_url` | Platform API URL |
| `region` | Region |
| `http_timeout` | HTTP timeout in seconds |
| `max_retries` | Maximum retry count |
| `domain` | Data plane domain |
| `llm_api_key` | LLM API key for NL inference and the coding agent (stored as `EBX_LLM_API_KEY`) |
| `llm_model` | LLM model name (default: `qwen3-coder-plus`) |
| `llm_base_url` | LLM API base URL, OpenAI-compatible (default: DashScope compatible-mode) |
| `access_key_id` | Alibaba Cloud AccessKey ID (🧪 experimental AK/SK auth) |
| `access_key_secret` | Alibaba Cloud AccessKey Secret (🧪 experimental AK/SK auth) |
| `acr_namespace` | ACR namespace for `ebx install` / `ebx template deploy` (stored as `ACR_NAMESPACE`) |
| `github_token` | GitHub token for template downloads (`ebx template install` / `ebx template search`; mapped to `GITHUB_TOKEN`, stored in `~/.ebx/.env`, shown masked) |

### Guided Configuration (ebx config init)

```bash
ebx config init
```

The interactive wizard prompts for: the sandbox API key, the default region, the LLM API key, the ACR namespace (`ACR_NAMESPACE`), the AccessKey ID, and the AccessKey secret. Press Enter to skip a prompt. Secrets and the namespace are stored in `~/.ebx/.env`; the region goes to `~/.ebx/config.toml`. Non-TTY environments or `--yes` never block; the equivalent `ebx config set` commands are printed instead.

### AK/SK Authentication Configuration (Experimental)

When `access_key_id` and `access_key_secret` are set via `ebx config set`, they are stored in `~/.ebx/.env` (mapped to environment variables `ALICLOUD_ACCESS_KEY_ID` and `ALICLOUD_ACCESS_KEY_SECRET` respectively). Used for AK/SK → API Key token exchange authentication.

> **Note**: This feature is experimental. The token exchange endpoint is pending FC platform confirmation. See [Authentication](../guide/authentication.md#aksk-alibaba-cloud-extended-authentication-) for details.

---

## SDK Parameter Override

Pass parameters directly in code (highest priority):

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.create(
    api_key="REPLACE_ME",
    api_url="https://api.cn-beijing.e2b.fc.aliyuncs.com",
    access_key_id="REPLACE_ME",
    access_key_secret="REPLACE_ME",
)
```

---

## .env File

The SDK reads both `.env` files and merges them per key:

1. `.env` in the current directory (wins when it sets the key)
2. `~/.ebx/.env` (used for any key the project file does not set)

`.env` file format:

```bash
E2B_API_KEY=your-api-key
SANDBOX_REGION=cn-beijing
```

The `ebx config set sandbox_api_key <KEY>` command saves the API Key to `~/.ebx/.env` (file permissions 600). Credential keys such as `github_token` (mapped to `GITHUB_TOKEN`) are stored the same way.

---

## Configuration File Locations Summary

| File | Path | Description |
|------|------|-------------|
| config.toml | `~/.ebx/config.toml` | SDK extended configuration |
| .env | `~/.ebx/.env` | Authentication credentials (written by auth login / `ebx config set`) |
| .env (local) | `./.env` | Project-level environment variables |
| Session storage | `~/.ebx/sessions/*.json` | Local session data |
| Template cache | `~/.ebx/templates/` | Installed templates |
