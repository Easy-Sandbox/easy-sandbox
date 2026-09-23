# API Reference

> **Renaming Notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

This document lists all public API signatures, parameters, return values, and exceptions of the Easy Sandbox Python SDK.

---

## Sandbox Class

```python
from easy_sandbox.api.sandbox import Sandbox
```

### Class Methods

#### `Sandbox.create()`

```python
@classmethod
async def create(
    cls,
    template: str = "base",
    *,
    timeout: int = 300,
    metadata: dict[str, str] | None = None,
    envs: dict[str, str] | None = None,
    cpu: int | None = None,
    memory: int | None = None,
    disk: int | None = None,
    gpu: str | None = None,
    description: str | None = None,
    secure: bool = True,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> Sandbox
```

Create a new sandbox. When `description` is provided and `template` remains at its default value `"base"`, the SDK uses an LLM to infer the optimal template and resource configuration.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `template` | `str` | `"base"` | Sandbox template name |
| `timeout` | `int` | `300` | Timeout in seconds (1–86400) |
| `metadata` | `dict` | `None` | Arbitrary metadata key-value pairs |
| `envs` | `dict` | `None` | Injected environment variables |
| `cpu` | `int` | `None` | Number of CPU cores |
| `memory` | `int` | `None` | Memory in MB |
| `disk` | `int` | `None` | Disk in MB |
| `gpu` | `str` | `None` | GPU specification (e.g., `"A10"`) |
| `description` | `str` | `None` | Natural language description (triggers inference) |
| `secure` | `bool` | `True` | Secure mode (port access requires token) |
| `api_key` | `str` | `None` | API Key override |
| `api_url` | `str` | `None` | Platform API URL override |
| `domain` | `str` | `None` | Domain override |
| `access_key_id` | `str` | `None` | Alibaba Cloud AK |
| `access_key_secret` | `str` | `None` | Alibaba Cloud SK |

**Returns**: `Sandbox` instance

**Sync version**: `Sandbox.create_sync(...)`

#### `Sandbox.connect()`

```python
@classmethod
async def connect(
    cls,
    sandbox_id: str,
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> Sandbox
```

Connect to an existing sandbox.

**Returns**: `Sandbox` instance

**Sync version**: `Sandbox.connect_sync(...)`

#### `Sandbox.list()`

```python
@classmethod
async def list(
    cls,
    *,
    status: SandboxStatus | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: str | None = None,
    api_url: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> list[SandboxInfo]
```

List sandboxes (class method, no instance required).

**Returns**: `list[SandboxInfo]`

**Sync version**: `Sandbox.list_sync(...)`

#### `Sandbox.kill_by_id()`

```python
@classmethod
async def kill_by_id(
    cls,
    sandbox_id: str,
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> None
```

Destroy a sandbox by ID (class method, no prior connection required).

**Sync version**: `Sandbox.kill_by_id_sync(...)`

#### `Sandbox.deploy()`

```python
@classmethod
async def deploy(
    cls,
    project_path: str,
    description: str,
    *,
    max_wall_time: str = "10m",
    max_tool_calls: int = 100,
    llm_api_key: str | None = None,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
    timeout: int = 900,
    envs: dict[str, str] | None = None,
    cpu: int | None = None,
    memory: int | None = None,
    on_progress: Callable[[str], None] | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> Sandbox
```

Automatically deploy a project using the qwen-code agent. Creates a `qwen-code` template sandbox, uploads the project, and automatically analyzes, installs dependencies, builds, and starts the service.

**Returns**: `Sandbox` instance (still running); the `_deploy_result` attribute contains the deployment result.

**Sync version**: `Sandbox.deploy_sync(...)`

### Instance Methods

| Method | Signature | Description | Sync Version |
|--------|-----------|-------------|--------------|
| `kill()` | `async def kill() -> None` | Destroy the sandbox and release resources | `kill_sync()` |
| `set_timeout()` | `async def set_timeout(timeout: int) -> None` | Update timeout duration | `set_timeout_sync()` |
| `is_running()` | `async def is_running() -> bool` | Check running status (makes an API call) | `is_running_sync()` |
| `pause()` | `async def pause() -> None` | Pause the sandbox | `pause_sync()` |
| `resume()` | `async def resume() -> None` | Resume a paused sandbox | `resume_sync()` |
| `refresh_info()` | `async def refresh_info() -> SandboxInfo` | Refresh sandbox info | `refresh_info_sync()` |

#### `run_code()`

```python
async def run_code(
    self,
    code: str,
    *,
    language: str = "python",
    timeout: int = 30,
    envs: dict[str, str] | None = None,
    on_stdout: Callable[[str], None] | None = None,
    on_stderr: Callable[[str], None] | None = None,
    on_result: Callable[..., None] | None = None,
) -> CodeResult
```

