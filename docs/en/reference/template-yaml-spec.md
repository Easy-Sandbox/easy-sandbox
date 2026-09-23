# template.yaml Specification

> **Renaming Notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

This document precisely defines all fields of the `template.yaml` file (from the user's perspective).

---

## File Location

The template's `template.yaml` is located at the root of the template directory:

```text
my-template/
├── template.yaml    ← The file defined in this document
├── Dockerfile       # Optional
└── ...
```

After installation, it resides at `~/.ebx/templates/<template-name>/template.yaml`.

---

## Complete Field Definitions

### Basic Information

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | ✅ | — | Template name, used with the `--template` parameter |
| `version` | `str` | ❌ | `"1.0.0"` | Semantic version number |
| `description` | `str` | ❌ | `""` | Template description |
| `author` | `str` | ❌ | `""` | Author |
| `license` | `str` | ❌ | `""` | License identifier (e.g., `"MIT"`) |
| `tags` | `list[str]` | ❌ | `[]` | Classification tags |

### Build Configuration

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `base` | `str` | ❌ | `"ubuntu:22.04"` | Base Docker image |
| `system_packages` | `list[str]` | ❌ | `[]` | System packages installed via `apt-get install` |
| `python_packages` | `list[str]` | ❌ | `[]` | Python packages installed via `pip install` |
| `node_packages` | `list[str]` | ❌ | `[]` | Node.js packages installed via `npm install -g` |
| `commands` | `list[str]` | ❌ | `[]` | Shell commands executed sequentially during build (each generates a `RUN` instruction) |
| `copy_files` | `dict[str, str]` | ❌ | `{}` | File copy mappings; keys are source paths, values are destination paths (generates `COPY` instructions) |

> When a `Dockerfile` exists in the template directory, the `Dockerfile` takes priority over the above build fields.

### Runtime Configuration

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `env` | `dict[str, str]` | ❌ | `{}` | Environment variables (generates `ENV` instructions) |
| `ports` | `list[int]` | ❌ | `[]` | Exposed ports (generates `EXPOSE` instructions) |

### Resource Specifications

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `cpu_count` | `int` | ❌ | `None` | Default CPU core count |
| `memory_mb` | `int` | ❌ | `None` | Default memory in MB |

### Capability Declarations

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `capabilities` | `list[str] \| null` | ❌ | `null` | Runtime capability list |

**Allowed values** (standard capabilities `STANDARD_CAPABILITIES`):

| Capability | Description |
|------------|-------------|
| `shell` | Shell command execution (`commands.run()`, etc.) |
| `files` | Filesystem operations (`files.read()`, etc.) |
| `code` | Code Interpreter execution (`run_code()`, etc.) |
| `terminal` | PTY terminal sessions (`get_terminal()`) |
| `ports` | Port URL access (`network.get_url()`, etc.) |

**Behavior rules**:
- `null` (undeclared) → Uses the default capability set `{shell, files, code}`
- Explicit list → Only the listed capabilities are enabled (can be a subset or superset of the standard set)
- Values in the list must be from the standard capability set; otherwise, validation fails (raises `TemplateParseError` E2004)

### Custom Commands

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `custom_commands` | `dict[str, Command]` | ❌ | `{}` | Named command mappings |

**Command structure**:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `cmd` | `str` | ✅ | — | Shell command template, supports `{placeholder}` tokens |
| `description` | `str` | ❌ | `""` | Command description |
| `cwd` | `str` | ❌ | `"/app"` | Working directory |
| `timeout` | `int` | ❌ | `60` | Timeout in seconds |
| `env` | `dict[str, str]` | ❌ | `{}` | Command-specific environment variables |
| `args` | `list[Arg]` | ❌ | `[]` | Argument definition list |

**Arg structure**:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | ✅ | — | Argument name (corresponds to `{name}` placeholder in `cmd`) |
| `type` | `str` | ❌ | `"string"` | Type: `string` / `integer` / `float` / `boolean` |
| `required` | `bool` | ❌ | `false` | Whether required |
| `default` | `str \| null` | ❌ | `null` | Default value (string form) |
| `description` | `str` | ❌ | `""` | Argument description |

---

## Complete Example

```yaml
name: flask-web
version: "2.0.0"
description: "Flask Web Development Environment"
author: "Easy Sandbox Team"
license: "MIT"
tags:
  - python
  - web
  - flask

base: python:3.11-slim

system_packages:
  - curl
  - git
  - postgresql-client

python_packages:
  - flask>=3.0
  - sqlalchemy>=2.0
  - gunicorn

commands:
  - "mkdir -p /app"

env:
  PYTHONUNBUFFERED: "1"
  FLASK_ENV: "development"

copy_files:
  ./requirements.txt: /app/requirements.txt

ports:
  - 5000
  - 8080

cpu_count: 2
memory_mb: 2048

capabilities:
  - shell
  - files
  - code
  - terminal
  - ports

custom_commands:
  dev:
    cmd: "flask run --host=0.0.0.0 --port={port}"
    description: "Start Flask development server"
    cwd: "/app"
    timeout: 0
    env:
      FLASK_DEBUG: "1"
    args:
      - name: port
        type: string
        required: false
        default: "5000"
        description: "Listening port"

  test:
    cmd: "python -m pytest {path} -v --tb=short"
    description: "Run pytest tests"
    cwd: "/app"
    timeout: 120
    args:
      - name: path
        type: string
        required: false
        default: "tests/"
        description: "Test file path"

  migrate:
    cmd: "flask db upgrade"
    description: "Execute database migration"
    cwd: "/app"
    timeout: 60
```

---

## Dockerfile Conversion

Build fields in `template.yaml` generate Dockerfile instructions in the following order:

1. `base` → `FROM {base}`
2. `system_packages` → `RUN apt-get update && apt-get install -y {pkgs} && rm -rf /var/lib/apt/lists/*`
3. `python_packages` → `RUN pip install --no-cache-dir {pkgs}`
4. `node_packages` → `RUN npm install -g {pkgs}`
5. `commands` → `RUN {cmd}` for each command
6. `env` → `ENV {key}={value}` for each variable
7. `copy_files` → `COPY {src} {dst}` for each mapping
