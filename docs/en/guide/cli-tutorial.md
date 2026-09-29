# CLI Tutorial

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

### Quick Orientation: `config init` vs `template init` vs `create`

| I want to... | Command |
|--------------|---------|
| Store credentials / endpoints (run first) | `ebx config init` — guided interactive wizard |
| Create a cloud sandbox (default, existing template, or AI-generated) | `ebx create [DESCRIPTION]` |
| Scaffold an editable local template project | `ebx template init [DIRECTORY]` — writes files only, no build or deploy |

### Using the Default Template

```bash
ebx create --template base
# Output similar to:
# ✓ Sandbox created: sbx-xxxx
```

### Natural Language Creation (AI-generated templates)

```bash
# First run: guided setup for platform credentials and Qwen Code
# ebx config init

# Qwen Code generates Dockerfile + template.yaml → build & deploy → create sandbox
ebx create "a Python data analysis environment"
```

Before generating, the agent first researches the publicly verifiable facts itself — whether the tool is Node.js-based, its official install method, common runtimes and dependencies — then assesses the description for completeness (target: 80%). Only user preferences, private constraints, and business decisions it cannot infer become questions, asked **one at a time** and numbered `Question 1`, `Question 2`, … with no total shown; press Enter to cancel:

```text
Description is about 40% complete. I'll ask for the missing details one question at a time — press Enter to cancel.
Question 1: Which region and resource size should the sandbox use?
```

Answers like "you decide" / "use the default" delegate the choice back to the agent (safe defaults apply), and already-answered topics are never asked again.

Non-interactive environments (CI, piped input) must pass `-y` to skip confirmations and the clarification assessment; otherwise the install/credential/build steps fail fast with a Quick Setup guide, and a description below the completeness threshold fails fast with `E2008` (missing details + a ready-to-use example description):

```bash
# ebx create -y "a node.js api server"
# ebx create "run python"    # non-interactive, incomplete → E2008
```

An explicit `--template` skips AI generation and takes the direct template path (`ebx create --template <name>`). `DESCRIPTION` and `--template` are mutually exclusive — passing both is rejected with a usage error instead of silently ignoring one of them:

```bash
# ebx create "a node.js api server" --template base   # rejected (exit code 1)
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
```

This is a line-based REPL, not a PTY or an SSH session: each line runs in its own
process with a 30-second timeout, so `cd`, environment variables and shell state
do not persist between lines (use `cd /path && <cmd>` on one line, or
`ebx exec --cwd`). Interactive terminals get basic line editing and history
(Up/Down, Ctrl+R, Ctrl+A/E). Type `exit`, `quit`, or `Ctrl+D` to leave; `Ctrl+C`
also disconnects. Failed commands are reported as a single friendly message.

```text
ebx:sbx-xxxx> ls /app
main.py  data/
ebx:sbx-xxxx> cd /app && python main.py
Hello from main.py
ebx:sbx-xxxx> exit
Disconnected.
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

### Scaffold a Template Locally

```bash
# Create ./python/ from the built-in 'python' case
ebx template init -t python

# Or scaffold into an explicit directory
ebx template init -t python ./my-template
```

`ebx init` is a top-level shortcut that delegates to the exact same command as `ebx template init` (guided credentials setup remains `ebx config init`).

#### Interactive case selection

- **TTY**: running `ebx init` / `ebx template init` without `-t` shows an arrow-key (Up/Down) selector over the built-in cases; `Enter` confirms, `Ctrl+C` aborts without writing anything.
- **Non-TTY / CI / `--json`**: the selector never blocks — the command fails fast with the list of valid cases (use `-t python|node|minimal` or `--list`), keeping scripts deterministic.

#### Advanced usage: top-level shortcuts vs your own commands

- Built-in top-level shortcuts (`create`, `list`, `init`, `install`, `deploy`, `run`, …) are registered by **project maintainers** in the `lazy_subcommands` map of `src/easy_sandbox/cli/main.py`. It is an internal registration point, not a user extension mechanism.
- To add your own commands, declare `custom_commands` in the template's `template.yaml` or register them on a SandboxServer (`@registry.command`), then invoke them with `ebx run <SANDBOX_ID> <COMMAND_NAME>`.
- The `config.toml [shortcuts]` section from the early CLI design draft was **never implemented** — do not expect user-declared aliases in `~/.ebx/config.toml` to work.
- Unknown top-level commands get targeted hints: `ebx crate` → `Did you mean 'create'?`; with no close match the error points to `custom_commands` + `ebx run`.

See the [CLI design doc](../design/cli-design.md) for the full boundary description.

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

# Clear one stored value (returns to default / not set)
ebx config set region ""
```

Available configuration keys: `api_key`, `api_url`, `region`, `http_timeout`, `max_retries`, `domain`, `llm_api_key`, `llm_model`, `llm_base_url`, `qwen_code_api_key`, `qwen_code_base_url`, `qwen_code_model`, `github_token`, `access_key_id`, `access_key_secret`.

> **Tip:** hit a GitHub anonymous rate limit while using `ebx template search` / `ebx install`? Run `ebx config set github_token` in an interactive terminal (masked input, stored in `~/.ebx/.env`), or inject `GITHUB_TOKEN` as a CI secret. See [Authentication](authentication.md) and the CLI reference for the `--token` precedence notes.
>
> **Local pre-CI check:** run `make ci` before pushing — it mirrors the GitHub Actions pipeline (ruff check + format check, mypy, non-integration tests, package build, `twine check`, `py.typed` in wheel) on a single local interpreter.

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

For a detailed list of global options (including `--verbose`, `--log-level`, `--timeout`, etc.), see [CLI Reference — Global Options](../reference/cli-reference.md#global-options). Note that `--region`/`-r` is a command-level option (accepted by `ebx list`, `ebx kill`, the template control-plane commands, and `ebx mcp deploy`), not a global one; set the persistent default via `ebx config set region`.

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
