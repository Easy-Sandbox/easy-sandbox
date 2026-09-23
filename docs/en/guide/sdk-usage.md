# SDK Usage Guide

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

This document covers the complete usage of the Easy Sandbox Python SDK.

---

## Installation

```bash
pip install easy-sandbox
```

## Import

```python
from easy_sandbox.api.sandbox import Sandbox
```

---

## Create and Destroy

### Async Creation

```python
sandbox = await Sandbox.create(
    template="base",      # Template name (default "base")
    timeout=300,           # Timeout in seconds (1–86400, default 300)
    envs={"KEY": "val"},   # Injected environment variables
    metadata={"team": "x"},# Arbitrary metadata key-value pairs
    cpu=2,                 # CPU cores (optional)
    memory=4096,           # Memory in MB (optional)
    disk=10240,            # Disk in MB (optional)
    gpu="A10",             # GPU spec (optional)
)
```

### Sync Creation

```python
sandbox = Sandbox.create_sync(template="base")
```

### Context Manager (recommended)

Automatically calls `kill()` to destroy the sandbox when exiting the `with` block:

```python
async with await Sandbox.create(template="base") as sandbox:
    result = await sandbox.run_code("print(1+1)")
    print(result.text)  # "2"
# Automatically destroyed
```

### Natural Language Creation

When `description` is provided and `template` is left at its default value, the SDK infers the best template and resource configuration via LLM:

```python
sandbox = await Sandbox.create(
    description="I need a data analysis environment with pandas and matplotlib",
)
```

### Connect to an Existing Sandbox

```python
sandbox = await Sandbox.connect("sbx-xxxx")

# Sync version
sandbox = Sandbox.connect_sync("sbx-xxxx")
```

### Destroy a Sandbox

```python
# Instance method
await sandbox.kill()

# Class method (destroy by ID, no need to connect first)
await Sandbox.kill_by_id("sbx-xxxx")

# Sync version
Sandbox.kill_by_id_sync("sbx-xxxx")
```

### List Sandboxes

```python
sandboxes = await Sandbox.list(status=SandboxStatus.RUNNING, limit=20)
for sb in sandboxes:
    print(f"{sb.sandbox_id} - {sb.template} - {sb.status.value}")
```

---

## Execute Code — run_code

Execute code via the Code Interpreter:

```python
result = await sandbox.run_code(
    "print('hello')",
    language="python",   # Default "python"
    timeout=30,          # Timeout in seconds (default 30)
    envs={"KEY": "val"}, # Temporary environment variables for this execution
)

print(result.text)           # Output text (stdout with trailing whitespace stripped)
print(result.stdout)         # Raw stdout
print(result.stderr)         # Raw stderr
print(result.exit_code)      # Exit code
print(result.execution_time) # Execution time (seconds)
print(result.output_files)   # Output file list [OutputFile]
```

Callback support:

```python
result = await sandbox.run_code(
    "for i in range(3): print(i)",
    on_stdout=lambda s: print(f"[OUT] {s}"),
    on_stderr=lambda s: print(f"[ERR] {s}"),
)
```

> **Capability requirement**: Requires the `code` capability (included in the default capability set `{shell, files, code}`).

---

## Execute Commands — commands

The `sandbox.commands` submodule provides shell command execution capabilities.

### Execute and Wait

```python
result = await sandbox.commands.run(
    "ls -la /home/user",
    timeout=60,                # Timeout in seconds (default 60)
    env={"MY_VAR": "value"},   # Additional environment variables
    cwd="/app",                # Working directory
)

print(result.stdout)
print(result.stderr)
print(result.exit_code)
print(result.execution_time)
print(result.success)  # exit_code == 0
```

### Streaming Output

```python
async for chunk in sandbox.commands.stream("pip install flask"):
    if chunk.type.value == "stdout":
        print(chunk.data, end="")
    elif chunk.type.value == "stderr":
        print(chunk.data, end="", file=sys.stderr)
    elif chunk.type.value == "exit":
        print(f"\nExit code: {chunk.exit_code}")
```

### Background Execution

```python
reader = await sandbox.commands.start("python server.py")
# reader is a StreamReader that can be consumed asynchronously
```

You can also use the `background=True` parameter of `run`:

```python
reader = await sandbox.commands.run("sleep 60", background=True)
```

### Process Management

```python
# List processes
processes = await sandbox.commands.list()

# Kill a process
await sandbox.commands.kill(pid=12345)

# Send a signal
await sandbox.commands.send_signal(pid=12345, signal=15)  # SIGTERM

# Send stdin data
await sandbox.commands.send_input(pid=12345, data="yes\n")
```

### Sync Versions

All methods have synchronous counterparts with a `_sync` suffix:

```python
result = sandbox.commands.run_sync("echo hello")
```

