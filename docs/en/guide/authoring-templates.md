# Authoring Templates

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

This document explains how to create custom Easy Sandbox templates, including directory structure, field reference, capability declarations, custom commands, and publishing.

---

## Template Directory Structure

A complete template directory structure is as follows:

```text
my-template/
├── template.yaml      # Required — template definition
├── Dockerfile         # Optional — custom Docker build (takes priority over build steps in template.yaml)
├── commands.py        # Optional — register custom commands via @sandbox.register
└── README.md          # Optional — template description
```

`template.yaml` is the only required file.

---

## template.yaml Basic Example

```yaml
name: my-python-template
version: "1.0.0"
description: "Python data analysis environment with pre-installed pandas and matplotlib"

base: python:3.11-slim

system_packages:
  - curl
  - git

python_packages:
  - pandas
  - matplotlib
  - numpy

env:
  PYTHONUNBUFFERED: "1"
  APP_DIR: "/app"

capabilities:
  - shell
  - files
  - code
  - terminal

ports:
  - 8080
```

---

## Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | ✅ | — | Template name |
| `version` | `str` | ❌ | `"1.0.0"` | Semantic version |
| `description` | `str` | ❌ | `""` | Template description |
| `base` | `str` | ❌ | `"ubuntu:22.04"` | Base Docker image |
| `system_packages` | `list[str]` | ❌ | `[]` | System packages installed via apt |
| `python_packages` | `list[str]` | ❌ | `[]` | Python packages installed via pip |
| `node_packages` | `list[str]` | ❌ | `[]` | Node packages installed globally via npm |
| `commands` | `list[str]` | ❌ | `[]` | Shell commands executed during build |
| `env` | `dict[str, str]` | ❌ | `{}` | Environment variables |
| `copy_files` | `dict[str, str]` | ❌ | `{}` | File copy mapping (src → dst) |
| `cpu_count` | `int` | ❌ | `None` | Default CPU cores |
| `memory_mb` | `int` | ❌ | `None` | Default memory in MB |
| `ports` | `list[int]` | ❌ | `[]` | Exposed port list |
| `author` | `str` | ❌ | `""` | Author |
| `license` | `str` | ❌ | `""` | License |
| `tags` | `list[str]` | ❌ | `[]` | Tags |
| `capabilities` | `list[str]` | ❌ | `None` | Capability declarations (see below) |
| `custom_commands` | `dict` | ❌ | `{}` | Custom commands (see below) |

For detailed field definitions, see [template.yaml Spec](../reference/template-yaml-spec.md).

---

## Capability Declarations

Declare the runtime capabilities supported by the template via the `capabilities` field:

```yaml
capabilities:
  - shell      # Shell command execution
  - files      # Filesystem operations
  - code       # Code Interpreter
  - terminal   # PTY terminal
  - ports      # Port network access
```

**Standard capability set**: `shell`, `files`, `code`, `terminal`, `ports`

**Default capability set** (when `capabilities` is not declared): `shell`, `files`, `code`

`terminal` and `ports` must be explicitly declared in the template to be used. The SDK performs a gate check via `check_capability()` before calling related features; if the capability is not enabled, it raises `CapabilityNotSupportedError` (E3004).

> **Server-side capability groups**: The server has 8 capability groups (CORE, COMMANDS, FILE_OPS, PROCESS, TERMINAL, SYSTEM, DEV_TOOLS, BROWSER). TERMINAL is enabled by default; only DEV_TOOLS and BROWSER are disabled by default (`_DEFAULT_DISABLED = {DEV_TOOLS, BROWSER}`).

---

## Custom Commands

### Declaring in template.yaml

```yaml
custom_commands:
  dev:
    cmd: "python -m flask run --host=0.0.0.0 --port={port}"
    description: "Start the development server"
    cwd: "/app"
    timeout: 300
    env:
      FLASK_ENV: development
    args:
      - name: port
        type: string
        required: false
        default: "8080"
        description: "Listening port"

  test:
    cmd: "python -m pytest {path} -v"
    description: "Run tests"
    cwd: "/app"
    timeout: 120
    args:
      - name: path
        type: string
        required: false
        default: "tests/"
        description: "Test path"
```

