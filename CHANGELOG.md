# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

_Nothing yet._

## [0.1.0] - 2026-09-29

First stable release. Includes all changes below (formerly tracked as `0.1.0-dev`) plus the current cycle:

### Breaking Changes (Task 201 — config Reset Removal & Value Semantics)

1. **Removed `ebx config reset`**.
   Clearing is now per key via `ebx config set KEY ""`: the stored value is removed and the key returns to its business default or to not set. An empty string is never stored as a credential or as an override. When an environment variable still overrides the key at runtime, the command says so explicitly without printing its value.
   *Migration*: replace `ebx config reset --yes` with one `ebx config set KEY ""` per key you want to clear (e.g. `ebx config set region ""`).

2. **`ebx config list` shows effective values and their sources**.
   Sources are annotated as `(env)`, `(user)`, `(default)` or `(not set)`. Keys with a real business default (`qwen_code_base_url`, `qwen_code_model`) show the concrete default; keys without one (`llm_api_key`, `llm_base_url`, `llm_model`) show `(not set)` instead of a blank `(default)`. Secrets stay masked.
   *Migration*: consumers parsing `config list` output now see source suffixes and `(not set)` where the old output showed blank defaults.

3. **`ebx config init` secret prompts echo one `*` per character**.
   Previously typed secrets were completely invisible; now every typed or pasted character shows a single `*` (never the plaintext), with Backspace / Ctrl-C / EOF / Unicode handled correctly. Terminals that cannot render it fall back to the previous no-echo behaviour with an explicit notice.
   *Migration*: no action required — the plaintext is never displayed in either mode.

### Breaking Changes (ADR 2026-09-23 — Overdesign Cleanup)

1. **`ebx template install` default behaviour changed: download → download+build+deploy**.
   `install` now fetches the template sources and then builds the Docker image, pushes to ACR, and registers the template via the official API by default — cloud-side operations that can incur Alibaba Cloud costs (ACR storage/traffic, template resources). The previous download-only behaviour is available via `--download-only`.
   *Migration*: add `--download-only` to `ebx template install` / `ebx install` invocations that should not build and deploy.

2. **Removed `SerializerType.PICKLE` / `SerializerType.MSGPACK`**.
   The `@sandbox` decorator now only supports `serializer="json"`. Non-JSON serializable return values must be converted to `dict`/`list`/`str` before returning.
   *Migration*: change `@sandbox(serializer="pickle")` → `@sandbox(serializer="json")` and ensure return values are JSON-compatible.

3. **Removed runtime `check_capability()` gate from most modules**.
   `CommandsModule`, `FilesModule`, and `NetworkModule` no longer raise `CapabilityNotSupportedError` (E3004) at call time. **Exception: `CodeContextModule` retains the `code` capability gate** — all its methods (`run`, `create_context`, `list_contexts`, `restart_context`, `remove_context`) still raise E3004 when the `code` capability is missing (fail-closed). E3004 is also still raised during template resolution / model validation via `resolve_capabilities()`.
   *Migration*: remove `try/except CapabilityNotSupportedError` around `commands.*`, `files.*`, and `network.*` calls; declare required capabilities in `template.yaml` instead. **Keep** `try/except CapabilityNotSupportedError` around `run_code()` / `code.*` calls if your template may lack the `code` capability.

4. **Removed `easy_sandbox.integrations` sub-module**.
   The LangChain/CrewAI/AutoGen adapter module was an empty abstract placeholder and has been deleted.
   *Migration*: use `agent.tools` or MCP integration directly.

5. **Removed `SessionStore` abstract base class**.
   Only `LocalSessionStore` remains. The `session/base.py` ABC has been deleted.
   *Migration*: if you were subclassing `SessionStore`, switch to `LocalSessionStore` or implement your own storage directly.

6. **`SecretStore` changed from macOS Keychain to file-based storage**.
   Secrets are now stored in `~/.ebx/secrets.json` (plaintext, chmod 600). Old Keychain entries are **not** automatically migrated.
   *Migration*: re-add secrets via environment variables (`E2B_API_KEY`, `SANDBOX_API_KEY`) or `~/.ebx/.env` file. Use `ebx config set api_key <value>` to persist API keys.

