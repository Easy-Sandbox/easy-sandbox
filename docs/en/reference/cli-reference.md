# CLI Reference

## Command Overview

```
ebx
├── Top-level Shortcuts (11)
│   create / list / info / kill / exec / connect / run / upload / download / deploy / install
├── sandbox Subgroup (17)
│   ├── files: list / stat / mkdir / rm / mv / search
│   ├── process: list / start / info / signal
│   ├── system: info / env / ports / packages / metrics
│   ├── capabilities
│   └── shell-stream
├── template (10)
│   init / deploy / build / push / create / install / list / info / delete / search
├── config (5)
│   init / get / set / list / reset
└── mcp (4)
    install / start / status / deploy
```

### Removed command groups (pre-0.1.0 migration)

The following command groups from earlier pre-releases were removed before the first stable release (`0.1.0`) — these are **breaking changes** with explicit replacements:

| Removed | Replacement |
|---------|-------------|
| `ebx auth login/logout/status/switch` | `ebx config set api_key <value>` to persist credentials, or the `E2B_API_KEY` / `SANDBOX_API_KEY` environment variables; check the effective state with `ebx config list` |
| `ebx secret create/list/delete/inject` | Environment variables or `.env` files for credentials and secrets; sandbox environment injection via `ebx create --env KEY=VALUE` |
| `ebx session` / `ebx sessions list/info/rename/export/import/clean` | Session data is still stored locally in `~/.ebx/sessions/` by `LocalSessionStore`; use the SDK's `Sandbox.connect()` programmatically (the interactive REPL `ebx connect <SANDBOX_ID>` remains available) |
| `ebx skill search/install/list/create/publish` | Templates are the current capability-distribution mechanism (`ebx template search` / `ebx template install`); the repository-root `SKILL.md` documents agent-facing usage |

See the `Unreleased` section of the repository `CHANGELOG.md` for the full breaking-change list and migration notes.

### Which command? — `config init` vs `template init` vs `create`

| Goal | Command | What it does | Talks to the cloud? |
|------|---------|--------------|---------------------|
| Store credentials / endpoints before first use | `ebx config init` | Interactive guided wizard (platform API key, region, Qwen Code credentials); on non-TTY or with `--yes` it prints the equivalent `ebx config set` commands | No |
| Scaffold a local template project | `ebx template init [DIRECTORY]` | Generates an editable `template.yaml` + `Dockerfile` (+ `commands.py`) in a local directory; nothing is built or deployed. `ebx init` is a top-level shortcut that delegates to the exact same command | No |
| Create a cloud sandbox | `ebx create --template <NAME>` / `ebx create "DESCRIPTION"` | `--template NAME` launches an existing template (`base` for the default sandbox); a DESCRIPTION alone goes through the research-first clarification flow (the agent researches public facts itself, then asks one question per round when interactive), then Qwen Code template generation → build & deploy → create. Bare `ebx create` (no `--template`, no DESCRIPTION) is an explicit usage error, not an implicit `base` launch | Yes |

