# CLI Command System Design

> `ebx` CLI is the command-line entry point for Easy Sandbox, designed for both human developers and AI Agents. The CLI's ultimate goal: **Users don't need to know about templates, resource specs, or configuration parameters — just describe what you want to do, and the sandbox handles everything automatically.**

***

## Table of Contents

1. [Command Tree](#1-command-tree)
2. [Global Options](#2-global-options)
3. [Natural Language Creation](#3-natural-language-creation)
4. [Core Command Details](#4-core-command-details)
5. [Configuration Management](#5-configuration-management)
6. [Core Workflows](#6-core-workflows)
7. [OutputManager Unified Output Management](#7-outputmanager-unified-output-management)
8. [AI Friendly Design Principles](#8-ai-friendly-design-principles)
9. [Future Plans](#9-future-plans)

***

## 1. Command Tree

```mermaid
graph TB
    ebx["ebx"]

    ebx --- create["create - Create sandbox (NL → Qwen Code template generation)"]
    ebx --- list["list - List all sandboxes"]
    ebx --- info["info - View sandbox details"]
    ebx --- kill["kill - Destroy sandbox / --all"]
    ebx --- execCmd["exec - Execute raw shell command"]
    ebx --- run["run - Dispatch named command"]
    ebx --- connect["connect - Interactive connection"]
    ebx --- upload["upload - Upload file/directory"]
    ebx --- download["download - Download file"]
    ebx --- deploy["deploy - Deploy project"]
    ebx --- install["install - Install community template"]
    ebx --- sandbox["sandbox"]
    ebx --- template["template"]
    ebx --- mcp["mcp"]
    ebx --- config["config"]

    sandbox --- sb_crud["create / list / info / kill / exec / connect / upload / download / run"]
    sandbox --- sb_files["files"]
    sandbox --- sb_process["process"]
    sandbox --- sb_system["system"]
    sandbox --- sb_cap["capabilities"]
    sandbox --- sb_shell["shell-stream"]

    sb_files --- f_list["list"]
    sb_files --- f_stat["stat"]
    sb_files --- f_mkdir["mkdir"]
    sb_files --- f_rm["rm"]
    sb_files --- f_mv["mv"]
    sb_files --- f_search["search"]

    sb_process --- p_list["list"]
    sb_process --- p_start["start"]
    sb_process --- p_info["info"]
    sb_process --- p_signal["signal"]

    sb_system --- sys_info["info"]
    sb_system --- sys_env["env"]
    sb_system --- sys_ports["ports"]
    sb_system --- sys_packages["packages"]
    sb_system --- sys_metrics["metrics"]

    template --- tpl_init["init"]
    template --- tpl_deploy["deploy"]
    template --- tpl_build["build"]
    template --- tpl_push["push"]
    template --- tpl_create["create"]
    template --- tpl_install["install"]
    template --- tpl_list["list"]
    template --- tpl_info["info"]
    template --- tpl_delete["delete"]
    template --- tpl_search["search"]

    mcp --- mcp_install["install"]
    mcp --- mcp_start["start"]
    mcp --- mcp_status["status"]
    mcp --- mcp_deploy["deploy"]

    config --- cfg_init["init"]
    config --- cfg_get["get"]
    config --- cfg_set["set"]
    config --- cfg_list["list"]
```

> `config reset` was removed before the first stable release — clear a stored value with `ebx config set KEY ""` (the empty value clears the key and it falls back to its default or to not set).

***

## 2. Global Options

| Option         | Short  | Description                | Default        |
| -------------- | ------ | -------------------------- | -------------- |
| `--json`       | `-j`   | Output in JSON format (AI-friendly) | `false`        |
| `--quiet`      | `-q`   | Quiet mode, only output key results | `false`        |
| `--verbose`    | `-v`   | Verbose output (DEBUG level logs)   | `false`        |
| `--no-color`   |        | Disable colored output             | `false`        |
| `--log-level`  |        | Explicitly set log level (DEBUG/INFO/WARNING/ERROR) | `None` |
| `--ci`         |        | CI/CD mode (equivalent to quiet + no-color + json) | `false` |
| `--timeout`    | `-t`   | Default timeout in seconds         | `300`          |
| `--profile`    | `-p`   | [Reserved] Configuration profile   | `None`         |
| `--version`    |        | Show version number                |                |
| `--help`       | `-h`   | Show help and exit (every command level) |           |

Every command accepts both `-h` and `--help`: the alias is configured once on the root group (`context_settings={'help_option_names': ['-h', '--help']}`) and inherited by the whole command tree through Click's Context mechanism — lazily loaded groups and nested sub-groups included.

```bash
# Example: JSON output + quiet
ebx list --json --quiet

# CI/CD mode (auto quiet + no-color + json)
ebx list --ci

# Specify log level
ebx create "python environment" --log-level DEBUG
```

`--region`/`-r` is a **command-level option**, not a global one. Only commands that talk to a regional control plane accept it:

```bash
# Region override for a single invocation
ebx list --region cn-shanghai
ebx sandbox list --region cn-shanghai
ebx template build ./my-template --acr-namespace ns --region cn-shanghai
ebx mcp deploy --region cn-shanghai

# Persistent region default
ebx config set region cn-shanghai
```

Resolution priority: command `--region` > `ebx config set region` / `SANDBOX_REGION` env > `cn-hangzhou`.

The CLI automatically detects CI environments (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `JENKINS_URL`, etc.) and enables CI mode automatically. Color output is automatically disabled in non-TTY environments.

***

## 3. Natural Language Creation (AI Template Generation)

> **Describe what you need in natural language, and the CLI calls Qwen Code to generate a Dockerfile plus a slim template.yaml, then builds, deploys, and creates the sandbox.**

`ebx create` has three routes, decided by the invocation:

| Invocation | Path |
|-----------|------|
| `ebx create` (no arguments) | **Rejected** — explicit usage error (exit code 2) listing the three valid routes; bare create never defaults to `base` silently |
| `ebx create --template <name>` | Direct template path (no AI generation) |
| `ebx create "natural language description"` | AI path (the focus of this section) |
| `ebx create "description" --template <name>` | Rejected — `DESCRIPTION` and `--template` are mutually exclusive (usage error, exit code 1) |

Neither input is ever silently dropped: when both are given the command refuses to run.

### AI Path Flow

```mermaid
graph TD
    Input["ebx create 'description'"] --> Find{"Locate Qwen Code<br/>PATH / ~/.ebx/bin"}
    Find -- not installed --> Install{"Interactive TTY and no --yes?"}
    Install -- confirm install --> Download["Download official standalone<br/>SHA256 verify → ~/.ebx/bin"]
    Install -- declined / non-TTY --> E2005["E2005 + Quick Setup"]
    Find -- installed --> Creds{"Credentials available?<br/>qwen_code_api_key → llm_api_key → env"}
    Creds -- missing --> Prompt["Interactive input & save<br/>non-TTY → E2006 + Quick Setup"]
    Creds -- available --> Research["Research round: agent settles public facts<br/>with its own tools (no schema)"]
    Research --> Assess{"Structured assessment<br/>same session, --json-schema"}
    Assess -- "complete / skipped / unavailable" --> Generate["Qwen Code headless generation<br/>Dockerfile + template.yaml"]
    Assess -- "incomplete, non-TTY" --> E2008["E2008 + missing details + example"]
    Assess -- "incomplete, TTY" --> Ask["Ask ONE question per round<br/>Question N, no total shown"]
    Ask --> Assess
    Generate -- success --> Verify["Validate Dockerfile (FROM)<br/>+ YAML schema"]
    Generate -- failure / timeout --> E2007["E2007 + keep generated dir"]
    Verify -- pass --> Confirm{"Confirm build & deploy?"}
    Confirm -- confirmed --> Deploy["Reuse template deploy pipeline<br/>build & push → deploy"]
    Deploy --> Create["Create sandbox"]
    Verify -- fail --> E2007
```

1. **Executable discovery**: checks `PATH` first, then `~/.ebx/bin` (recognizing `.cmd`/`.exe` suffixes on Windows).
2. **Install guidance**: when missing, interactive terminals are asked whether to install the official standalone build (SHA256-verified, atomically installed into `~/.ebx/bin`, executable bit set on Unix); non-TTY or a declined prompt raises `E2005` with the Quick Setup — no hang, no silent fallback.
3. **Credential resolution**: priority is the stored `qwen_code_api_key` → existing `llm_api_key` (officially compatible same-family credential) → exported `OPENAI_API_KEY`/`DASHSCOPE_API_KEY`/`BAILIAN_CODING_PLAN_API_KEY` (inherited by the child process, not injected) → `~/.qwen/settings.json`. Interactive terminals may prompt for and securely store a key; non-TTY raises `E2006`.
4. **Pre-generation clarification (research-first, two phases on one native session)**: before generating, the coding agent first runs a plain research round (`--session-id`, **no** `--json-schema`) in which it settles every publicly verifiable fact with its own tools (web fetch / shell) — tool stack, official install method, common runtimes and dependencies — recording safe defaults for anything unreachable. The same session then continues (`--resume`) with one structured `--json-schema` assessment round; verified against qwen-code 0.15.11, `--json-schema` ends the session on the first valid `structured_output` call, so the schema is deliberately absent from the research round to keep the tool loop free. Only user preferences, private constraints, and business decisions the agent cannot infer may count as missing. Below the 80% threshold, interactive terminals are asked exactly ONE question per round, numbered `Question 1`, `Question 2`, … with **no total shown** (the internal 5-round cap is mentioned only when reached); each answer resumes the same native session and triggers a fresh assessment against the full description + Q/A history, already-asked topics are embedded in every follow-up prompt (an exactly-repeated question breaks the loop defensively), and delegation answers ("you decide" / "use the default") instruct the agent to settle the choice itself with safe defaults. Non-TTY / CI sessions without `--yes` fail fast with `E2008`, listing the missing template facets and a ready-to-use example description. `--yes` skips research and assessment entirely; a failed research round only warns (never a gate), and an unavailable assessment degrades to direct generation with a warning. Phase status (assessing / re-assessing / generating) renders as a spinner on **stderr** (TTY) or one machine-readable progress line (non-TTY); stdout stays clean and the model's research output is never echoed. Generation then resumes the clarification session, so the model keeps the description, the research summary, and every Q/A pair in its own memory.
5. **Generation & validation**: runs Qwen Code in headless mode inside a fresh `~/.ebx/generated/<slug>-<timestamp>/` workspace (template name `ebx-nl-<slug>-<token>`) via `qwen "<prompt>" --output-format json --yolo` (the prompt is positional — the legacy `-p` flag is deprecated per the 0.15.11 `--help`; list-form arguments, bounded cwd and timeout — 600s by default, overridable with `EBX_QWEN_CODEGEN_TIMEOUT`), expecting a Dockerfile and a slim template.yaml; both are then validated — the Dockerfile must contain `FROM`, and template.yaml must pass the `parse_template_data` YAML schema check. Failure or timeout raises `E2007` and keeps the generated directory for inspection.
6. **Build & create**: after confirmation, reuses the `ebx template deploy` build/deploy pipeline (`--acr-namespace` selects the push namespace) and then calls the existing `Sandbox.create`. No step ever silently falls back to `base`; failures report the error code, the Quick Setup, and next-step commands.

### Examples

```bash
# Interactive: AI-generated template → build & deploy → create
# ebx create "run python data analysis with pandas and jupyter"

# Non-interactive (CI): -y is required, otherwise install/credentials/confirm steps fail fast
# ebx create -y "a node.js api server"

# Explicit template bypasses AI generation
# ebx create --template codex
# ebx create -T browser-automation

# Non-interactive with an incomplete description → E2008 (missing details + example)
# ebx create "run python"

# Rejected: DESCRIPTION and --template are mutually exclusive (exit code 1)
# ebx create "a node.js api" --template base

# With file upload
# ebx create "analyze this CSV file" --upload data.csv
```

### Install & Credential Guidance

- **Automatic install**: official standalone assets are downloaded into `~/.ebx/bin`; download sources are verified — the Aliyun mirror is preferred with the GitHub release asset as fallback, and `SHA256SUMS` must validate (a mismatch fails immediately, no fallback).
- **Manual install**: the Quick Setup and `ebx create --help` print the official installer commands (`install-qwen-standalone.sh` / `.ps1`).
- **Credential storage**: `ebx config set qwen_code_api_key <KEY>` writes to `~/.ebx/.env`; alternatively `ebx config init` configures the platform API key, region, and Qwen Code credentials in one guided pass (printing equivalent non-interactive commands on non-TTY).

### Available Templates

The single source of truth for template content and the index is the
[`Easy-Sandbox/awesome-templates`](https://github.com/Easy-Sandbox/awesome-templates)
repository (`awesome-templates.yaml` at its root). The CLI no longer ships a
fixed template list — it discovers templates from the remote index:

```bash
ebx template search web             # search the remote index by name/tag/description
ebx template install node-web      # install by index name (resolved to owner/repo//subdir@ref)
```

- The index is cached under `~/.ebx/index/` with a 1-hour TTL; a fresh cache is served without touching the network.
- On network failures / rate limits (403/429/5xx) the client falls back to the stale cache with a warning; without a cache it fails loudly with remediation (`ebx config set github_token` / `GITHUB_TOKEN`, `--index-url`, `--refresh`). An anonymous rate limit (E5000) additionally shows the officially documented fine-grained PAT prefill URL, and in an interactive terminal offers a masked one-shot `github_token` setup followed by exactly one automatic retry.
- Entries may pin a remote revision via the `ref` field; bare names that resolve to builtin templates (`base`, `code-interpreter-v1`) never hit the network.
- The index schema carries a `schema_version`; a version newer than the client supports fails explicitly with an upgrade hint.

> This repository's `examples/templates/` keeps only the minimal `python-hello`
offline **fixture** — it is not a publishing source.

***

## 4. Core Command Details

### ebx create

```bash
ebx create [DESCRIPTION] [options]

Arguments:
  DESCRIPTION               Natural language description (optional; the basis for AI generation)

Options:
  --template, -T <name>     Specify template name (skips AI generation; mutually exclusive with DESCRIPTION)
  --upload, -u <path>       Upload local file/directory after creation
  --timeout, -t <seconds>   Sandbox timeout
  --env, -e <KEY=VALUE>     Environment variable (can be used multiple times)
  --metadata, -m <KEY=VALUE> Metadata key-value pair (can be used multiple times)
  --yes, -y                 Skip interactive confirmations and the research-first clarification flow (install/credentials/description research & assessment/build & deploy); required in non-interactive environments
  --acr-namespace <ns>      ACR namespace for building and pushing AI-generated templates

Examples:
  ebx create "python data analysis"       # AI-generated template → build & deploy → create
  ebx create -y "node.js api server"     # Non-interactive AI path
  ebx create --template code-interpreter # Direct template path
  ebx create "Node.js API" -e PORT=3000
  ebx create "Analyze data" --upload ./data.csv
```

### ebx list

```bash
ebx list [options]

Options:
  --status, -s <status>     Filter by status (running/stopped/creating/paused/error)
  --limit, -l <n>           Limit count (default: 20)

Examples:
  ebx list
  ebx list --status running --json
  ebx list -l 50
```

**Output Format**:

```
$ ebx list
  ID            Template             Status    Region
  sb-a1b2c3d4   code-interpreter     running   cn-hangzhou
  sb-e5f6g7h8   python-data-science  running   cn-hangzhou
  sb-i9j0k1l2   base                 stopped   cn-shanghai
```

### ebx info

```bash
ebx info <sandbox-id>

Examples:
  ebx info sb-a1b2c3d4
  ebx info sb-a1b2c3d4 --json
```

**Output Format**:

```
$ ebx info sb-a1b2c3d4
  ID:           sb-a1b2c3d4
  Template:     code-interpreter
  Status:       running
  Region:       cn-hangzhou
  Timeout:      300s
  URL:          https://sb-a1b2c3d4.envd.example.com
  Started:      2026-09-01 14:00:00
```

### ebx kill

```bash
ebx kill <sandbox-id> [options]
ebx kill --all [options]

Options:
  --all                     Destroy all running sandboxes
  --yes, -y                 Skip confirmation prompt

Examples:
  ebx kill sb-abc123
  ebx kill sb-abc123 --yes
  ebx kill --all --yes
```

### ebx exec

```bash
ebx exec <sandbox-id> <command> [options]

Options:
  --timeout, -t <seconds>   Command timeout (default: 60)
  --cwd <path>              Working directory (default: /app)

Examples:
  ebx exec sb-abc123 "python train.py"
  ebx exec sb-abc123 "npm start" --timeout 120
  ebx exec sb-abc123 "ls -la" --json
```

**Output Format**:

```
$ ebx exec sb-abc123 "python -c 'print(1+1)'"
2

$ ebx exec sb-abc123 "python -c 'print(1+1)'" --json
{
  "stdout": "2\n",
  "stderr": "",
  "exit_code": 0,
  "execution_time": 0.12
}
```

The `exec` command propagates the exit code from the sandbox command as its own exit code.

### ebx run

```bash
ebx run <sandbox-id> <command-name> [options]

Arguments:
  command-name              Named command declared in the template's `custom_commands`

Options:
  --arg, -a <KEY=VALUE>     Named command arguments (can be used multiple times)
  --timeout, -t <seconds>   Override command-declared timeout

Examples:
  ebx run sb-abc123 serve --arg port=9000
  ebx run sb-abc123 migrate --arg target=head --json
```

`run` is a **template-aware** named command dispatcher: it resolves `command-name` against the sandbox template's `custom_commands` declaration, validates `--arg` parameters against the `args` schema, escapes them with `shlex.quote()`, fills in the command template, and executes in the sandbox.

**Semantic distinction between `run` and `exec`**:

- `ebx exec` = raw shell command (arbitrary string, requires `shell` capability).
- `ebx run` = template-declared named command (structured parameters + injection prevention).

Error handling:

- `command-name` not declared → error with list of available commands.
- Missing `required` parameters → error before execution.
- Sandbox lacks required capability → throws `CapabilityNotSupportedError` (E3xxx) with fix suggestions.

See ADR `2026-09-03-cli-run-vs-exec.md` for details.

### ebx deploy

`ebx deploy` supports two modes: **NL mode** (default, uses qwen-code agent to automatically analyze, install dependencies, build, and start the service) and **traditional mode** (manual build + run).

```bash
ebx deploy [PATH] [INSTRUCTION] [options]

Arguments:
  PATH                            Project directory (default: .)
  INSTRUCTION                     Natural language deployment instruction (optional)

Options:
  --instruction, -i <text>        NL deployment instruction (alternative to positional arg)
  --max-wall-time <duration>      qwen-code max execution time (e.g., '10m', '600s')
  --max-session-turns <n>         qwen-code session turn limit (default: 100)
  --alias, -a <name>              Template alias (traditional mode)
  --watch                         Watch file changes for auto-redeploy (traditional mode)
  --traditional                   Use traditional build+run mode instead of AI deployment

Examples:
  # NL mode (default)
  ebx deploy ./my-project "This is a FastAPI project that needs Redis"
  ebx deploy ./my-project -i "Deploy to port 8080"

  # Traditional mode
  ebx deploy ./my-project --traditional
```

NL mode workflow:
1. Create a `qwen-code` template sandbox
2. Upload project files to `/workspace`
3. qwen-code agent automatically analyzes project type, installs dependencies, builds, and starts the service
4. Parse deployment results (status, URL, ports, logs)

Traditional mode supports automatic project type detection (Python / Node.js / Go / Java / Docker) and provides `ebx deploy build` and `ebx deploy run` subcommands for fine-grained control.

### ebx connect

```bash
ebx connect <sandbox-id>

Examples:
  ebx connect sbx-abc123
```

Connect to the sandbox's interactive, line-based REPL - not a PTY or an SSH session. Every entered line runs in a new process (30-second timeout) and no shell state survives between lines: `cd`, environment variables and aliases are gone after each command (use `cd /path && <cmd>` on one line, or `ebx exec --cwd`). Interactive terminals get basic line editing and history (Up/Down, Ctrl+R, Ctrl+A/E). Type `exit`, `quit`, or `Ctrl+D` to disconnect; `Ctrl+C` also disconnects. Failed commands produce one friendly message - never a raw HTTP error, sandbox URL or MDN link.

**Interactive Example**:

```
$ ebx connect sbx-abc123
✓ Connected to sandbox sbx-abc123
Type 'exit' or Ctrl+D to disconnect
Note: each line runs in an independent process - cd, environment variables and shell state do not persist

ebx:sbx-abc1> ls /app
main.py  data/  requirements.txt

ebx:sbx-abc1> sl /app
[E3006] Command not found: sl
  Suggestion: Did you mean 'ls'? It ran earlier in this session.

ebx:sbx-abc1> python -c "print('hello')"
hello

ebx:sbx-abc1> exit
Disconnected.
```

### ebx upload

```bash
ebx upload <sandbox-id> <local-path> <remote-path>

Examples:
  ebx upload sb-abc123 ./script.py /app/script.py
  ebx upload sb-abc123 ./data/ /app/data/
```

Supports uploading single files or entire directories. Directory uploads recursively upload all files.

### ebx download

```bash
ebx download <sandbox-id> <remote-path> <local-path>

Examples:
  ebx download sb-abc123 /app/result.csv ./result.csv
  ebx download sb-abc123 /app/output.log .
```

Download files from the sandbox to local. If `local-path` is a directory, the filename is taken from the remote path.

### ebx sandbox files

Sandbox file operation subcommand group with 6 commands.

#### files list

```bash
ebx sandbox files list <sandbox-id> [options]

Options:
  --path, -p <path>       Directory path (default: /home/user)
  --recursive, -r         List recursively (max depth 5)

Examples:
  ebx sandbox files list abc123
  ebx sandbox files list abc123 --path /app --recursive
```

#### files stat

```bash
ebx sandbox files stat <sandbox-id> [options]

Options:
  --path, -p <path>       File or directory path (required)

Examples:
  ebx sandbox files stat abc123 --path /home/user/app.py
```

#### files mkdir

```bash
ebx sandbox files mkdir <sandbox-id> [options]

Options:
  --path, -p <path>       Directory path to create (required)

Examples:
  ebx sandbox files mkdir abc123 --path /home/user/myproject/src
```

Automatically creates parent directories.

#### files rm

```bash
ebx sandbox files rm <sandbox-id> [options]

Options:
  --path, -p <path>       File or directory path to delete (required)
  --yes, -y               Skip confirmation

Examples:
  ebx sandbox files rm abc123 --path /home/user/temp.txt
  ebx sandbox files rm abc123 --path /home/user/old_dir -y
```

#### files mv

```bash
ebx sandbox files mv <sandbox-id> [options]

Options:
  --source, -s <path>     Source path (required)
  --dest, -d <path>       Destination path (required)

Examples:
  ebx sandbox files mv abc123 --source /home/user/old.py --dest /home/user/new.py
```

#### files search

```bash
ebx sandbox files search <sandbox-id> [options]

Options:
  --path, -p <path>       Search directory (required)
  --pattern <glob>        Glob pattern, e.g., '*.py' (required)
  --max-depth <n>         Max search depth (default: 5)

Examples:
  ebx sandbox files search abc123 --path /home/user --pattern "*.py"
  ebx sandbox files search abc123 --path /app --pattern "*.log" --max-depth 3
```

### ebx sandbox process

Sandbox process management subcommand group with 4 commands.

#### process list

```bash
ebx sandbox process list <sandbox-id>

Examples:
  ebx sandbox process list abc123
```

Lists processes running in the sandbox, including PID, command, and status.

#### process start

```bash
ebx sandbox process start <sandbox-id> [options]

Options:
  --command, -c <cmd>     Command to run (required)
  --timeout, -t <seconds> Timeout in seconds (default: 300)
  --cwd <path>            Working directory

Examples:
  ebx sandbox process start abc123 --command "python app.py"
  ebx sandbox process start abc123 -c "node server.js" --cwd /app
```

Outputs stdout/stderr after process completion; exit code propagates as CLI exit code.

#### process info

```bash
ebx sandbox process info <sandbox-id> <pid>

Examples:
  ebx sandbox process info abc123 1234
```

Queries process information using `ps`, outputting PPID, User, State, RSS, Elapsed, etc.

#### process signal

```bash
ebx sandbox process signal <sandbox-id> <pid> [options]

Options:
  --signal, -s <number>   Signal number (default: 15/SIGTERM)

Examples:
  ebx sandbox process signal abc123 1234
  ebx sandbox process signal abc123 1234 --signal 9
```

Common signals: 15 (SIGTERM), 9 (SIGKILL), 2 (SIGINT).

### ebx sandbox system

Sandbox system information subcommand group with 5 commands.

#### system info

```bash
ebx sandbox system info <sandbox-id>

Examples:
  ebx sandbox system info abc123
```

Displays OS, architecture, CPU count, Python version, disk space, etc.

#### system env

```bash
ebx sandbox system env <sandbox-id> [options]

Options:
  --filter, -f <names>    Comma-separated variable name allowlist

Examples:
  ebx sandbox system env abc123
  ebx sandbox system env abc123 --filter PATH,HOME,LANG
```

Sensitive variables containing TOKEN, SECRET, KEY, PASSWORD are automatically excluded.

#### system ports

```bash
ebx sandbox system ports <sandbox-id>

Examples:
  ebx sandbox system ports abc123
```

Queries listening TCP ports using `ss -tlnp` or `netstat -tlnp`.

#### system packages

```bash
ebx sandbox system packages <sandbox-id> [options]

Options:
  --manager, -m <pip|npm> Package manager (default: pip)

Examples:
  ebx sandbox system packages abc123
  ebx sandbox system packages abc123 --manager npm
```

#### system metrics

```bash
ebx sandbox system metrics <sandbox-id>

Examples:
  ebx sandbox system metrics abc123
```

Displays CPU load (1/5/15 min), disk usage, and other real-time metrics.

### ebx sandbox capabilities

```bash
ebx sandbox capabilities <sandbox-id>

Examples:
  ebx sandbox capabilities abc123
```

Lists capability groups supported by the sandbox (e.g., shell, files, code, terminal, ports, etc.).

### ebx sandbox shell-stream

```bash
ebx sandbox shell-stream <sandbox-id> [options]

Options:
  --command, -c <cmd>     Command to execute (required)
  --timeout, -t <seconds> Timeout in seconds (default: 300)
  --cwd <path>            Working directory

Examples:
  ebx sandbox shell-stream abc123 --command "pip install numpy"
  ebx sandbox shell-stream abc123 -c "make build" --cwd /app
```

Unlike `exec`, `shell-stream` prints output line by line in real time (using SSE streaming), suitable for long-running commands. Exit code propagates as CLI exit code.

### ebx install

```bash
ebx install <template-ref> [options]

Options:
  --registry-url <url>      Registry URL (default: GitHub)
  --registry-type <type>    Registry type (github/local), auto-detected
  --token <token>           Access token (private repos / higher rate limits); temporary override only — prefer 'ebx config set github_token' (--token may leak into shell history and process listings)
  --alias, -a <name>        Template alias

Examples:
  ebx install node-web                    # bare name → remote index → owner/repo//subdir[@ref]
  ebx install owner/repo
  ebx install owner/repo//subdir@v1.0
  ebx install ./my-template --registry-type local
```

This is a top-level shortcut for `ebx template install`.  Bare-name resolution and
degraded behaviour: see [§3 Available Templates](#available-templates).

### ebx template

#### template init

```bash
ebx template init [DIRECTORY] [options]

Options:
  -t, --template <case>     Built-in scaffold case (python, node, minimal)
  --from <ref>              Fetch template source from a registry ref (owner/repo or local path)
  --name <name>             Template name (default: case name or fetched template name)
  --list                    List available scaffold cases
  --force                   Overwrite existing files

Examples:
  ebx template init --list
  ebx template init -t python            # Creates ./python/
  ebx template init -t python ./my-app   # Explicit directory
  ebx template init --from owner/repo
```

Generates an editable local template project (`template.yaml` + `Dockerfile` + `commands.py`) without building or deploying anything — continue with `ebx template deploy <dir>` when ready. `ebx init` is a top-level shortcut delegating to the exact same command object; guided credentials setup is `ebx config init`.

##### Top-level shortcuts vs user custom commands

- **Built-in top-level shortcuts** (`create`, `list`, `init`, `install`, `deploy`, `run`, …) are registered in the `LazyGroup(lazy_subcommands=...)` map in `src/easy_sandbox/cli/main.py`. This map is a **project-maintainer registration point** for the built-in top-level entry points — it is not a user-facing extension mechanism.
- **User-defined commands** are declared in the template's `template.yaml` (`custom_commands`) or registered on a SandboxServer (`@registry.command`), and invoked through `ebx run COMMAND` / `Sandbox.custom(name)`.
- The `config.toml [shortcuts]` section sketched in the original CLI design draft (`2026-09-23-cli-final-design.md` §2.2) was **never implemented**: there is no user-side declarative alias configuration. Any doc or config snippet suggesting `[shortcuts]` in `~/.ebx/config.toml` describes an unimplemented historical draft, not a current capability.
- Unknown top-level commands get a targeted hint: a close spelling match (difflib, cutoff 0.6) yields `Did you mean '…'?`; with no plausible candidate the error points to `custom_commands` + `ebx run`. Exit code 2 and stderr-only output are preserved; only the root group is affected.

#### template deploy

```bash
ebx template deploy <template-dir> [options]

Options:
  (same as template build — performs build → push → create in one step)

Examples:
  ebx template deploy ./my-template
  ebx template deploy ./my-template --alias my-env
```

End-to-end pipeline: build Docker image locally, push to ACR, and call CreateTemplate API. This is the recommended one-command workflow for publishing templates.

#### template build

```bash
ebx template build <template-dir> [options]

Options:
  --acr-registry <url>      ACR registry URL
  --acr-namespace <ns>      ACR namespace (required)
  --alias, -a <name>        Template alias
  --tag, -t <tag>           Image tag
  --platform <platform>     Target platform
  --cpu <n>                 CPU cores
  --memory <mb>             Memory in MB
  --dockerfile, -f <path>   Custom Dockerfile path
  --official-api/--legacy-api   Use official CreateTemplate API
  ... (see --help for full options)

Examples:
  ebx template build ./my-template --acr-namespace my-ns
```

Build a Docker image from a template directory, push to ACR, and register via CreateTemplate API.

#### template push

```bash
ebx template push <image> [options]

Options:
  --acr-registry <url>      ACR registry URL
  --acr-namespace <ns>      ACR namespace (required)
  --acr-username <user>     ACR username
  --acr-password <pass>     ACR password

Examples:
  ebx template push my-image:v1 --acr-namespace my-ns
```

Push an existing local Docker image to ACR without building or registering a template.

#### template create

```bash
ebx template create <image> [options]

Options:
  --name, -n <name>         Template name (required)
  --team-id <id>            Team ID
  --cpu <n>                 CPU cores
  --memory <mb>             Memory in MB
  --disk-size <mb>          Disk size in MB
  --start-cmd <cmd>         Start command
  --ready-cmd <cmd>         Readiness probe command
  ... (see --help for full options)

Examples:
  ebx template create registry.cn-hangzhou.aliyuncs.com/ns/img:v1 -n my-template
```

Register a template from an image already in ACR by calling the CreateTemplate API. Use this when the image is already pushed.

#### template install

```bash
ebx template install <template-ref> [options]

Options:
  --registry-url <url>      Registry URL (default: GitHub)
  --registry-type <type>    Registry type (github/local)
  --token <token>           Access token (required for private repos); temporary override only — prefer 'ebx config set github_token' (--token may leak into shell history and process listings)
  --alias, -a <name>        Template alias

Examples:
  ebx template install owner/repo              # Entire repo
  ebx template install owner/repo//subdir      # Specific subdirectory
  ebx template install owner/repo@v1.0         # Specific version
  ebx template install owner/repo --token xxx  # Private repo (one-off; prefer 'ebx config set github_token')
  ebx template install ./my-template           # Local directory
```

Token resolution order: `--token` > process `GITHUB_TOKEN` > stored `github_token` (`ebx config set github_token`, masked input, stored in `~/.ebx/.env`) > no token. On an anonymous rate limit the full `owner/repo//subdir@ref` reference is preserved in the error, and an interactive terminal is offered the masked token setup with one automatic retry.

Install templates from GitHub or local directories. The template directory must contain a `template.yaml` file.

#### template list

```bash
ebx template list [options]

Options:
  --official-api/--no-official-api   Use official API
```

Lists all templates (queried via Platform API).

#### template info

```bash
ebx template info <template-id> [options]

Options:
  --official-api/--no-official-api   Use official API
```

View template details.

#### template delete

```bash
ebx template delete <template-id>
```

Delete a template (requires confirmation).

#### template search

```bash
ebx template search <query> [options]

Options:
  --tag, -t <tag>           Filter by tag
  --status, -s <status>     Filter by status

Examples:
  ebx template search python
  ebx template search "data science" --tag ml
```

Search templates by name, description, or tags.

### ebx mcp

#### mcp install

```bash
ebx mcp install --target <cursor|claude|vscode>
```

Install MCP Server configuration to a specified IDE. Supports Cursor, Claude Desktop, and VS Code. After installation, lists registered tools:

- `create_sandbox` — Create a cloud sandbox
- `run_code` — Execute code
- `run_command` — Execute commands
- `read_file` — Read files
- `write_file` — Write files
- `list_files` — List files
- `kill_sandbox` — Destroy sandbox

#### mcp start

```bash
ebx mcp start [options]

Options:
  --template <name>         Default sandbox template (default: code-interpreter-v1)
  --api-key <key>           API Key override (env: E2B_API_KEY)
  --api-url <url>           API URL override (env: E2B_API_URL)
  --domain <domain>         Domain override (env: E2B_DOMAIN)
```

Start MCP Server in STDIO mode. Usually called automatically by the IDE; manual execution is not typically needed.

#### mcp status

```bash
ebx mcp status
```

Display MCP Server status: transport mode, tool count, auth config, installation status for each IDE.

#### mcp deploy

```bash
ebx mcp deploy [options]

Options:
  --name <name>             FC function name (default: easy-sandbox-mcp)
  --region <region>         FC region; falls back to ebx config set region /
                            SANDBOX_REGION env, else cn-hangzhou
  --template <name>         Default sandbox template (default: base)
  --memory <mb>             FC function memory (default: 512)
  --timeout <seconds>       FC function timeout (default: 600)
  --auth-token-file <path>  Bearer token file (or --generate-token)
  --generate-token          Auto-generate a random Bearer token
  --enable-session-affinity / --no-session-affinity
                            Mcp-Session-Id affinity (default: enabled)
  --api-key <key>           Inject API key into FC env
  --custom-domain <domain>  Custom domain for the MCP endpoint
  --output-dir <path>       Write the artifact to this directory

Examples:
  ebx mcp deploy --generate-token --api-key $E2B_API_KEY --output-dir ./artifact
  ebx mcp deploy --auth-token-file ./token.txt --region cn-shanghai
```

Generate an Alibaba Cloud FC deployment artifact (requirements.txt, app.py ASGI entry point, and a YAML config.yaml manifest) and print manual FC deployment steps. Automatic FC API deployment is not implemented. See [MCP Server Design — FC Deployment](mcp-server.md#7-fc-deployment) for architecture details.

***

## 5. Configuration Management

The configuration file is located at `~/.ebx/config.toml`, with API Keys stored separately in `~/.ebx/.env`.

### Configurable Items

| Config Key      | Description                           | Default                   |
| --------------- | ------------------------------------- | ------------------------- |
| `api_key`       | E2B API Key                           | (not set)                 |
| `api_url`       | Platform API URL                      | (auto)                    |
| `region`        | Default region                        | `cn-hangzhou`             |
| `http_timeout`  | HTTP request timeout (seconds)        | (auto)                    |
| `max_retries`   | Max retry count                       | (auto)                    |
| `domain`        | Envd Domain                           | (auto)                    |
| `llm_api_key`   | LLM API Key (for deploy; also a compatible fallback for Qwen Code credentials) | (not set) |
| `llm_model`     | LLM model name                        | (not set)                |
| `llm_base_url`  | LLM API Base URL (OpenAI compatible)  | (not set)                |
| `qwen_code_api_key` | Qwen Code API Key (AI template generation, stored in `.env`) | (not set) |
| `qwen_code_base_url` | Qwen Code OpenAI-compatible Base URL | DashScope compatible endpoint |
| `qwen_code_model` | Qwen Code model name                  | `qwen3-coder-plus`       |

Sensitive config items (`api_key`, `llm_api_key`, `qwen_code_api_key`) are automatically masked in `config list` output.

### Command Examples

```bash
# Set API Key
ebx config set api_key e2b_xxx

# Configure Qwen Code credentials (dedicated key for AI template generation)
ebx config set qwen_code_api_key sk-xxx

# Or run the guided wizard (platform API key, region, Qwen Code)
ebx config init

# llm_api_key works as a compatible fallback for Qwen Code credentials
ebx config set llm_api_key sk-xxx

# View configuration
ebx config list
ebx config get region

# Clear one stored value (falls back to default / not set)
ebx config set region ""
```

LLM configuration also supports environment variable overrides: `EBX_LLM_API_KEY`, `EBX_LLM_MODEL`, `EBX_LLM_BASE_URL`.

***

## 6. Core Workflows

### Workflow 1: Quick Experimentation

```bash
# One command, from description to usable environment
ebx create "python data analysis with pandas and matplotlib"
# → sb-abc123

ebx exec sb-abc123 "python -c 'import pandas; print(pandas.__version__)'"
# 2.1.0

ebx kill sb-abc123
```

### Workflow 2: File-Based Interactive Development

```bash
# Create sandbox and upload project
ebx create -T code-interpreter --upload ./project

# View sandbox contents
ebx exec sb-abc123 "ls /home/user/"

# Execute code
ebx exec sb-abc123 "python /home/user/main.py"

# Download results
ebx download sb-abc123 /app/result.csv ./result.csv

# Destroy when done
ebx kill sb-abc123 --yes
```

### Workflow 3: Interactive Debugging

```bash
# Create and connect to sandbox
ebx create -T code-interpreter
ebx connect sbx-abc123

# Work in the line-based REPL (each line is a fresh process)
ebx:sbx-abc1> pip install requests && python my_script.py
ebx:sbx-abc1> cat /app/output.log
ebx:sbx-abc1> exit
```

### Workflow 4: AI Agent Integration

```bash
# Install MCP Server to Cursor
ebx mcp install --target cursor

# Check status
ebx mcp status

# AI Agent automatically uses sandboxes via MCP
# (Natural language operations in Cursor/Claude)
```

### Workflow 5: Custom Templates

```bash
# Install community template from GitHub
ebx install owner/my-template

# Or build from Dockerfile
ebx template build -f ./Dockerfile --alias my-ml-env

# Check template status
ebx template list

# Use custom template
ebx create --template my-ml-env
```

***

## 7. OutputManager Unified Output Management

> All CLI commands uniformly use `OutputManager` (`cli/output.py`) instead of bare `click.echo` calls, ensuring consistent output behavior across different modes.

### Channel Policy: Results vs. Diagnostics

The manager owns two channels and never mixes them, so machine-readable output stays pipeable:

| Channel | Content | Consumers |
|---------|---------|-----------|
| **stdout** | Final results: `data`, `table`, `success` | humans and scripts (`ebx ... --json \| jq`) |
| **stderr** | Progress state and diagnostics: `info`, `progress`, `warning`, `error`, `debug`, plus **every stdlib `logging` record** | humans following a long-running command |

Consequences:

- In `--json` mode stdout stays a **single JSON document**; the JSON forms of `info` / `warning` / `progress` / `debug` / `error` are written to stderr instead.
- Library warnings and DEBUG diagnostics are bridged through one handler on the root logger, so a warning is rendered exactly once (no duplicate `WARNING:` line next to the SDK's timestamped line).
- Progress spinners render on stderr; every write pauses the live spinner and resumes it afterwards, so status text and results never interleave.
- `--quiet`, `--json` and `--ci` therefore keep stdout free of status text and log records.

### Output Methods

| Method | Description | Channel | Quiet Mode | JSON Mode |
|--------|-------------|---------|------------|-----------|
| `info(message)` | Informational message | stderr | Suppressed | `{"level": "info", ...}` → stderr |
| `success(message)` | Success message (green) | stdout | Suppressed | `{"status": "success", ...}` → stdout |
| `warning(message)` | Warning message (yellow) | stderr | Suppressed | `{"level": "warning", ...}` → stderr |
| `error(message)` | Error message (red, **always shown**) | stderr | Shown | `{"status": "error", ...}` → stderr |
| `debug(message)` | Debug message (verbose mode only) | stderr | Suppressed | `{"level": "debug", ...}` → stderr |
| `data(data)` | Structured data (dict/list) | stdout | Values only | JSON object |
| `table(headers, rows)` | Table data (Rich table + plain text fallback) | stdout | Tab-separated | `[{...}, ...]` |
| `progress(message)` | Progress/status message | stderr | Suppressed | `{"level": "progress", ...}` → stderr |

### Environment Auto-Detection

- **TTY Detection**: Automatically detects whether stdout is connected to a terminal; color output is automatically disabled in non-TTY environments.
- **CI Environment Detection**: Detects `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `JENKINS_URL`, `TRAVIS`, `CIRCLECI`, `BITBUCKET_PIPELINES`, `TF_BUILD`, `CODEBUILD_BUILD_ID` and other environment variables, automatically enabling CI mode (quiet + no-color + json).

### Logging Bridge

`OutputManager` installs one `_LogBridgeHandler` on the **root** logger (format `LEVELNAME: message`, level = the CLI log level) and drops the SDK's standalone handler installed by `easy_sandbox.utils.logging`. That is what keeps a library warning such as the capability-resolver fallback from being printed twice:

```
WARNING: Could not resolve capabilities for template 'base'; falling back to DEFAULT_CAPABILITIES
```

Log propagation stays enabled, so test log capture (`caplog`) and embedding applications keep seeing records. During a CLI run the verbosity flags (`--verbose` / `--quiet` / `--log-level`, plus CI auto-detection) are the single source of truth for the log level; `SANDBOX_LOG_LEVEL` applies to standalone SDK use, where the SDK owns logging.

### Spinner Pause / Resume

Interactive spinners are Rich `Status` objects rendered on stderr. The manager keeps the live statuses on a stack and pauses all of them before writing anything, resuming afterwards (`_spinner_guard`). This replaces the old behaviour where a raw logging handler wrote straight past the live display and produced garbled text such as `⠋ Waiting...DEBUG: https://...`.

### Usage

```python
from easy_sandbox.cli.output import get_output

# Get OutputManager in any Click command
out = get_output(ctx)
out.info("Creating sandbox...")
out.success("Sandbox created successfully")
out.data({"sandbox_id": "sb-abc123", "status": "running"})
```

`get_output(ctx)` retrieves the `OutputManager` instance from Click context's `ctx.meta["sbox.output"]`, falling back to a default instance when no context is available.

***

## 8. AI Friendly Design Principles

The CLI is designed for both humans and AI; the following principles ensure AI Agents can efficiently use the CLI:

### Principle 1: Structured Output

```bash
# All commands support --json for structured JSON output
ebx list --json
ebx info sb-abc123 --json
ebx exec sb-abc123 "echo hello" --json
```

### Principle 2: Deterministic Exit Codes

| Exit Code | Meaning     |
| --------- | ----------- |
| `0`       | Success     |
| `1`       | General error |
| `2`       | Argument error |
| `3`       | Auth failure |
| `4`       | Resource not found |
| `5`       | Timeout     |
| `6`       | Quota exceeded |

### Principle 3: Non-Interactive Mode

```bash
# --yes skips confirmation (supported by kill, etc.)
ebx kill --all --yes

# --quiet minimizes output
ebx create "python environment" --quiet
```

### Principle 4: Composable Pipelines

```bash
# Get ID directly after creation
ID=$(ebx create "python environment" --quiet)

# Pipeline composition
ebx list --json | jq '.[].sandbox_id'

# Batch destroy
ebx list --json | jq -r '.[].sandbox_id' | xargs -I{} ebx kill {} --yes
```

### Principle 5: Self-Describing Help

Every command accepts both `-h` and `--help` — the alias is configured once at the root group and inherited by the whole command tree.

```bash
# Every command's --help / -h includes complete documentation
ebx create --help
ebx create -h
ebx template install --help

# Error messages include fix suggestions
$ ebx config set unknown_key value
Error: Unknown config key: 'unknown_key'
Available keys: api_key, api_url, domain, ...
```

### Principle 6: Lazy Loading for High Performance

The CLI uses `LazyGroup` for lazy loading, achieving `ebx --help` response time < 200ms. Modules and dependencies are only loaded when a command is actually executed.

***

## 9. Future Plans

The following features are not yet implemented and are planned for future versions:

- **`ebx build [path]`**: Automatically detect and build sandbox images from project directories
- **`ebx logs <sandbox-id>`**: View sandbox real-time logs
- **`ebx hibernate / wake`**: Sandbox hibernation and wake (requires underlying platform support)
- **`ebx snapshot`**: Create sandbox snapshots (requires underlying platform support)
- **Hot Reload Mode**: `--watch` flag for automatic sync of local file changes to sandbox
