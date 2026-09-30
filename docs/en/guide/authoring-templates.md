# Authoring Templates

This document explains how to create custom Easy Sandbox templates, including directory structure, field reference, capability declarations, custom commands, and publishing.

Three ways to start, all of them local files only (publish later with `ebx deploy`):

| Starting point | Command |
|----------------|---------|
| Built-in scaffold | `ebx template init -t python ./my-template` |
| A sentence (Qwen Code writes a new directory) | `ebx template init "a Python data analysis environment"` |
| A project that already has source code | `ebx template init --adopt ./app` — see [Adapt an existing project](#adapt-an-existing-project) |

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
author: "Your Name"
tags:
  - python
  - data-analysis

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
| `env` | `dict[str, str]` | ❌ | `{}` | Environment variables |
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

`terminal` and `ports` must be explicitly declared in the template to be used. Capability tokens are used at the template resolution layer (`resolve_capabilities()`) which is fail-closed: if a template’s YAML is malformed or missing, the resolver raises `TemplateParseError` (E2004) rather than silently granting capabilities. All API methods remain callable regardless of declared capabilities; capability declarations serve as metadata for template validation and model inference.

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

Registered commands are served by the in-sandbox HTTP server; clients invoke them via `sandbox.custom()` or `ebx run`.

> **Note:** `sandbox.run_command()` is a deprecated alias for `sandbox.custom()`. New code should use `sandbox.custom()`, which returns a full `CommandResult`.

---

## Dockerfile Customization

The actual build process uses `Dockerfile` directly along with language-native dependency files (`requirements.txt` / `package.json`):

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

The `Dockerfile` in the template directory is the sole source for building images. `template.yaml` only defines runtime configuration (capabilities, commands, environment variables, resources) and does not contain build instructions.

---

## Adapt an existing project

`ebx template init --adopt` is for a directory that already has application code and is missing the sandbox template files. Qwen Code reads a copy of that project and ebx writes the template files back into the same directory. Nothing is built, pushed, or launched; publish with `ebx deploy` afterwards.

```bash
ebx template init --adopt . --hint "the API listens on 8080"
ebx template init --adopt ./app --dry-run          # list the files; send nothing
ebx template init --adopt ./app --name my-api -y   # non-interactive
ebx deploy ./app --acr-namespace my-ns
```

`--hint` is free text for facts the code does not show (the listen port, a sidecar, a private constraint). `--name` sets the template name: it must match `^[a-z0-9][a-z0-9-]*$`. When `--name` is omitted, ebx slugs the directory name. A name that cannot be slugged (a Chinese-only directory, for example) needs `--name`.

### Files written back

Only these files are written, and only after you confirm the preview (or pass `-y`):

| File | When |
|------|------|
| `Dockerfile` | Always |
| `commands.py` | The `SandboxServer` HTTP entry point, port 9000 |
| `template.yaml` | Name, resources, ports, capabilities |
| `.dockerignore` | Only when the project does not already have one |

Application source stays as it is. A file the agent creates or edits outside that list is reported and discarded. A replaced file is kept as `*.ebx-bak`; an existing backup is never overwritten (the next one is `.ebx-bak.1`).

### What is sent to the model

ebx copies candidate files into a temporary directory (`ebx-adopt-…` under the system temp dir, never `~/.ebx`) and asks before sending them. The agent runs only in that copy.

Left out of the copy: `.git`, `node_modules`, virtualenvs, and similar heavy directories; `.env` and other secret-named files (keys, `credentials*`, `kubeconfig`, …); files whose contents look like a secret; symlinks; binaries; files larger than 1 MiB. The copy stops above 2 000 files or 20 MiB and tells you to point `--adopt` at a subdirectory.

`--dry-run` prints that file list and deletes the copy. It does not call the model and does not write the project. A non-interactive shell (CI, piped input, `--json`) must pass `-y`; otherwise the command stops before any copy is made.

The agent process does not inherit cloud or registry credentials (`ALICLOUD_*`, `E2B_*`, `ACR_*`, `AWS_*`, `GITHUB_TOKEN`). It does receive the Qwen Code key from `ebx config`.

This sends your project source to the model. `ebx template init "DESCRIPTION"` sends only the sentence you typed.

### Checks before anything is written

ebx rejects the result, leaves the project unchanged, and prints the staging path when:

- the Dockerfile has no `FROM`, or `commands.py` does not start `easy_sandbox.server`
- port 9000 is missing from `template.yaml` `ports` or from `EXPOSE`
- a `COPY` / `ADD` names a file that is missing or ignored (`COPY *.whl` is the wheel `ebx deploy` injects at build time, so it is allowed)
- a secret-named file would still be in the Docker build context after `.dockerignore` and `Dockerfile.dockerignore`
- an ignore file excludes `*.whl`, which would block the SDK wheel

An existing `.dockerignore` that does not exclude `.env` (including one re-included with `!`) fails before the model is called, with the lines to add. An existing `.dockerignore` is never rewritten.

### Replacing files that are already there

| Already in the project | What happens |
|------------------------|--------------|
| `template.yaml` | Refused: the directory is already a template. Run `ebx deploy`, or pass `--force` to regenerate (the original is kept as `template.yaml.ebx-bak`) |
| `commands.py` that does not import `easy_sandbox.server` | Needs `--force` |
| `Dockerfile`, or an Easy Sandbox `commands.py` | An interactive preview can replace it. `-y`, `--json`, and CI need `--force` because there is no preview |

`ebx template init --from <local directory>` requires a `template.yaml` in that directory. A source tree without one is refused and the message points at `--adopt`, so `.env` and `.git` are not copied as template source.

If generation fails, the project is unchanged and the error includes the staging directory. Delete that `ebx-adopt-…` directory after you have inspected it.

`--adopt` cannot be combined with `-t`, `--from`, or `--list`. `--hint` and `--dry-run` require `--adopt`.

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

### Building and Registering Templates Locally (template deploy)

When you need to register a custom Docker image as a sandbox template, use the `template deploy` subcommand. It automatically performs: local Docker build → ACR push → CreateTemplate API call.

> **Prerequisites**:
> - Docker daemon is running
> - Alibaba Cloud AK/SK credentials (configured in `.env` or environment variables)
> - Install the official SDK extra: `pip install "easy-sandbox[cli,alicloud]"` (if CLI is already installed you can just add `pip install "easy-sandbox[alicloud]"`)

```bash
# Default: official CreateTemplate API
ebx template deploy ./my-template \
  --acr-namespace my-ns --acr-repo my-template

# Specify resource parameters
ebx template deploy ./my-template \
  --acr-namespace my-ns --cpu 4 --memory 4096 --disk-size 10240 --internet-access

# Use legacy v3/v2 API (old script compatibility)
ebx template deploy ./my-template \
  --acr-namespace my-ns --legacy-api
```

**Two paths explained**:

| Path | Default? | Authentication | Dependency |
|------|----------|---------------|------------|
| Official CreateTemplate API | ✅ Yes | AK/SK | `easy-sandbox[alicloud]` |
| Legacy v3/v2 Platform API | No (`--legacy-api`) | E2B API Key | No extra dependency |

> **Region note**: The official API uses the region configured via `ebx config set region` (else `cn-hangzhou`). A single deployment can override it with the command-level `--region`/`-r` option on `template deploy`/`build`/`create`/`push`/`list`/`info`/`install`/`delete`. Cross-region ACR access may require VPC-related parameters.

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
