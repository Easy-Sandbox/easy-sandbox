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

> The top-level shortcuts above (plus `ebx init`) are **system defaults, not fixed commands**: every one of them can be re-mapped, removed, or extended through the `[shortcuts]` section of `~/.ebx/config.toml`, and any other command path can gain its own alias. They work out of the box with no configuration — see [Shortcut aliases (`shortcuts.<alias>`)](#shortcut-aliases-shortcutsalias).

### Removed command groups (pre-0.1.0 migration)

The following command groups from earlier pre-releases were removed before the first stable release (`0.1.0`) — these are **breaking changes** with explicit replacements:

| Removed | Replacement |
|---------|-------------|
| `ebx auth login/logout/status/switch` | `ebx config set sandbox_api_key <value>` to persist credentials, or the `E2B_API_KEY` / `SANDBOX_API_KEY` environment variables; check the effective state with `ebx config list` |
| `ebx secret create/list/delete/inject` | Environment variables or `.env` files for credentials and secrets; sandbox environment injection via `ebx create --env KEY=VALUE` |
| `ebx session` / `ebx sessions list/info/rename/export/import/clean` | Session data is still stored locally in `~/.ebx/sessions/` by `LocalSessionStore`; use the SDK's `Sandbox.connect()` programmatically (the interactive REPL `ebx connect <SANDBOX_ID>` remains available) |
| `ebx skill search/install/list/create/publish` | Templates are the current capability-distribution mechanism (`ebx template search` / `ebx template install`); the repository-root `SKILL.md` documents agent-facing usage |

See the `Unreleased` section of the repository `CHANGELOG.md` for the full breaking-change list and migration notes.

### Which command? — `config init` vs `template init` vs `create`

| Goal | Command | What it does | Talks to the cloud? |
|------|---------|--------------|---------------------|
| Store credentials / endpoints before first use | `ebx config init` | Interactive guided wizard (platform API key, region, Qwen Code credentials); on non-TTY or with `--yes` it prints the equivalent `ebx config set` commands | No |
| Scaffold a local template project | `ebx template init [DIRECTORY]` / `ebx template init "DESCRIPTION"` / `ebx template init --adopt [DIRECTORY]` | A path scaffolds an editable `template.yaml` + `Dockerfile` (+ `commands.py`). A description (whitespace or CJK) asks Qwen Code for a usable template: `Dockerfile`, `commands.py` (the `SandboxServer` HTTP entry point), `template.yaml` and `README.md`. `--adopt` does the same for a project that already has source code: the agent sees a copy, and only those template files (plus a generated `.dockerignore`) are written back. Nothing is built, pushed, deployed, or launched. `ebx init` is the same command | No |
| Create a cloud sandbox | `ebx create --template <NAME>` / `ebx create "DESCRIPTION"` | `--template NAME` launches an existing template (`base` for the default sandbox); a DESCRIPTION alone goes through the research-first clarification flow (the agent researches public facts itself, then asks one question per round when interactive), then Qwen Code template generation → build & deploy → create. An interactive terminal is first asked whether to switch to `ebx template init` and stop after the local files. Bare `ebx create` (no `--template`, no DESCRIPTION) is an explicit usage error, not an implicit `base` launch | Yes |

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

# 6. Natural language, template files only (no build, push, or sandbox)
ebx template init "a Python data analysis environment with pandas and jupyter"
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

> **Region is a command-level option, not a global one**: only commands that talk to a regional control plane accept `--region`/`-r` — [`ebx list`](#ebx-list), [`ebx kill`](#ebx-kill), the template control-plane commands (`list`/`info`/`create`/`push`/`build`/`install`/`delete`), and [`ebx mcp deploy`](#ebx-mcp-deploy). Resolution priority: command `--region` > `SANDBOX_REGION` > `ebx config set region` > `cn-hangzhou`. Credential order is in [Credential resolution](configuration.md#credential-resolution). Use `ebx config set region` for the persistent default.

---

## Sandbox Lifecycle Commands

### ebx create

Create a new sandbox.

**Routing rules** (decides which path is taken):

| Invocation | Path |
|-----------|------|
| `ebx create` (no arguments) | **Rejected** — explicit usage error (exit code 2) with the three valid routing options; bare create no longer defaults to `base` |
| `ebx create --template <name>` | Direct template path (no AI generation) |
| `ebx create "natural language description"` | AI path: an interactive terminal is first asked whether to switch to template init (local files only). Otherwise: research-first clarification (the agent researches public facts on its own native session, then asks one question per round when interactive — only for details it cannot infer) → Qwen Code generates Dockerfile + commands.py (SandboxServer) + template.yaml → build & deploy → create sandbox. `--yes` skips the switch and runs this full pipeline |
| `ebx create "description" --template <name>` | **Rejected** — `DESCRIPTION` and `--template` are mutually exclusive; a usage error is raised (exit code 1) and the description is never silently ignored |

Mutual exclusion is deliberate: either the description or the template would have to be silently dropped, so the CLI refuses the combination instead.

The AI path requires a locally available Qwen Code CLI and DashScope/ModelStudio credentials. When it is missing, interactive terminals are offered an official standalone install (verified via SHA256, installed into `~/.ebx/bin`); non-interactive environments must pass `--yes` explicitly. On a terminal that install is an `Installing ... 12s` header with the download, checksum, and extract milestones in grey underneath; the archive bytes and the API key are not shown. Creating the sandbox itself uses `Creating sandbox... 12s` (file names appear under it only when `--upload` is set).

Before generating, the agent runs a two-phase clarification on one native session: a plain **research round** first (its own tools settle the publicly verifiable facts — tool stack, official install method, common dependencies; unreachable facts get safe defaults), then a **structured assessment** of the description's completeness (target: 80%). Below the threshold, interactive sessions are asked **one question at a time**, numbered `Question 1`, `Question 2`, … with no total shown (an internal 5-round cap is mentioned only when reached); every answer resumes the same session, re-assesses the full description plus the whole Q/A history, already-asked topics are never repeated, and delegation answers ("you decide" / "use the default") instruct the agent to settle the choice itself with safe defaults. Non-interactive sessions without `--yes` fail fast with `E2008`, listing the missing details and a ready-to-use example description; `--yes` skips research and assessment entirely. The research round is bounded (20 agent turns, 240 s by default, override with `EBX_QWEN_RESEARCH_TIMEOUT`); when it times out or runs out of turns the CLI warns with the reason and continues with safe defaults, and the assessment then starts a fresh session. If the assessment is unavailable (timeout, crash, unparseable payload), the CLI warns and generates directly. While the agent works, a TTY shows a header such as `Researching public facts... 12s` / `Assessing description... 12s` with the agent's last four activity lines in grey on the lines below it (recent assistant text and tool names; they scroll line by line, `EBX_ACTIVITY_LINES=1..10` changes the count, and it also works under `--verbose`); nothing of this is printed to stdout or in `--json` / `--quiet` / CI modes.

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
| `--dir` | | Parent directory for the AI-generated `Dockerfile` / `template.yaml`; a fresh `<name>-<timestamp>-<id>/` subfolder is created inside it (default `~/.ebx/generated`). When omitted, an interactive terminal is asked (Enter accepts the default); `--yes` / `--json` / non-TTY use the default silently. Requires a `DESCRIPTION`; ignored (with a warning) when you switch to local-only template generation |
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

Permanently destroy one sandbox or all running sandboxes. Confirmation required unless `--yes` is supplied. On a terminal, `--all` shows `Killing N sandbox(es)... 12s` with `i/N <id>` in grey underneath; a single kill shows only the elapsed header. Non-TTY sessions print the success or error lines only.

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

On an interactive terminal a directory upload shows `Uploading ... 12s` with each relative path in grey underneath. File contents are not printed. `--json`, `--quiet`, CI, and non-TTY print only the success line.

### ebx download

Download a file from the sandbox to local.

```bash
ebx download <SANDBOX_ID> <REMOTE_PATH> <LOCAL_PATH>
```

```bash
ebx download abc123 /app/result.csv ./result.csv
ebx download abc123 /app/output.log .
```

On an interactive terminal the transfer shows `Downloading <path>... 12s`. The file bytes are not printed.

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
| `sandbox_api_key` | Sandbox service API key (stored in `~/.ebx/.env` as `E2B_API_KEY`, shown masked; `api_key` is a get/set alias) |
| `access_key_id` | Alibaba Cloud AccessKey ID (template deploy, ACR push) |
| `access_key_secret` | Alibaba Cloud AccessKey Secret (shown masked) |
| `acr_namespace` | ACR namespace for template build, push, and install (stored as `ACR_NAMESPACE`) |
| `api_url` | Platform API URL |
| `domain` | envd data-plane domain |
| `region` | Default region |
| `http_timeout` | HTTP request timeout in seconds |
| `http2` | Enable HTTP/2 (true/false) |
| `max_retries` | Maximum retry attempts |
| `llm_api_key` | LLM API key for NL inference and the coding agent (shown masked; stored as `EBX_LLM_API_KEY`) |
| `llm_model` | LLM model name (default: `qwen3-coder-plus`) |
| `llm_base_url` | LLM API base URL, OpenAI-compatible (default: DashScope compatible-mode) |
| `github_token` | GitHub token for template downloads (`ebx template install` / `ebx template search`; stored in `~/.ebx/.env`, mapped to `GITHUB_TOKEN`, shown masked) |

`ebx config get shortcuts` reads the whole `[shortcuts]` alias table — see [Shortcut aliases (`shortcuts.<alias>`)](#shortcut-aliases-shortcutsalias) below.

### Shortcut aliases (`shortcuts.<alias>`)

Top-level command aliases are user-configurable in the `[shortcuts]` section of `~/.ebx/config.toml`. The built-in top-level shortcuts (`create`, `list`, `info`, `kill`, `exec`, `connect`, `run`, `upload`, `download`, `deploy`, `install`, `init`) are the **system defaults** — enabled out of the box, freely customizable, never hard-coded.

| Command | Effect |
|---------|--------|
| `ebx config set shortcuts.<alias> "<target>"` | Add / modify an alias. The target is an existing command path with no `ebx` prefix, e.g. `"sandbox process list"` or `"template init"` (not `"ebx template init"`). Afterwards `ebx <alias> [args…]` behaves exactly like the target command |
| `ebx config set shortcuts.<alias> ""` | Delete an alias (the empty value removes it) |
| `ebx config get shortcuts` | View all configured aliases |
| `ebx config init --reset-shortcuts` | Reset shortcuts to the default set |

Alternatively, edit the `[shortcuts]` section of `~/.ebx/config.toml` directly:

```toml
[shortcuts]
create   = "sandbox create"         # factory default
list     = "sandbox list"           # factory default
ps       = "sandbox process list"   # your own alias
```

Rules:

- The target must be an existing command path; aliases never chain to other aliases, and arguments after the alias are passed through unchanged.
- Write the path without the `ebx` prefix. `ebx config set shortcuts.aaaaa "ebx template init"` exits 2, saves nothing, and prints the command to retry: `ebx config set shortcuts.aaaaa "template init"`. An unknown path is rejected with the same rule and the legal targets grouped by command (`template: build, init, install, search`). A bad value already in the file is skipped at startup (`Invalid shortcut ignored` on stderr); the other aliases keep working.
- Reserved command names (`sandbox`, `template`, `config`, `mcp`) cannot be overridden, redirected, or deleted.
- If `~/.ebx/config.toml` cannot be parsed, the CLI warns on stderr and disables all shortcuts for that session — the built-in command groups (`sandbox` / `config` / `mcp` / `template`) still work, and a broken shortcuts config never bricks the CLI.

### ebx config init

Guided configuration wizard: platform API key, default region, LLM API key, ACR namespace, and Alibaba Cloud AccessKey pair.

```bash
ebx config init
ebx config init --yes   # Non-interactive: print equivalent ebx config set commands
ebx config init --reset-shortcuts   # Reset the [shortcuts] aliases to the default set
```

- Interactive terminals prompt for six items in order; sensitive values (API keys and the AccessKey secret) are typed with asterisk feedback (one `*` per character, never echoed) when the terminal supports it — otherwise a no-echo fallback is used with an explicit notice. Press Enter to skip a prompt. Secrets are stored in `~/.ebx/.env` (`E2B_API_KEY`, `EBX_LLM_API_KEY`, `ALICLOUD_ACCESS_KEY_ID`, `ALICLOUD_ACCESS_KEY_SECRET`); the ACR namespace is stored there as `ACR_NAMESPACE`; the region is written to `~/.ebx/config.toml`.
- The wizard also writes a complete `[shortcuts]` template (every available command, ready to edit) into `~/.ebx/config.toml`; `--reset-shortcuts` restores the factory defaults without touching credentials.
- Enter accepts the current value / skips the prompt, Backspace edits, and Ctrl-C / EOF (Ctrl-D) abort the wizard cleanly.
- Non-TTY environments (CI, piped input) or `--yes` never block: they print the equivalent non-interactive `ebx config set` commands and exit 0.

```bash
ebx config init
# 1/6 Sandbox API key (E2B_API_KEY, input masked)
# 2/6 Region (default cn-hangzhou)
# 3/6 LLM API key (DashScope/ModelStudio, input masked)
# 4/6 ACR namespace (needed by ebx install / template deploy)
# 5/6 Alibaba Cloud AccessKey ID
# 6/6 Alibaba Cloud AccessKey Secret (input masked)
```

### ebx config set

```bash
ebx config set <KEY> <VALUE>
```

Settings are stored in `~/.ebx/config.toml`, except credentials (`sandbox_api_key`, `access_key_id`, `access_key_secret`, `acr_namespace`, `llm_api_key`, `github_token`) which are written to `~/.ebx/.env` (chmod 600).

Passing an empty `<VALUE>` clears the stored value for `KEY` instead: the key falls back to its built-in default or becomes not set. An empty string is never stored as a credential or as an override. When an environment variable still overrides the key at runtime, the command says so explicitly (without printing its value).

In an interactive terminal `<VALUE>` may be omitted: sensitive keys (`github_token`, `sandbox_api_key`, `access_key_secret`, `llm_api_key`) are then read through the masked (asterisk) input and the typed value is never echoed, while other keys use a visible prompt. Pressing Enter at the prompt cancels without changing anything; non-interactive sessions must pass `<VALUE>` explicitly (exit code 2 with the equivalent command otherwise).

```bash
ebx config set sandbox_api_key YOUR_API_KEY
ebx config set access_key_id YOUR_ACCESS_KEY_ID
ebx config set acr_namespace YOUR_ACR_NAMESPACE
ebx config set region cn-hangzhou
ebx config set http_timeout 120
ebx config set region ""        # clear the stored region (falls back to default)
ebx config set sandbox_api_key ""       # remove the stored API key (becomes not set)
ebx config set github_token            # masked prompt (VALUE omitted, interactive terminal)
ebx config set github_token YOUR_GITHUB_TOKEN
ebx config set github_token ""         # remove the stored token
```

### ebx config list

```bash
ebx config list
```

List all effective configuration values and their sources: `(env)` a process environment variable, `(user)` a value in `./.env` or stored with `ebx config set`, `(default)` a built-in default, and `(not set)` when no value exists anywhere. A set environment variable wins over either file. `./.env` wins over `~/.ebx` for a key it sets. See [Credential resolution](configuration.md#credential-resolution). Keys with a real business default (e.g. `llm_base_url`, `llm_model`) show the concrete default; `llm_api_key` and `sandbox_api_key` show `(not set)` when absent. Sensitive values are always masked.

### ebx config delete

```bash
ebx config delete <KEY>
```

Remove one stored value. The key falls back to its built-in default or becomes not set. `ebx config set KEY ""` does the same thing. An environment variable that still overrides the key is left alone and named in the output, without printing its value. This does not delete `~/.ebx` or every key at once; there is no `ebx config reset`.

```bash
ebx config delete acr_namespace
ebx config delete access_key_secret
ebx config delete shortcuts.ps
```

---

## Template Commands — ebx template

Discover, scaffold, build, and manage sandbox templates.

### ebx template init

Scaffold a new sandbox template project from a built-in case, from a natural-language description, or from an existing project (`--adopt`). None of these paths builds, pushes, deploys, or creates a sandbox.

```bash
ebx template init [DIRECTORY] [options]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--template` | `-t` | Built-in scaffold case (`python`, `node`, `minimal`) |
| `--from` | | Fetch template source from a registry ref. A local directory with no `template.yaml` is rejected; use `--adopt` |
| `--name` | | Template name |
| `--list` | | List available scaffold cases |
| `--force` | | Overwrite existing files. With `--adopt` and `--yes`, also required to replace an existing Dockerfile |
| `--adopt` | | Adapt an existing project in DIRECTORY (default `.`): Qwen Code adds the template files |
| `--hint` | | With `--adopt`: ports, services, anything the code does not say |
| `--dry-run` | | With `--adopt`: list every file that would be sent. Nothing is sent or written |
| `-v` / `--verbose` | | Debug logging |
| `--yes` | `-y` | Skip confirmation. Required for non-interactive AI generation, including `--adopt` |

**DIRECTORY behaviour**: when omitted, a new subdirectory `./<name>` is created. `<name>` is resolved by priority: `--name` > scaffold case name > fetched template name > generated name.

A path token (`my-app`, `./my app`) is a directory. Whitespace or CJK text is a description: Qwen Code writes `Dockerfile` + `template.yaml` into `./<name>/` and stops. An interactive terminal asks `Directory for the template project` first; Enter keeps `./<name>/` (or `./<--name>/` when `--name` is set), and any other path is the project directory itself. `--yes`, `--json`, and a non-interactive shell skip the question. That is the same result as answering yes to the switch question on `ebx create "DESCRIPTION"` (the switch does not ask again; it writes `./<name>/`).

```bash
ebx template init --list
ebx template init -t python
ebx template init -t python --name myapp
ebx template init -t python ./my-template
ebx template init --from owner/repo
ebx template init "a python data science env"
ebx template init -y "a node.js api server"
ebx template init --adopt . --hint "listens on 8080"
ebx template init --adopt ./app --dry-run
ebx template init --adopt ./app -y          # non-interactive; then ebx deploy ./app
```

`--adopt` copies candidate files to a temp directory and asks before sending them to the model. Secrets (`.env`, keys, secret-looking files) are left out of that copy. The agent cannot modify the project: only `Dockerfile`, `commands.py`, `template.yaml` and, when you don't already have one, a generated `.dockerignore` are written, and only after a second confirmation (or `--yes`). Replaced files are kept as `*.ebx-bak`. The model process does not inherit cloud credentials (`ALICLOUD_*`, `E2B_*`, `ACR_*`, …). This shows the model your project source; it is a larger exposure than `ebx template init "DESCRIPTION"`, which only sends the sentence you typed.

> `ebx init` **is** a top-level shortcut: it is the exact same command object as `ebx template init` (options unchanged). Guided credentials setup is `ebx config init`.
>
> Unknown top-level commands produce a targeted hint: a close spelling match gets a `Did you mean '…'?` suggestion; otherwise the error points to template `custom_commands` (declared in `template.yaml`) invoked via `ebx run COMMAND`.
>
> Top-level shortcuts like `init` are system defaults and can be re-mapped or removed via the `[shortcuts]` config section — see [Shortcut aliases (`shortcuts.<alias>`)](#shortcut-aliases-shortcutsalias).

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

On an interactive terminal the CreateTemplate call shows `Creating template <name>... 12s`. The registry password is not printed.

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

Token resolution order: `--token` > process `GITHUB_TOKEN` > `./.env` > stored `github_token` (`ebx config set github_token`; masked input, stored in `~/.ebx/.env`) > no token. On an anonymous GitHub rate limit (E5000) the full `owner/repo//subdir@ref` reference is preserved in the error — including subdirectory and pinned ref — together with the officially documented fine-grained PAT prefill URL (public repositories need no extra permissions; 90-day expiry recommended). In an interactive terminal only, the CLI offers a masked one-shot `github_token` setup and retries the failed operation **exactly once**; CI / non-interactive sessions are told to inject `GITHUB_TOKEN` as a secret or to run `ebx config set github_token` in a terminal. The token is never printed or logged.

### ebx install (shortcut)

Top-level shortcut for `ebx template install` — same options and behaviour. It is a system-default alias: like every top-level shortcut it can be re-mapped or removed via the `[shortcuts]` config section.

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

Start the local MCP server. The default transport is STDIO: notes, configuration, and how to stop go to stderr, and stdout is JSON-RPC only. The process waits on stdin; that wait is the running state. Stop it with Ctrl-C or `ebx mcp stop`. `--background` detaches an HTTP server (STDIO cannot keep serving after detach).

```bash
ebx mcp start [options]
ebx mcp start --http --background
```

| Option | Description |
|--------|-------------|
| `--template` | Default sandbox template (default: `code-interpreter-v1`) |
| `--api-key` | API Key override |
| `--api-url` | API URL override |
| `--domain` | Domain override |
| `--http` | Serve Streamable HTTP instead of STDIO |
| `--host` | HTTP bind address (default `127.0.0.1`). A non-loopback host requires a non-empty `--auth-token` |
| `--port` | HTTP port (default `9000`) |
| `--auth-token` | HTTP Bearer token (env `EBX_MCP_AUTH_TOKEN`) |
| `--background` | Detach the HTTP server; stop it later with `ebx mcp stop` |

### ebx mcp stop

Stop the local process recorded by `ebx mcp start` (foreground STDIO or background HTTP). Sends SIGTERM to that pid and waits for it to exit. When nothing is running, prints `MCP server is not running.`

```bash
ebx mcp stop
```

### ebx mcp status

Show MCP tools, authentication state, whether the local server is running (`mcp_running`), and IDE installation status.

```bash
ebx mcp status
```

### ebx mcp deploy

Generate an Alibaba Cloud FC deployment artifact (Streamable HTTP ASGI). Does not call the FC deployment API.

`POST /mcp` handles requests and `DELETE /mcp` terminates a session. `GET /mcp` returns 405 until SSE server notifications exist. Deploy requires a non-empty Bearer token.

```bash
ebx mcp deploy [options]
```

| Option | Description |
|--------|-------------|
| `--name` | FC function name (default: `easy-sandbox-mcp`) |
| `--region` | FC region (command `--region` > `SANDBOX_REGION` > `ebx config set region` > `cn-hangzhou`) |
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

Publish a template project: `docker build` → push to ACR → register the template → wait until ready. Fixed pipeline; **no description, no LLM, no LLM key**. It is step 2 of the template lifecycle (`ebx template init` → **`ebx deploy`** → `ebx create --template`); what the template is lives in `template.yaml`.

```bash
ebx deploy [PATH] [options]
```

`PATH` is the template directory (default: `.`). It must contain a `Dockerfile` unless `--dockerfile` is given. `template.yaml` supplies `name` (ACR repository), `resources.cpu`, `resources.memory` and `generation`; options override it.

`ebx deploy` accepts **every option of `ebx template deploy`** (`--acr-registry`, `--acr-namespace`, `--acr-repo`, `--alias -a`, `--tag -t`, `--cpu`, `--memory`, `--dockerfile -f`, `--yes -y`, `--verbose -v`, `--region -r`, ...; see `ebx deploy --help`). `--traditional` is deprecated and ignored.

```bash
ebx template init "a python data science env"   # 1. author (AI optional)
ebx deploy ./<name> --acr-namespace my-ns       # 2. publish
ebx create --template <TEMPLATE_ID>             # 3. launch
```

There is no instruction argument or `--agent` flag: describe the template once, when you author it. The in-sandbox agent deployment (`Sandbox.deploy`) is available from the SDK only.

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
