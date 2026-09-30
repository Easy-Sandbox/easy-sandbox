# Deploy and Build

Easy Sandbox provides three ways to build and deploy: the **template lifecycle** (`ebx template init` → `ebx deploy` → `ebx create`), the **SDK-only in-sandbox agent deploy**, and the **Image chained build**.

---

## The template lifecycle

A sandbox template goes through three steps. Each has one job, and **what a template is lives in `template.yaml`** — not in command-line flags.

| Step | Command | Input | AI? |
|------|---------|-------|-----|
| 1. Author | `ebx template init` / `ebx template init "DESCRIPTION"` / `ebx template init --adopt [DIR]` | a scaffold case, a description, or an existing project | optional |
| 2. Publish | `ebx deploy [PATH]` | the template directory (`Dockerfile`, `template.yaml`, ...) | never |
| 3. Launch | `ebx create --template <TEMPLATE_ID>` | the template ID | never |

`ebx create "DESCRIPTION"` is steps 1 + 2 + 3 in one command (with a confirmation before anything is pushed).

```bash
# 1a. An existing project: files are written into that same directory
ebx template init --adopt ./app --hint "listens on 8080"
ebx deploy ./app --acr-namespace my-ns

# 1b. A new project from a sentence: files land in ./<name>/
ebx template init "a python data science env"
ebx deploy ./<name> --acr-namespace my-ns

ebx create --template <TEMPLATE_ID>               # 3. launch a sandbox
```