**Command fields**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cmd` | `str` | — | Shell command template; use `{name}` to reference parameters |
| `description` | `str` | `""` | Command description |
| `cwd` | `str` | `"/app"` | Working directory |
| `timeout` | `int` | `60` | Timeout in seconds |
| `env` | `dict` | `{}` | Environment variables |
| `args` | `list` | `[]` | Parameter definitions |

**Parameter fields**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | — | Parameter name (corresponds to `{placeholder}`) |
| `type` | `str` | `"string"` | Type: `string`/`integer`/`float`/`boolean` |
| `required` | `bool` | `false` | Whether required |
| `default` | `str` | `None` | Default value |
| `description` | `str` | `""` | Parameter description |

### Registering via @sandbox.register

Register Python functions as custom commands via the decorator in `commands.py`:

```python
from easy_sandbox.declarative import sandbox

@sandbox.register
def demo(x: int, y: str) -> str:
    return f"{y}={x}"

# Enable built-in routes
sandbox.register.upload()    # POST /upload
sandbox.register.download()  # GET  /download
```

Registered commands are served by the in-sandbox HTTP server; clients invoke them via `sandbox.run_command()` or `ebx run`.

---

## Dockerfile Customization

When finer control is needed, you can provide a `Dockerfile` directly:

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pandas matplotlib numpy

WORKDIR /app

ENV PYTHONUNBUFFERED=1
```

When a `Dockerfile` is present, it takes priority over the build steps in `template.yaml` (`system_packages`, `python_packages`, `commands`, etc.).

---

## Publishing Templates

### Publish to GitHub

Push the template directory to a GitHub repository, and other users can install it with:

```bash
ebx template install your-org/your-template
```

### Local Installation

```bash
ebx template install ./my-template --registry-type local
```

Installed templates are saved in the `~/.ebx/templates/` directory.

### Building and Registering Templates Locally (build-local)

When you need to register a custom Docker image as a sandbox template, use the `build-local` subcommand. It automatically performs: local Docker build → ACR push → CreateTemplate API call.

> **Prerequisites**:
> - Docker daemon is running
> - Alibaba Cloud AK/SK credentials (configured in `.env` or environment variables)
> - Install the official SDK extra: `pip install "easy-sandbox[cli,alicloud]"` (if CLI is already installed you can just add `pip install "easy-sandbox[alicloud]"`)

```bash
# Default: official CreateTemplate API
ebx template build-local ./my-template \
  --acr-namespace my-ns --acr-repo my-template

# Specify resource parameters
ebx template build-local ./my-template \
  --acr-namespace my-ns --cpu 4 --memory 4096 --disk-size 10240 --internet-access

# Use legacy v3/v2 API (old script compatibility)
ebx template build-local ./my-template \
  --acr-namespace my-ns --legacy-api
```

**Two paths explained**:

| Path | Default? | Authentication | Dependency |
|------|----------|---------------|------------|
| Official CreateTemplate API | ✅ Yes | AK/SK | `easy-sandbox[alicloud]` |
| Legacy v3/v2 Platform API | No (`--legacy-api`) | E2B API Key | No extra dependency |

> **Region note**: The official API defaults to `cn-hangzhou` region, configurable via the `--region` global option. Cross-region ACR access may require VPC-related parameters.

### Creating Templates from Existing Images

If the image is already pushed to ACR, you can create a template directly without local building:

```bash
ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag --name my-template
```

---

## Next Steps

- [Using Templates](using-templates.md) — Install and use templates
- [template.yaml Spec](../reference/template-yaml-spec.md) — Precise definitions for all fields
- [Declarative Usage](declarative-usage.md) — The @sandbox decorator
