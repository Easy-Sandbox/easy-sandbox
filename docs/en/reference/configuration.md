# Configuration Reference

> **Renaming Notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

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

When both `E2B_API_KEY` and `SANDBOX_API_KEY` are present, `E2B_API_KEY` takes priority.

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
```

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
ebx config get api_key

# Set a value
ebx config set api_key your-new-key
ebx config set region cn-beijing
ebx config set http_timeout 60

# Reset all configuration
ebx config reset --yes
```

### Keys Configurable via ebx config

| Config Key | Description |
|-----------|-------------|
| `api_key` | API Key |
| `api_url` | Platform API URL |
| `region` | Region |
| `http_timeout` | HTTP timeout in seconds |
| `max_retries` | Maximum retry count |
| `domain` | Data plane domain |
| `llm_api_key` | LLM API Key (for deploy) |
| `llm_model` | LLM model name (for deploy) |
| `llm_base_url` | LLM API Base URL (for deploy) |

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

The SDK searches for `.env` files in the following order:

1. `.env` in the current directory
2. `~/.ebx/.env`

`.env` file format:

```bash
E2B_API_KEY=your-api-key
SANDBOX_REGION=cn-beijing
```

The `ebx auth login` command saves the API Key to `~/.ebx/.env` (file permissions 600).

---

## Configuration File Locations Summary

| File | Path | Description |
|------|------|-------------|
| config.toml | `~/.ebx/config.toml` | SDK extended configuration |
| .env | `~/.ebx/.env` | Authentication credentials (written by auth login) |
| .env (local) | `./.env` | Project-level environment variables |
| Session storage | `~/.ebx/sessions/*.json` | Local session data |
| Template cache | `~/.ebx/templates/` | Installed templates |
