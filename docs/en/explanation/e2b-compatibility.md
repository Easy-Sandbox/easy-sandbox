# E2B Compatibility

> **Renaming Notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

This document explains Easy Sandbox's compatibility strategy with the E2B Python SDK — what is compatible, what is not, and the design rationale behind the decisions.

---

## Design Goals

Easy Sandbox's E2B compatibility strategy is:

> **Allow users of the E2B SDK to migrate to Easy Sandbox with minimal changes, without being constrained by E2B's historical design decisions.**

Specifically:
- Core API signatures remain consistent
- Environment variable names are compatible
- A `compat` module is provided to simplify migration
- New capabilities do not break compatibility

---

## What Is Compatible

### API Signatures

The following APIs are fully compatible with the E2B Python SDK:

| API | Status |
|-----|--------|
| `Sandbox.create(template, timeout, metadata, envs)` | ✅ Compatible |
| `Sandbox.connect(sandbox_id)` | ✅ Compatible |
| `Sandbox.list()` | ✅ Compatible |
| `sandbox.kill()` | ✅ Compatible |
| `sandbox.is_running()` | ✅ Compatible |
| `sandbox.pause()` | ✅ Compatible |
| `sandbox.set_timeout(seconds)` | ✅ Compatible |
| `sandbox.run_code(code, language, timeout)` | ✅ Compatible |
| `sandbox.commands.run(cmd, timeout, env, cwd)` | ✅ Compatible |
| `sandbox.files.read(path)` | ✅ Compatible |
| `sandbox.files.write(path, content)` | ✅ Compatible |
| `sandbox.files.list(path)` | ✅ Compatible |
| `sandbox.files.remove(path)` | ✅ Compatible |
| `async with await Sandbox.create() as sb:` | ✅ Compatible |

### Environment Variables

| Variable | Status |
|----------|--------|
| `E2B_API_KEY` | ✅ Compatible (highest priority) |
| `E2B_API_URL` | ✅ Compatible |
| `E2B_DOMAIN` | ✅ Compatible |

### Compatibility Layer

```python
from easy_sandbox.compat import Sandbox
```

The `compat` module re-exports the `Sandbox` class with no additional wrapping.

---

## What Is Not Compatible

### 1. `Sandbox.kill(id)` Class Method

**E2B**: `Sandbox.kill(id)` is a class method that destroys a sandbox by ID.

**Easy Sandbox**: The class method is renamed to `Sandbox.kill_by_id(id)`, while `kill()` is reserved as an instance method.

**Rationale**: In Python, having both a class method and an instance method with the same name creates ambiguity. Explicitly naming the class method `kill_by_id` is clearer and avoids confusion between `Sandbox.kill("sbx-xxxx")` and `sandbox.kill()`.

### 2. `sandbox.get_host(port)` Direct Method

**E2B**: `sandbox.get_host(port)` is a direct method on the Sandbox instance.

**Easy Sandbox**: Moved to `sandbox.network.get_host(port)` submodule.

**Rationale**: Network-related functionality is consolidated under the `network` submodule, maintaining a consistent organizational structure with `commands`, `files`, and other submodules. Additionally, `network` methods require `ports` capability gating.

### 3. `get_upload_url()` / `get_download_url()`

**E2B**: Returns pre-signed URLs for direct upload/download.

**Easy Sandbox**: These methods exist but raise `NotImplementedError` — they are reserved placeholders.

**Rationale**: Easy Sandbox uses a different backend architecture where file operations are proxied through envd. Use `files.write()` / `files.read()` / `files.upload()` / `files.download()` instead.

### 4. Capability Gating

**E2B**: No capability checking mechanism; all features are always available.

**Easy Sandbox**: Introduces a capability model that checks whether a template declares the required capabilities before an API call.

**Rationale**:
- **Security**: Restricts sandbox functionality scope, following the principle of least privilege
- **Clarity**: Fails immediately at call time (E3004) rather than returning obscure backend errors
- **Extensibility**: Lays the groundwork for future fine-grained permission control

### 5. Certain RPC Paths

Some APIs (`run_code`, `get_terminal`, etc.) have RPC paths reverse-engineered from the E2B SDK. These paths are not publicly documented by Alibaba Cloud and may differ.

---

## Extensions (Non-E2B Features)

Easy Sandbox adds the following features on top of E2B compatibility:

| Feature | Description |
|---------|-------------|
| AK/SK Authentication | Alibaba Cloud AccessKey pair authentication |
| Capability Model | Template-level capability declarations and runtime gating |
| Custom Commands | Parameterized shell commands defined in template.yaml |
| @sandbox Decorator | Declarative remote function execution |
| Image Chaining API | Modal-style image building |
| MCP Server | AI IDE integration (Cursor/Claude/VS Code) |
| Session Management | Named session persistence |
| NL Deployment | Natural language-driven project deployment |
| Secret Management | `ebx secret` secure storage |
| Skill System | `ebx skill` search and install |

---

## Next Steps

- [Migrate from E2B](../guide/migrate-from-e2b.md) — Step-by-step migration guide
- [Architecture Overview](architecture-overview.md) — System architecture
- [SDK Usage Guide](../guide/sdk-usage.md) — Complete SDK usage
