# Comparison with Other Sandbox Tools

This document provides an objective comparison of Easy Sandbox (ebx) with other popular sandbox and remote execution platforms: E2B, Modal, and Docker Sandbox.

---

## Positioning and Use Cases

| Platform | Core Positioning | Primary Use Cases |
|----------|-----------------|-------------------|
| **Easy Sandbox (ebx)** | E2B-compatible cloud sandbox SDK on Alibaba Cloud FC | AI agent code execution, cloud dev environments, template-driven sandboxes |
| **E2B** | Cloud sandboxes built for AI apps | AI agent tool-use, code interpreters, data analysis in LLM workflows |
| **Modal** | Serverless compute for data/ML pipelines | GPU workloads, batch jobs, model inference, scheduled tasks |
| **Docker Sandbox** | Container-based local/remote isolation | Local development, CI/CD, reproducible environments |

---

## SDK Comparison

| Dimension | Easy Sandbox | E2B | Modal |
|-----------|-------------|-----|-------|
| **Language** | Python | Python, JS/TS, Kotlin, Go | Python |
| **Install** | `pip install easy-sandbox` | `pip install e2b` | `pip install modal` |
| **Sandbox creation** | `await Sandbox.create()` | `await Sandbox.create()` | `@app.function()` decorator |
| **Sync support** | `Sandbox.create_sync()` | `Sandbox()` (sync class) | N/A (async-native) |
| **Command execution** | `sandbox.commands.run()` | `sandbox.commands.run()` | Remote function call |
| **File operations** | `sandbox.files.read/write/list` | `sandbox.files.read/write/list` | `modal.Volume` mount |
| **Code execution** | `sandbox.run_code()` | `sandbox.run_code()` | Remote function execution |
| **Custom commands** | `sandbox.custom(name, **kwargs)` | N/A | N/A |
| **Network access** | `sandbox.network.get_host()` | `sandbox.get_host()` | Built-in URL routing |
| **Terminal (PTY)** | `sandbox.get_terminal()` | `sandbox.terminal.start()` | `modal shell` |
| **E2B compat layer** | `from easy_sandbox.compat import Sandbox` | Native | N/A |
| **Auth methods** | API Key, Alibaba Cloud AK/SK | API Key | Token-based |

### Code Examples

**Easy Sandbox:**

```python
from easy_sandbox.api.sandbox import Sandbox

async with await Sandbox.create(template="python-hello") as sb:
    result = await sb.run_code("print('hello')")
    print(result.text)
```

**E2B:**

```python
from e2b import Sandbox

sandbox = Sandbox()
result = sandbox.run_code("print('hello')")
print(result.text)
sandbox.kill()
```

**Modal:**

```python
import modal
app = modal.App("example")

@app.function()
def hello():
    print("hello")
```

### Usage Style Comparison

Easy Sandbox supports both **imperative** (E2B style) and **declarative** (Modal style) programming paradigms:

| Dimension | E2B Style (Imperative) | Modal Style (Declarative) |
|-----------|----------------------|-------------------------|
| **Creation** | Manual `Sandbox.create()` | Automatic (`@sandbox` decorator) |
| **Dependency install** | `sb.run("pip install ...")` | Decorator argument `packages=[...]` |
| **Data transfer** | `files.write()` + `files.read()` | Function args and return values auto-serialized |
| **Execution** | `sb.run()` / `sb.run_code()` | Call function directly |
| **Result retrieval** | Parse stdout / read files | Function return value |
| **Lifecycle** | Manual `kill()` or `async with` | Automatically managed |
| **Best for** | Fine-grained control, long-running interactions, multi-step workflows | Simple compute tasks, batch processing, function-as-a-service |

**E2B Style (Imperative) — fine-grained control:**

```python
from easy_sandbox.api.sandbox import Sandbox

async with await Sandbox.create() as sb:
    await sb.run("pip install pandas")
    await sb.files.write("/app/data.csv", csv_content)
    result = await sb.run("python3 /app/analyze.py")
    report = await sb.files.read("/app/report.txt")
```

**Modal Style (Declarative) — call like a local function:**

```python
from easy_sandbox.declarative import sandbox

@sandbox(packages=["pandas"])
def analyze(data: list[dict]) -> dict:
    import pandas as pd
    df = pd.DataFrame(data)
    return {"mean": df["value"].mean(), "count": len(df)}

# Called just like a local function — automatically runs in a remote sandbox
result = analyze(my_data)
```

> See [`examples/compat-demos/comparison.py`](../../examples/compat-demos/comparison.py) for a complete example.

---

## CLI Comparison

