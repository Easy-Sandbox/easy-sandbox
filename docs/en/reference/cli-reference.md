# CLI Reference

> **Renaming Notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

## Command Overview

```
ebx
├── Top-level Shortcuts (12)
│   create / list / info / kill / exec / connect / run / upload / download / deploy / install / init
├── sandbox Subgroup (17)
│   ├── files: list / stat / mkdir / rm / mv / search
│   ├── process: list / start / info / signal
│   ├── system: info / env / ports / packages / metrics
│   ├── capabilities
│   └── shell-stream
├── template (10)
│   init / deploy / build / push / create / install / list / info / delete / search
├── config (4)
│   get / set / list / reset
└── mcp (4)
    install / start / status / deploy
```

---

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

Type `exit`, `quit`, or `Ctrl+D` to disconnect. Each interactive command has a 30-second timeout. Each command executes in an independent process.

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

Execute a custom command defined in the template or registered via `@registry.command`.

```bash
ebx run <SANDBOX_ID> <COMMAND_NAME> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--arg` | `-a` | Argument `KEY=VALUE` (repeatable) |

Supports two argument styles:

```bash
# Legacy style
ebx run sbx-xxxx dev --arg file=tests/

# New style (pass-through --key value)
ebx run sbx-xxxx demo --x 1 --y hello
```

#### Two Custom Command Mechanisms

**Mechanism A: template.yaml Declarative**

Define simple shell commands in `template.yaml` via `custom_commands`, using placeholders for parameters:

```yaml
custom_commands:
  dev:
    command: "npm run dev"
  test:
    command: "pytest {file} -v"
    description: "Run tests"
```

Usage example:

```bash
ebx run sbx-xxxx test --arg file=tests/test_api.py
# Actually executes: pytest tests/test_api.py -v
```

**Mechanism B: @registry.command Programmatic**

Register custom commands via decorators in Python code running inside the sandbox, with typed parameters and complex logic:

```python
from easy_sandbox.server.registry import registry

@registry.command("greet")
def greet(name: str) -> str:
    return f"Hello, {name}!"

registry.freeze()
```

Usage example:

```bash
ebx run sbx-xxxx greet --name World
```

**Resolution logic**: `ebx run` invokes `Sandbox.custom()` which first tries Mechanism A (template `custom_commands`); if the command is not found, it automatically falls back to Mechanism B (`@registry.command` on SandboxServer), transparent to the user. The unified return type is `CommandResult`, containing `value`, `stdout`, `stderr`, `exit_code`, `execution_time`, and `source` (`"template"` or `"server"`).

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

### ebx template init

Scaffold a new template directory from a built-in case, so you don't have to hand-write `template.yaml` / `Dockerfile` / `commands.py`.

```bash
ebx template init [DIRECTORY] [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--template` | `-t` | Built-in scaffold case (`python`, `node`, `minimal`) |
| `--from` | | Fetch template source from a registry ref |
| `--name` | | Template name |
| `--list` | | List available scaffold cases |
| `--force` | | Overwrite existing files |

**DIRECTORY behaviour**: when `DIRECTORY` is omitted, a new subdirectory `./<name>` is created in the current working directory. The `<name>` is resolved with the following priority:

1. `--name` value (highest)
2. Scaffold case name (the `-t/--template` value, e.g. `python`)
3. Template name fetched via `--from`

```bash
# List available scaffold cases
ebx template init --list

# Scaffold a Python template — DIRECTORY omitted → creates ./python/
ebx template init -t python

# Explicit --name → creates ./myapp/
ebx template init -t python --name myapp

# Explicit DIRECTORY → uses that directory
ebx template init -t python ./my-template

# From a registry ref — DIRECTORY omitted → creates ./<template-name>/
ebx template init --from owner/repo
```

Example output of `--list`:

```
  python       Python 3.11 sandbox with shell, files, and code capabilities
  node         Node.js 20 sandbox with shell, files, and code capabilities
  minimal      Bare-minimum template with only template.yaml + Dockerfile
```

The scaffold prints the created files and the next steps:

```
✅ Template 'my-template' created in ./my-template
Created files:
  Dockerfile
  README.md
  commands.py
  template.yaml

Next steps:
  ebx template deploy ./my-template --acr-namespace <ns>
  ebx install ./my-template --acr-namespace <ns>
```

### ebx init (shortcut)

