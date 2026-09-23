# Declarative Usage (@sandbox Decorator)

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

The `@sandbox` decorator lets you declaratively execute Python functions in a remote sandbox without manually managing the sandbox lifecycle.

---

## Basic Usage

```python
from easy_sandbox.declarative import sandbox

@sandbox(template="code-interpreter-v1")
def analyze(data):
    import pandas as pd
    df = pd.DataFrame(data)
    return df.describe().to_dict()

# When called, it automatically: creates sandbox → uploads function → executes → returns result → destroys sandbox
result = analyze({"col1": [1, 2, 3], "col2": [4, 5, 6]})
print(result)
```

---

## Parameter Configuration

```python
@sandbox(
    template="code-interpreter-v1",  # Template name (default "code-interpreter-v1")
    timeout=300,                      # Sandbox timeout in seconds (default 300)
    envs={"MY_KEY": "value"},         # Environment variables
    packages=["pandas", "numpy"],     # pip packages to pre-install remotely
    serializer="json",                # Serialization method (default "json")
    sandbox_id=None,                  # Reuse an existing sandbox ID (skips creation when not None)
    keep_alive=False,                 # When True, the sandbox is not destroyed after execution
    api_key=None,                     # API Key override
    api_url=None,                     # Platform API URL override
    domain=None,                      # Domain override
    image=None,                       # Image object (takes priority over template)
    cpu=None,                         # CPU cores
    memory=None,                      # Memory in MB
)
def my_func():
    pass
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `template` | `str` | `"code-interpreter-v1"` | Sandbox template name |
| `timeout` | `int` | `300` | Sandbox timeout in seconds |
| `envs` | `dict` | `None` | Injected environment variables |
| `packages` | `list[str]` | `None` | pip packages to pre-install remotely |
| `serializer` | `str` | `"json"` | Serialization mode (`json`/`pickle`/`msgpack`) |
| `sandbox_id` | `str` | `None` | Reuse an existing sandbox ID |
| `keep_alive` | `bool` | `False` | Do not destroy the sandbox after execution |
| `api_key` | `str` | `None` | API Key override |
| `api_url` | `str` | `None` | Platform URL override |
| `domain` | `str` | `None` | Platform domain |
| `image` | `Image` | `None` | Image object (takes priority over template) |
| `cpu` | `int` | `None` | CPU cores |
| `memory` | `int` | `None` | Memory in MB |

---

## Serialization Rules

The `serializer` parameter controls how function arguments and return values are serialized:

| Mode | Extra Dependencies | Supported Types | Description |
|------|-------------------|-----------------|-------------|
| `json` (default) | None | JSON-serializable types | Safest, cross-language compatible |
| `pickle` | `cloudpickle` | Any Python object | Supports complex objects, but has security risks |
| `msgpack` | `msgpack` | msgpack-compatible types | Binary format, more compact |

**JSON mode**: Arguments are serialized via `json.dumps`, and results are deserialized via `json.loads`. Unsupported types fall back to `default=str`.

**Pickle mode**: Uses `cloudpickle` for serialization and base64-encoded transport. Supports lambdas, closures, and other complex objects. Requires `cloudpickle` to be installed in the remote sandbox (via the `packages` parameter).

**Msgpack mode**: Uses `msgpack` for serialization and base64-encoded transport. Requires `msgpack` to be installed in the remote sandbox.

---

## Using with async

The decorator automatically detects whether the decorated function is asynchronous:

```python
@sandbox(template="code-interpreter-v1")
async def async_analyze(data):
    import pandas as pd
    df = pd.DataFrame(data)
    return df.describe().to_dict()

# Async call
result = await async_analyze({"col": [1, 2, 3]})
```

For synchronous functions, the decorator generates a synchronous wrapper. If the synchronous wrapper is called within an existing event loop, it uses a `ThreadPoolExecutor` to avoid blocking.

---

## Reusing a Sandbox

```python
# Create a sandbox and keep it running
@sandbox(template="code-interpreter-v1", keep_alive=True)
def setup():
    import subprocess
    subprocess.run(["pip", "install", "flask"])
    return "ready"

sandbox_id = "sbx-xxxx"  # Get the sandbox ID

# Reuse the existing sandbox
@sandbox(sandbox_id=sandbox_id)
def use_flask():
    from flask import Flask
    return "Flask imported successfully"
```

---

## Using the Image Object

The `image` parameter takes priority over `template` — it builds the image first, then creates the sandbox:

```python
from easy_sandbox.api.image import Image
from easy_sandbox.declarative import sandbox

image = (
    Image.from_template("python-base")
    .pip_install("flask", "sqlalchemy")
    .apt_install("postgresql-client")
)

@sandbox(image=image)
def my_app():
    from flask import Flask
    return "Flask app ready"
```

---

## Registration-Style Commands

In addition to the decorator pattern, the `sandbox` object also supports registration-style commands:

```python
from easy_sandbox.declarative import sandbox

@sandbox.register
def demo(x: int, y: str) -> str:
    """A simple demo command"""
    return f"{y}={x}"

# Sync call
result = sandbox.run("demo", x=1, y="hello")
print(result)  # "hello=1"

# Async call
result = await sandbox.run_async("demo", x=2, y="world")

# List registered commands
commands = sandbox.list_registered()
```

Registered function parameters only support scalar types: `str`, `int`, `float`, `bool`.

### Built-in Routes

```python
sandbox.register.upload()    # Enable POST /upload route
sandbox.register.download()  # Enable GET /download route
```

### Start the HTTP Server

```python
sandbox.server.start(port=9000, host="0.0.0.0")
```

---

## Limitations

1. **Parameter serialization**: Function arguments and return values must be processable by the selected serializer
2. **Function source code**: The decorator obtains function source via `inspect.getsource()` — lambdas and dynamically generated functions are not supported
3. **Imports**: Libraries needed in the remote sandbox must be pre-installed via the `packages` parameter or already included in the template
4. **Registered command parameter types**: `@sandbox.register` only supports scalar types (`str`/`int`/`float`/`bool`) — complex types are not supported
5. **Closure variables**: External variables referenced in the function are not automatically serialized (unless using the `pickle` serializer and the variables are serializable)
6. **Execution environment isolation**: The decorated function runs in an independent remote Python process and does not share state with the local process

---

## Next Steps

- [SDK Usage Guide](sdk-usage.md) — Use the Sandbox API directly
- [Authoring Templates](authoring-templates.md) — Create custom templates
- [API Reference](../reference/api-reference.md) — Complete API signatures
