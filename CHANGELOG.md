# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Breaking Changes (ADR 2026-09-23 — Overdesign Cleanup)

1. **`ebx template install` default behaviour changed: download → download+build+deploy**.
   `install` now fetches the template sources and then builds the Docker image, pushes to ACR, and registers the template via the official API by default. The previous download-only behaviour is available via `--download-only`.
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

### Added
- **`Sandbox.custom(name, *, server_port=9000, **kwargs) -> CommandResult`**: New method for named custom-command dispatch. Uses A→B resolution: first tries template `custom_commands` (mechanism A), then falls back to `@registry.command` on SandboxServer (mechanism B). Returns `CommandResult` with `value`, `stdout`, `stderr`, `exit_code`, `execution_time`, `source` (`"template"` | `"server"`), and `success` property.
- **`CommandResult` data model**: Structured return type for `custom()` replacing the bare `Any` that `run_command()` returned.
- **`ebx template init` / `ebx init`**: New scaffold command that generates a complete template project from built-in cases (`python`, `node`, `minimal`) or an existing registry reference (`--from`). Includes interactive case selection on TTY.

### Deprecated
- **`Sandbox.run_command()` / `Sandbox.run_command_sync()`**: Deprecated in favour of `Sandbox.custom()` / `Sandbox.custom_sync()`. Both deprecated methods wrap `custom()` internally but only return `result.value` (type `Any`) for backward compatibility — the full `CommandResult` (with `stdout`, `stderr`, `exit_code`, `execution_time`, `source`, `success`) is discarded. If you were treating the old return value as a `ProcessResult`, migrate to `custom()` / `custom_sync()` which return the complete `CommandResult`. Will be removed in a future release.

### Changed
- `commands.run()`, `commands.stream()`, and `commands.start()` now auto-wrap commands containing unquoted shell operators (`|`, `;`, `&&`, `||`, `>`, `<`, `(...)`, `$(...)`) in `sh -c`. Variable expansion (`$VAR`), backticks, and globs still require explicit `sh -c '...'`.
- **`ebx template build-local`**: Default mode switched to **official CreateTemplate API** (`--official-api`). Legacy v3/v2 behaviour now requires explicit `--legacy-api` flag.
- **Official template path prerequisites**: `ebx template create` and `ebx template build-local` (default mode) now require the `alicloud` extra (`pip install "easy-sandbox[cli,alicloud]"` or `pip install "easy-sandbox[alicloud]"`) and Alibaba Cloud AK/SK credentials.
- When `envdInject` is enabled and `--target-image` is omitted, `copy.image` is now auto-derived with a `-fcsandbox-<hex>` random suffix to satisfy the platform requirement that `copy.image` must differ from `sandboxConfig.image`. For a stable tag, pass `--target-image` explicitly.

### Migration
- Existing automation scripts using `build-local` without `--legacy-api` will now invoke the official API. To preserve old behaviour, add `--legacy-api` to the command.

## [0.1.0-dev] - 2026-09-02

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
