# CLI Reference

> **Renaming Notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

## Global Options

```text
ebx [global-options] <subcommand> [subcommand-options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--json` | `-j` | Output in JSON format |
| `--quiet` | `-q` | Minimize output |
| `--verbose` | `-v` | Verbose output (DEBUG level logging) |
| `--no-color` | | Disable colored output |
| `--log-level` | | Set log level: `DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `--ci` | | CI/CD mode (equivalent to `--quiet --no-color --json`) |
| `--timeout` | `-t` | Default timeout in seconds (default 300) |
| `--region` | `-r` | Region (default cn-hangzhou) |
| `--profile` | `-p` | [Reserved] Configuration profile |
| `--version` | | Show version number |

---

## Sandbox Lifecycle Commands

### ebx create

Create a new sandbox. Optionally provide a natural language description to automatically infer the template.

```bash
ebx create [DESCRIPTION] [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--template` | `-T` | Sandbox template name |
| `--upload` | `-u` | Local file/directory to auto-upload after creation |
| `--timeout` | `-t` | Timeout in seconds |
| `--env` | `-e` | Environment variable `KEY=VALUE` (repeatable) |
| `--metadata` | `-m` | Metadata `KEY=VALUE` (repeatable) |

```bash
# Create with default template
ebx create --template base

# Natural language creation
ebx create "A Python data analysis environment"

# Create and upload files
ebx create --template base --upload ./project/ --env MY_KEY=value
```

### ebx list

List sandboxes.

```bash
ebx list [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--status` | `-s` | Filter by status: `running`/`stopped`/`creating`/`paused`/`error` |
| `--limit` | `-l` | Maximum number of results (default 20) |

### ebx info

View sandbox details.

```bash
ebx info <SANDBOX_ID>
```

### ebx kill

Destroy a sandbox.

```bash
ebx kill <SANDBOX_ID> [options]
ebx kill --all [options]
```

| Option | Description |
|--------|-------------|
| `--all` | Destroy all running sandboxes |
| `--yes` / `-y` | Skip confirmation |

### ebx exec

Execute a command in a sandbox.

```bash
ebx exec <SANDBOX_ID> <COMMAND> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--timeout` | `-t` | Timeout in seconds (default 60) |
| `--cwd` | | Working directory |

```bash
ebx exec sbx-xxxx "echo hello"
ebx exec sbx-xxxx "pip install flask" --timeout 120
```

### ebx connect

Interactively connect to a sandbox (similar to SSH).

```bash
ebx connect <SANDBOX_ID>
```

Type `exit`, `quit`, or `Ctrl+D` to disconnect. Each command executes in an independent process.

---

## File Operation Commands

### ebx upload

Upload a local file or directory to a sandbox.

```bash
ebx upload <SANDBOX_ID> <LOCAL_PATH> <REMOTE_PATH>
```

```bash
ebx upload sbx-xxxx ./script.py /app/script.py
ebx upload sbx-xxxx ./data/ /app/data/
```

### ebx download

Download a file from a sandbox to local.

```bash
ebx download <SANDBOX_ID> <REMOTE_PATH> <LOCAL_PATH>
```

```bash
ebx download sbx-xxxx /app/result.csv ./result.csv
ebx download sbx-xxxx /app/output.log .
```

---

## Custom Commands

### ebx run

Execute a custom command defined in the template or registered via `@sandbox.register`.

```bash
ebx run <SANDBOX_ID> <COMMAND_NAME> [options]
```

Supports two argument styles:

```bash
# Legacy style
ebx run sbx-xxxx dev --arg file=tests/

# New style
ebx run sbx-xxxx demo --x 1 --y hello
```

---

## Authentication Commands — ebx auth

### ebx auth login

```bash
ebx auth login [--api-key KEY]
```

Interactively enter an API Key and save it to `~/.ebx/.env`.

### ebx auth logout

```bash
ebx auth logout
```

Remove saved credentials.

### ebx auth status

```bash
ebx auth status
```

Show current authentication status (API Key / AK/SK / unauthenticated).

---

## Configuration Commands — ebx config

### ebx config get

```bash
ebx config get <KEY>
```

Available config keys: `api_key`, `api_url`, `region`, `http_timeout`, `max_retries`, `domain`, `llm_api_key`, `llm_model`, `llm_base_url`.

### ebx config set

```bash
ebx config set <KEY> <VALUE>
```

### ebx config list

```bash
ebx config list
```

Show all configuration values with their sources (user/default).

### ebx config reset

```bash
ebx config reset [--yes/-y]
```

---

## Template Commands — ebx template

### ebx template install

Install a template from GitHub or a local directory.

```bash
ebx template install <TEMPLATE_REF> [options]
```

| Option | Description |
|--------|-------------|
| `--registry-url` | Registry URL (default GitHub) |
| `--registry-type` | `github` / `local` (auto-detected) |
| `--token` | Private repository access token |
| `--alias` / `-a` | Template alias |

```bash
ebx template install owner/repo
ebx template install owner/repo@v1.0
ebx template install owner/repo//subdir
ebx template install ./my-template --registry-type local
```

### ebx install (shortcut)

Top-level shortcut for `ebx template install`:

```bash
ebx install owner/repo
```

### ebx template create

Create a sandbox template from an existing container image. Uses the official Alibaba Cloud FCSandbox CreateTemplate API.

> **Prerequisites**: Requires AK/SK credentials and `pip install "easy-sandbox[alicloud]"` SDK extra (or install with CLI via `pip install "easy-sandbox[cli,alicloud]"`).

```bash
ebx template create <IMAGE> --name <NAME> [options]
```

| Option | Description |
|--------|-------------|
| `--name` / `-n` | Template name (required) |
| `--team-id` | Team ID (or env `TEAM_ID` / `E2B_TEAM_ID`; auto-resolved if omitted) |
| `--cpu` | CPU cores (default 2) |
| `--memory` | Memory in MB (default 2048) |
| `--disk-size` | Disk size in MB |
| `--internet-access/--no-internet-access` | Internet access (default: platform decides) |
| `--generation` | Sandbox generation (default 1) |
| `--envd-inject/--no-envd-inject` | Enable envd injection |
| `--registry-type` | Registry type: `acr` / `acree` (auto-detected) |
| `--acree-instance-id` | ACR EE instance ID |
| `--registry-username` | Registry login username |
| `--registry-password` | Registry login password |
| `--start-cmd` | Container start command |
| `--ready-cmd` | Container readiness check command |

```bash
# Create from a pushed ACR image
ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag --name my-template

# Specify resources
ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \
  --name my-tpl --cpu 4 --memory 4096 --disk-size 10240 --internet-access
```

### ebx template build-local

Local Docker build → ACR push → create sandbox template.

Defaults to the **official CreateTemplate API** (requires AK/SK and `easy-sandbox[alicloud]`; if CLI is not yet installed use `pip install "easy-sandbox[cli,alicloud]"`).
Legacy scripts should use `--legacy-api` to switch back to v3/v2 API.

```bash
ebx template build-local <TEMPLATE_DIR> [options]
```

| Option | Description |
|--------|-------------|
| `--acr-registry` | ACR registry host (default `registry.cn-hangzhou.aliyuncs.com`) |
| `--acr-namespace` | ACR namespace (required) |
| `--acr-repo` | ACR repository name (defaults to template dir name) |
| `--acr-username` / `--acr-password` | ACR credentials (defaults to AK/SK from .env) |
| `--acree-instance-id` | ACR EE instance ID |
| `--tag` / `-t` | Docker image tag (default `latest`) |
| `--platform` | Target platform (default `linux/amd64`) |
| `--cpu` | CPU cores |
| `--memory` | Memory in MB |
| `--disk-size` | Disk size in MB (official API only) |
| `--internet-access/--no-internet-access` | Internet access (official API only) |
| `--official-api/--legacy-api` | Use official API (default) or legacy v3/v2 API |
| `--team-id` | Team ID |
| `--envd-inject/--no-envd-inject` | envd injection (default enabled) |
| `--generation` | Sandbox generation |
| `--dockerfile` / `-f` | Custom Dockerfile path |
| `--start-cmd` / `--ready-cmd` | Start/readiness command |
| `--timeout` | Build timeout in seconds |

```bash
# Default official API
ebx template build-local ./examples/templates/python-hello \
  --acr-namespace my-ns --acr-repo python-hello

# Specify disk and internet
ebx template build-local ./my-template \
  --acr-namespace prod --disk-size 10240 --internet-access

# ACR EE instance
ebx template build-local ./my-template \
  --acr-namespace prod --acree-instance-id cri-xxx

# Legacy API
ebx template build-local ./my-template \
  --acr-namespace prod --legacy-api
```

> **Two paths explained**:
> - **Official path** (default): `build-local` → Docker build → ACR push → `CreateTemplate` API. Requires AK/SK and `easy-sandbox[alicloud]`; default region is `cn-hangzhou`.
> - **Legacy path**: `build-local --legacy-api` → Docker build → ACR push → v3/v2 Platform API. Requires E2B API Key.
> - **Image-only creation**: `ebx template create <IMAGE>` calls CreateTemplate API only — no local build.

---

## Session Commands — ebx session

### ebx session start

```bash
ebx session start <NAME> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--template` | `-T` | Template (default base) |
| `--timeout` | `-t` | Timeout in seconds |
| `--env` | `-e` | Environment variable `KEY=VALUE` |
| `--metadata` | `-m` | Metadata `KEY=VALUE` |

### ebx session connect

```bash
ebx session connect <NAME>
```

### ebx session list

```bash
ebx session list
```

### ebx session stop

```bash
ebx session stop <NAME> [--keep-alive]
```

`--keep-alive` only unregisters the session tracking without destroying the sandbox.

### ebx session info

```bash
ebx session info <NAME>
```

---

## Secret Commands — ebx secret

### ebx secret create

```bash
ebx secret create <NAME>
```

Interactively and securely enter the secret value.

### ebx secret list

```bash
ebx secret list
```

### ebx secret delete

```bash
ebx secret delete <NAME>
```

### ebx secret inject

```bash
ebx secret inject <SANDBOX_ID> -s SECRET_NAME [-s ANOTHER_SECRET]
```

---

## MCP Commands — ebx mcp

### ebx mcp install

```bash
ebx mcp install --target <cursor|claude|vscode>
```

Write the MCP Server configuration to the target IDE's config file.

### ebx mcp start

```bash
ebx mcp start [options]
```

| Option | Description |
|--------|-------------|
| `--template` | Default template (default code-interpreter-v1) |
| `--api-key` | API Key override |
| `--api-url` | API URL override |
| `--domain` | Domain override |

Start the MCP Server in STDIO mode (typically invoked automatically by the IDE).

### ebx mcp status

```bash
ebx mcp status
```

Show MCP Server status, number of available tools, and installation status for each IDE.

---

## Deploy Command — ebx deploy

```bash
ebx deploy <PROJECT_PATH> <DESCRIPTION> [options]
```

Automatically deploy a project using the qwen-code agent. See [Deploy & Build](../guide/deploy-and-build.md) for details.

---

## Skill Commands — ebx skill

### ebx skill search

```bash
ebx skill search <QUERY>
```

### ebx skill install

```bash
ebx skill install <SKILL_REF> [--target cursor|vscode|claude|project|global]
```

---

## sandbox Subcommand Group

`ebx sandbox` provides the same sandbox operations as the top-level commands, plus extended subgroups:

```bash
ebx sandbox create / list / info / kill / exec / connect / upload / download / run
```

### ebx sandbox files — Extended File Operations

| Subcommand | Description | Main Parameters |
|------------|-------------|-----------------|
| `list` | List directory contents | `SANDBOX_ID`, `--path` (default /home/user), `--recursive` |
| `stat` | View file/directory info | `SANDBOX_ID`, `--path` (required) |
| `mkdir` | Create directory (including parents) | `SANDBOX_ID`, `--path` (required) |
| `rm` | Delete file/directory | `SANDBOX_ID`, `--path` (required), `--yes` |
| `mv` | Move/rename file | `SANDBOX_ID`, `--source`, `--dest` |
| `search` | Search files by glob pattern | `SANDBOX_ID`, `--path`, `--pattern`, `--max-depth` |

```bash
ebx sandbox files list sbx-xxxx --path /app --recursive
ebx sandbox files search sbx-xxxx --path /home/user --pattern "*.py"
```

### ebx sandbox process — Process Management

| Subcommand | Description | Main Parameters |
|------------|-------------|-----------------|
| `list` | List running processes | `SANDBOX_ID` |
| `start` | Start a background process | `SANDBOX_ID`, `--command` (required), `--timeout`, `--cwd` |
| `info` | View process details for a given PID | `SANDBOX_ID`, `PID` |
| `signal` | Send a signal to a process | `SANDBOX_ID`, `PID`, `--signal` (default 15/SIGTERM) |

```bash
ebx sandbox process list sbx-xxxx
ebx sandbox process start sbx-xxxx --command "python app.py" --cwd /app
ebx sandbox process signal sbx-xxxx 1234 --signal 9
```

### ebx sandbox system — System Information

| Subcommand | Description | Main Parameters |
|------------|-------------|-----------------|
| `info` | View system info (OS, CPU, memory, disk) | `SANDBOX_ID` |
| `env` | View environment variables (sensitive values auto-filtered) | `SANDBOX_ID`, `--filter` |
| `ports` | View listening TCP ports | `SANDBOX_ID` |
| `packages` | List installed packages (pip/npm) | `SANDBOX_ID`, `--manager` (default pip) |
| `metrics` | View resource usage (CPU load, disk usage) | `SANDBOX_ID` |

```bash
ebx sandbox system info sbx-xxxx
ebx sandbox system packages sbx-xxxx --manager npm
ebx sandbox system metrics sbx-xxxx
```

### ebx sandbox capabilities — Capability Group Status

View the currently enabled capability groups for a sandbox (e.g., shell, files, code, terminal, etc.).

```bash
ebx sandbox capabilities <SANDBOX_ID>
```

### ebx sandbox shell-stream — SSE Streaming Shell

Stream command execution output in real-time via SSE (unlike `exec`, output is printed line by line).

```bash
ebx sandbox shell-stream <SANDBOX_ID> --command "pip install numpy"
ebx sandbox shell-stream <SANDBOX_ID> -c "make build" --cwd /app
```

| Option | Short | Description |
|--------|-------|-------------|
| `--command` | `-c` | Command to execute (required) |
| `--timeout` | `-t` | Timeout in seconds (default 300) |
| `--cwd` | | Working directory |

---

## Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Argument error |
| 3 | Authentication failure |
| 4 | Resource not found |
| 5 | Timeout |
| 6 | Quota exceeded |