7. **Removed `ebx auth` CLI command group**.
   The `ebx auth login/logout/status/switch` commands have been removed.
   *Migration*: use `ebx config set api_key <value>` to persist credentials, or set `E2B_API_KEY` / `SANDBOX_API_KEY` environment variables directly.

8. **Removed `ebx secret` CLI command group**.
   The `ebx secret create/list/delete/inject` commands have been removed.
   *Migration*: use environment variables or `.env` files to manage credentials and secrets. For sandbox environment injection, use `ebx create --env KEY=VALUE`.

9. **Removed `ebx session` / `ebx sessions` CLI command group**.
   The `ebx sessions list/info/rename/export/import/clean` and `ebx start/connect` commands have been removed.
   *Migration*: session data is still stored locally in `~/.ebx/sessions/` by `LocalSessionStore`. Use the SDK's `Sandbox.connect()` API programmatically.

10. **Removed `ebx skill` CLI command group**.
   The `ebx skill search/install/list/create/publish` commands have been removed.
   *Migration*: Skills system is a future planned feature. Use templates as the current capability distribution mechanism.

11. **`Sandbox.run()` is now a bare-shell shortcut** (was named-command dispatcher).
    `Sandbox.run(cmd)` now delegates to `sandbox.commands.run(cmd)` and returns `ProcessResult | StreamReader`. It no longer dispatches named custom commands.
    *Migration*: replace `sandbox.run("name", **kwargs)` with `sandbox.custom("name", **kwargs)`.

### Breaking Changes (ADR 2026-09-29 — init/create Semantics, partially superseded)

> **Update (2026-09-29, ADR `2026-09-29-init-restore-and-create-explicit-error`):** item 1 below is **superseded** — the top-level `ebx init` shortcut has been **restored** as an exact alias of `ebx template init` (same click command object, option surface unchanged). Items 2–3 stand, and item 3 replaces the earlier "`ebx create` (no arguments) uses the `base` template" routing.

1. ~~**Removed the top-level `ebx init` shortcut**.~~ **Superseded: restored.** The top-level `ebx init` shortcut is back and delegates to the exact same command object as `ebx template init` (options unchanged). Guided credentials setup remains `ebx config init`; cloud sandbox creation remains `ebx create`.
   *Migration*: `ebx init [DIRECTORY]` and `ebx template init [DIRECTORY]` are interchangeable again.

2. **`ebx create "DESCRIPTION" --template NAME` is now rejected**.
   Previously `--template` silently won and the description was ignored. Passing both now raises a usage error (exit code 1) before any AI generation or network call — neither input is silently dropped.
   *Migration*: keep DESCRIPTION for the Qwen Code AI path, or `--template` for a direct launch, but not both.

3. **`ebx create` with no arguments is now an explicit usage error** (exit code 2).
   Previously bare `ebx create` silently launched the `base` template. It now prints a routing hint (`--template base`, `--template <NAME>`, or `"DESCRIPTION"` for the AI path) so the choice is always explicit.
   *Migration*: use `ebx create --template base` to launch the base template.

### Changed (CLI UX)

- **Unknown top-level commands now get targeted hints.** A close spelling candidate (e.g. `ebx crate`) gets a `Did you mean 'create'?` suggestion; with no plausible candidate the error points to template `custom_commands` (declared in `template.yaml`) and running them via `ebx run COMMAND`. Exit code 2 and stderr-only output are preserved; only the root group is affected.
- **Top-level shortcut registration is explicit.** Built-in top-level shortcuts (`create`, `list`, `init`, `install`, `deploy`, `run`, …) are registered in the `LazyGroup(lazy_subcommands=...)` map in `src/easy_sandbox/cli/main.py` — a maintainer-facing registration point, not a user-facing extension mechanism. User-defined commands stay in `template.yaml` `custom_commands` (or the SandboxServer `@registry.command` registry) and are invoked through `ebx run`. The `config.toml [shortcuts]` section from the original CLI design draft was **never implemented** and is not a current capability.

### Breaking Changes (ADR 2026-09-29 — qwen-code Session-Turns Parameter Unification)