Top-level shortcut for `ebx template init` — behaviour is identical, including DIRECTORY auto-creation when omitted (see above):

```text
Usage: ebx init [OPTIONS] [DIRECTORY]

  Scaffold a new template (shortcut for 'ebx template init').

Options:
  -t, --template TEXT  Built-in scaffold case (python, node, minimal)
  --from TEXT          Fetch template source from a registry ref
  --name TEXT          Template name
  --list               List available scaffold cases
  --force              Overwrite existing files
  --help               Show this message and exit.
```

### ebx template deploy

One-click deployment: local Docker build → ACR push → create sandbox template (i.e., the end-to-end pipeline of build + push + create).

Defaults to the **official CreateTemplate API** (requires AK/SK and `easy-sandbox[alicloud]`; if CLI is not yet installed use `pip install "easy-sandbox[cli,alicloud]"`).
Legacy scripts should use `--legacy-api` to switch back to v3/v2 API.

```bash
ebx template deploy <TEMPLATE_DIR> [options]
```

| Option | Description |
|--------|-------------|
| `--acr-registry` | ACR registry host (default `registry.cn-hangzhou.aliyuncs.com`) |
| `--acr-namespace` | ACR namespace (resolved via CLI > environment variable > `.env` file; errors if not found anywhere — see "Parameter Defaults & Priority" below) |
| `--acr-repo` | ACR repository name (defaults to the `name` field in the template directory's `template.yaml`, then the template dir name) |
| `--acr-username` / `--acr-password` | ACR credentials (defaults to AK/SK from .env) |
| `--acree-instance-id` | ACR EE instance ID |
| `--tag` / `-t` | Docker image tag (default `latest`) |
| `--platform` | Target platform (default `linux/amd64`) |
| `--cpu` | CPU cores (defaults to `resources.cpu` in `template.yaml`, fallback 2) |
| `--memory` | Memory in MB (defaults to `resources.memory` in `template.yaml`, fallback 2048) |
| `--disk-size` | Disk size in MB (official API only) |
| `--internet-access/--no-internet-access` | Internet access (official API only) |
| `--official-api/--legacy-api` | Use official API (default) or legacy v3/v2 API |
| `--team-id` | Team ID |
| `--envd-inject/--no-envd-inject` | envd injection (default enabled) |
| `--generation` | Sandbox generation (1 = first-gen rund, 2 = second-gen MicroVM Beta; default 1; can also be read from `template.yaml` `generation` field) |
| `--target-image` | Target image ref for envd copy (auto-derived with a random suffix when omitted) |
| `--dockerfile` / `-f` | Custom Dockerfile path |
| `--start-cmd` / `--ready-cmd` | Start/readiness command |
| `--timeout` | Build timeout in seconds |
| `--vpc-id` | VPC ID for ACR access (env: ACR_VPC_ID) |
| `--vswitch-ids` | VSwitch IDs (env: ACR_VSWITCH_IDS) |
| `--security-group-id` | Security group ID (env: ACR_SECURITY_GROUP_ID) |
| `--alias` / `-a` | Template alias (defaults to the resolved repository name) |

```bash
# One-click deploy (default official API)
ebx template deploy ./examples/templates/python-hello \
  --acr-namespace my-ns --acr-repo python-hello

# Specify disk and internet
ebx template deploy ./my-template \
  --acr-namespace prod --disk-size 10240 --internet-access

# ACR EE instance
ebx template deploy ./my-template \
  --acr-namespace prod --acree-instance-id cri-xxx

# Legacy API
ebx template deploy ./my-template \
  --acr-namespace prod --legacy-api
```

> **Three paths explained**:
> - **One-click deploy** (recommended): `template deploy` → Docker build → ACR push → `CreateTemplate` API.
> - **Step-by-step**: `template build` → `template push` → `template create`, for scenarios that need custom intermediate steps.
> - **Image-only creation**: `ebx template create <IMAGE>` calls CreateTemplate API only — no local build.

#### Parameter Defaults & Priority

Parameters for `template build` / `template deploy` are resolved through the following **5-level priority chain** (highest first):

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | Explicit CLI flag | e.g., `--acr-namespace my-ns` (highest priority) |
| 2 | OS environment variable | e.g., `ACR_NAMESPACE` |
| 3 | `.env` file in the current working directory | e.g., `ACR_NAMESPACE=serverless-sandbox-test` in `.env` |
| 4 | `template.yaml` in the template directory | `name` → `--acr-repo`/`--alias`; `resources.cpu` → `--cpu`; `resources.memory` → `--memory` |
| 5 | Hardcoded fallback | cpu=2, memory=2048, tag=latest, platform=linux/amd64 (lowest priority) |

Default resolution order per parameter:

| Parameter | Resolution order |
|-----------|------------------|
| `--acr-namespace` | CLI > env var `ACR_NAMESPACE` > `.env` file; raises a friendly `UsageError` if not found anywhere (still **effectively required** — it just no longer has to appear on the command line) |
| `--acr-repo` | CLI > `name` in `template.yaml` > template directory name |
| `--alias` | CLI > resolved repository name |
| `--cpu` | CLI > `resources.cpu` in `template.yaml` > `2` |
| `--memory` | CLI > `resources.memory` in `template.yaml` > `2048` |
| `--tag` | CLI > `latest` |
| `--platform` | CLI > `linux/amd64` |

Example `template.yaml` fields used for resolution:

```yaml
name: node-web          # → --acr-repo / --alias
resources:
  cpu: 2                # → --cpu
  memory: 2048          # → --memory
```

#### `.env` File Support

The CLI automatically reads the `.env` file in the **current working directory**, which can provide `ACR_NAMESPACE` and other settings:

```bash
# .env
ACR_NAMESPACE=serverless-sandbox-test
```

- OS environment variables take precedence over the `.env` file.
- It is recommended to add `.env` to `.gitignore` to avoid leaking configuration.

#### Minimal Usage

Thanks to automatic resolution from `template.yaml` and `.env`, most parameters can be omitted:

```bash
# When ACR_NAMESPACE is set in .env, just pass the template directory:
ebx template deploy ./examples/templates/node-web
ebx template build ./examples/templates/node-web

# Without a .env file, specify the namespace inline:
ebx template deploy ./examples/templates/node-web --acr-namespace serverless-sandbox-test
```

Repository name, alias, CPU, and memory are read automatically from the template directory's `template.yaml` — no need to repeat them.

### ebx template build

Build Docker image and push to ACR + register template only (same parameters as `deploy`).

```bash
ebx template build <TEMPLATE_DIR> [options]
```

Parameters are the same as `template deploy` (including `--target-image` and `--generation`); see the options table and the "Parameter Defaults & Priority" section above.

### ebx template push

Push an existing local image to ACR only.

```bash
ebx template push <IMAGE> [options]
```

| Option | Description |
|--------|-------------|
| `--acr-registry` | ACR registry host (default `registry.cn-hangzhou.aliyuncs.com`) |
| `--acr-namespace` | ACR namespace (required) |
| `--acr-username` / `--acr-password` | ACR credentials |
| `--acree-instance-id` | ACR EE instance ID |

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
| `--generation` | Sandbox generation (1 = first-gen rund, 2 = second-gen MicroVM Beta; default 1; can also be read from `template.yaml` `generation` field) |
| `--target-image` | Target image ref for envd copy (auto-derived with a random suffix when omitted) |
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

### ebx template install

Download a template and (by default) build + deploy it. By default, `install` downloads the template, then runs docker build, pushes to ACR, and creates a sandbox template via the official API. Use `--download-only` to skip the build/deploy step and only download to the local cache (`~/.ebx/templates/`).

```bash
ebx template install <TEMPLATE_REF> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--registry-url` | | Registry URL (default GitHub) |
| `--registry-type` | | `github` / `local` (auto-detected if not specified) |
| `--token` | | Private repository access token |
| `--alias` | `-a` | Template alias |
| `--download-only` | | Only download to local cache (skip build and deploy) |
| `--dir` | | Download template source to a custom directory instead of the default cache (`~/.ebx/templates`) |
| `--acr-namespace` | | ACR namespace for deploy (env `ACR_NAMESPACE`, or set in `.env`) |
| `--cpu` | | CPU cores (default: from `template.yaml` or 2) |
| `--memory` | | Memory in MB (default: from `template.yaml` or 2048) |
| `--yes` | `-y` | Skip confirmation prompt |

```bash
ebx install owner/repo --acr-namespace my-ns    # Download + build + deploy
ebx install owner/repo --download-only          # Download only
ebx install owner/repo//subdir --download-only  # Subdirectory of a repo
ebx install ./my-template --acr-namespace ns    # Local dir + deploy
ebx install owner/repo@v1.0 --yes               # Skip confirmation
```

> ⚠️ **Cost & safety**: without `--download-only`, `install` pushes an image to ACR and calls the official `CreateTemplate` API — these may incur charges on your Alibaba Cloud account. If no ACR namespace is resolved (via `--acr-namespace`, `ACR_NAMESPACE`, or `.env`), install stops before building and prints how to provide one.

### ebx install (shortcut)

Top-level shortcut for `ebx template install` (same options — including `--dir` — and default full-pipeline behavior):

```bash
ebx install owner/repo --acr-namespace my-ns
ebx install owner/repo --download-only
```

### ebx template list

List available templates.

```bash
ebx template list [options]
```

| Option | Description |
|--------|-------------|
| `--official-api/--no-official-api` | Use official Alibaba Cloud API (default false) |

### ebx template info

Show template details.

```bash
ebx template info <TEMPLATE_ID> [options]
```

| Argument/Option | Description |
|-----------------|-------------|
| `TEMPLATE_ID` | Template ID (required) |
| `--official-api/--no-official-api` | Use official Alibaba Cloud API |

### ebx template delete

Delete a template.

```bash
ebx template delete <TEMPLATE_ID>
```

### ebx template search

Search templates.

```bash
ebx template search <QUERY> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--tag` | `-t` | Filter by tag |
| `--status` | `-s` | Filter by status |

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

Start the local MCP Server in STDIO mode (typically invoked automatically by the IDE). This mode does not require the HTTP transport dependencies.

### ebx mcp status

```bash
ebx mcp status
```

Show MCP Server status, number of available tools, and installation status for each IDE.

### ebx mcp deploy

```bash
ebx mcp deploy [options]
```

Generate an artifact for manually deploying the remote MCP Server to Alibaba Cloud Function Compute (FC), using MCP Streamable HTTP (2025-06-18). This command does not call an FC deployment API. The HTTP runtime requires `easy-sandbox[mcp]`; if Starlette is unavailable, application creation raises a clear `RuntimeError`.

| Option | Description |
|--------|-------------|
| `--name` | FC function name (default: easy-sandbox-mcp) |
| `--region` | FC region (default: cn-hangzhou) |
| `--template` | Default sandbox template |
| `--memory` | FC function memory in MB (default: 512) |
| `--timeout` | FC function timeout in seconds (default: 600) |
| `--auth-token-file` | Path to Bearer token file |
| `--generate-token` | Auto-generate a random Bearer token |
| `--enable-session-affinity/--no-session-affinity` | Enable Mcp-Session-Id affinity (default: enabled) |
| `--api-key` | E2B_API_KEY to inject into FC environment |
| `--custom-domain` | Custom domain for the MCP endpoint |
| `--output-dir` | Write the FC deployment artifact to this directory |

**Examples:**

```bash
# Generate an artifact with an automatically generated token
ebx mcp deploy --generate-token --api-key $E2B_API_KEY \
  --output-dir ./deploy-artifact

# Generate an artifact using a token file
ebx mcp deploy --auth-token-file ./token.txt --region cn-shanghai \
  --output-dir ./deploy-artifact
```

The command writes `requirements.txt`, `app.py`, and `config.yaml`, then prints manual steps. `config.yaml` is a provider-neutral manifest, not an FC API payload. Use the official Alibaba Cloud FC console or SDK to package the artifact, create the function and HTTP trigger, and translate the manifest settings. Replace `<FC_HTTP_TRIGGER_URL>` and `<BEARER_TOKEN>` in the IDE template after deployment.

`POST /mcp` handles requests and `DELETE /mcp` terminates a session. Clients should call `DELETE /mcp` when finished. `GET /mcp` currently returns 501; SSE server notifications are deferred to Phase 2. Session affinity requires FC support for routing the same `Mcp-Session-Id` to the same instance.

`config.yaml` can contain `E2B_API_KEY` and the Bearer token in plaintext. Do not commit the artifact or a completed IDE configuration to version control.

---

## Deploy Command — ebx deploy

```bash
ebx deploy [PATH] [INSTRUCTION] [options]
```

Automatically deploy a project using the qwen-code agent. See [Deploy & Build](../guide/deploy-and-build.md) for details.

| Argument/Option | Short | Description |
|-----------------|-------|-------------|
| `PATH` | | Project path (optional) |
| `INSTRUCTION` | | Natural language deploy instruction (optional) |
| `--instruction` | `-i` | Natural language deploy instruction (alternative to positional INSTRUCTION) |
| `--max-wall-time` | | Maximum execution time for qwen-code agent (default: "10m") |
| `--max-tool-calls` | | Maximum tool calls for qwen-code agent (default: 100) |
| `--alias` | `-a` | Template alias (traditional mode) |
| `--watch` | | Watch for file changes and auto-redeploy (traditional mode) |
| `--traditional` | | Use traditional build+run mode instead of AI deploy |

---

## sandbox Subcommand Group

`ebx sandbox` provides the same sandbox operations as the top-level commands, plus extended subgroups:

```bash
ebx sandbox create / list / info / kill / exec / connect / upload / download / run
```

### ebx sandbox files — Extended File Operations

| Subcommand | Description | Main Parameters |
|------------|-------------|-----------------|
| `list` | List directory contents | `SANDBOX_ID`, `--path -p` (default /home/user), `--recursive -r` |
| `stat` | View file/directory info | `SANDBOX_ID`, `--path -p` (required) |
| `mkdir` | Create directory (including parents) | `SANDBOX_ID`, `--path -p` (required) |
| `rm` | Delete file/directory | `SANDBOX_ID`, `--path -p` (required), `--yes -y` |
| `mv` | Move/rename file | `SANDBOX_ID`, `--source -s` (required), `--dest -d` (required) |
| `search` | Search files by glob pattern | `SANDBOX_ID`, `--path -p` (required), `--pattern` (required), `--max-depth` (default 5) |

```bash
ebx sandbox files list sbx-xxxx --path /app --recursive
ebx sandbox files stat sbx-xxxx --path /app/main.py
ebx sandbox files mkdir sbx-xxxx --path /app/data
ebx sandbox files rm sbx-xxxx --path /app/temp.log --yes
ebx sandbox files mv sbx-xxxx --source /app/old.py --dest /app/new.py
ebx sandbox files search sbx-xxxx --path /home/user --pattern "*.py"
ebx sandbox files search sbx-xxxx --path /app --pattern "*.log" --max-depth 3
```

### ebx sandbox process — Process Management

| Subcommand | Description | Main Parameters |
|------------|-------------|-----------------|
| `list` | List running processes | `SANDBOX_ID` |
| `start` | Execute a command synchronously | `SANDBOX_ID`, `--command -c` (required), `--timeout -t` (default 300), `--cwd` |
| `info` | View process details for a given PID | `SANDBOX_ID`, `PID` |
| `signal` | Send a signal to a process | `SANDBOX_ID`, `PID`, `--signal -s` (default 15/SIGTERM) |

```bash
ebx sandbox process list sbx-xxxx
ebx sandbox process start sbx-xxxx --command "python app.py" --cwd /app
ebx sandbox process start sbx-xxxx -c "make build" --timeout 600
ebx sandbox process info sbx-xxxx 1234
ebx sandbox process signal sbx-xxxx 1234 --signal 9
```

### ebx sandbox system — System Information

| Subcommand | Description | Main Parameters |
|------------|-------------|-----------------|
| `info` | View system info (OS, CPU, memory, disk) | `SANDBOX_ID` |
| `env` | View environment variables (sensitive values auto-filtered) | `SANDBOX_ID`, `--filter -f` |
| `ports` | View listening TCP ports | `SANDBOX_ID` |
| `packages` | List installed packages (pip/npm) | `SANDBOX_ID`, `--manager -m` (default pip) |
| `metrics` | View resource usage (CPU load, disk usage) | `SANDBOX_ID` |

```bash
ebx sandbox system info sbx-xxxx
ebx sandbox system env sbx-xxxx --filter PATH
ebx sandbox system ports sbx-xxxx
ebx sandbox system packages sbx-xxxx --manager npm
ebx sandbox system metrics sbx-xxxx
```

### ebx sandbox capabilities — Capability Group Status

View the currently enabled capability groups for a sandbox (e.g., shell, files, code, terminal, etc.).

```bash
ebx sandbox capabilities <SANDBOX_ID>
```

### ebx sandbox shell-stream — HTTP Streaming Shell

Stream command execution output in real-time via HTTP streaming (unlike `exec`, output is printed line by line).

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
