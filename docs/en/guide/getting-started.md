# Getting Started

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

This tutorial walks you through the complete sandbox lifecycle, from installation to teardown.

---

## Prerequisites

- Python 3.10 or later
- A valid API Key (obtained from the Easy Sandbox platform)
- Network access to the Alibaba Cloud Hangzhou region (default `cn-hangzhou`)

## 1. Installation

```bash
# Install the SDK (includes the CLI tool)
pip install easy-sandbox

# Install with CLI extras (recommended)
pip install "easy-sandbox[cli]"

# Verify the installation
ebx --version
```

## 2. Configure the API Key

There are three ways to configure credentials (in descending order of priority):

### Option 1: Environment variable (recommended for CI/CD)

```bash
export E2B_API_KEY="your-api-key-here"
```

### Option 2: CLI login (recommended for local development)

```bash
ebx auth login
# Interactively enter your API Key, saved to ~/.ebx/.env (permissions 600)
```

### Option 3: Code parameter

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.create(api_key="your-api-key-here")
```

Verify the authentication status:

```bash
ebx auth status
```

## 3. Create Your First Sandbox

### Using the SDK (async)

```python
import asyncio
from easy_sandbox.api.sandbox import Sandbox

async def main():
    # Create a sandbox (default template: base, timeout: 300 seconds)
    sandbox = await Sandbox.create(template="base", timeout=300)
    print(f"Sandbox created: {sandbox.id}")
    print(f"Status: {sandbox.status.value}")

asyncio.run(main())
```

### Using the SDK (sync)

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = Sandbox.create_sync(template="base")
print(f"Sandbox ID: {sandbox.id}")
```

### Using the CLI

```bash
ebx create --template base
```

## 4. Execute Code

### SDK

```python
result = await sandbox.run_code("print('Hello, Easy Sandbox!')")
print(result.text)     # "Hello, Easy Sandbox!"
print(result.stdout)   # "Hello, Easy Sandbox!\n"
print(result.exit_code)  # 0
```

### CLI

```bash
ebx exec <sandbox-id> "echo 'Hello from sandbox'"
```

## 5. Run Shell Commands

### SDK

```python
result = await sandbox.commands.run("ls -la /home/user")
print(result.stdout)
print(f"Exit code: {result.exit_code}")
```

### CLI

```bash
ebx exec <sandbox-id> "pip install requests && python -c 'import requests; print(requests.__version__)'"
```

## 6. File Operations

### Upload files to the sandbox

```python
# Write a text file
await sandbox.files.write("/home/user/hello.py", "print('hello world')")

# Upload a local file
await sandbox.files.upload("./local_script.py", "/home/user/script.py")
```

### Download files from the sandbox

```python
# Read text
content = await sandbox.files.read("/home/user/hello.py")
print(content)

# Download to local
await sandbox.files.download("/home/user/output.csv", "./output.csv")
```

### CLI upload/download

```bash
# Upload
ebx upload <sandbox-id> ./data.csv /home/user/data.csv

# Download
ebx download <sandbox-id> /home/user/result.csv ./result.csv
```

## 7. List Directory Contents

```python
files = await sandbox.files.list("/home/user")
for f in files:
    print(f"{f.name} ({f.type.value}, {f.size} bytes)")
```

## 8. Destroy a Sandbox

### SDK

```python
await sandbox.kill()
```

### Using a Context Manager (recommended)

```python
async with await Sandbox.create(template="base") as sandbox:
    result = await sandbox.run_code("print('auto cleanup')")
    print(result.text)
# Automatically destroyed after exiting the with block
```

### CLI

```bash
ebx kill <sandbox-id>

# Destroy all running sandboxes
ebx kill --all --yes
```

## 9. Complete Example

```python
import asyncio
from easy_sandbox.api.sandbox import Sandbox

async def main():
    async with await Sandbox.create(template="base") as sandbox:
        # Install dependencies
        await sandbox.commands.run("pip install requests")

        # Execute code
        result = await sandbox.run_code("""
import requests
resp = requests.get('https://httpbin.org/get')
print(resp.status_code)
""")
        print(f"Status code: {result.text}")

        # Write and read files
        await sandbox.files.write("/home/user/note.txt", "Hello!")
        content = await sandbox.files.read("/home/user/note.txt")
        print(f"File content: {content}")

asyncio.run(main())
```

---

## Next Steps

- [Authentication](authentication.md) — Authentication methods and configuration priority
- [SDK Usage Guide](sdk-usage.md) — Complete API usage
- [CLI Tutorial](cli-tutorial.md) — Full CLI lifecycle operations
- [Using Templates](using-templates.md) — Create sandboxes from templates
- [Error Codes Reference](../reference/error-codes.md) — Error troubleshooting
- [Troubleshooting](troubleshooting.md) — Common issues and solutions