1. **Renamed the qwen-code session-turns parameter to `max_session_turns` / `--max-session-turns` everywhere** (SDK, CLI, qwen-code template `template.yaml`/`commands.py`, docs).
   The old names were misleading: `Sandbox.deploy(max_tool_calls=...)`, `DeployModule.deploy_project(max_tool_calls=...)`, and `ebx deploy --max-tool-calls` all forwarded the value to qwen-code's official `--max-session-turns` flag (user/model/tool turn cap, exit code 53), not to the semantically different upstream `--max-tool-calls` budget (cumulative tool calls, exit code 55). The pre-existing template arg `max_turns` is renamed for the same reason and its default is unified to `100`.
   *Migration*: rename `max_tool_calls=` → `max_session_turns=`, `--max-tool-calls` → `--max-session-turns`, and template arg `max_turns` → `max_session_turns`. Old names fail loudly (CLI usage error / SDK `TypeError`); no aliases are kept, matching the pre-release no-compat-shim policy.
2. **`run_qwen_code_headless()` / `_build_headless_command()` accept an optional `max_session_turns` keyword** (`None` by default adds no flag). This is the stable naming contract for the natural-language `ebx create` pipeline and future headless callers.

### Breaking Changes (Task 187 — Template Catalog Single Source of Truth)

