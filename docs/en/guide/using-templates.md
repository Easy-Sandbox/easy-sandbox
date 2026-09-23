# Using Templates

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

Templates are preconfigured sandbox environment definitions that include a base image, pre-installed software, capability declarations, and custom commands.

---

## What Is a Template

A template is a directory containing a `template.yaml` that defines the sandbox runtime environment. Templates can:

- Specify a base Docker image and pre-installed packages
- Declare supported capabilities (`shell`, `files`, `code`, `terminal`, `ports`)
- Define custom commands
- Set default environment variables and resource specifications

When no template is specified, the SDK uses the built-in `base` template, which provides the default capability set `{shell, files, code}`.

---

## List Available Templates

Currently, the template list comes from locally installed templates (located in `~/.ebx/templates/`). Use `ebx template install` to install templates.

---

## Install Templates

### Install from GitHub

```bash
# Basic format: owner/repo
ebx template install owner/repo

# Specify a version tag
ebx template install owner/repo@v1.0

# Specify a subdirectory
ebx template install owner/repo//path/to/template

# Use an alias
ebx template install owner/repo --alias my-python

# Private repository
ebx template install owner/private-repo --token ghp_xxx
```

### Install from a Local Directory

```bash
ebx template install ./my-template --registry-type local
```

### Shortcut

`ebx install` is a top-level shortcut for `ebx template install`:

```bash
ebx install owner/repo
```

---

## Create a Sandbox from a Template

### CLI

```bash
ebx create --template my-python
```

### SDK

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.create(template="my-python")
```

---

## Natural Language Creation

When you are unsure which template to use, you can describe your needs in natural language:

### CLI

```bash
ebx create "a Python data analysis environment with pandas and matplotlib"
```

### SDK

```python
sandbox = await Sandbox.create(
    description="a Python data analysis environment with pandas and matplotlib",
)
```

The SDK infers the best template and resource configuration via LLM. Inference is triggered only when `template` is left at the default value `"base"` and `description` is provided.

---

## Built-in Templates

| Template | Description | Default Capabilities |
|----------|-------------|----------------------|
| `base` | Basic Ubuntu environment | `shell`, `files`, `code` |

> **Tip**: You can install more templates from the community via `ebx template install`, or create your own by following [Authoring Templates](authoring-templates.md).

---

## Capability Model

Templates declare the sandbox's supported capabilities via the `capabilities` field:

| Capability | Description | Default |
|------------|-------------|---------|
| `shell` | Execute shell commands | ✅ |
| `files` | Filesystem operations | ✅ |
| `code` | Code Interpreter code execution | ✅ |
| `terminal` | PTY terminal sessions | ❌ (must be explicitly declared) |
| `ports` | Port URL access | ❌ (must be explicitly declared) |

When a template does not declare `capabilities`, the default capability set `{shell, files, code}` is used.

---

## Custom Commands

Templates can define custom commands, invoked by users via `ebx run` or `sandbox.run()`:

```bash
# CLI
ebx run sbx-xxxx dev --arg port=8080

# SDK
result = await sandbox.run("dev", port="8080")
```

View commands defined by a template:

```python
commands = sandbox.list_commands()
for cmd in commands:
    print(f"{cmd['name']}: {cmd['description']}")
```

---

## Next Steps

- [Authoring Templates](authoring-templates.md) — Create your own templates
- [CLI Tutorial](cli-tutorial.md) — Complete CLI tutorial
- [Template YAML Spec](../reference/template-yaml-spec.md) — template.yaml field reference
