# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
