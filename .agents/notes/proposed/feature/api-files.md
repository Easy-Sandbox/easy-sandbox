# Decision: Files Module (L4)

Status: proposed

## Problem
Users need file operations in sandboxes including read, write, upload, download, and directory watching.

## Decision
`api/files.py` — `FilesModule` with:
- `read(path, encoding) → str | bytes`
- `write(path, data, encoding) → None`
- `list(path) → list[FileInfo]`
- `upload(local_path, remote_path) → None` (convenience: read local + write remote)
- `download(remote_path, local_path) → None` (convenience: read remote + write local)
- `exists(path) → bool`
- `remove(path) → None`
- `make_dir(path) → None`
- `watch(path) → AsyncIterator[FileEvent]` (streaming directory watch)

Large file support: chunked upload/download for files > 5MB.

## Alternatives considered
- **Separate Upload/Download classes** — Over-abstraction for simple file ops
- **pathlib-style interface** — Too different from E2B API, breaks compatibility

## Dependencies
- `protocol/filesystem.py` for Connect protocol file operations

## Test Strategy
- File CRUD operations with mock protocol
- Binary file handling (images, archives)
- Large file chunked transfer
- Directory watch event stream

## Acceptance criteria
- Full file operations work (read/write/list/upload/download/exists/remove/mkdir)
- Binary files handled correctly
- Watch produces real-time events