| Dimension | ebx | e2b CLI | modal CLI |
|-----------|-----|---------|-----------|
| **Install** | `pip install easy-sandbox[cli]` | `npm i -g @e2b/cli` | `pip install modal` |
| **Runtime** | Python (Click) | Node.js | Python (Typer) |
| **Create sandbox** | `ebx create` | `e2b sandbox create` | N/A (code-driven) |
| **List sandboxes** | `ebx sandbox list` | `e2b sandbox list` | `modal container list` |
| **Connect to sandbox** | `ebx connect <id>` | `e2b sandbox connect` | `modal shell` |
| **Template build** | `ebx template build` | `e2b template build` | N/A |
| **Template deploy** | `ebx template deploy` | `e2b template build --push` | N/A |
| **Auth setup** | Via environment variables (`.env`) | `e2b auth login` | `modal token set` |
| **MCP integration** | `ebx mcp install` | N/A | N/A |
| **Secret management** | Via environment variables (`.env`) | N/A | `modal secret create` |

---

## Infrastructure

| Dimension | Easy Sandbox | E2B | Modal | Docker Sandbox |
|-----------|-------------|-----|-------|----------------|
| **Isolation** | Container (Alibaba Cloud FC) | Firecracker MicroVM | Container (gVisor) | Container (runc/containerd) |
| **Startup time** | Seconds | ~150ms (MicroVM) | Seconds (cold) / ms (warm) | Seconds |
| **Regions** | Alibaba Cloud regions (cn-hangzhou, etc.) | US, EU | US (aws-us-east-1, etc.) | Self-hosted |
| **Platform** | Managed (Alibaba Cloud) | Managed (E2B Cloud) | Managed (Modal Cloud) | Self-hosted / Docker Desktop |
| **GPU support** | Via template config | N/A | Native (A10G, A100, H100) | Via NVIDIA Container Toolkit |
| **Max lifetime** | Configurable (up to 86400s) | Configurable | Per-invocation | Unlimited |
| **Pricing** | Alibaba Cloud FC billing | Per-sandbox-second | Per-second compute | Infrastructure cost |

---

## Unique Capabilities of Easy Sandbox

### E2B Protocol Compatibility

Easy Sandbox maintains API-level compatibility with the E2B Python SDK. Existing E2B code can migrate with minimal changes:

```python
# Minimal migration — just change the import
from easy_sandbox.compat import Sandbox  # drop-in for e2b.Sandbox
```

See [Migrating from E2B](migrate-from-e2b.md) for the full guide.

### Alibaba Cloud Ecosystem Integration

| Extension | Description |
|-----------|-------------|
| **AK/SK Auth** | Native Alibaba Cloud AccessKey authentication |
| **OSS Mount** | Mount Alibaba Cloud OSS buckets into sandbox filesystem |
| **VPC** | Attach sandboxes to an Alibaba Cloud VPC |
| **Custom Domain** | Bind custom domains to sandbox services |
| **ACR** | Build and push template images to Alibaba Cloud Container Registry |

### Custom Commands

Templates can define custom commands in `template.yaml` and implement them via a Server SDK inside the container. The SDK exposes them through a unified API:

```python
result = await sandbox.custom("analyze", data="input.csv")
```

This is not available in E2B or Modal.

### MCP Server Integration

Easy Sandbox includes a built-in MCP (Model Context Protocol) Server, enabling AI IDEs (Cursor, Claude Desktop, VS Code) to operate sandboxes directly:

```bash
ebx mcp install --target cursor
```

Provides 7 tools: `create_sandbox`, `run_code`, `run_command`, `read_file`, `write_file`, `list_files`, `kill_sandbox`.

### Declarative Sandbox Decorator

```python
from easy_sandbox import sandbox

@sandbox(template="python-hello", timeout=60)
async def my_task():
    ...
```

---

## Other Platforms (Brief)

| Platform | Notes |
|----------|-------|
| **Daytona** | Cloud development environment platform. Transitioned to closed-source in 2026. Previously offered an open-source self-hosted option. |
| **Google Gemini Sandbox** | Code execution sandbox within Google Cloud's Gemini Enterprise Agent Platform (formerly Vertex AI). Managed service, tightly coupled to Google Cloud ecosystem. |
| **Cloudflare Workers** | Uses V8 Isolates for process-level isolation with sub-millisecond cold starts. Focused on edge computing rather than general-purpose sandboxes. |
| **Fly.io Machines** | Firecracker-based ephemeral VMs. Good for running full Linux environments with fast boot times. API-driven, no sandbox-specific SDK. |

---

## Summary

| Consideration | Recommended Platform |
|--------------|---------------------|
| Migrating from E2B to Alibaba Cloud | **Easy Sandbox** — protocol-compatible, minimal code changes |
| AI agent with code execution needs | **Easy Sandbox** or **E2B** — purpose-built sandbox SDKs |
| GPU-heavy ML/inference workloads | **Modal** — native GPU support and serverless scaling |
| Local development isolation | **Docker** — industry-standard, self-hosted |
| Alibaba Cloud ecosystem integration | **Easy Sandbox** — native OSS, VPC, ACR, AK/SK support |
| MCP-based AI IDE integration | **Easy Sandbox** — built-in MCP Server |

---

## Further Reading

- [Migrating from E2B](migrate-from-e2b.md)
- [SDK Usage Guide](sdk-usage.md)
- [CLI Tutorial](cli-tutorial.md)
- [MCP Integration](mcp-integration.md)
- [Authentication](authentication.md)
