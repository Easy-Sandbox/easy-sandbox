# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0-dev] - 2026-09-02

### Added
- **Core SDK**: `Sandbox` class with `create()`, `connect()`, `kill()`, `run_code()` and async context manager
- **Commands Module**: `run()`, `stream()`, `start()` for executing commands in sandboxes
- **Files Module**: `read()`, `write()`, `list()`, `upload()`, `download()`, `exists()`, `remove()`, `make_dir()`
- **Network Module**: Port URL and access headers calculation (`get_host()`, `get_url()`, `get_access_headers()`).
- **Code Interpreter**: `run()` for code execution with multi-language support
- **CLI (`sbox`)**: `create`, `list`, `info`, `kill`, `exec`, `shell`, `auth`, `config` commands
- **Dual Authentication**: API Key (`SANDBOX_API_KEY`) and AK/SK (`ALICLOUD_ACCESS_KEY_ID/SECRET`)
- **Connect Protocol**: Full `application/connect+json` implementation with Server-Streaming support
- **Transport Layer**: HTTP/2 connection pooling, WebSocket with heartbeat/reconnect, layered configuration
- **Error System**: Structured exceptions with error codes (E1001-E5002), suggestions, and docs URLs
- **E2B Compatibility**: Drop-in compatible `compat.Sandbox` wrapper
- **Output Formats**: Table (rich), JSON, and quiet modes for CLI
- **Sync Support**: All async methods have synchronous variants via `run_sync()`

### Changed
- **Network Module**: Removed experimental `expose()` and `list_ports()` APIs in favor of a simpler local URL calculation interface based on official documentation. Port URL is now computed client-side as `https://{port}-sbx-{sandbox_id}.{domain}`.

### Architecture
- Six-layer architecture: Transport → Protocol → API → CLI
- Async-first design with sync wrappers
- Lazy imports for fast CLI startup (< 200ms)
- Domain-partitioned HTTP connection pools (Platform API vs envd API)
