# Deploy and Build

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

Easy Sandbox provides two build and deployment mechanisms: **NL (Natural Language) Deploy** and **Image Chained Build**.

---

## ebx deploy (NL Deploy)

`ebx deploy` uses the qwen-code agent to automatically analyze a project and complete deployment.

### CLI Usage

```bash
ebx deploy <PROJECT_PATH> <DESCRIPTION> [options]
```

```bash
ebx deploy ./my-flask-app "Deploy this Flask app on port 8080"
```

The agent automatically:
1. Creates a sandbox with the `qwen-code` template (default 2 CPU / 4096MB memory)
2. Uploads the project directory
3. Analyzes the project structure and dependencies
4. Installs dependencies and builds
5. Starts the service

### SDK Usage

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.deploy(
    project_path="./my-flask-app",
    description="Deploy this Flask app on port 8080",
    max_wall_time="10m",         # Max agent runtime (default 10m)
    max_tool_calls=100,          # Max agent tool calls
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

The deploy feature requires an LLM API Key. The SDK looks for one in the following order:

1. `llm_api_key` parameter
2. `BAILIAN_CODING_PLAN_API_KEY` environment variable
3. `DASHSCOPE_API_KEY` environment variable
4. `OPENAI_API_KEY` environment variable
5. `llm_api_key` in `ebx config`

If none is found, `DeployLLMKeyMissingError` (E7001) is raised.

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
