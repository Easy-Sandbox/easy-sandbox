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

### Interactive Login

```bash
ebx auth login
# Follow the prompt to enter your API Key, saved to ~/.ebx/.env
```

### Verify Status

```bash
ebx auth status
# Example output:
#   API Key: abcd****efgh
#   Source: /Users/you/.ebx/.env
#   Auth Mode: api_key
```

### Or via Environment Variable

```bash
export E2B_API_KEY="your-api-key"
```

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

If the template defines custom commands (or commands registered via `@sandbox.register`), you can use `ebx run` to execute them:

```bash
# View available commands
ebx run sbx-xxxx --help

# Execute a command
ebx run sbx-xxxx dev --arg file=tests/
ebx run sbx-xxxx demo --x 1 --y hello
```

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

---

## Session Management

A session associates a sandbox with a name, making it easy to reconnect repeatedly:

```bash
# Start a session
ebx session start my-project --template base

# Connect to a session
ebx session connect my-project

# List all sessions
ebx session list

# View session info
ebx session info my-project

# Stop a session
ebx session stop my-project
```

---

## Secret Management

```bash
# Create a secret (secure input)
ebx secret create MY_TOKEN

# List secrets
ebx secret list

# Inject into a sandbox
ebx secret inject sbx-xxxx -s MY_TOKEN -s ANOTHER_SECRET

# Delete a secret
ebx secret delete MY_TOKEN
```

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

Use Easy Sandbox as an MCP Server for AI IDEs:

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

---

## Global Options

The `ebx` command supports the following global options, which can be used before any subcommand:

| Option | Description |
|--------|-------------|
| `--json` / `-j` | Output in JSON format for easy script parsing |
| `--quiet` / `-q` | Minimize output |
| `--no-color` | Disable colored output |
| `--ci` | CI/CD mode (equivalent to `--quiet --no-color --json`) |

For a detailed list of global options (including `--verbose`, `--log-level`, `--timeout`, `--region`, etc.), see [CLI Reference — Global Options](../reference/cli-reference.md#全局选项).

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
