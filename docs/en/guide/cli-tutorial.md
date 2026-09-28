# CLI Tutorial

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

This tutorial walks you through mastering the `ebx` CLI step by step, covering the complete sandbox lifecycle, template usage, and MCP integration.

---

## Step 1: Installation

```bash
pip install easy-sandbox
```

After installation, the `ebx` command is available:

```bash
ebx --version
```

---

## Step 2: Authentication

### Set API Key via config

```bash
ebx config set api_key your-api-key
```

### Or via Environment Variable

```bash
export E2B_API_KEY="your-api-key"
```

> For more authentication methods (AK/SK, .env files, config.toml, etc.), see [Authentication](authentication.md).

---

## Step 3: Create a Sandbox

### Using the Default Template

```bash
ebx create --template base
# Output similar to:
# ✓ Sandbox created: sbx-xxxx
```

### Natural Language Creation

```bash
ebx create "a Python data analysis environment"
# The SDK infers the best template and configuration via LLM
```

### Upload Files on Creation

```bash
ebx create --template base --upload ./project/ --env MY_KEY=value
```

---

## Step 4: View and Manage Sandboxes

### List All Sandboxes

```bash
ebx list
ebx list --status running
ebx list --limit 5
```

### View Details

```bash
ebx info sbx-xxxx
```

---

## Step 5: Execute Commands in a Sandbox

### Execute a Single Command

```bash
ebx exec sbx-xxxx "echo Hello World"
ebx exec sbx-xxxx "pip install flask" --timeout 120
```

### Interactive Connection

```bash
ebx connect sbx-xxxx
# Enters interactive mode; type commands and press Enter to execute
# Type exit, quit, or Ctrl+D to leave
```

---

## Step 6: File Operations

### Upload

```bash
ebx upload sbx-xxxx ./script.py /app/script.py
ebx upload sbx-xxxx ./data/ /app/data/
```

### Download

```bash
ebx download sbx-xxxx /app/result.csv ./result.csv
```

---

## Step 7: Execute Custom Commands

`ebx run` supports two custom command mechanisms:

### Mechanism A: template.yaml Declarative

Declare shell commands in the template's `template.yaml`:

```yaml
custom_commands:
  dev:
    command: "npm run dev"
  test:
    command: "pytest {file} -v"
    description: "Run tests"
```

Execute:

```bash
ebx run sbx-xxxx dev
ebx run sbx-xxxx test --arg file=tests/test_api.py
```

### Mechanism B: @registry.command Programmatic

Register custom commands in Python code running inside the sandbox:

```python
from easy_sandbox.server.registry import registry

@registry.command("greet")
def greet(name: str) -> str:
    return f"Hello, {name}!"

registry.freeze()
```

Execute:

```bash
ebx run sbx-xxxx greet --name World
```

> `ebx run` automatically tries Mechanism A first; if the command is not found, it falls back to Mechanism B, fully transparent to the user.

---

## Step 8: Destroy a Sandbox

```bash
# Destroy a single sandbox
ebx kill sbx-xxxx

# Destroy all sandboxes (requires confirmation)
ebx kill --all

# Skip confirmation
ebx kill --all --yes
```

---

## Using Templates

### Install Templates from GitHub

```bash
ebx template install owner/repo
ebx template install owner/repo@v1.0
ebx template install owner/repo//subdir
```

### Shortcut

```bash
ebx install owner/repo
```

### Use an Installed Template

```bash
ebx create --template my-template
```

### One-Click Deploy Custom Templates

```bash
ebx template deploy ./my-template \
  --acr-namespace my-ns --acr-repo my-template
```

`template deploy` automatically performs: local Docker build → ACR push → CreateTemplate API call. See [Authoring Templates](authoring-templates.md) for details.

---

## Configuration Management

```bash
# View configuration
ebx config list
ebx config get api_key

# Set configuration
ebx config set region cn-beijing
ebx config set http_timeout 60

# Reset
ebx config reset --yes
```

Available configuration keys: `api_key`, `api_url`, `region`, `http_timeout`, `max_retries`, `domain`, `llm_api_key`, `llm_model`, `llm_base_url`.

---

## MCP Integration

Use Easy Sandbox as a local STDIO MCP Server for AI IDEs. STDIO mode does not require the HTTP transport dependencies:

```bash
# Install to Cursor
ebx mcp install --target cursor

# Install to Claude Desktop
ebx mcp install --target claude

# View MCP status
ebx mcp status

# Start manually (usually invoked automatically by the IDE)
ebx mcp start --template code-interpreter-v1
```

### Remote MCP Server Deployment Artifact

Generate a Streamable HTTP MCP artifact for manual deployment to Alibaba Cloud FC. The command does not call an FC deployment API:

```bash
# Generate files with a new Bearer token
ebx mcp deploy --generate-token --api-key $E2B_API_KEY \
  --output-dir ./deploy-artifact
```

Install `easy-sandbox[mcp]` in the HTTP runtime. Then use the official Alibaba Cloud FC console or SDK to package the artifact and create the function and HTTP trigger. Treat `config.yaml` as a provider-neutral checklist—not an FC API payload—and translate its settings through the official interface. Replace the URL and token placeholders in the printed IDE template with the deployment values.

Clients should call `DELETE /mcp` when a session ends. `GET /mcp` currently returns 501; SSE server notifications are planned for Phase 2. `config.yaml` may contain plaintext credentials, so do not commit the artifact or completed IDE configuration to version control.

---

## Global Options

The `ebx` command supports the following global options, which can be used before any subcommand:

| Option | Description |
|--------|-------------|
| `--json` / `-j` | Output in JSON format for easy script parsing |
| `--quiet` / `-q` | Minimize output |
| `--no-color` | Disable colored output |
| `--ci` | CI/CD mode (equivalent to `--quiet --no-color --json`) |

For a detailed list of global options (including `--verbose`, `--log-level`, `--timeout`, `--region`, etc.), see [CLI Reference — Global Options](../reference/cli-reference.md#global-options).

---

## CI/CD Mode

Use the `--ci` flag in automation environments:

```bash
ebx --ci create --template base
# Equivalent to --quiet --no-color --json
```

Combined with `--json` for machine-readable output:

```bash
ebx --json list | jq '.[] | .sandbox_id'
```

---

## Next Steps

- [SDK Usage Guide](sdk-usage.md) — Use Easy Sandbox in Python code
- [Authentication](authentication.md) — Deep dive into authentication methods and configuration priority
- [Using Templates](using-templates.md) — Discover, install, and use templates
- [CLI Reference](../reference/cli-reference.md) — Complete reference for all commands
