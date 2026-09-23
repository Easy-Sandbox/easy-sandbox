# Migrating from E2B

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

Easy Sandbox is designed to maintain a high degree of API compatibility with the E2B Python SDK. This document provides a migration guide.

---

## API Mapping Table

| E2B SDK | Easy Sandbox | Notes |
|---------|-------------|-------|
| `from e2b import Sandbox` | `from easy_sandbox.api.sandbox import Sandbox` | Main class import |
| `Sandbox.create()` | `Sandbox.create()` | ✅ Fully compatible |
| `Sandbox.connect(id)` | `Sandbox.connect(id)` | ✅ Fully compatible |
| `Sandbox.list()` | `Sandbox.list()` | ✅ Fully compatible |
| `sandbox.kill()` | `sandbox.kill()` | ✅ Fully compatible |
| `Sandbox.kill(id)` | `Sandbox.kill_by_id(id)` | ⚠️ Different method name |
| `sandbox.is_running()` | `sandbox.is_running()` | ✅ Fully compatible |
| `sandbox.pause()` | `sandbox.pause()` | ✅ Fully compatible |
| `sandbox.set_timeout(t)` | `sandbox.set_timeout(t)` | ✅ Fully compatible |
| `sandbox.commands.run(cmd)` | `sandbox.commands.run(cmd)` | ✅ Fully compatible |
| `sandbox.files.read(path)` | `sandbox.files.read(path)` | ✅ Fully compatible |
| `sandbox.files.write(path, d)` | `sandbox.files.write(path, d)` | ✅ Fully compatible |
| `sandbox.run_code(code)` | `sandbox.run_code(code)` | ✅ Fully compatible |
| `sandbox.get_host(port)` | `sandbox.network.get_host(port)` | ⚠️ Requires the network submodule |
| `sandbox.get_upload_url(path)` | `sandbox.get_upload_url(path)` | ❌ Raises NotImplementedError |
| `sandbox.get_download_url(path)` | `sandbox.get_download_url(path)` | ❌ Raises NotImplementedError |

---

## Import Path Replacement

### Direct Replacement

```python
# E2B
from e2b import Sandbox

# Easy Sandbox (recommended)
from easy_sandbox.api.sandbox import Sandbox
```

### Using the Compatibility Layer

```python
# Compatibility layer import (minimal changes)
from easy_sandbox.compat import Sandbox
```

The compatibility layer `easy_sandbox.compat` re-exports the `Sandbox` class with an API signature consistent with the E2B SDK.

---

## Compatibility Layer Details

The compatibility module `easy_sandbox.compat.sandbox` provides:

```python
from easy_sandbox.compat import Sandbox
from easy_sandbox.compat import E2BSandbox  # Alias
```

Both are the same `Sandbox` class, only differing in name.

---

## Environment Variable Compatibility

Easy Sandbox is compatible with E2B's environment variable naming:

| E2B Variable | Easy Sandbox Alternative | Priority |
|-------------|--------------------------|----------|
| `E2B_API_KEY` | `SANDBOX_API_KEY` | E2B takes precedence |
| `E2B_API_URL` | `SANDBOX_API_BASE_URL` | E2B takes precedence |
| `E2B_DOMAIN` | — | E2B only |

When both `E2B_API_KEY` and `SANDBOX_API_KEY` are set, `E2B_API_KEY` takes precedence.

---

## Incompatibilities and Solutions

### 1. `Sandbox.kill(id)` → `Sandbox.kill_by_id(id)`

In E2B, the class method `Sandbox.kill(id)` destroys a sandbox by ID. In Easy Sandbox, this is provided by `Sandbox.kill_by_id(id)`; `sandbox.kill()` is an instance method.

```python
# E2B
await Sandbox.kill("sbx-xxxx")

# Easy Sandbox
await Sandbox.kill_by_id("sbx-xxxx")
```

### 2. `get_host(port)` requires the network submodule

```python
# E2B
host = sandbox.get_host(8080)

# Easy Sandbox
host = sandbox.network.get_host(8080)
url = sandbox.network.get_url(8080)
```

> **Note**: `network.get_host()` and `network.get_url()` require the template to declare the `ports` capability. If not declared, `CapabilityNotSupportedError` (E3004) is raised.

### 3. `get_upload_url()` / `get_download_url()` not implemented

These two methods currently raise `NotImplementedError` and serve as placeholders. Use `files.write()` and `files.read()` instead:

```python
# E2B
url = await sandbox.get_upload_url("/path/file.txt")

# Easy Sandbox — use files instead
await sandbox.files.write("/path/file.txt", content)
text = await sandbox.files.read("/path/file.txt")
```

### 4. Capability gates

Easy Sandbox introduces a capability model. Certain operations require the template to declare the corresponding capability; otherwise, `CapabilityNotSupportedError` (E3004) is raised:

- `run_code()` → Requires the `code` capability
- `commands.run()` → Requires the `shell` capability
- `files.*` → Requires the `files` capability
- `network.*` → Requires the `ports` capability
- `get_terminal()` → Requires the `terminal` capability

The default capability set `{shell, files, code}` covers most common operations.

### 5. Alibaba Cloud extensions

Easy Sandbox adds Alibaba Cloud AK/SK authentication, which does not exist in E2B:

```python
sandbox = await Sandbox.create(
    access_key_id="your-ak",
    access_key_secret="your-sk",
)
```

---

## Migration Steps

1. **Replace dependency**: `pip install easy-sandbox` (uninstall `e2b`)
2. **Replace imports**:
   - Minimal changes: `from e2b import Sandbox` → `from easy_sandbox.compat import Sandbox`
   - Recommended: `from easy_sandbox.api.sandbox import Sandbox`
3. **Replace `Sandbox.kill(id)`**: Change to `Sandbox.kill_by_id(id)`
4. **Replace `get_host()`**: Change to `sandbox.network.get_host()`
5. **Replace `get_upload_url` / `get_download_url`**: Use `files.write()` / `files.read()` instead
6. **Keep environment variables**: `E2B_API_KEY` and other variables continue to work

---

## Next Steps

- [Authentication](authentication.md) — Learn about all authentication methods
- [SDK Usage Guide](sdk-usage.md) — Complete SDK usage
- [E2B Compatibility Explained](../explanation/e2b-compatibility.md) — Design background and rationale