Execute code via the Code Interpreter. Requires the `code` capability.

**Returns**: `CodeResult` (with `text`, `stdout`, `stderr`, `exit_code`, `execution_time`, `output_files`)

**Raises**: `CapabilityNotSupportedError` (E3004) — if the `code` capability is not enabled

**Sync version**: `run_code_sync()`

#### `get_terminal()`

```python
async def get_terminal(
    self,
    *,
    cols: int = 80,
    rows: int = 24,
    shell: str = "/bin/bash",
) -> TerminalSession
```

Open an interactive PTY terminal session. Requires the `terminal` capability.

**Returns**: `TerminalSession` (WebSocket connection)

**Raises**: `CapabilityNotSupportedError` (E3004) — if the `terminal` capability is not enabled

**Sync version**: `get_terminal_sync()`

#### `list_commands()`

```python
def list_commands(self) -> list[dict[str, Any]]
```

Return the list of custom commands defined by the template. Requires the `shell` capability.

**Returns**: List where each item contains `name`, `description`, `args`

#### `run()`

```python
async def run(self, name: str, **kwargs: str) -> ProcessResult
```

Execute a named custom command. Looks up the template's `custom_commands` definition, fills `{placeholder}` tokens, and runs the shell command.

**Raises**: `ValueError` — command does not exist, missing required arguments, or undeclared arguments

#### `run_command()`

```python
async def run_command(
    self,
    name: str,
    *,
    server_port: int = 9000,
    **kwargs: Any,
) -> Any
```

Call a named command on the in-sandbox HTTP server (`POST {port_url}/commands/{name}`). Requires the `ports` capability.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | `str` | Sandbox ID |
| `status` | `SandboxStatus` | Current status (cached value; call `refresh_info()` to update) |
| `url` | `str` | envd URL |
| `info` | `SandboxInfo` | Full sandbox info |
| `capabilities` | `frozenset[str]` | Effective capability set |

### Submodules

| Property | Type | Description |
|----------|------|-------------|
| `commands` | `CommandsModule` | Shell command execution |
| `files` | `FilesModule` | Filesystem operations |
| `network` | `NetworkModule` | Port URL computation |
| `code` | `CodeContextModule` | Code Interpreter operations |

### Context Manager

```python
async with await Sandbox.create() as sandbox:
    ...  # Automatically calls kill() on exit
```

---

## CommandsModule

```python
sandbox.commands  # CommandsModule instance
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `run()` | `async def run(cmd, *, timeout=60, env=None, cwd="", user="", background=False) -> ProcessResult \| StreamReader` | Execute a command and wait. Returns `StreamReader` when `background=True` |
| `stream()` | `async def stream(cmd, *, timeout=60, env=None, cwd="", user="") -> AsyncIterator[ProcessChunk]` | Stream command output |
| `start()` | `async def start(cmd, *, timeout=60, env=None, cwd="", user="") -> StreamReader[ProcessChunk]` | Start a command in the background, return StreamReader |
| `list()` | `async def list() -> list[ProcessInfo]` | List running processes |
| `kill()` | `async def kill(pid: int) -> None` | Terminate a process |
| `send_input()` | `async def send_input(pid: int, data: str) -> None` | Send data to process stdin |
| `send_stdin()` | `async def send_stdin(pid: int, data: str) -> None` | (Deprecated) Same as `send_input()` |
| `send_signal()` | `async def send_signal(pid: int, signal: int = 15) -> None` | Send a signal to a process |

All methods require the `shell` capability. Each async method has a `_sync` suffixed sync version (e.g., `run_sync()`).

---

## FilesModule

```python
sandbox.files  # FilesModule instance
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `read()` | `async def read(path, *, encoding="utf-8") -> str` | Read a text file |
| `read_bytes()` | `async def read_bytes(path) -> bytes` | Read a binary file |
| `write()` | `async def write(path, content: str \| bytes) -> None` | Write a file |
| `list()` | `async def list(path="/") -> list[FileInfo]` | List a directory |
| `remove()` | `async def remove(path) -> None` | Delete a file/directory |
| `exists()` | `async def exists(path) -> bool` | Check if a path exists |
| `make_dir()` | `async def make_dir(path) -> None` | Create a directory (including parents) |
| `upload()` | `async def upload(local_path, remote_path) -> None` | Upload a local file to the sandbox |
| `download()` | `async def download(remote_path, local_path) -> None` | Download a sandbox file to local |
| `watch()` | `async def watch(path) -> StreamReader[WatchEvent]` | Watch for directory changes |
| `move()` | `async def move(source, destination) -> None` | Move/rename |
| `rename()` | `async def rename(old_path, new_path) -> None` | (Deprecated) Same as `move()` |
| `get_info()` | `async def get_info(path) -> FileInfo` | Get file info |
| `upload_url()` | `async def upload_url(path) -> str` | Get upload URL (for compatibility) |
| `download_url()` | `async def download_url(path) -> str` | Get download URL (for compatibility) |