1. **The template catalog moved to the dedicated repository [`Easy-Sandbox/awesome-templates`](https://github.com/Easy-Sandbox/awesome-templates)**.
   Template content, the machine-readable index (`awesome-templates.yaml`), releases and CI now live there — it is the single source of truth for official & community templates. This repository no longer bundles the template collection: `examples/templates/` keeps only a minimal `python-hello` **offline fixture**, explicitly marked as a fixture (not a publishing source). The repository-root `awesome-templates.yaml` has been removed.
   *Migration*: instead of deploying a bundled folder (e.g. `ebx template deploy ./examples/templates/node-web`), install from the index (`ebx template install node-web`) or reference the source repo directly (`ebx template install Easy-Sandbox/awesome-templates//node-web@v1.0.0`).
2. **`ebx template search` / `ebx template install <bare-name>` now resolve against the remote index** (cached under `~/.ebx/index/`). Bare names that are not builtins are looked up in the index; a miss triggers one forced refresh, and the resolved `owner/repo//subdir[@ref]` is printed (`Resolved '<name>' via the template index: ...`).
   *Migration*: no action needed for direct `owner/repo` references; bare names must exist in the index. Use `--index-url` / `EBX_TEMPLATE_INDEX_URL` for private mirrors.

### Added
- **Remote template index client (`easy_sandbox.utils.template_index`)**: fetches `awesome-templates.yaml` from the SSOT repository via `raw.githubusercontent.com` (CDN — not subject to the API 60 req/hour anonymous limit), with a `~/.ebx/index/` cache, 1-hour TTL, `If-None-Match` revalidation, and explicit degraded modes (stale-cache fallback with a warning on network failures / rate limits / 5xx; loud errors with remediation when no cache exists; `schema_version` newer than supported fails with an upgrade hint). `--index-url` / `EBX_TEMPLATE_INDEX_URL` and `--token` / `GITHUB_TOKEN` are supported.
- **`SKILL.md`**: Static Agent Skills–style usage guide at the repository root for AI coding tools and agents in other projects — covers when to use, install, credential safety (including never-leak rules), MCP vs SDK selection, sandbox create/execute/files/destroy workflows, and common error diagnosis. Referenced from `llms.txt`. Documentation only: the removed `ebx skill` command group, Skills registry, and runtime are **not** restored (ADR 2026-09-29). Shipped in the sdist but not the wheel (evidence: `tests/test_packaging.py`; guide/code consistency: `tests/test_agent_guide.py`).
- **`Sandbox.custom(name, *, server_port=9000, **kwargs) -> CommandResult`**: New method for named custom-command dispatch. Uses A→B resolution: first tries template `custom_commands` (mechanism A), then falls back to `@registry.command` on SandboxServer (mechanism B). Returns `CommandResult` with `value`, `stdout`, `stderr`, `exit_code`, `execution_time`, `source` (`"template"` | `"server"`), and `success` property.
- **`CommandResult` data model**: Structured return type for `custom()` replacing the bare `Any` that `run_command()` returned.
- **`ebx template init`**: New scaffold command that generates a complete template project from built-in cases (`python`, `node`, `minimal`) or an existing registry reference (`--from`). Includes interactive case selection on TTY.
- **`github_token` config key (`ebx config set github_token`)**: persistent GitHub token for template downloads, mapped to the `GITHUB_TOKEN` environment variable and stored in `~/.ebx/.env` (chmod 600). In an interactive terminal the value may be omitted — the token is read through the existing masked (asterisk) input and never echoed; `ebx config get` / `ebx config list` show it masked, and `ebx config set github_token ""` removes it. Resolution order: `--token` > process `GITHUB_TOKEN` > stored `github_token` > no token.
- **One-shot GitHub rate-limit onboarding (E5000)**: `ebx template search` / `ebx template install` (`ebx install`) now print the officially documented fine-grained PAT prefill URL when the anonymous limit (60/hour) is hit — public repositories need no extra permissions and a 90-day expiry is recommended. In an interactive terminal only, the CLI offers to store the token with masked input and retries the failed operation **exactly once**; declining, cancelling, or a retry that fails again surfaces the original error. CI / non-interactive sessions are told to inject `GITHUB_TOKEN` as a secret or to run `ebx config set github_token` in a terminal. The CLI never runs `gh auth token`, never opens a browser, and never prints or logs a token.
- **Unified rate-limit guidance (`easy_sandbox.utils.github_token`)**: shared headline + remediation used by the registry tarball client and the template-index client; `owner/repo//subdir@ref` references are preserved verbatim in download errors (e.g. `Easy-Sandbox/awesome-templates//codex-agent-api@v1.0`).

### Deprecated
- **`Sandbox.run_command()` / `Sandbox.run_command_sync()`**: Deprecated in favour of `Sandbox.custom()` / `Sandbox.custom_sync()`. Both deprecated methods wrap `custom()` internally but only return `result.value` (type `Any`) for backward compatibility — the full `CommandResult` (with `stdout`, `stderr`, `exit_code`, `execution_time`, `source`, `success`) is discarded. If you were treating the old return value as a `ProcessResult`, migrate to `custom()` / `custom_sync()` which return the complete `CommandResult`. Will be removed in a future release.

### Breaking Changes (Official CreateTemplate API convergence)

1. **`ebx template build-local` was removed and replaced by `ebx template build`**.
   The old `build-local` command name no longer exists (invoking it fails with `No such command 'build-local'`). `ebx template build` runs the full pipeline: local Docker build → ACR push → template registration, and `ebx template deploy` remains an alias invoking the same pipeline.
   *Migration*: replace `ebx template build-local <DIR>` with `ebx template build <DIR>` (same option surface).

2. **`ebx template build` / `template deploy` default to the official CreateTemplate API**.
   The legacy v3/v2 platform API is no longer the default; it remains available behind the explicit `--legacy-api` flag (the approved convergence decision — the default switched to the official API while the legacy code path stays behind a flag). The ACR push and the remote template registration are cloud-side operations that can incur Alibaba Cloud costs (ACR storage/traffic, template resources).
   *Migration*: scripts needing the legacy v3/v2 behaviour must pass `--legacy-api` explicitly.

### Changed
- **`--token` is documented as a temporary override**: `ebx template install` / `ebx template search` help now warns that `--token <value>` may leak into shell history and process listings, and recommends the persistent `ebx config set github_token` as the default fix.
- `commands.run()`, `commands.stream()`, and `commands.start()` now auto-wrap commands containing unquoted shell operators (`|`, `;`, `&&`, `||`, `>`, `<`, `(...)`, `$(...)`) in `sh -c`. Variable expansion (`$VAR`), backticks, and globs still require explicit `sh -c '...'`.
- **`ebx template build` (renamed from `build-local`)**: default mode switched to the **official CreateTemplate API** (`--official-api`). Legacy v3/v2 behaviour now requires an explicit `--legacy-api` flag.
- **Official template path prerequisites**: `ebx template create` and `ebx template build` (default mode) now require the `alicloud` extra (`pip install "easy-sandbox[cli,alicloud]"` or `pip install "easy-sandbox[alicloud]"`) and Alibaba Cloud AK/SK credentials.
- When `envdInject` is enabled and `--target-image` is omitted, `copy.image` is now auto-derived with a `-fcsandbox-<hex>` random suffix to satisfy the platform requirement that `copy.image` must differ from `sandboxConfig.image`. For a stable tag, pass `--target-image` explicitly.

### Migration
- Replace `ebx template build-local <DIR>` with `ebx template build <DIR>` — the old command name was removed.
- Existing automation scripts invoking the build pipeline without `--legacy-api` now hit the official CreateTemplate API. To preserve the legacy v3/v2 behaviour, add `--legacy-api` to the command.
- **Automation / CI hardening**: pass `--acr-namespace` and the template directory explicitly on the command line instead of relying on `ACR_NAMESPACE` / `EBX_TEMPLATE_DIR` environment variables or `.env` files, so builds cannot silently drift with the surrounding environment. For `ebx template install` / `ebx install`, either pass `--acr-namespace` explicitly or use `--download-only` when the pipeline must not touch the cloud at all.


### Added
- **Server Module**: Container-side HTTP server (`easy_sandbox.server`) expanded from 6 to 42 endpoints across 8 capability groups (CORE, COMMANDS, FILE_OPS, PROCESS, SYSTEM, TERMINAL, DEV_TOOLS, BROWSER)
- **Server CapabilityGroup.BROWSER**: New browser automation capability group with 8 Playwright-backed endpoints (navigate, screenshot, content, click, type, evaluate, pdf, console)
- **Server PTY Terminal**: WebSocket-based interactive PTY terminal system with session management (REST create/list/delete + WebSocket I/O)
- **Server SSE Shell**: Streaming shell execution via Server-Sent Events (`POST /shell/stream`) for real-time command output
- **Server RouteTable**: Declarative route registry replacing if/elif dispatch; capability groups can be toggled at runtime or via `EBX_SERVER_DISABLED_GROUPS` env var
- **CLI `ebx sandbox files`**: 6 file-operation subcommands — `list`, `stat`, `mkdir`, `rm`, `mv`, `search`
- **CLI `ebx sandbox process`**: 4 process-management subcommands — `list`, `start`, `info`, `signal`
- **CLI `ebx sandbox system`**: 5 system-info subcommands — `info`, `env`, `ports`, `packages`, `metrics`
- **CLI `ebx sandbox capabilities`**: Show supported capability groups of a sandbox
- **CLI `ebx sandbox shell-stream`**: Real-time streaming command execution (SSE-backed)
- **CLI Global Options**: Added `--ci` (CI/CD mode: quiet + no-color + json), `--log-level` (explicit DEBUG/INFO/WARNING/ERROR)
- **CLI OutputManager**: Unified output manager (`cli/output.py`) with TTY/CI auto-detection, replacing ad-hoc click.echo calls
- **Template Migration**: All 10 templates migrated to new `CapabilityGroup` API
- **Core SDK**: `Sandbox` class with `create()`, `connect()`, `kill()`, `run_code()` and async context manager
- **Commands Module**: `run()`, `stream()`, `start()` for executing commands in sandboxes
- **Files Module**: `read()`, `write()`, `list()`, `upload()`, `download()`, `exists()`, `remove()`, `make_dir()`
- **Network Module**: Port URL and access headers calculation (`get_host()`, `get_url()`, `get_access_headers()`).
- **Code Interpreter**: `run()` for code execution with multi-language support
- **CLI (`ebx`)**: `create`, `list`, `info`, `kill`, `exec`, `shell`, `auth`, `config` commands
- **Dual Authentication**: API Key (`SANDBOX_API_KEY`) and AK/SK (`ALICLOUD_ACCESS_KEY_ID/SECRET`)
- **Connect Protocol**: Full `application/connect+json` implementation with Server-Streaming support
- **Transport Layer**: HTTP/2 connection pooling, WebSocket with heartbeat/reconnect, layered configuration
- **Error System**: Structured exceptions with error codes (E1001-E5002), suggestions, and docs URLs
- **E2B Compatibility**: Drop-in compatible `compat.Sandbox` wrapper
- **Output Formats**: Table (rich), JSON, and quiet modes for CLI
- **Sync Support**: All async methods have synchronous variants via `run_sync()`
- **Community Template Index**: `awesome-templates.yaml` — curated index of official and community sandbox templates

### Changed
- **Network Module**: Removed experimental `expose()` and `list_ports()` APIs in favor of a simpler local URL calculation interface based on official documentation. Port URL is now computed client-side as `https://{port}-sbx-{sandbox_id}.{domain}`.

### Architecture
- Six-layer architecture: Transport → Protocol → Extensions → API → Declarative → Agent Integration (+ CLI + Server)
- Async-first design with sync wrappers
- Lazy imports for fast CLI startup (< 200ms)
- Domain-partitioned HTTP connection pools (Platform API vs envd API)