---

## File Operations — files

The `sandbox.files` submodule provides filesystem operations.

### Read/Write

```python
# Write text or bytes
await sandbox.files.write("/home/user/hello.txt", "Hello World")
await sandbox.files.write("/home/user/data.bin", b"\x00\x01\x02")

# Read text
text = await sandbox.files.read("/home/user/hello.txt", encoding="utf-8")

# Read bytes
data = await sandbox.files.read_bytes("/home/user/data.bin")
```

### Upload / Download

```python
# Upload a local file to the sandbox
await sandbox.files.upload("./local_file.py", "/home/user/remote.py")

# Download a sandbox file to local
await sandbox.files.download("/home/user/output.csv", "./output.csv")
```

### Directory Operations

```python
# List directory contents
entries = await sandbox.files.list("/home/user")
for entry in entries:
    print(f"{entry.name} - {entry.type.value} - {entry.size}")

# Create a directory (including parents)
await sandbox.files.make_dir("/home/user/new/nested/dir")

# Check if a path exists
exists = await sandbox.files.exists("/home/user/hello.txt")

# Get file info
info = await sandbox.files.get_info("/home/user/hello.txt")
```

### Move / Delete

```python
# Move/rename
await sandbox.files.move("/home/user/old.txt", "/home/user/new.txt")

# Delete a file or directory
await sandbox.files.remove("/home/user/temp.txt")
```

### Watch File Changes

```python
watcher = await sandbox.files.watch("/home/user")
async for event in watcher:
    print(f"{event.type}: {event.path}")
```

---

## Network — network

The `sandbox.network` submodule computes port access URLs (purely local computation, no network requests involved).

> **Capability requirement**: Requires the `ports` capability. The default capability set does not include `ports`; it must be explicitly declared in the template's `template.yaml`.

```python
# Get port URL
url = sandbox.network.get_url(8080)
# => "https://8080-sbx-xxxx.cn-hangzhou.e2b.fc.aliyuncs.com"

# Get host
host = sandbox.network.get_host(8080)
# => "8080-sbx-xxxx.cn-hangzhou.e2b.fc.aliyuncs.com"

# Get access headers (includes X-Access-Token in secure mode)
headers = sandbox.network.get_access_headers()
```

---

## Sandbox Lifecycle

```python
# Check if running (makes an API call)
running = await sandbox.is_running()

# Refresh sandbox info
info = await sandbox.refresh_info()

# Set timeout
await sandbox.set_timeout(600)

# Pause/resume
await sandbox.pause()
await sandbox.resume()
```

### Properties

```python
sandbox.id           # Sandbox ID (str)
sandbox.status       # Current status (SandboxStatus)
sandbox.url          # envd URL (str)
sandbox.info         # Full info (SandboxInfo)
sandbox.capabilities # Capability set (frozenset[str])
```

---

## Sync vs Async

The SDK uses an **async-first** design — all core methods are asynchronous. Each async method has a corresponding synchronous wrapper (generated via `make_sync`):

| Async Method | Sync Method |
|--------------|-------------|
| `Sandbox.create()` | `Sandbox.create_sync()` |
| `Sandbox.connect()` | `Sandbox.connect_sync()` |
| `sandbox.kill()` | `sandbox.kill_sync()` |
| `sandbox.run_code()` | `sandbox.run_code_sync()` |
| `sandbox.commands.run()` | `sandbox.commands.run_sync()` |
| `sandbox.files.read()` | `sandbox.files.read_sync()` |
| `sandbox.files.write()` | `sandbox.files.write_sync()` |

Sync methods run an event loop in the background and are suitable for scripts and non-async environments.

---

## Error Handling

All SDK errors inherit from `SandboxError` and carry `code`, `message`, and `suggestion` attributes:

```python
from easy_sandbox.models.errors import (
    SandboxError,
    InvalidAPIKeyError,       # E1001
    TemplateNotFoundError,    # E2001
    CapabilityNotSupportedError,  # E3004
    FileNotFoundError_,       # E4001
    ConnectionError_,         # E5001
)

try:
    sandbox = await Sandbox.create(template="nonexistent")
except TemplateNotFoundError as e:
    print(f"[{e.code}] {e.message}")
    print(f"Suggestion: {e.suggestion}")
except SandboxError as e:
    print(f"SDK error: {e}")
```

See [Error Codes Reference](../reference/error-codes.md) for details.

---

## Custom Commands

Templates can define custom commands. Use `sandbox.run()` to execute and `sandbox.list_commands()` to list them:

```python
# List available commands
commands = sandbox.list_commands()
for cmd in commands:
    print(f"{cmd['name']}: {cmd['description']}")

# Execute a custom command
result = await sandbox.run("dev", port="8080")
print(result.stdout)
```
