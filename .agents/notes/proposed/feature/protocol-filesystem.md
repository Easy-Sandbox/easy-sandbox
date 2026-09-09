# Decision: Filesystem Protocol (L2, Connect)

Status: proposed

## Problem
File operations use Connect protocol. Need typed protocol layer for filesystem management in sandboxes.

## Decision
`protocol/filesystem.py` implements Connect RPC endpoints:
- `list_files(path) → list[FileInfo]`
- `file_exists(path) → bool`
- `get_file_info(path) → FileInfo`
- `read_file(path) → bytes`
- `write_file(path, data) → None`
- `make_dir(path) → None`
- `remove(path) → None`
- `rename(old_path, new_path) → None`
- `watch_dir(path) → AsyncIterator[FileEvent]` (streaming)

Binary file content transferred as base64-encoded strings in JSON.

## Alternatives considered
- **Direct HTTP multipart upload** — E2B protocol uses Connect, not multipart
- **Combined with process protocol** — Separate concerns, different streaming patterns

## Dependencies
- `transport/http.py` for HTTP client
- `transport/codec.py` for JSON encoding/decoding
- `models/filesystem.py` for FileInfo, FileEvent models

## Test Strategy
- File CRUD operations with mock responses
- Binary file encoding/decoding (base64)
- Watch directory streaming events

## Acceptance criteria
- Read/write/list files in sandbox via protocol layer
- Binary files handled correctly (base64 roundtrip)
- Directory watch produces real-time file change events