`--adopt` sends a copy of the project source to the model (secrets excluded) and writes back only the template files. The rules, the preview, and `--dry-run` are in [Authoring Templates — Adapt an existing project](authoring-templates.md#adapt-an-existing-project).

Everything you would otherwise describe to the AI at deploy time — what the service is, its ports, resources, capabilities, environment, custom commands — is written into `template.yaml` (and `Dockerfile` / `commands.py`) during step 1, where you can review and version it. Describe it once, at authoring time.

### ebx deploy — the publish step

`ebx deploy` is a **fixed, deterministic pipeline** and needs **no LLM and no LLM key**:

1. `docker build` the `Dockerfile`
2. push the image to Alibaba Cloud ACR
3. register it as a template (`CreateTemplate`)
4. wait until the template is ready

It is the same pipeline as `ebx template deploy DIR`, with `PATH` defaulting to `.`, and it accepts every option of that command (`--acr-namespace`, `--alias`, `--yes`, `-v/--verbose`, `--region`, ...). From `template.yaml` it reads the template `name` (used as the ACR repository unless `--acr-repo` is given), `resources.cpu`, `resources.memory` and `generation`; command-line options override them.

On an interactive terminal the build, the push, and the wait for READY each show a `message... 12s` header with the latest four log lines in grey underneath, so a long `docker build` is not a frozen spinner. The elapsed time keeps moving once a second while a step is silent. `--verbose` prints every line instead. `--json`, `--quiet`, CI, and non-TTY keep a single progress line. Creating a sandbox, upload, download, template fetch, image registration, the coding-agent install, and `ebx kill --all` use that same moving header on a terminal. Grey lines are only safe text (paths, milestones, build output); file bytes and credentials stay off the screen. Those commands print nothing for the header when stdout is not a terminal.

```bash
ebx deploy --acr-namespace my-ns          # publish ./ (needs ./Dockerfile)
ebx deploy ./my-template --yes -v         # non-interactive, with debug logs
```

If the directory has no `Dockerfile`, the command stops and points you at `ebx template init --adopt` (an existing project), `ebx template init "DESCRIPTION"`, or `ebx template init -t`.

> **Migration note.** Earlier versions started an agent inside a cloud sandbox for every `ebx deploy ./p "instruction"` and required `BAILIAN_CODING_PLAN_API_KEY` / `DASHSCOPE_API_KEY` / `OPENAI_API_KEY`. `ebx deploy` no longer takes an instruction; author the template with `ebx template init --adopt` or `ebx template init "DESCRIPTION"` and publish it with `ebx deploy`. The in-sandbox agent flow remains available as the SDK API `Sandbox.deploy()` (below). `--traditional` is deprecated and ignored.

---

## Sandbox.deploy (SDK only)

`Sandbox.deploy()` starts a `qwen-code` template sandbox, uploads the project and lets the in-sandbox agent analyze, install, build and start the service. It is available as a Python API only.

The agent:
1. Creates a sandbox with the `qwen-code` template (default 2 CPU / 4096MB memory)
2. Uploads the project directory
3. Analyzes the project structure and dependencies
4. Installs dependencies and builds
5. Starts the service

### Usage

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.deploy(
    project_path="./my-flask-app",
    description="Deploy this Flask app on port 8080",
    max_wall_time="10m",         # Max agent runtime (default 10m)
    max_session_turns=100,       # Max qwen-code session turns (default 100)
    timeout=900,                 # Sandbox timeout in seconds (default 900)
    cpu=2,                       # CPU cores (default 2)
    memory=4096,                 # Memory in MB (default 4096)
    on_progress=lambda msg: print(f"[Progress] {msg}"),
)

# The sandbox is still running; you can continue operating on it
print(f"Sandbox ID: {sandbox.id}")
print(f"Deploy result: {sandbox._deploy_result}")
```

### LLM Key Configuration

`Sandbox.deploy()` (not `ebx deploy`) requires an LLM API key. The SDK looks for one in this order:

1. `llm_api_key=` argument
2. Process environment: `EBX_LLM_API_KEY`, then `BAILIAN_CODING_PLAN_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`, then a legacy `EBX_QWEN_CODE_API_KEY`
3. The same names in `./.env`
4. `EBX_LLM_API_KEY` saved by `ebx config set llm_api_key` (`~/.ebx/.env`)

Base URL and model follow the same layers (`openai_base_url=` / `openai_model=`, then `EBX_LLM_BASE_URL` / `OPENAI_BASE_URL` and `EBX_LLM_MODEL` / `OPENAI_MODEL`, then the same names in `./.env`, then `~/.ebx/config.toml`). A blank value does not count. The full table is in [Credential resolution](../reference/configuration.md#credential-resolution).

If no key is found, `DeployLLMKeyMissingError` (E7001) is raised. `ebx deploy` never raises it.

---

## Image Chained API

The `Image` class provides a Modal-like chained API for declarative Docker image building.

### Basic Usage

```python
from easy_sandbox.api.image import Image

image = (
    Image.from_template("python-base")
    .pip_install("flask", "sqlalchemy")
    .apt_install("postgresql-client")
    .env(DATABASE_URL="postgresql://localhost/mydb")
    .run_command("echo 'setup complete'")
)
```

### Starting from a Docker Image

```python
image = (
    Image.from_image("python:3.11-slim")
    .pip_install("pandas", "matplotlib")
    .workdir("/app")
    .expose(8080)
    .entrypoint("python app.py")
)
```

### Chained Methods

| Method | Description |
|--------|-------------|
| `Image.from_template(name)` | Based on an existing template |
| `Image.from_image(ref)` | Based on a Docker image |
| `.pip_install(*pkgs)` | Install pip packages |
| `.apt_install(*pkgs)` | Install system packages |
| `.copy_local(src, dst)` | Copy local files |
| `.env(**kv)` | Set environment variables |
| `.run_command(cmd)` | Execute a command during build |
| `.workdir(path)` | Set the working directory |
| `.expose(*ports)` | Expose ports |
| `.entrypoint(cmd)` | Set the entrypoint command |

### Generate a Dockerfile

```python
dockerfile = image.to_dockerfile()
print(dockerfile)
# FROM python-base
# RUN pip install --no-cache-dir flask sqlalchemy
# RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*
# ENV DATABASE_URL=postgresql://localhost/mydb
# RUN echo 'setup complete'
```

### Build as a Template

```python
template_info = await image.build(
    alias="my-flask-app",  # Template alias
    timeout=600,           # Build timeout in seconds
    cpu_count=2,           # Default CPU
    memory_mb=4096,        # Default memory
    start_cmd="python app.py",  # Start command
)

print(f"Template ID: {template_info.template_id}")
print(f"Build status: {template_info.build_status.value}")

# Create a sandbox using the built template
sandbox = await Sandbox.create(template=template_info.template_id)
```

### Combining with the @sandbox Decorator

```python
from easy_sandbox.declarative import sandbox
from easy_sandbox.api.image import Image

image = Image.from_template("python-base").pip_install("flask")

@sandbox(image=image)
def my_app():
    from flask import Flask
    return "Flask ready"
```

The `image` parameter takes priority over the `template` parameter.

---

## Docker Build Process

The internal process for Image builds:

1. **Generate Dockerfile**: `image.to_dockerfile()` converts the chained calls into a Dockerfile
2. **Create HTTP client**: Using configured authentication credentials
3. **Call TemplateManager.build()**: Uploads the Dockerfile to the platform
4. **Wait for build completion**: Polls build status until `ready` or `error`
5. **Return TemplateInfo**: Contains `template_id` and build status

### Build-Related Errors

| Error | Code | Scenario |
|-------|------|----------|
| `TemplateBuildError` | E7010 | Template build failed |
| `TemplateBuildTimeoutError` | E7011 | Build timed out |
| `DockerBuildError` | E7020 | Local Docker build failed |
| `ACRPushError` | E7021 | Push to ACR failed |
| `ACRLoginError` | E7022 | ACR login failed |

---

## Next Steps

- [Authoring Templates](authoring-templates.md) — Define templates via template.yaml
- [SDK Usage Guide](sdk-usage.md) — Complete SDK usage
- [API Reference](../reference/api-reference.md) — Image class API details