All methods require the `files` capability. Each async method has a `_sync` suffixed sync version.

---

## NetworkModule

```python
sandbox.network  # NetworkModule instance
```

All methods are local computations with no network requests. All require the `ports` capability.

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_host()` | `def get_host(port: int) -> str` | Returns `{port}-{sandbox_id}.{domain}` |
| `get_url()` | `def get_url(port: int) -> str` | Returns `https://{port}-{sandbox_id}.{domain}` |
| `get_access_headers()` | `def get_access_headers() -> dict[str, str]` | Returns HTTP headers required for port access |

---

## CodeContextModule

```python
sandbox.code  # CodeContextModule instance
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `run()` | `async def run(code, *, language="python", timeout=30, context_id=None, envs=None, on_stdout=None, on_stderr=None, on_result=None) -> CodeResult` | Execute code |
| `create_context()` | `async def create_context(*, language="python") -> dict` | Create an execution context |
| `list_contexts()` | `async def list_contexts() -> list[dict]` | List all contexts |
| `restart_context()` | `async def restart_context(context_id) -> dict` | Restart a context |
| `remove_context()` | `async def remove_context(context_id) -> None` | Delete a context |

All methods require the `code` capability. Each async method has a `_sync` suffixed sync version.

---

## Image Class

```python
from easy_sandbox.api.image import Image
```

Chaining image builder (Modal-style).

### Factory Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `from_template()` | `@classmethod def from_template(template: str) -> Image` | Create from an existing template |
| `from_image()` | `@classmethod def from_image(image: str) -> Image` | Create from a Docker image |

### Chaining Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `pip_install()` | `def pip_install(*packages: str) -> Image` | Install pip packages |
| `apt_install()` | `def apt_install(*packages: str) -> Image` | Install system packages |
| `copy_local()` | `def copy_local(src: str, dst: str) -> Image` | Copy local files |
| `env()` | `def env(**kwargs: str) -> Image` | Set environment variables |
| `run_command()` | `def run_command(cmd: str) -> Image` | Execute a command during build |
| `workdir()` | `def workdir(path: str) -> Image` | Set working directory |
| `expose()` | `def expose(*ports: int) -> Image` | Expose ports |
| `entrypoint()` | `def entrypoint(cmd: str) -> Image` | Set entrypoint command |

### Output Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `to_dockerfile()` | `def to_dockerfile() -> str` | Generate Dockerfile text |
| `build()` | `async def build(*, alias=None, api_key=None, ..., timeout=600) -> TemplateInfo` | Build as a platform template |

---

## Data Models

### SandboxStatus

```python
from easy_sandbox.models.sandbox import SandboxStatus

class SandboxStatus(str, Enum):
    CREATING = "creating"
    RUNNING  = "running"
    PAUSED   = "paused"
    STOPPING = "stopping"
    STOPPED  = "stopped"
    ERROR    = "error"
```

### SandboxInfo

| Field | Type | Description |
|-------|------|-------------|
| `sandbox_id` | `str` | Sandbox ID |
| `template` | `str` | Template name |
| `status` | `SandboxStatus` | Current status |
| `envd_url` | `str \| None` | envd data plane URL |
| `envd_access_token` | `str \| None` | envd authentication token |
| `metadata` | `dict` | User metadata |
| `started_at` | `datetime \| None` | Creation time |

### CodeResult

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | stdout (trailing whitespace stripped) |
| `stdout` | `str` | Raw stdout |
| `stderr` | `str` | Raw stderr |
| `exit_code` | `int` | Exit code |
| `execution_time` | `float` | Execution time (seconds) |
| `output_files` | `list` | Output file list |

### ProcessResult

| Field | Type | Description |
|-------|------|-------------|
| `stdout` | `str` | Standard output |
| `stderr` | `str` | Standard error |
| `exit_code` | `int` | Exit code |
| `execution_time` | `float` | Execution time (seconds) |
| `success` | `bool` | `exit_code == 0` (property) |

### ProcessChunk

| Field | Type | Description |
|-------|------|-------------|
| `type` | `ProcessChunkType` | `stdout` / `stderr` / `exit` |
| `data` | `str` | Data content |
| `exit_code` | `int \| None` | Exit code (only for `exit` type) |

### FileInfo

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | File name |
| `path` | `str` | Absolute path |
| `type` | `FileType` | `file` / `directory` |
| `size` | `int` | File size (bytes) |

---

## Exception Hierarchy

All exceptions inherit from `SandboxError` and carry `code`, `message`, `suggestion`, and `docs_url` attributes.

See [Error Codes Reference](./error-codes.md) for the complete error code listing.