```bash
# 1. Guided credentials setup (run first)
ebx config init

# 2. Create a sandbox with the default template
ebx create

# 3. Create from an existing template (no AI generation)
ebx create --template python-hello

# 4. Create from natural language (Qwen Code generates + deploys the template)
ebx create "a Python data analysis environment with pandas and jupyter"

# 5. Scaffold a local template project to edit and deploy yourself
ebx template init -t python ./my-template
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
| `--log-level` | | Set log level: `debug`/`info`/`warning`/`error` |
| `--ci` | | CI/CD mode (equivalent to `--quiet --no-color --json`) |
| `--timeout` | `-t` | Default sandbox lifetime in seconds (positive integer; default: 300) |
| `--profile` | `-p` | [Reserved] Configuration profile |
| `--version` | | Show version number |
| `--help` | `-h` | Show help and exit (available on every command and sub-group) |

> **`-h` / `--help` work at every level**: the alias is enabled once on the root group and inherited by the whole command tree, so `ebx -h`, `ebx sandbox -h`, `ebx sandbox files list -h` all print the help of the addressed command. A command that reserves `-h` for its own parameter keeps it — Click then drops only the alias there and `--help` keeps working.

> **Region is a command-level option, not a global one**: only commands that talk to a regional control plane accept `--region`/`-r` — [`ebx list`](#ebx-list), [`ebx kill`](#ebx-kill), the template control-plane commands (`list`/`info`/`create`/`push`/`build`/`install`/`delete`), and [`ebx mcp deploy`](#ebx-mcp-deploy). Resolution priority: command `--region` > `ebx config set region` / `SANDBOX_REGION` env > `cn-hangzhou`. Use `ebx config set region` for the persistent default.

---

## Sandbox Lifecycle Commands

### ebx create

Create a new sandbox.

**Routing rules** (decides which path is taken):

| Invocation | Path |
|-----------|------|
| `ebx create` (no arguments) | **Rejected** — explicit usage error (exit code 2) with the three valid routing options; bare create no longer defaults to `base` |
| `ebx create --template <name>` | Direct template path (no AI generation) |
| `ebx create "natural language description"` | AI path: research-first clarification (the agent researches public facts on its own native session, then asks one question per round when interactive — only for details it cannot infer) → Qwen Code generates Dockerfile + template.yaml → build & deploy → create sandbox |
| `ebx create "description" --template <name>` | **Rejected** — `DESCRIPTION` and `--template` are mutually exclusive; a usage error is raised (exit code 1) and the description is never silently ignored |

Mutual exclusion is deliberate: either the description or the template would have to be silently dropped, so the CLI refuses the combination instead.

The AI path requires a locally available Qwen Code CLI and DashScope/ModelStudio credentials. When it is missing, interactive terminals are offered an official standalone install (verified via SHA256, installed into `~/.ebx/bin`); non-interactive environments must pass `--yes` explicitly.

Before generating, the agent runs a two-phase clarification on one native session: a plain **research round** first (its own tools settle the publicly verifiable facts — tool stack, official install method, common dependencies; unreachable facts get safe defaults), then a **structured assessment** of the description's completeness (target: 80%). Below the threshold, interactive sessions are asked **one question at a time**, numbered `Question 1`, `Question 2`, … with no total shown (an internal 5-round cap is mentioned only when reached); every answer resumes the same session, re-assesses the full description plus the whole Q/A history, already-asked topics are never repeated, and delegation answers ("you decide" / "use the default") instruct the agent to settle the choice itself with safe defaults. Non-interactive sessions without `--yes` fail fast with `E2008`, listing the missing details and a ready-to-use example description; `--yes` skips research and assessment entirely. If the assessment is unavailable (timeout, crash, unparseable payload), the CLI warns and generates directly.

```bash
ebx create [DESCRIPTION] [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--template` | `-T` | Template ID or alias (default: `base`); skips AI generation when provided; cannot be combined with DESCRIPTION |
| `--upload` | `-u` | Local file/directory to upload after creation |
| `--timeout` | `-t` | Sandbox lifetime in seconds (positive integer; default: global `--timeout`) |
| `--request-timeout` | | HTTP request timeout for the create call (floor: 120s or configured `http_timeout`) |
| `--env` | `-e` | Environment variable `KEY=VALUE` (repeatable) |
| `--metadata` | `-m` | Metadata `KEY=VALUE` (repeatable) |
| `--yes` | `-y` | Skip interactive confirmations and the research-first clarification flow (Qwen Code install, credential input, description research/assessment, build/deploy confirmation); required in non-interactive environments |
| `--acr-namespace` | | ACR namespace used to build and push AI-generated templates (env: `ACR_NAMESPACE`) |
| `--verbose` | `-v` | Verbose output (DEBUG level) |

```bash
# Create the default (base) template sandbox
ebx create --template base

# AI-generated template and create (interactive; add -y for non-interactive use)
ebx create "a python data analysis environment"
ebx create -y "a node.js api server"

# Non-interactive with an incomplete description → E2008 (missing details + example)
# ebx create "run python"

# Create and upload files
ebx create --upload ./app --timeout 600 --env MY_KEY=value

# Rejected: DESCRIPTION and --template cannot be combined (exit code 1)
# ebx create "a node.js api server" --template base

# Rejected: bare `ebx create` without --template or DESCRIPTION (exit code 2)
# ebx create
```

When the AI path fails (not installed `E2005`, missing credentials `E2006`, generation failure `E2007`) it never silently falls back to `base`; it prints a Quick Setup guide and next-step commands instead.

### ebx list

List sandboxes, optionally filtered by lifecycle status.

```bash
ebx list [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--status` | `-s` | Filter by status: `running`/`stopped`/`creating`/`paused`/`error` |
| `--limit` | `-l` | Maximum results (positive integer; default: 20) |
| `--region` | `-r` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

### ebx info

Show status, template, region, timeout, and URL for a sandbox.

```bash
ebx info <SANDBOX_ID>
```

### ebx kill

Permanently destroy one sandbox or all running sandboxes. Confirmation required unless `--yes` is supplied.

```bash
ebx kill [SANDBOX_ID] [options]
ebx kill --all [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--all` | | Kill all running sandboxes |
| `--yes` | `-y` | Skip confirmation |
| `--region` | `-r` | Region override for the `--all` control-plane call (default: `ebx config set region` value, else `cn-hangzhou`) |

### ebx exec

Execute one command in a sandbox and return its exit code.

```bash
ebx exec <SANDBOX_ID> <COMMAND> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--timeout` | `-t` | Timeout in seconds (positive integer; default: 60) |
| `--cwd` | | Working directory |
| `--verbose` | `-v` | Verbose output (DEBUG level) |

```bash
ebx exec abc123 "python --version"
ebx exec abc123 "pytest -q" --cwd /app --timeout 300
```

### ebx connect

Open an interactive command REPL for a sandbox. This is a line-based REPL - not a PTY or a full SSH session: every entered line runs in a new process with a 30-second timeout, and `cd`, environment variables and shell state do not persist between lines (use `cd /path && <cmd>` on one line, or `ebx exec --cwd` instead).

On interactive terminals basic line editing and command history are enabled (Up/Down history, Ctrl+R search, Ctrl+A/E and friends). Type `exit`/`quit` or press `Ctrl+D` to disconnect; `Ctrl+C` also disconnects. Failed commands are reported as one friendly message - never as a raw HTTP error, sandbox URL or MDN link.

```bash
ebx connect <SANDBOX_ID>
```

```bash
ebx connect abc123
```

---

## File Operation Commands

### ebx upload

Upload a local file or directory to the sandbox.

```bash
ebx upload <SANDBOX_ID> <LOCAL_PATH> <REMOTE_PATH>
```

```bash
ebx upload abc123 ./script.py /app/script.py
ebx upload abc123 ./data/ /app/data/
```

### ebx download

Download a file from the sandbox to local.

```bash
ebx download <SANDBOX_ID> <REMOTE_PATH> <LOCAL_PATH>
```

```bash
ebx download abc123 /app/result.csv ./result.csv
ebx download abc123 /app/output.log .
```

---

## Custom Commands

### ebx run

Run a named custom command or registered command.

```bash
ebx run <SANDBOX_ID> <COMMAND_NAME> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--arg` | `-a` | Argument `KEY=VALUE` (repeatable, legacy style) |

Supports two argument styles:

```bash
# Legacy style
ebx run abc123 test --arg file=tests/

# New style (pass-through --key value)
ebx run abc123 demo --x 1 --y hello
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

Manage persistent credentials and CLI defaults. Values are stored in `~/.ebx/config.toml` and `~/.ebx/.env`. Environment variables can still override stored configuration at runtime.

### ebx config get

```bash
ebx config get <KEY>
```

Available config keys:

| Key | Description |
|-----|-------------|
| `api_key` | E2B API Key (stored in `~/.ebx/.env`, shown masked) |
| `access_key_id` | Alibaba Cloud AccessKey ID (template deploy, ACR push) |
| `access_key_secret` | Alibaba Cloud AccessKey Secret (shown masked) |
| `api_url` | Platform API URL |
| `domain` | envd data-plane domain |
| `region` | Default region |
| `http_timeout` | HTTP request timeout in seconds |
| `http2` | Enable HTTP/2 (true/false) |
| `max_retries` | Maximum retry attempts |
| `llm_api_key` | LLM API Key for NL inference (shown masked; also used as a compatible fallback for Qwen Code credentials) |
| `llm_model` | LLM model name |
| `llm_base_url` | LLM API base URL (OpenAI-compatible) |
| `qwen_code_api_key` | Qwen Code API Key for AI template generation (stored in `~/.ebx/.env`, shown masked) |
| `qwen_code_base_url` | Qwen Code OpenAI-compatible base URL (default: DashScope compatible-mode) |
| `qwen_code_model` | Qwen Code model name (default: `qwen3-coder-plus`) |
| `github_token` | GitHub token for template downloads (`ebx template install` / `ebx template search`; stored in `~/.ebx/.env`, mapped to `GITHUB_TOKEN`, shown masked) |

### ebx config init

Guided configuration wizard: platform API Key, default region, and Qwen Code (AI) credentials.

```bash
ebx config init
ebx config init --yes   # Non-interactive: print equivalent ebx config set commands
```

- Interactive terminals prompt for the three items in order; sensitive values (API keys) are typed with asterisk feedback (one `*` per character, never echoed) when the terminal supports it — otherwise a no-echo fallback is used with an explicit notice. Secrets are stored in `~/.ebx/.env` (`E2B_API_KEY`, `EBX_QWEN_CODE_API_KEY`), while the region is written to `~/.ebx/config.toml`.
- Enter accepts the current value / skips the prompt, Backspace edits, and Ctrl-C / EOF (Ctrl-D) abort the wizard cleanly.
- Non-TTY environments (CI, piped input) or `--yes` never block: they print the equivalent non-interactive `ebx config set` commands and exit 0.

```bash
ebx config init
# 1/3 Platform API key (E2B_API_KEY, input masked)
# 2/3 Region (default cn-hangzhou)
# 3/3 Qwen Code API key (DashScope/ModelStudio, input masked)
```

### ebx config set

```bash
ebx config set <KEY> <VALUE>
```

Settings are stored in `~/.ebx/config.toml`, except credentials (`api_key`, `access_key_id`, `access_key_secret`, `qwen_code_api_key`, `github_token`) which are written to `~/.ebx/.env` (chmod 600).

Passing an empty `<VALUE>` clears the stored value for `KEY` instead: the key falls back to its built-in default or becomes not set. An empty string is never stored as a credential or as an override. When an environment variable still overrides the key at runtime, the command says so explicitly (without printing its value).

In an interactive terminal `<VALUE>` may be omitted: sensitive keys (`github_token`, `api_key`, `access_key_secret`, `qwen_code_api_key`) are then read through the masked (asterisk) input and the typed value is never echoed, while other keys use a visible prompt. Pressing Enter at the prompt cancels without changing anything; non-interactive sessions must pass `<VALUE>` explicitly (exit code 2 with the equivalent command otherwise).

```bash
ebx config set api_key YOUR_API_KEY
ebx config set access_key_id YOUR_ACCESS_KEY_ID
ebx config set region cn-hangzhou
ebx config set http_timeout 120
ebx config set region ""        # clear the stored region (falls back to default)
ebx config set api_key ""       # remove the stored API key (becomes not set)
ebx config set github_token            # masked prompt (VALUE omitted, interactive terminal)
ebx config set github_token YOUR_GITHUB_TOKEN
ebx config set github_token ""         # remove the stored token
```

### ebx config list

```bash
ebx config list
```

List all effective configuration values and their sources: `(env)` a process environment variable, `(user)` a value stored with `ebx config set`, `(default)` a built-in default, and `(not set)` when no value exists anywhere. Keys with a real business default (e.g. `qwen_code_base_url`, `qwen_code_model`) show the concrete default; keys without one (`llm_api_key`, `llm_base_url`, `llm_model`) show `(not set)`. Sensitive values are always masked.

### Clearing stored values

There is no `ebx config reset` command. Clear individual keys with `ebx config set KEY ""` — an empty string is never written as a credential — and the key returns to its business default or to not set.

---

## Template Commands — ebx template

Discover, scaffold, build, and manage sandbox templates.

### ebx template init

Scaffold a new sandbox template project from a built-in case.

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

**DIRECTORY behaviour**: when omitted, a new subdirectory `./<name>` is created. `<name>` is resolved by priority: `--name` > scaffold case name > fetched template name.

```bash
ebx template init --list
ebx template init -t python
ebx template init -t python --name myapp
ebx template init -t python ./my-template
ebx template init --from owner/repo
```

> `ebx init` **is** a top-level shortcut: it is the exact same command object as `ebx template init` (options unchanged). Guided credentials setup is `ebx config init`.
>
> Unknown top-level commands produce a targeted hint: a close spelling match gets a `Did you mean '…'?` suggestion; otherwise the error points to template `custom_commands` (declared in `template.yaml`) invoked via `ebx run COMMAND`.

### ebx template deploy

Build, push, and create template in one step (alias of `template build`).

> **Cloud side effects & costs**: the ACR push and the remote template registration are cloud-side operations that can incur Alibaba Cloud costs (ACR storage/traffic, template resources). An interactive confirmation (or `--yes`) is required before any cloud operation starts; non-interactive sessions fail fast instead of deploying silently.

Requires: Docker daemon running, ACR credentials, and an ACR namespace. AK/SK credentials are read from `ALICLOUD_ACCESS_KEY_ID` / `ALICLOUD_ACCESS_KEY_SECRET` when `--acr-username`/`--acr-password` are omitted.

```bash
ebx template deploy <TEMPLATE_DIR> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--acr-registry` | | ACR registry host |
| `--acr-namespace` | | ACR namespace (CLI > env `ACR_NAMESPACE` > `.env`) |
| `--acr-repo` | | ACR repository name (defaults to `template.yaml` name or dir name) |
| `--acr-username` / `--acr-password` | | ACR credentials |
| `--acree-instance-id` | | ACR EE instance ID |
| `--vpc-id` | | VPC ID |
| `--vswitch-ids` | | Comma-separated VSwitch IDs |
| `--security-group-id` | | Security group ID |
| `--alias` | `-a` | Template alias |
| `--tag` | `-t` | Docker image tag |
| `--platform` | | Target platform |
| `--cpu` | | CPU cores (default: `template.yaml` → 2) |
| `--memory` | | Memory in MB (default: `template.yaml` → 2048) |
| `--start-cmd` / `--ready-cmd` | | Start/readiness command |
| `--timeout` | | Build timeout in seconds |
| `--dockerfile` | `-f` | Custom Dockerfile path |
| `--disk-size` | | Disk size in MB (official API only) |
| `--internet-access/--no-internet-access` | | Internet access (official API only) |
| `--official-api/--legacy-api` | | Official CreateTemplate API (default) or legacy v3/v2 |
| `--team-id` | | Team ID |
| `--envd-inject/--no-envd-inject` | | envd injection (default off) |
| `--generation` | | Sandbox generation (1=first-gen rund, 2=second-gen MicroVM; default: `template.yaml` → 1) |
| `--target-image` | | Destination image ref for envd copy |
| `--yes` | `-y` | Skip confirmation |
| `--verbose` | `-v` | Verbose output |
| `--region` | `-r` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

```bash
ebx template deploy ./examples/templates/python-hello \
  --acr-namespace my-ns --acr-repo python-hello

ebx template deploy ./my-template --acr-namespace prod --yes
```

#### Parameter Defaults & Priority

Parameters for `template build` / `template deploy` are resolved through a **5-level priority chain** (highest first):

| Priority | Source |
|----------|--------|
| 1 | Explicit CLI flag |
| 2 | OS environment variable |
| 3 | `.env` file in the current working directory |
| 4 | `template.yaml` in the template directory |
| 5 | Hardcoded fallback |

> **Automation / CI**: pass `--acr-namespace` and the template directory explicitly on the command line instead of relying on `ACR_NAMESPACE` / `EBX_TEMPLATE_DIR` environment variables or a `.env` file, so builds cannot silently drift with the surrounding environment. For `template install` / `install`, either pass `--acr-namespace` explicitly or use `--download-only` when the pipeline must not touch the cloud at all.

### ebx template build

Build Docker image locally, push to ACR, and create a sandbox template.

> **Cloud side effects & costs**: the default pipeline is local Docker build → ACR push → template registration via the official CreateTemplate API. The ACR push and the remote registration are cloud-side operations that can incur Alibaba Cloud costs (ACR storage/traffic, template resources). An interactive confirmation (or `--yes`) is required before the cloud operations start.

Supports two modes: `--official-api` (default, requires AK/SK and `easy-sandbox[alicloud]`) and `--legacy-api` (legacy v3/v2 platform API — kept behind an explicit flag, not the default). The old command name `ebx template build-local` was removed before `0.1.0`; it is replaced by `ebx template build` (same pipeline, same options).

```bash
ebx template build <TEMPLATE_DIR> [options]
```

Parameters are the same as `template deploy`.

### ebx template push

Push a locally-built image to Alibaba Cloud ACR.

```bash
ebx template push <IMAGE> [options]
```

| Option | Description |
|--------|-------------|
| `--acr-registry` | ACR registry host |
| `--acr-namespace` | ACR namespace |
| `--acr-username` / `--acr-password` | ACR credentials |
| `--acree-instance-id` | ACR EE instance ID |
| `--region` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

```bash
ebx template push python-hello:latest --acr-namespace my-ns
```

### ebx template create

Create a sandbox template from an existing container image. Uses the official Alibaba Cloud FCSandbox CreateTemplate API (requires AK/SK and `easy-sandbox[alicloud]`).

```bash
ebx template create <IMAGE> --name <NAME> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--name` | `-n` | Template name (required) |
| `--team-id` | | Team ID |
| `--cpu` | | CPU cores (default 2, FLOAT) |
| `--memory` | | Memory in MB (default 2048) |
| `--disk-size` | | Disk size in MB |
| `--internet-access/--no-internet-access` | | Internet access |
| `--generation` | | Sandbox generation |
| `--envd-inject/--no-envd-inject` | | envd injection |
| `--target-image` | | Destination image ref for envd copy |
| `--registry-type` | | Registry type: `acr` / `acree` (auto-detected) |
| `--acree-instance-id` | | ACR EE instance ID |
| `--registry-username` | | Registry login username |
| `--registry-password` | | Registry login password |
| `--start-cmd` | | Container start command |
| `--ready-cmd` | | Container readiness check command |
| `--region` | `-r` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

```bash
ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag --name my-template

ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \
  --name my-tpl --cpu 4 --memory 4096 --disk-size 10240 --internet-access
```

### ebx template install

Download a template and (by default) build + deploy it. Use `--download-only` to skip the build/deploy step and only download to the local cache (`~/.ebx/templates/`). Use `--dir` to download to a custom directory.

By default the build + deploy step performs a local Docker build, an ACR push, and a CreateTemplate registration — cloud-side operations that can incur Alibaba Cloud costs (ACR storage/traffic, template resources); `--download-only` skips them entirely. An interactive confirmation (or `--yes`) is required before the cloud operations start; non-interactive sessions fail fast with a `--download-only` hint when prerequisites are missing.

`TEMPLATE_REF` is either a **bare template name** from the remote index (published by the source-of-truth repository `Easy-Sandbox/awesome-templates`) or a registry reference (`owner/repo[//subdir][@ref]`). Bare-name resolution order: local path → builtin (`base` / `code-interpreter-v1`, no network) → remote index (on a hit it prints `Resolved '<name>' via the template index: ...`). Entries may pin a version via `ref`, and the pin is honoured; a missed bare name triggers one forced index refresh, so a freshly published template never waits for the cache TTL.

```bash
ebx template install <TEMPLATE_REF> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--registry-url` | | Registry URL (default: GitHub) |
| `--registry-type` | | `github` / `local` (auto-detected) |
| `--token` | | GitHub token: private-repo access + higher rate limits for the remote index (env: `GITHUB_TOKEN`). Temporary override only — prefer `ebx config set github_token`; `--token` may leak into shell history and process listings |
| `--alias` | `-a` | Template alias |
| `--download-only` | | Only download to local cache (skip build and deploy) |
| `--dir` | | Download to a custom directory |
| `--acr-namespace` | | ACR namespace for deploy |
| `--cpu` | | CPU cores |
| `--memory` | | Memory in MB |
| `--yes` | `-y` | Skip confirmation prompt |
| `--region` | `-r` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

```bash
ebx install owner/repo --acr-namespace my-ns    # Download + build + deploy
ebx install owner/repo --download-only          # Download only
ebx install owner/repo//subdir --dir ./local    # Subdirectory + custom path
ebx install node-web --download-only            # Bare name resolved via the remote index
ebx install Easy-Sandbox/awesome-templates//node-web@v1.0.0 --download-only  # Pin a version
```

Token resolution order: `--token` > process `GITHUB_TOKEN` > stored `github_token` (`ebx config set github_token`; masked input, stored in `~/.ebx/.env`) > no token. On an anonymous GitHub rate limit (E5000) the full `owner/repo//subdir@ref` reference is preserved in the error — including subdirectory and pinned ref — together with the officially documented fine-grained PAT prefill URL (public repositories need no extra permissions; 90-day expiry recommended). In an interactive terminal only, the CLI offers a masked one-shot `github_token` setup and retries the failed operation **exactly once**; CI / non-interactive sessions are told to inject `GITHUB_TOKEN` as a secret or to run `ebx config set github_token` in a terminal. The token is never printed or logged.

### ebx install (shortcut)

Top-level shortcut for `ebx template install` — same options and behaviour.

### ebx template list

List custom templates registered for the current account. By default, queries the platform endpoint; pass `--official-api` to use the Alibaba Cloud FCSandbox API (AK/SK).

```bash
ebx template list [options]
```

| Option | Description |
|--------|-------------|
| `--official-api` | Query via the official Alibaba Cloud FCSandbox API (AK/SK) |
| `--region` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

### ebx template info

Show details for a template ID. Pass `--official-api` to use the Alibaba Cloud FCSandbox GetTemplate API.

```bash
ebx template info <TEMPLATE_ID> [options]
```

| Option | Description |
|--------|-------------|
| `--official-api` | Query via the official Alibaba Cloud FCSandbox API (AK/SK) |
| `--region` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

### ebx template delete

Delete a custom template from the remote platform (irreversible). Does not remove the local cache. Confirmation required.

```bash
ebx template delete <TEMPLATE_ID> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--yes` | `-y` | Skip confirmation prompt |
| `--region` | `-r` | Region override for this command (default: `ebx config set region` value, else `cn-hangzhou`) |

### ebx template search

Search templates by name, tag, or description against the `awesome-templates.yaml` index published by the source-of-truth repository [`Easy-Sandbox/awesome-templates`](https://github.com/Easy-Sandbox/awesome-templates). The index is cached under `~/.ebx/index/` (1-hour TTL; a fresh cache makes no network call); on network failures / rate limits it falls back to the stale cache with a warning. Without a cache, an anonymous rate limit (E5000) reports the unified guidance — `ebx config set github_token` / `GITHUB_TOKEN`, the fine-grained PAT prefill URL, the `--token` leak warning, and a mirror hint — and an interactive terminal is offered a masked one-shot `github_token` setup followed by exactly one automatic retry (never a loop). Non-interactive sessions are pointed at secret injection or an interactive `ebx config set github_token`.

```bash
ebx template search <QUERY> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--tag` | `-t` | Filter by exact tag name |
| `--status` | `-s` | Filter by status: `official` / `community` / `experimental` |
| `--index-url` | | Index location: HTTP(S) URL or local file path (env: `EBX_TEMPLATE_INDEX_URL`; default: the canonical remote index) |
| `--token` | | GitHub token for private mirrors / higher rate limits (env: `GITHUB_TOKEN`). Temporary override only — prefer `ebx config set github_token` |
| `--refresh` | | Force a re-fetch of the index, ignoring the local cache |

```bash
ebx template search python
ebx template search browser --status official
ebx template search qwen --tag deploy
ebx template search python --refresh              # Bypass the local cache
ebx template search web --index-url https://mirror.example/idx.yaml  # Private mirror
```

---

## MCP Commands — ebx mcp

Configure and run Easy Sandbox as an MCP server. Supports local STDIO transport (IDE integrations) and Streamable HTTP deployment artifact (manual FC deployment).

### ebx mcp install

Install MCP Server configuration to a target IDE.

```bash
ebx mcp install --target <cursor|claude|vscode>
```

| Option | Description |
|--------|-------------|
| `--target` | Target IDE (`cursor` / `claude` / `vscode`, required) |

### ebx mcp start

Start MCP Server in STDIO mode (typically invoked by the IDE).

```bash
ebx mcp start [options]
```

| Option | Description |
|--------|-------------|
| `--template` | Default sandbox template (default: `code-interpreter-v1`) |
| `--api-key` | API Key override |
| `--api-url` | API URL override |
| `--domain` | Domain override |

### ebx mcp status

Show MCP tools, authentication state, and IDE installation status.

```bash
ebx mcp status
```

### ebx mcp deploy

Generate an Alibaba Cloud FC deployment artifact (Streamable HTTP ASGI). Does not call the FC deployment API.

`POST /mcp` handles requests and `DELETE /mcp` terminates a session. `GET /mcp` currently returns 501; SSE server notifications are planned for Phase 2.

```bash
ebx mcp deploy [options]
```

| Option | Description |
|--------|-------------|
| `--name` | FC function name (default: `easy-sandbox-mcp`) |
| `--region` | FC region (command-level override; falls back to `ebx config set region` / `SANDBOX_REGION`, else `cn-hangzhou`) |
| `--template` | Default sandbox template |
| `--memory` | FC function memory in MB |
| `--timeout` | FC function timeout in seconds |
| `--auth-token-file` | Path to a Bearer token file |
| `--generate-token` | Auto-generate a random Bearer token |
| `--enable-session-affinity/--no-session-affinity` | Mcp-Session-Id affinity (default: enabled) |
| `--api-key` | E2B_API_KEY to inject into FC function env |
| `--custom-domain` | Custom domain for the MCP endpoint |
| `--output-dir` | Write the deployment artifact to this directory |

```bash
ebx mcp deploy --generate-token --api-key $E2B_API_KEY --output-dir ./deploy-artifact
ebx mcp deploy --auth-token-file ./token.txt --region cn-shanghai --output-dir ./artifact
```

---

## Deploy Command — ebx deploy

Deploy a local project to a sandbox using an AI agent or traditional mode.

```bash
ebx deploy [PATH] [INSTRUCTION] [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--instruction` | `-i` | NL deploy instruction |
| `--max-wall-time` | | qwen-code max wall time (default: `10m`) |
| `--max-session-turns` | | qwen-code session turn limit (default: 100) |
| `--alias` | `-a` | Template alias (traditional mode) |
| `--watch` | | Watch for file changes and auto-redeploy (traditional mode) |
| `--traditional` | | Use traditional build+run mode |

```bash
ebx deploy ./my-project "deploy this FastAPI app on port 8080"
ebx deploy ./my-project --traditional --alias my-app
```

---

## sandbox Subcommand Group

`ebx sandbox` provides the same sandbox operations as the top-level commands (create / list / info / kill / exec / connect / upload / download / run), plus extended subgroups below.

### ebx sandbox files — File Operations

| Subcommand | Description | Main Options |
|------------|-------------|--------------|
| `list` | List directory contents | `--path -p`, `--recursive -r` |
| `stat` | Get file/directory info | `--path -p` (required) |
| `mkdir` | Create directory (including parents) | `--path -p` (required) |
| `rm` | Delete file/directory | `--path -p` (required), `--yes -y` |
| `mv` | Move/rename | `--source -s` (required), `--dest -d` (required) |
| `search` | Search by glob pattern | `--path -p` (required), `--pattern` (required), `--max-depth` (default 5) |

```bash
ebx sandbox files list abc123 --path /app --recursive
ebx sandbox files stat abc123 --path /app/main.py
ebx sandbox files mkdir abc123 --path /app/data
ebx sandbox files rm abc123 --path /app/temp.log --yes
ebx sandbox files mv abc123 --source /app/old.py --dest /app/new.py
ebx sandbox files search abc123 --path /app --pattern "*.py"
```

### ebx sandbox process — Process Management

| Subcommand | Description | Main Options |
|------------|-------------|--------------|
| `list` | List running processes | — |
| `start` | Execute command synchronously | `--command -c` (required), `--timeout -t` (default 300), `--cwd` |
| `info` | Get process details by PID | `PID` |
| `signal` | Send signal to process | `PID`, `--signal -s` (default 15/SIGTERM) |

```bash
ebx sandbox process list abc123
ebx sandbox process start abc123 --command "python app.py" --cwd /app
ebx sandbox process info abc123 1234
ebx sandbox process signal abc123 1234 --signal 9
```

### ebx sandbox system — System Information

| Subcommand | Description | Main Options |
|------------|-------------|--------------|
| `info` | System info (OS, CPU, memory, disk) | — |
| `env` | Environment variables (sensitive values auto-filtered) | `--filter -f` (comma-separated names) |
| `ports` | Listening TCP ports | — |
| `packages` | Installed packages (pip/npm) | `--manager -m` (default `pip`) |
| `metrics` | Resource usage (CPU load, disk usage) | — |

```bash
ebx sandbox system info abc123
ebx sandbox system env abc123 --filter PATH,HOME,LANG
ebx sandbox system ports abc123
ebx sandbox system packages abc123 --manager npm
ebx sandbox system metrics abc123
```

### ebx sandbox capabilities — Capability Group Status

Show the capability groups declared by a sandbox template (shell, files, code, terminal, ports).

```bash
ebx sandbox capabilities <SANDBOX_ID>
```

### ebx sandbox shell-stream — HTTP Streaming Shell

Execute a command with real-time HTTP chunked streaming output.

```bash
ebx sandbox shell-stream <SANDBOX_ID> [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--command` | `-c` | Command to execute (required) |
| `--timeout` | `-t` | Timeout in seconds (positive integer; default: 300) |
| `--cwd` | | Working directory |

```bash
ebx sandbox shell-stream abc123 --command "pip install numpy"
ebx sandbox shell-stream abc123 -c "make build" --cwd /app
```

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
