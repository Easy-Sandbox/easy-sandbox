# BYO Agent Integration (Bring Your Own Agent)

This guide is for **agent CLI owners**: Qwen Code, Codex, Claude Code, Qoder CLI, in-house agent harnesses, or any other command-line agent you want to run **inside** an Easy Sandbox.

> **How these facts were verified:** every command, flag, environment variable, and license statement below was checked on 2026-09-29 against the tools' official documentation or verified CLI behaviour (sources at the end). Vendor CLIs change quickly — re-check the linked pages before pinning a version.

The model is **Bring Your Own Agent (BYO)**: Easy Sandbox never plans, reasons, or runs the agent's tool loop for you. It provides the isolated runtime and the operational surface; your agent binary provides everything above that line.

---

## 1. The responsibility split

| Easy Sandbox provides | The agent CLI provides |
|-----------------------|------------------------|
| Isolated runtime — an FC sandbox booted from a template image | Planning and reasoning (its own LLM calls) |
| Lifecycle — create, TTL, kill (`ebx create --timeout`, `ebx kill <id>`) | Prompt interpretation and task decomposition |
| Files — upload/download, read/write via SDK and CLI | Code generation and editing |
| Commands — shell execution (`ebx exec`, `sb.commands.run()`) | The internal tool loop (its own file/exec/MCP tools) |
| Network — egress and exposed ports (`ports` capability) | Deciding which model, tools, and prompts to use |
| MCP — the Easy Sandbox MCP server lets chat agents drive sandboxes remotely | — |
| Credentials — environment-variable injection at create time (`ebx create --env KEY=...`) | Producing machine-readable results and honest exit codes |
| Templates — build/deploy pipeline and the `template.yaml` contract | Being installed, pinned, probed, and invoked inside the image |

Two consequences worth stating explicitly:

- **The SDK adds no LLM client dependency and no agent runtime.** There is no planner, no reasoning loop, and no orchestration engine in `easy_sandbox`. Agent capability = a CLI binary inside the sandbox, invoked through `commands.run()` / `ebx exec` / `ebx run` (named commands).
- **The SDK stays thin on purpose.** Adding an agent means building a template or a command, not extending the SDK.

---

## 2. Two independent axes: host-side create vs in-sandbox agents

People often conflate these. They are **two independent axes** with different lifecycles, credentials, and purposes:

| | Axis A — host-side generation | Axis B — in-sandbox agent (this guide) |
|---|---|---|
| **What runs** | Qwen Code CLI on **your machine** | Any agent CLI **inside the sandbox** |
| **Why** | `ebx create "<natural-language description>"` generates `Dockerfile` + `template.yaml` before building | Do the actual coding/deploying work in the sandbox |
| **Who provides credentials** | Your host Qwen Code / DashScope configuration (`ebx config set`) | Template whitelist injected per sandbox (`ebx create --env`) |
| **Lifecycle** | One host process per create invocation | One process per sandbox turn; sandbox TTL applies |
| **Replaceable?** | Yes — the host backend is pluggable (Qwen Code is the default) | Yes — BYO templates, no SDK change |

Details for Axis A live in [CLI Design §3 — Natural language create](../design/cli-design.md) and the [CLI Reference](../reference/cli-reference.md). **Nothing in Axis B depends on Axis A**, and Axis A is not a sandbox-embedded agent: it runs on the host, generates template files, and exits.

### The default base image ships no agent CLI

`base` and the other general-purpose templates are deliberately agent-free: they carry a shell, files, Python/Node runtimes — not Qwen Code, Codex, Claude Code, or Qoder CLI. This keeps them small, auditable, and license-clean.

The recommended path is therefore:

1. **A dedicated template per agent** — install and pin the agent CLI at image build time (see [section 3](#3-the-minimal-contract-templateyaml-custom_commands)).
2. **This BYO guide** — the responsibility boundary, the minimal `custom_commands` contract, credential whitelists, version locking, and license rules.
3. **Discover existing templates** — `ebx template search <keyword>` resolves templates from the [awesome-templates catalog](../design/templates-catalog.md).

Official catalog templates only ship agents whose license permits redistribution **and** whose install can be version-pinned. Proprietary agents (Claude Code, Qoder CLI) are documented for **self-built or community templates** — this repository distributes no proprietary binaries.

---

## 3. The minimal contract: template.yaml custom_commands

The minimal contract maps **entirely onto the existing `template.yaml` `custom_commands` mechanism** — a named command, declared by the template, invoked by CLI or SDK. No new capability, no new SDK API, no template schema change.

| Contract element | Where it lives today |
|-------------------|----------------------|
| Install / probe | `Dockerfile` (build-time install) + a probe command in `custom_commands` |
| Headless startup | `custom_commands.<name>.cmd` (the template string with `{placeholders}`) |
| Prompt input | A `required: true` argument in `custom_commands.<name>.args` |
| JSON output | Documented in `description`; the flags live in `cmd`; stdout is parsed by the caller |
| Auth env whitelist | `env` in `template.yaml` (names only) + real values injected via `ebx create --env` |
| Working directory | `custom_commands.<name>.cwd` (default `/app`; agent templates conventionally use `/workspace`) |
| Timeout | `custom_commands.<name>.timeout` (per-turn bound, in seconds) |
| Resource limits | `resources.cpu` / `resources.memory` in `template.yaml`; `Sandbox.create(cpu=, memory=)` can override |
| Lifecycle | Sandbox TTL (`ebx create --timeout`), destroy with `ebx kill <id>` |
| Error mapping | Non-zero exit code and stderr; surfaced as `exit_code` / `stderr` on `CommandResult` |
| Version locking | Exact versions in the `Dockerfile` (+ SHA256 for standalone archives) |
| License boundary | [Section 8](#8-version-locking-updates-and-licensing) |

### The `custom_commands` entry, field by field

These are the real fields of the `CustomCommand` model (see the [template.yaml spec](../reference/template-yaml-spec.md)):

| Field | Type | Default | Agent-contract use |
|-------|------|---------|--------------------|
| `cmd` | `str` (required) | — | The full headless invocation with `{placeholder}` tokens |
| `description` | `str` | `""` | State the output format ("stdout is a JSON payload") |
| `cwd` | `str` | `"/app"` | Run the agent in the workspace (`/workspace`) |
| `env` | `dict[str, str]` | `{}` | Non-secret defaults only — never credentials |
| `timeout` | `int` | `60` | Bound one agent turn (seconds) |
| `args` | `list[Arg]` | `[]` | At least one required prompt argument |

Arguments are filled into `{placeholders}` after `shlex.quote()` escaping — a prompt containing quotes, `;`, or `$` cannot break out of the command. Prefer the named-argument form over pasting a prompt into a shell string yourself.

### Example: a BYO Qwen Code template (illustrative)

> This is a **public example**, not a maintained catalog template. Your production template lives in your own repository (or the awesome-templates catalog) — see [Authoring Templates](authoring-templates.md).

`template.yaml`:

```yaml
name: my-qwen-agent
version: "1.0.0"
description: "BYO Qwen Code agent template (example)"

capabilities:
  - shell
  - files
  - ports

ports:
  - 9000

env:
  DASHSCOPE_API_KEY: ""        # name only — inject the real value per sandbox
  PATH: "/usr/local/bin:$PATH"
  WORKSPACE: "/workspace"

custom_commands:
  agent_probe:
    cmd: "command -v qwen"
    description: "Probe that the pinned agent CLI is installed (add the vendor's version flag if documented)"
    cwd: "/workspace"
    timeout: 30

  agent_run:
    # Positional prompt — the deprecated legacy -p form is not used.
    cmd: "qwen {prompt} --output-format json --max-session-turns {max_turns}"
    description: "One headless Qwen Code turn; stdout is a JSON payload, diagnostics go to stderr"
    cwd: "/workspace"
    timeout: 600
    args:
      - name: prompt
        type: string
        required: true
        description: "Natural-language instruction for the agent"
      - name: max_turns
        type: integer
        required: false
        default: "50"
        description: "Session turn budget"

resources:
  cpu: 2
  memory: 4096
```

`Dockerfile` — install at build time, pin exact versions:

```dockerfile
FROM node:22-bookworm-slim

# Pin an exact version. Do not use floating tags such as latest.
RUN npm install -g @qwen-code/qwen-code@<X.Y.Z>

WORKDIR /workspace
```

Then use your template:

```bash
# Build/deploy it (see Authoring Templates), then:
ebx create --template my-qwen-agent --env DASHSCOPE_API_KEY=<YOUR_KEY> --timeout 3600

# Probe the installation
ebx run <sandbox-id> agent_probe

# Run one agent turn; the prompt is escaped for you
ebx run <sandbox-id> agent_run --arg prompt="fix the failing test in tests/"
```

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(
    template="my-qwen-agent",
    envs={"DASHSCOPE_API_KEY": "..."},
    timeout=3600,
) as sb:
    result = await sb.custom("agent_run", prompt="fix the failing test in tests/")
    print(result.exit_code, result.stdout)   # stdout is the JSON payload
```

---

## 4. Agent CLI reference (verified 2026-09-29)

Each agent keeps its own headless dialect — **the template adapts to the CLI, the contract does not force uniformity**. What must be uniform: a probe, a named run command with a required prompt argument, a documented output format, and a whitelisted auth variable.

| | Qwen Code | Codex CLI | Claude Code | Qoder CLI |
|---|---|---|---|---|
| **Official template eligible** | Yes (Apache-2.0) | Yes (Apache-2.0) | No — BYO/community only | No — BYO/community only |
| **Install channels** | Official standalone (bundles Node), npm `@qwen-code/qwen-code` (Node 22+), Homebrew | Official standalone, npm `@openai/codex`, Homebrew | Official native installer, plus brew / winget / apt / dnf / apk | Official installer from the vendor site |
| **Headless command** | `qwen "<prompt>" --output-format json` | `codex exec "<prompt>" --json` | `claude -p "<prompt>"` | `qoder -p "<prompt>"` |
| **Useful flags** | `--max-session-turns <n>` | `--sandbox workspace-write` | `--allowedTools`, `--output-format json` / `stream-json`, `--bare` | `--output-format json` / `stream-json`, `--max-turns <n>`, `--permission-mode bypass_permissions` |
| **Auth environment variables** | `DASHSCOPE_API_KEY`, `BAILIAN_CODING_PLAN_API_KEY`, or OpenAI-compatible `OPENAI_API_KEY` + `OPENAI_BASE_URL` | `OPENAI_API_KEY` | `ANTHROPIC_API_KEY` | `QODER_PERSONAL_ACCESS_TOKEN` |
| **Alternative auth** | Vendor CLI login (host-side setup only) | Interactive login (host-side setup only) | Subscription login (host-side setup only) | Browser OAuth (host-side setup only) |
| **License** | Apache-2.0 | Apache-2.0 | Proprietary | Proprietary |

Operator notes:

- **Interactive logins cannot be completed inside a headless sandbox.** Use the API-key/token variable from the whitelist, injected at create time. Complete any browser/OAuth login on the host only when the vendor CLI requires it for host-side workflows.
- **Headless dialects differ across vendors:** Qwen Code takes the prompt as a positional argument, Codex uses a subcommand (`codex exec`), and Claude Code / Qoder CLI use `-p`. Do not "normalize" them in the template — keep each vendor's real invocation.
- **Permission-bypass flags are sandbox-only tools.** `--yolo` (Qwen Code) and `--permission-mode bypass_permissions` (Qoder CLI) exist to make an agent non-interactive; use them **only** in disposable sandboxes, never on a host machine and never against data you cannot lose (see [section 9](#9-safety-boundaries)).
- **A custom agent** (your own binary, or any CLI not listed here) fits the same contract: install it in the `Dockerfile`, declare `agent_probe` and `agent_run`, whitelist exactly the environment variables it needs, and document its output format. "BYO" is not limited to the four vendors above.

---

## 5. Credentials and the environment-variable whitelist

The rule: **the template declares which variables the agent may receive; the sandbox receives values per creation; nothing is baked into the image.**

| Agent | Whitelisted variables (inject at create time) |
|-------|-----------------------------------------------|
| Qwen Code | `DASHSCOPE_API_KEY` / `BAILIAN_CODING_PLAN_API_KEY`, or `OPENAI_API_KEY` + `OPENAI_BASE_URL` |
| Codex | `OPENAI_API_KEY` |
| Claude Code | `ANTHROPIC_API_KEY` |
| Qoder CLI | `QODER_PERSONAL_ACCESS_TOKEN` |
| Custom | Only what your binary documents — add nothing "for convenience" |

```bash
# Inject per sandbox; the value never touches the image or template.yaml
ebx create --template my-qwen-agent --env DASHSCOPE_API_KEY=<YOUR_KEY>
```

```python
sb = await Sandbox.create(
    template="my-qwen-agent",
    envs={"DASHSCOPE_API_KEY": "..."},
)
```

Additional rules:

- **Never commit real keys** to a template, `template.yaml`, `custom_commands.env`, a Dockerfile `ENV`, or an uploaded file. A template's `env` block lists **names** with empty or non-secret defaults only.
- **Never print keys.** Masked display (`ebx config get api_key`) and masked logging apply to Easy Sandbox's own credentials; treat the agent's variables with the same discipline.
- **One sandbox, one credential.** Sandboxes are disposable; do not reuse a long-lived key across tenants, and rotate any key that has appeared in output or a transcript.
- **Read the environment-variable guide** for envd direct-exec semantics ([Environment Variables](environment-variables.md)) before debugging why a variable "is not there" — shell features (`$VAR`, pipes, redirects) require `sh -c '...'` inside envd execs.
- The `custom_commands.<name>.env` block is for **non-secret defaults** (for example `CODEX_MODEL`); it must never carry the values from the table above.

---

## 6. Lifecycle, timeout, and resource limits

| Control | Where | Notes |
|---------|-------|-------|
| Sandbox TTL | `ebx create --timeout <seconds>` / `Sandbox.create(timeout=...)` | Hard backstop for the whole session; the CLI `--timeout` is the sandbox lifetime, **not** an HTTP timeout |
| Per-turn timeout | `custom_commands.<name>.timeout` | Bounds one agent invocation (default `60`; agent runs commonly use `300`–`600`) |
| HTTP request timeout | `SANDBOX_HTTP_TIMEOUT` / `ebx config set http_timeout N` | Only bounds control-plane requests; raising it does not extend a sandbox |
| Resources | `resources.cpu` / `resources.memory` in the template | Defaults for every sandbox from this template; `Sandbox.create(cpu=, memory=)` can override per creation |
| Destroy | `ebx kill <id>` / `await sb.kill()` | End the session explicitly; for coding agents prefer one-shot sandboxes |

Recommended pattern for agent work:

1. Create a sandbox with a TTL that comfortably exceeds the longest expected agent turn.
2. Run one agent turn per `agent_run` invocation; parse stdout; check `exit_code`.
3. Upload results or download artifacts, then `ebx kill` the sandbox. Do not keep a bypass-permissions agent alive "for later".

---

## 7. Error mapping

A BYO agent command is a program, so its failures must be **machine-readable**:

| Situation | What the caller sees | Contract requirement |
|-----------|----------------------|----------------------|
| Success | Exit code `0`; stdout parses against the documented format | Emit the JSON payload on stdout |
| Agent/model failure | Non-zero exit code; diagnostics on stderr | Never exit `0` on failure; keep stdout parseable or empty |
| Turn timeout | The command fails with a timeout | Respect `custom_commands.timeout`; a hung agent must not hang the caller forever |
| Missing credential | The agent CLI's own auth error | Document which message/exit code your template produces |
| JSON parse failure | Caller-side parse error | Treat as failure; do not guess a result out of partial output |

`CommandResult` exposes `exit_code`, `stdout`, `stderr`, and `source` (`template` for `custom_commands`, `server` for registered commands) — map your agent's exit codes onto that, and surface stderr instead of swallowing it. For sandbox-level failures (network, auth to the control plane, missing sandbox) see [Troubleshooting](troubleshooting.md) and the [Error Codes reference](../reference/error-codes.md).

---

## 8. Version locking, updates, and licensing

**Version locking**

- Install the agent **at image build time**, not at first run. A first-run download inside the sandbox is slow, unrepeatable, and a supply-chain risk.
- Pin **exact versions**: `npm install -g @qwen-code/qwen-code@<X.Y.Z>` / `@openai/codex@<X.Y.Z>`; for standalone archives pin the release URL **and** verify the published SHA256 before running it.
- Record the pinned version in the template README so operators can audit what runs.
- Updates are a **template version bump** (rebuild → redeploy → new sandboxes), never a silent in-place upgrade. `ebx template build` / `ebx template deploy` are the pipeline.
- Re-verify a vendor's flags when bumping: headless flags are not a stable API across major versions.

**Licensing boundary**

| Agent | License | Official binary distribution by this repository |
|-------|---------|--------------------------------------------------|
| Qwen Code | Apache-2.0 | Allowed — may be maintained as an official template |
| Codex CLI | Apache-2.0 | Allowed — may be maintained as an official template |
| Claude Code | Proprietary | **No** — BYO or community template instructions only |
| Qoder CLI | Proprietary | **No** — BYO or community template instructions only |

For proprietary agents, **you** accept the vendor's terms when you build a template that installs them; Easy Sandbox neither redistributes their binaries nor bundles installers for them. If you publish such a template, do not commit the binary — install it from the vendor's official channel at build time.

**No unverified install pipelines.** This project does not recommend `curl … | sh`-style pipelines: download installers or archives to a file, pin a version, verify the hash (`shasum -a 256`), then install. The same rule applies inside Dockerfiles: no unpinned `curl | sh` lines.

---

## 9. Safety boundaries

1. **Permission bypass only in disposable sandboxes.** `--yolo` and `--permission-mode bypass_permissions` are acceptable solely because the sandbox is the isolation boundary. Never use those flags on a host machine.
2. **Cap the blast radius:** set a sandbox TTL (`--timeout`) as the backstop, prefer one-shot sandboxes, and `ebx kill` when done.
3. **Do not expose agent ports to untrusted networks.** A sandbox running a bypass-permissions agent is a powerful service; treat its ports as sensitive. Prefer driving it via the SDK, CLI, or MCP instead of a public URL.
4. **Egress leaves the sandbox.** Model calls go to the vendor's API over the network; confirm your compliance policy allows the destination before injecting credentials.
5. **MCP is for the driver, not the agent's escape hatch.** The Easy Sandbox MCP server lets a chat agent create/exec/kill sandboxes; it grants no extra privileges inside the sandbox ([MCP Integration](mcp-integration.md)).
6. **Least privilege credentials.** Prefer scoped API keys over account-wide tokens; rotate on any suspected exposure.

---

## 10. Troubleshooting checklist

- **`agent_probe` fails** → the CLI was not installed in the image, or `PATH` misses its location (`PATH` in template `env` must include the install prefix).
- **Auth error from the agent** → the whitelisted variable is missing from `ebx create --env`, or the wrong variable family was used (Qwen Code accepts several — pick one family).
- **Empty stdout** → check the headless flag combination against the vendor docs; some CLIs need an explicit output-format flag to emit JSON.
- **Turn timeout** → raise `custom_commands.timeout`, and separately check the sandbox TTL; the two are independent.
- **`ebx run` reports a non-zero exit** → inspect `stderr` first; the protocol is exit-code based, so the agent's own diagnostics are the fastest signal.
- **Interactive login prompts appear** → the CLI is falling back to interactive auth inside a headless sandbox; switch to the API-key variable and complete any host-side login locally.

More platform-side issues: [Troubleshooting](troubleshooting.md).

---

## Related documentation

- [Authoring Templates](authoring-templates.md) — build, pin, and publish your BYO agent template
- [Using Templates](using-templates.md) — discover and install catalog templates
- [template.yaml Spec](../reference/template-yaml-spec.md) — the exact `custom_commands` field reference
- [CLI Reference — ebx run](../reference/cli-reference.md) — named-command invocation
- [SDK Usage — custom commands](sdk-usage.md) — `sandbox.custom()` / `sandbox.list_commands()`
- [Environment Variables](environment-variables.md) — injection semantics and envd direct exec
- [Agent Skill Installation](agent-skill-installation.md) — the other direction: install the Easy Sandbox skill into your agent
- [中文版本](../../zh/guide/byo-agent-integration.md)

## Sources (verified 2026-09-29)

- Qwen Code — [official repository](https://github.com/QwenLM/qwen-code) (npm `@qwen-code/qwen-code`, Node 22+, Homebrew, standalone); headless positional prompt (`qwen "<prompt>"`) with `--output-format json` / `--max-session-turns`; Apache-2.0.
- Codex CLI — npm `@openai/codex`, official standalone and Homebrew; headless `codex exec --json` / `--sandbox workspace-write`; Apache-2.0.
- Claude Code — [setup docs](https://code.claude.com/docs/en/setup) (native installer, brew / winget / apt / dnf / apk); headless `claude -p`, `--allowedTools`, `--output-format json` / `stream-json`, `--bare`; proprietary license.
- Qoder CLI — [official page](https://qoder.com/cli) and vendor docs (proprietary installer); headless `qoder -p`, `--output-format json` / `stream-json`, `--max-turns`, `--permission-mode bypass_permissions`; proprietary license.
- Easy Sandbox contract — `src/easy_sandbox/models/template.py` (`CustomCommand`), [template.yaml spec](../reference/template-yaml-spec.md), and the [awesome-templates catalog](../design/templates-catalog.md).
