# Easy Sandbox — Complete Design Document

> **Version**: v1.1 | **Last Updated**: 2026-09-02
>
> This document consolidates all design decisions for the Easy Sandbox project, serving as a complete technical blueprint ready for team execution.

---

## 1. Project Positioning and Core Philosophy

### 1.1 Project Basic Information

> **Rename Note**: This project has been fully renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package name: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

| Item | Value |
|------|-------|
| **Brand Name** | Easy Sandbox |
| **GitHub Repository** | `easy-sandbox` |
| **CLI Command** | `ebx` (concise and semantically clear) |
| **PyPI Package** | `easy-sandbox` (`pip install easy-sandbox`), Python import name `easy_sandbox` |
| **npm Package** | `@easy-sandbox/sdk` |
| **Positioning** | AI Agent-oriented cloud Serverless code execution sandbox platform |

### 1.2 What Problems We Solve

E2B is the current benchmark product in the AI Agent sandbox space, but has ten pain points in practical use:

| # | Pain Point | Our Solution |
|---|-----------|--------------|
| 1 | **Complex configuration** — Need to manually assemble `E2B_API_URL` / `E2B_DOMAIN`, replace region placeholders | Zero Config — SDK only needs a `region` parameter to auto-derive all endpoints |
| 2 | **Resource leaks** — Forgetting `kill()` causes sandboxes to idle and incur charges | Context Manager + automatic cleanup strategy + Session GC |
| 3 | **No reuse mechanism** — Every time: create → use → kill | SandboxPool warm pool + Session auto-management |
| 4 | **No declarative config** — All configuration must be in code | `sandbox.yaml` + config files + environment variable layered overrides |
| 5 | **Missing FC Extensions** — VPC/OSS/domain require additional SDKs | Unified SDK covering E2B compatibility + Alibaba Cloud extensions |
| 6 | **No Agent integration** — Missing MCP Server and Tool Schema | Built-in MCP Server + one-click installation to IDE |
| 7 | **No Skills system** — Cannot package and distribute best practices | Skills register/install/share ecosystem |
| 8 | **Limited template capabilities** — Dockerfile only, no chained builds | Image chained builder + template inheritance + GitHub tarball API distribution by ref |
| 9 | **Unfriendly error messages** — English-only errors, no fix suggestions | Structured error codes + bilingual (Chinese/English) + fix suggestions |
| 10 | **No structured output** — CLI doesn't support JSON | All commands support `--json`, AI can parse directly |

### 1.3 Three Design Principles

1. **E2B Protocol Compatibility** — L4 layer API is compatible with E2B data plane protocol, providing a migration helper layer `from easy_sandbox.compat import Sandbox` for migrating users (note: synchronous calls need to be changed to async); users who want pure E2B can use the E2B SDK directly
2. **AI-First** — Natural language sandbox creation, sandbox-embedded AI CLI tools, MCP Server as a first-class citizen, not an afterthought
3. **Zero Configuration Defaults** — Works out of the box, from installation to first sandbox run in no more than 3 lines of code

### 1.4 Relationship with E2B

Easy Sandbox **is compatible with the E2B data plane protocol** (Sandbox lifecycle, Commands, Filesystem, Code Interpreter), but **is not a replacement for the E2B SDK**.

**Core Differentiating Value**: Easy Sandbox's value lies above the E2B protocol — decorator mode (`@sandbox`), natural language sandbox creation, Skills ecosystem, sandbox-embedded AI CLI tools (Codex / Qwen CLI), deep MCP Server integration, Alibaba Cloud FC Extensions, etc., are unique capabilities not available in the E2B SDK.

**Migration Path**: For existing E2B users, a migration helper layer simplifies migration (synchronous calls need to be changed to async):

```python
# E2B original code
from e2b_code_interpreter import Sandbox
sb = Sandbox()

# Migration to Easy Sandbox — via migration helper layer (requires async calls)
from easy_sandbox.compat import Sandbox
sb = await Sandbox.create(template="code-interpreter")

# Recommended: Use Easy Sandbox native API for full enhanced capabilities
from easy_sandbox import Sandbox
sb = await Sandbox.create(template="code-interpreter")
```

### 1.5 Quick Start

Three steps to start using Easy Sandbox:

**Step 1: Install**

```bash
pip install easy-sandbox
```

**Step 2: Configure Authentication**

```bash
# Method 1: Set environment variable (recommended)
export SANDBOX_API_KEY=your-api-key

# Method 2: Login via CLI
ebx auth login
```

**Step 3: Create Your First Sandbox**

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("print('Hello, Easy Sandbox!')")
    print(result.text)
    # Sandbox automatically destroyed on exit
```

Or via CLI:

```bash
ebx create --template code-interpreter
ebx exec <sandbox-id> "python -c 'print(1+1)'"
ebx kill <sandbox-id>
```

---

## 2. System Architecture

### 2.1 Six-Layer Architecture

The Easy Sandbox SDK employs a six-layer architecture, abstracting from low-level transport to high-level AI integration, with each layer having a single responsibility and clear boundaries. Users can integrate at any layer.

```mermaid
graph TD
    L6["L6 Agent Integration Layer\nAI Integration — Sandbox-embedded AI CLI tool wrappers / MCP Server"]
    L5["L5 Declarative API Layer\nDeclarative API — @sandbox decorator / sandbox.yaml"]
    L4["L4 High-Level API Layer\nHigh-Level Convenience API — Sandbox / SandboxPool / Image"]
    L3["L3 Extension Layer\nAlibaba Cloud Extension — VPC / OSS / Domain / NAS Mount"]
    L2["L2 Core Protocol Layer\nCore Protocol — E2B Compatible Protocol / HTTP REST + WebSocket"]
    L1["L1 Transport and Auth Layer\nTransport & Auth — HTTP Connection Pool / API Key / AK-SK"]
    GW["Alibaba Cloud API Gateway"]
    FC["Alibaba Cloud Function Compute FC Sandbox Runtime"]
    L6 --> L5 --> L4 --> L3 --> L2 --> L1
    L1 --> GW
    L1 --> FC
```

### 2.2 Layer Responsibilities

#### L1 — Transport & Auth Layer

| Module | Responsibility |
|--------|---------------|
| `transport.http` | httpx-based HTTPS requests, connection pool management, timeout/retry strategies |
| `transport.ws` | websockets-based long connections, heartbeat keep-alive, auto-reconnect |
| `auth.api_key` | **API Key authentication (primary path)**: passed via `X-API-KEY` header, environment variable `SANDBOX_API_KEY` |
| `auth.ak_sk` | **AK/SK authentication (extension)**: exchange Alibaba Cloud AK/SK for temporary API Key, or for control plane OpenAPI calls |
| `auth.config` | Multi-environment config loading (code params → env vars → .env → config.toml → defaults) |

**AK/SK Token Exchange Lifecycle**:
- Temporary API Key validity: 1 hour (TTL=3600s)
- Auto-refresh: automatically renews 5 minutes before expiry
- Token cached in memory only, not persisted to disk
- Refresh failure: throws `AuthenticationError(E1003)`, prompting credential reconfiguration
- STS temporary credentials supported: RAM Role + STS recommended for enterprise scenarios

**Dual Authentication Modes**:

| Auth Method | Scenario | Transmission | Environment Variable |
|-------------|----------|--------------|---------------------|
| **API Key (primary)** | Cloud sandbox data plane operations | `X-API-KEY` header | `SANDBOX_API_KEY` |
| **AK/SK (extension)** | Exchange for temporary API Key, control plane OpenAPI | Alibaba Cloud V4 signature | `ALICLOUD_ACCESS_KEY_ID` / `ALICLOUD_ACCESS_KEY_SECRET` |

**envdAccessToken Dual-Token Authentication Flow**:

```mermaid
sequenceDiagram
    participant User as SDK / User
    participant Platform as Platform API
    participant Envd as Sandbox envd API

    User->>Platform: POST /sandboxes (X-API-KEY)
    Platform-->>User: sandboxId + envdAccessToken
    Note over User: Auto-extract envdAccessToken and cache in Sandbox instance
    User->>Envd: Process/file/code execution (X-Access-Token: envdAccessToken)
    Envd-->>User: Execution result
```

> **Note**: `X-API-KEY` is used for sandbox lifecycle operations (creation, management, destruction) via the Platform API; `envdAccessToken` is used for in-sandbox data plane operations (process, file, code execution) via the Sandbox envd API. The two tokens have different scopes; the SDK manages the switching automatically, transparent to users.

**Target Users**: Infrastructure developers, advanced users needing custom authentication logic.

#### L2 — Core Protocol Layer

**Self-implemented E2B compatible protocol**, independent of the E2B SDK, built directly on httpx + websockets.

**Two API layers must be clearly distinguished**:

- **Platform API** (sandbox lifecycle management): Standard HTTP REST, authenticated with `X-API-KEY`
  - Sandbox: create, connect, list, getInfo, kill, setTimeout, pause
  - Template: CRUD, build, tags, alias
- **Sandbox envd API** (process/file/code execution): Connect protocol (gRPC-compatible over HTTP), authenticated with `X-Access-Token` (envdAccessToken)
  - Content-Type: `application/connect+json`
  - Request routing: RPC-style (e.g., `/process.Process/Start`)
  - Supports Server-Streaming responses
  - Process: Start(streaming), List, Connect(streaming), SendStdin, Kill
  - Filesystem: List, Exists, GetInfo, Read, Write, MakeDir, Remove, Rename, WatchDir(streaming)
  - Code Interpreter: RunCode(streaming), CreateContext, ListContexts, RestartContext, RemoveContext
  - PTY: WebSocket bidirectional channel

| Module | Responsibility |
|--------|---------------|
| `protocol.sandbox` | Sandbox lifecycle management (Platform API — HTTP REST) |
| `protocol.process` | Remote process management (Sandbox envd API — Connect protocol + Server-Streaming) |
| `protocol.filesystem` | Remote filesystem operations (Sandbox envd API — Connect protocol) |
| `protocol.terminal` | Virtual terminal (PTY) multiplexing, WebSocket bidirectional communication |
| `protocol.port` | Port forwarding and mapping management (Platform API — HTTP REST) |

**Target Users**: Protocol-level developers, users needing fine-grained control.

#### L3 — Extension Layer (Alibaba Cloud Extensions)

| Module | Responsibility |
|--------|---------------|
| `extensions.vpc` | VPC network configuration, security group rules, ENI binding |
| `extensions.oss` | OSS mounting, file synchronization, large file transfer acceleration |
| `extensions.domain` | Custom domain binding and TLS certificate management |
| `extensions.nas` | NAS filesystem mounting (shared storage) |
| `extensions.log` | SLS log integration, structured log collection |

**Target Users**: Enterprise users, developers needing deep Alibaba Cloud service integration.

#### L4 — High-Level API Layer

| Module | Responsibility |
|--------|---------------|
| `api.sandbox` | Sandbox class — unified entry point for creation, management, execution, destruction |
| `api.pool` | SandboxPool — connection pool/warm pool, concurrency management |
| `api.image` | Image builder — chained API for custom image building |
| `api.files` | High-level file operations — upload/download/watch |
| `api.code` | Code execution engine — multi-language support, Rich Output |

**Target Users**: Most developers, the core layer for E2B compatibility mode.

#### L5 — Declarative API Layer

| Module | Responsibility |
|--------|---------------|
| `declarative.decorator` | `@sandbox` decorator — Modal-style remote execution |
| `declarative.config` | `sandbox.yaml` parsing and validation |
| `declarative.serializer` | Parameter/return value serialization (pickle / cloudpickle / JSON) |
| `declarative.scheduler` | Declarative task scheduling and orchestration |

**Target Users**: Python developers and ML engineers seeking minimal-effort experience.

#### L6 — Agent Integration Layer (AI Integration)

| Module | Responsibility |
|--------|---------------|
| `agent.builtin` | Built-in Agent wrappers — sandbox templates pre-install AI CLI tools (Codex / Qwen CLI), SDK provides syntactic sugar |
| `agent.tools` | Agent tool set — sandbox operations wrapped as OpenAI function calling format |
| `agent.mcp` | MCP Server implementation — exposes sandbox capabilities as MCP Tools |

**Target Users**: AI application developers, Agent framework integrators.

> **Note**: SDK has zero LLM dependencies and does not include a built-in LLM Provider adapter layer. Agent capabilities come from AI CLI tools pre-installed in sandbox templates.

### 2.3 Inter-Layer Dependencies

```mermaid
graph TD
    L6["L6 Agent Integration"] -->|depends on| L4["L4 High-Level API"]
    L5["L5 Declarative API"] -->|depends on| L4
    L4 -->|depends on| L3["L3 Extensions (optional)"]
    L4 -->|depends on| L2["L2 Core Protocol"]
    L2 --> L1["L1 Transport and Auth"]
```

**Dependency Rules**:

1. **Strict downward dependency**: Each layer can only depend on layers below it; reverse or cross-layer dependencies are forbidden
2. **L3 is optional**: L4 can depend directly on L2; L3 Extensions are enhancement modules included on demand
3. **L5 depends on L4**: Declarative API is implemented through L4 high-level API, not directly on L2
4. **L6 depends on L4**: Agent integration is implemented through L4 high-level API
5. **L1 is the foundation**: All upper layers ultimately depend on L1 for network communication and authentication

---

## 3. Sandbox Type System

### 3.1 Three Sandbox Modes

#### Ephemeral Sandbox

**Positioning**: Disposable one-time execution environment, the most commonly used mode. **Currently the only fully supported sandbox type.**

```python
from easy_sandbox import Sandbox

# Default is ephemeral sandbox
sb = await Sandbox.create(template="code-interpreter")
result = await sb.run_code("print('hello')")
await sb.kill()  # All data lost after destruction

# Context Manager auto-destruction
async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("print('hello')")
    # Destroyed on exit
```

#### Persistent Sandbox — 🔮 Future Plan

> **⚠️ Requires underlying platform support, currently a future plan.** Persistent sandboxes depend on persistent storage capabilities of the underlying platform, pending Alibaba Cloud FC support.

**Positioning**: Long-running development/service environment with state preserved across sessions.

```python
# Future API — pending platform support
from easy_sandbox import Sandbox

sb = await Sandbox.create(
    template="python-base",
    persistent=True,
    name="my-dev-env",
)

await sb.commands.run("pip install flask sqlalchemy")

# Reconnect later
sb = await Sandbox.connect("my-dev-env")
result = await sb.commands.run("pip list")  # flask, sqlalchemy still present
```

#### Hibernated Sandbox — 🔮 Future Plan

> **⚠️ Requires underlying platform support, currently a future plan.** Hibernated sandboxes depend on Snapshot / CRIU capabilities of the underlying platform, pending support.

**Positioning**: State frozen and suspended, resumes to the frozen state when woken, saving costs.

```python
# Future API — pending platform support
from easy_sandbox import Sandbox

sb = await Sandbox.create(
    template="python-data-science",
    hibernate_after=300,
    on_exit="hibernate",
)

await sb.run_code("import pandas as pd; df = pd.read_csv('data.csv')")

await sb.hibernate()       # Stop billing
sb = await Sandbox.connect("sb-xxx")
await sb.wake_up()         # Resume to hibernation state
```

### 3.2 Comparison Matrix

| Feature | Ephemeral | Persistent 🔮 | Hibernated 🔮 |
|---------|-----------|---------------|---------------|
| **Implementation Status** | **Currently Available** | Future Plan | Future Plan |
| **Lifecycle** | Destroyed when task ends | Runs until manually destroyed | Can be woken at any time after freezing |
| **State Persistence** | None | Full persistence | Snapshot-style freezing |
| **Filesystem** | tmpfs (RAM disk) | Persistent storage | Snapshot on freeze |
| **Processes** | Stopped when task completes | Background continuous running | Freeze/resume |
| **Network** | Temporary port mapping | Fixed domain/port | Restored on wake |
| **Startup Time** | Cold start ~2s | Already running ~0s | Wake ~3-5s |
| **Billing** | Pay per usage duration | Continuous billing | Low/free during hibernation |
| **Max Duration** | Default 5 minutes | Unlimited | Hibernation can last 30 days |
| **Typical Scenarios** | Code execution, data analysis | Development environment, web services | Intermittently used projects |

### 3.3 Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Creating : create()
    Creating --> Running : Ready
    Running --> Dead : kill()
    Running --> Paused : pause() (requires whitelist)
    Paused --> Running : resume()
```

> **Note**: `pause()` / `resume()` state transitions require whitelist permissions, currently a restricted feature. Snapshot-related state transitions are future plans, not reflected in the current state machine.

### 3.4 Automatic Cleanup Strategies

#### Ephemeral Sandbox

| Trigger | Action | Default |
|---------|--------|---------|
| Reached `timeout` | Force destroy | 300s |
| Context Manager exit | Graceful destroy | — |
| Client disconnects | Wait → destroy | Wait 30s |

#### Persistent Sandbox (🔮 Future Plan)

| Trigger | Action | Default |
|---------|--------|---------|
| Manual `kill()` | Destroy | — |
| CLI `ebx kill` | Destroy | — |
| Account in arrears | Freeze → destroy after 7 days | — |

#### Hibernated Sandbox (🔮 Future Plan)

| Trigger | Action | Default |
|---------|--------|---------|
| Idle beyond `hibernate_after` | Auto-hibernate | 300s |
| Manual `hibernate()` | Immediate hibernate | — |
| Hibernated beyond retention period | Auto-destroy | 30 days |

### 3.5 Billing Model

> **⚠️ The following costs are estimates; refer to official Alibaba Cloud pricing.**

```
Total Cost = Compute Cost + Storage Cost + Network Cost

Compute Cost = CPU unit price × CPU cores × runtime duration
             + Memory unit price × memory size × runtime duration
             + GPU unit price × GPU count × runtime duration

Storage Cost = Persistent storage unit price × storage size × retention period (🔮 future)

Network Cost = Public outbound traffic × traffic unit price
```

**Cost Estimation Examples** (estimates, refer to official Alibaba Cloud pricing):

| Scenario | Configuration | Cost (estimate) |
|----------|--------------|-----------------|
| Ephemeral sandbox 5 minutes | 1C/2G | ≈ ¥0.06 |
| Persistent sandbox 24 hours 🔮 | 2C/4G | ≈ ¥36 |
| Hibernated sandbox (2h running + 22h hibernated) 🔮 | 2C/4G | ≈ ¥3.09 (91% savings) |

---

## 4. SDK API Design

The Easy Sandbox SDK provides three usage paradigms covering everything from simple scripts to complex AI applications. All three paradigms can be mixed.

### 4.1 Configuration System (Zero Config)

The SDK follows a zero-configuration philosophy, loading configuration by priority:

```
Code parameters > Environment variables > .env file > ~/.ebx/config.toml > Defaults
```

#### Environment Variables

```bash
# Authentication (primary path — API Key)
export SANDBOX_API_KEY=your-api-key

# Authentication (extension — AK/SK, for exchanging temporary API Key or control plane calls)
# export ALICLOUD_ACCESS_KEY_ID=your-ak
# export ALICLOUD_ACCESS_KEY_SECRET=your-sk

# Optional configuration
export SANDBOX_REGION=cn-hangzhou               # Default region
export SANDBOX_TIMEOUT=300                       # Default timeout (seconds)
export SANDBOX_LOG_LEVEL=INFO                    # Log level
```

#### Configuration File

```toml
# ~/.ebx/config.toml
# ⚠️ Security Warning: Storing API Key in plaintext in config.toml poses a security risk.
# Recommended: Use system Keychain (macOS Keychain / Linux Secret Service) for sensitive credentials.
# See `ebx auth login --keychain` command.

[default]
region = "cn-hangzhou"
timeout = 300

[default.auth]
api_key = "your-api-key"              # Primary authentication
# access_key_id = "your-ak"          # Extended authentication (AK/SK exchange)
# access_key_secret = "your-sk"

[profiles.production]
region = "cn-shanghai"
timeout = 600

[profiles.production.auth]
api_key = "your-production-api-key"
```

#### Code Configuration

```python
from easy_sandbox import Sandbox, Config

# Global configuration
Config.set(region="cn-hangzhou", timeout=300, log_level="DEBUG")

# Instance-level configuration (overrides global)
sb = await Sandbox.create(template="code-interpreter", region="cn-shanghai", timeout=600)
```

### 4.2 Paradigm 1: E2B Compatibility Mode

API compatible with E2B data plane protocol, with a migration helper layer for existing E2B users (synchronous calls need to be changed to async).

```python
from easy_sandbox import Sandbox

# Create sandbox (async mode)
sb = await Sandbox.create(template="code-interpreter")

# Execute code
result = await sb.run_code("print('Hello, Easy Sandbox!')")
print(result.text)

# Execute command
result = await sb.commands.run("ls -la /app")
print(result.stdout)

# File operations
await sb.files.write("/app/data.csv", "name,age\nAlice,30\nBob,25")
content = await sb.files.read("/app/data.csv")
files = await sb.files.list("/app")

# Destroy sandbox
await sb.kill()
```

**Synchronous Mode**:

```python
from easy_sandbox import Sandbox

sb = Sandbox.create_sync(template="code-interpreter")
result = sb.run_code_sync("print(1+1)")
sb.kill_sync()
```

**Context Manager**:

```python
async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("import sys; print(sys.version)")
    # Sandbox automatically destroyed on exit
```

**Streaming Output**:

```python
sb = await Sandbox.create(template="code-interpreter")

async for chunk in sb.commands.stream("pip install pandas && python train.py"):
    if chunk.type == "stdout":
        print(chunk.data, end="")
    elif chunk.type == "stderr":
        print(f"[ERR] {chunk.data}", end="")
    elif chunk.type == "exit":
        print(f"\nExit code: {chunk.exit_code}")
```

### 4.3 Paradigm 2: Decorator Mode (Modal-Style)

Inspired by Modal's declarative experience, using decorators to transparently execute local functions in remote sandboxes.

```python
from easy_sandbox import sandbox, Image

@sandbox(template="python-data-science", cpu=2, memory=4096)
def analyze(data: str) -> str:
    import pandas as pd
    import io
    df = pd.read_csv(io.StringIO(data))
    summary = df.describe().to_string()
    return f"Data analysis results:\n{summary}"

# On invocation: create sandbox → serialize params → remote execution → return result → destroy
result = analyze("name,score\nAlice,95\nBob,87\nCarol,92")
```

**Custom Image**:

```python
from easy_sandbox import sandbox, Image

custom_image = (
    Image.from_template("python-data-science")
    .pip_install("scikit-learn", "xgboost", "lightgbm")
    .apt_install("libgomp1")
    .copy_local("./models/", "/app/models/")
    .env(MODEL_PATH="/app/models/latest.pkl")
)

@sandbox(image=custom_image, cpu=4, memory=8192, timeout=300)
def train_model(dataset_path: str) -> dict:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    model = RandomForestClassifier(n_estimators=100)
    # ... training logic
    return {"accuracy": 0.95, "model_path": "/app/output/model.pkl"}
```

**Async Decorator**:

```python
from easy_sandbox import sandbox

@sandbox(template="node-web", async_mode=True)
async def run_lighthouse(url: str) -> dict:
    import subprocess, json
    result = subprocess.run(
        ["npx", "lighthouse", url, "--output=json", "--quiet"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

import asyncio
results = await asyncio.gather(
    run_lighthouse("https://example.com"),
    run_lighthouse("https://test.com"),
)
```

> **Note**: Resource specification parameters (`cpu`/`memory`/`gpu`) are currently determined by templates. The SDK internally implements a two-step "find matching template / create matching template" operation. User-specified cpu/memory values are mapped to the closest available template specification.

#### Serialization Limitations and Risks

The decorator mode uses `cloudpickle` for function serialization, with the following known limitations:

**Type Limitations**:
- Supported: basic types (int/float/str/bool), list, dict, dataclass, Pydantic Model
- Not supported: database connections, file handles, C extension objects, thread/process objects
- Closures referencing non-serializable objects will fail at runtime

**Security Risks**:
- pickle deserialization can execute arbitrary code; SDK uses a restricted deserializer for return values
- Recommend using decorator mode in trusted network environments

**Cross-Version Compatibility**:
- Local and sandbox Python major versions must match (e.g., both 3.10.x or 3.11.x)
- cloudpickle artifacts between different Python versions are not guaranteed compatible

**Size Limits**:
- Serialized function arguments and return values must not exceed 10MB
- SDK throws `SerializationError` when the limit is exceeded

**MVP Phase Alternative**:
The decorator MVP can initially support JSON serialization only (limiting parameter types to JSON-compatible), with cloudpickle support added in later iterations.

### 4.4 Paradigm 3: Built-in Agent Mode

SDK built-in AI Agent capability wrappers. **Core concept**: Sandbox templates pre-install AI CLI tools (Codex, Qwen CLI, etc.), and the SDK Agent API is just syntactic sugar for `commands.run()`.

```python
from easy_sandbox import Sandbox

# Code Agent — essentially executes sb.commands.run("codex 'fix bug in main.py'")
sb = await Sandbox.create(template="codex")
result = await sb.agent.code("fix bug in main.py")
print(result.output)

# Browser Agent — essentially executes sb.commands.run("qwen-cli browse 'open Baidu and take screenshot'")
sb = await Sandbox.create(template="qwen-browser")
result = await sb.agent.browse("Open Baidu and take a screenshot of the homepage")
print(result.output)

# Shell Automation — essentially executes sb.commands.run("codex 'install nginx and configure...'")
sb = await Sandbox.create(template="codex")
result = await sb.agent.shell("Install nginx and configure reverse proxy to port 8080")
print(result.output)
```

> **Design Philosophy**: SDK has zero LLM dependencies, staying lightweight. AI tool authentication is pre-configured in sandbox templates; users don't need additional API Keys. Hot updates are possible by upgrading the AI CLI version within templates. Users can choose different templates (Codex template / Qwen template / custom template).

### 4.5 Natural Language Creation

> **Users don't need to know template names, resource specs, or configuration parameters — just describe what they want to do, and the SDK handles everything automatically.**

```python
from easy_sandbox import Sandbox

# Natural language description → auto-infer template + resource config
sb = await Sandbox.create("Run a python data analysis environment, need GPU")
# Inference result: template=python-data-science, gpu=auto, memory=8192

sb = await Sandbox.create("Start a Node.js Web service, expose port 3000")
# Inference result: template=node-web, expose=[3000]

sb = await Sandbox.create("Use playwright to scrape a web page and take a screenshot")
# Inference result: template=browser-automation, memory=4096
```

**Inference Implementation Strategy** (Three-Level Fallback):

```mermaid
flowchart TD
    A["Natural language description"] --> B{"Server-side AI inference endpoint"}
    B -- Available --> R1["Return inference result (optimal accuracy)"]
    B -- Unavailable/timeout --> C{"Local Qwen CLI / DashScope API"}
    C -- Available --> R2["Return inference result (local fallback)"]
    C -- Unavailable/timeout --> D["Keyword rule matching (fully offline)"]
    D --> R3["Return inference result (final fallback)"]
```

**Fallback Control Strategy**:
- Server-side AI timeout: 3 seconds, immediate fallback on timeout (no retry)
- Qwen CLI/DashScope timeout: 5 seconds, immediate fallback if not installed or auth fails
- Keyword rule matching: local execution, no timeout
- Confidence threshold: < 0.6 prompts user confirmation instead of direct creation
- All three levels fail: prompt user to manually specify template name, display available template list

**Inference Transparency**:

```python
# View inference result (without actually creating)
plan = await Sandbox.plan("Need an environment that can run TensorFlow, dataset is 50GB")
print(plan)
# SandboxPlan(
#   template='ml-gpu',
#   cpu=4, memory=16384, disk=65536,
#   gpu='A10',                    # ⚠️ GPU support depends on platform capabilities, currently future plan
#   confidence=0.92,
#   reasoning='Detected TensorFlow + large dataset requirements, selecting GPU template with expanded disk'
# )

# User can accept or override
sb = await Sandbox.create(plan)                     # Use inference result directly
sb = await Sandbox.create(plan, memory=32768)        # Override specific parameters
```

**Backward Compatibility**: `create()` intelligently judges the first argument — matches known template names for template creation, otherwise triggers the inference flow.

### 4.6 Sandbox Core API

```python
class Sandbox:
    """Sandbox core class — unified entry point for all operations"""

    # ── Lifecycle ──────────────────────────────────────
    @classmethod
    async def create(
        cls,
        description: str | None = None,      # Natural language description (AI-First)
        *,
        template: str = "base",
        timeout: int = 300,
        metadata: dict | None = None,
        env: dict[str, str] | None = None,
        cpu: int | None = None,               # Determined by template, SDK finds matching template
        memory: int | None = None,            # MB, same as above
        disk: int | None = None,              # MB
        gpu: str | None = None,               # GPU model or "auto"
        region: str | None = None,
        vpc: VPCConfig | None = None,
        upload: list[str] | None = None,
        project_dir: str | None = None,
        # 🔮 Future parameters — pending platform support
        # persistent: bool = False,
        # name: str | None = None,
        # hibernate_after: int | None = None,
        # on_exit: Literal["destroy", "hibernate", "keep"] = "destroy",
    ) -> "Sandbox": ...

    @classmethod
    async def plan(cls, description: str, **kwargs) -> "SandboxPlan": ...
    @classmethod
    async def connect(cls, sandbox_id: str) -> "Sandbox": ...
    @classmethod
    async def last(cls) -> "Sandbox": ...

    async def kill(self) -> None: ...
    async def keep_alive(self, duration: int) -> None: ...
    async def set_timeout(self, timeout: int) -> None: ...
    @property
    def is_running(self) -> bool: ...

    # Future API — pending platform support
    # async def hibernate(self) -> None: ...
    # async def wake_up(self) -> "Sandbox": ...
    # async def snapshot(self, name: str) -> str: ...

    # ── Properties ──────────────────────────────────────────
    @property
    def id(self) -> str: ...
    @property
    def status(self) -> SandboxStatus: ...
    @property
    def url(self) -> str: ...

    # ── Code Execution ──────────────────────────────────────
    async def run_code(self, code: str, *, language: str = "python", timeout: int = 30) -> CodeResult: ...

    # ── Submodules ────────────────────────────────────────
    @property
    def commands(self) -> CommandsModule: ...
    @property
    def files(self) -> FilesModule: ...
    @property
    def agent(self) -> AgentModule: ...
    @property
    def network(self) -> NetworkModule: ...

    # ── E2B Compatibility Methods ─────────────────────────
    def get_host(self, port: int) -> str: ...
    async def upload_url(self, path: str) -> str: ...
    async def download_url(self, path: str) -> str: ...
```

**CommandsModule**:

```python
class CommandsModule:
    async def run(self, cmd: str, *, timeout: int = 60, env: dict | None = None, cwd: str = "/app") -> ProcessResult: ...
    async def stream(self, cmd: str, **kwargs) -> AsyncIterator[ProcessChunk]: ...
    async def start(self, cmd: str, **kwargs) -> Process: ...
    async def list(self) -> list[ProcessInfo]: ...
    async def kill(self, pid: int) -> None: ...
```

**FilesModule**:

```python
class FilesModule:
    async def read(self, path: str, *, encoding: str = "utf-8") -> str: ...
    async def read_bytes(self, path: str) -> bytes: ...
    async def write(self, path: str, content: str | bytes) -> None: ...
    async def list(self, path: str = "/") -> list[FileInfo]: ...
    async def remove(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def upload(self, local_path: str, remote_path: str) -> None: ...
    async def download(self, remote_path: str, local_path: str) -> None: ...
    async def watch(self, path: str) -> AsyncIterator[WatchEvent]: ...
    async def make_dir(self, path: str) -> None: ...
```

**NetworkModule**:

```python
class NetworkModule:
    async def get_url(self, port: int) -> str: ...
    async def expose(self, port: int, *, public: bool = False) -> str: ...
    async def forward(self, remote_port: int, local_port: int) -> None: ...
    async def list_ports(self) -> list[PortInfo]: ...
    # ⚠️ Currently does not perform actual network changes, only records configuration
    async def update_config(self, config: NetworkConfig) -> None: ...
```

**CodeContextModule (E2B Compatible)**:

```python
class CodeContextModule:
    """E2B Code Context compatible API"""
    async def create(self, *, cwd: str = "/app", language: str = "python") -> "CodeContext": ...
    async def list(self) -> list["CodeContext"]: ...
    async def restart(self, context_id: str) -> None: ...
    async def remove(self, context_id: str) -> None: ...
```

### 4.7 Chained Image Building

```python
from easy_sandbox import Image

image = (
    Image.from_template("python-base")
    .python_version("3.11")
    .pip_install("pandas", "numpy", "matplotlib")
    .pip_install_from_requirements("./requirements.txt")
    .apt_install("ffmpeg", "libsm6")
    .copy_local("./src/", "/app/src/")
    .run_command("chmod +x /app/src/entrypoint.sh")
    .env(MODEL_PATH="/app/models/latest.pkl", DATA_DIR="/app/data")
    .workdir("/app")
    .expose(8080)
    .entrypoint("python /app/src/main.py")
)

sb = await Sandbox.create(image=image)

# Build and push as template
template_id = await image.build_and_push(name="my-ml-env", tag="v1.0")
```

**Building from Dockerfile**:

```python
image = Image.from_dockerfile("./Dockerfile")
image = Image.from_dockerfile_string("""
FROM python:3.11-slim
RUN pip install flask
COPY . /app
CMD ["python", "app.py"]
""")
```

### 4.8 SandboxPool

```python
from easy_sandbox import SandboxPool

pool = SandboxPool(
    template="code-interpreter",
    min_ready=3,           # Minimum warm pool size
    max_size=20,           # Maximum sandbox count
    idle_timeout=300,      # Idle timeout (seconds)
    scale_policy="auto",   # Auto-scaling
)

await pool.start()

# Acquire sandbox from pool (millisecond-level)
async with pool.acquire() as sb:
    result = await sb.run_code("print('instant!')")

# Batch execution
tasks = ["print(i)" for i in range(100)]
results = await pool.map(lambda sb, code: sb.run_code(code), tasks)

# Pool status
status = pool.status()
print(f"Ready: {status.ready}, In use: {status.in_use}, Total: {status.total}")

await pool.shutdown()
```

### 4.9 FC Extensions

#### VPC Network Configuration

```python
from easy_sandbox import Sandbox
from easy_sandbox.extensions import VPCConfig

sb = await Sandbox.create(
    template="base",
    vpc=VPCConfig(vpc_id="vpc-xxx", vswitch_ids=["vsw-xxx"], security_group_id="sg-xxx"),
)
result = await sb.commands.run("curl http://10.0.1.100:3306")
```

#### OSS Mount

```python
from easy_sandbox.extensions import OSSMount

sb = await Sandbox.create(
    template="python-data-science",
    mounts=[
        OSSMount(bucket="my-data-bucket", remote_path="datasets/", mount_point="/data", read_only=True),
        OSSMount(bucket="my-output-bucket", remote_path="results/", mount_point="/output", read_only=False),
    ],
)
```

#### Custom Domain

```python
from easy_sandbox.extensions import DomainConfig

sb = await Sandbox.create(
    template="node-web",
    domain=DomainConfig(domain="sandbox.example.com", port=3000, tls=True, cors=["https://myapp.com"]),
)
print(sb.network.public_url)  # https://sandbox.example.com
```

### 4.10 Error Handling System

#### Exception Class Hierarchy

```mermaid
classDiagram
    class SandboxError {
        <<Base Class>>
    }
    class AuthenticationError {
        Authentication Failed
    }
    class InvalidAPIKeyError {
        E1001 Invalid API Key
    }
    class InvalidCredentialsError {
        E1003 Invalid AK/SK
    }
    class TokenExpiredError {
        E1002 Token Expired
    }
    class SandboxCreationError {
        Creation Failed
    }
    class TemplateNotFoundError {
        E2001 Template Not Found
    }
    class QuotaExceededError {
        E2002 Quota Exceeded
    }
    class RegionUnavailableError {
        E2003 Region Unavailable
    }
    class ExecutionError {
        Execution Failed
    }
    class TimeoutError {
        E3001 Execution Timeout
    }
    class ProcessError {
        E3002 Process Abnormal Exit
    }
    class CodeExecutionError {
        E3003 Code Execution Error
    }
    class FileOperationError {
        E4001 File Operation Failed
    }
    class NetworkError {
        Network Error
    }
    class ConnectionLostError {
        E5002 Connection Lost
    }
    class ReconnectFailedError {
        Reconnect Failed
    }
    class AgentError {
        Agent Error
    }
    class ToolExecutionError {
        Tool Execution Failed
    }

    SandboxError <|-- AuthenticationError
    SandboxError <|-- SandboxCreationError
    SandboxError <|-- ExecutionError
    SandboxError <|-- FileOperationError
    SandboxError <|-- NetworkError
    SandboxError <|-- AgentError
    AuthenticationError <|-- InvalidAPIKeyError
    AuthenticationError <|-- InvalidCredentialsError
    AuthenticationError <|-- TokenExpiredError
    SandboxCreationError <|-- TemplateNotFoundError
    SandboxCreationError <|-- QuotaExceededError
    SandboxCreationError <|-- RegionUnavailableError
    ExecutionError <|-- TimeoutError
    ExecutionError <|-- ProcessError
    ExecutionError <|-- CodeExecutionError
    NetworkError <|-- ConnectionLostError
    NetworkError <|-- ReconnectFailedError
    AgentError <|-- ToolExecutionError
```

#### Error Code System

| Error Code | Category | Meaning | Fix Suggestion |
|------------|----------|---------|----------------|
| `E1001` | Auth | Invalid API Key | Check SANDBOX_API_KEY environment variable |
| `E1002` | Auth | Token expired | SDK will auto-refresh; if persistent, check clock sync |
| `E1003` | Auth | Invalid AK/SK | Check ALICLOUD_ACCESS_KEY_ID / SECRET environment variables |
| `E2001` | Creation | Template not found | Run `ebx template list` to view available templates |
| `E2002` | Creation | Quota exceeded | Contact admin to increase quota or destroy idle sandboxes |
| `E3001` | Execution | Command timeout | Increase timeout parameter |
| `E4001` | File | File not found | Use `files.list()` to check path |
| `E5001` | Network | Connection failed | Check network and firewall |
| `E5002` | Network | Connection lost | SDK will auto-reconnect; if persistent, check network environment |

#### Error Handling Example

```python
from easy_sandbox import Sandbox
from easy_sandbox.errors import (
    SandboxError, QuotaExceededError, TimeoutError, TemplateNotFoundError,
)

try:
    sb = await Sandbox.create(template="code-interpreter")
    result = await sb.run_code("import time; time.sleep(100)", timeout=5)
except TemplateNotFoundError as e:
    print(f"Template not found: {e.template}")
    print(f"Available templates: {e.available_templates}")
except QuotaExceededError as e:
    print(f"Quota exceeded: {e.current}/{e.limit}")
except TimeoutError as e:
    print(f"Execution timeout: {e.timeout}s, partial output: {e.partial_output}")
except SandboxError as e:
    print(f"[{e.code}] {e.message}")
    print(f"Fix suggestion: {e.suggestion}")
```

#### Error Scenario UX Design

| Error Scenario | User Perception | SDK Behavior |
|----------------|----------------|--------------|
| **Network disconnected** | CLI shows "⚠ Network interrupted, reconnecting..." | Auto-reconnect 3 times (exponential backoff 1s/2s/4s), throws `ConnectionLostError` after limit while preserving partial output |
| **Auth expired** | CLI shows "🔑 Authentication expired, refreshing..." | API Key mode auto-renews; AK/SK mode auto-re-exchanges; throws `TokenExpiredError` on all failures and guides re-login |
| **Sandbox crashed** | CLI shows "💥 Sandbox abnormal exit (OOM/Timeout)" | Collects pre-crash logs, returns `SandboxCrashedError` with `last_output`/`exit_reason`/`suggestion` (e.g., "Out of memory, consider increasing memory parameter") |
| **API rate limited** | CLI shows "⏳ Too many requests, waiting to retry..." | Auto backoff retry (respects `Retry-After` header), throws `RateLimitError` after 30s |

---

## 5. CLI Design

`ebx` CLI is the command-line entry point for Easy Sandbox, serving both human developers and AI Agents.

### 5.1 Command System

```mermaid
graph TB
    ebx["ebx"]

    ebx --- create["create - Create sandbox (natural language support)"]
    ebx --- list["list - List all sandboxes"]
    ebx --- info["info - View sandbox details"]
    ebx --- kill["kill - Destroy sandbox / --all"]
    ebx --- exec["exec - Execute command in sandbox"]
    ebx --- run["run - Execute code file"]
    ebx --- shell["shell - Interactive shell"]
    ebx --- logs["logs - View sandbox logs"]
    ebx --- upload["upload - Upload file"]
    ebx --- download["download - Download file"]
    ebx --- start["start - Start named session"]
    ebx --- connect["connect - Connect to existing session"]
    ebx --- sessions["sessions"]
    ebx --- build["build - Build image from directory"]
    ebx --- deploy["deploy - Deploy project directly"]
    ebx --- template["template"]
    ebx --- skill["skill"]
    ebx --- secret["secret"]
    ebx --- mcp["mcp"]
    ebx --- pool["pool"]
    ebx --- auth["auth"]
    ebx --- config["config"]
    ebx --- version["version - Version info"]

    sessions --- sess_list["list"]
    sessions --- sess_info["info"]
    sessions --- sess_rename["rename"]
    sessions --- sess_export["export"]
    sessions --- sess_clean["clean"]
    sessions --- sess_import["import"]

    template --- tpl_list["list"]
    template --- tpl_info["info"]
    template --- tpl_build["build"]
    template --- tpl_push["push"]
    template --- tpl_pull["pull"]
    template --- tpl_init["init"]
    template --- tpl_cache["cache"]

    skill --- sk_search["search"]
    skill --- sk_install["install"]
    skill --- sk_update["update"]
    skill --- sk_list["list"]
    skill --- sk_create["create"]
    skill --- sk_publish["publish"]
    skill --- sk_uninstall["uninstall"]

    secret --- sec_create["create"]
    secret --- sec_list["list"]
    secret --- sec_delete["delete"]
    secret --- sec_inject["inject"]

    mcp --- mcp_install["install"]
    mcp --- mcp_start["start"]
    mcp --- mcp_status["status"]
    mcp --- mcp_config["config"]

    pool --- pool_create["create"]
    pool --- pool_list["list"]
    pool --- pool_status["status"]
    pool --- pool_scale["scale"]
    pool --- pool_destroy["destroy"]

    auth --- auth_login["login"]
    auth --- auth_logout["logout"]
    auth --- auth_status["status"]
    auth --- auth_switch["switch"]

    config --- cfg_get["get"]
    config --- cfg_set["set"]
    config --- cfg_list["list"]
    config --- cfg_reset["reset"]
```

#### Global Options

| Option | Shorthand | Description | Default |
|--------|-----------|-------------|---------|
| `--json` | `-j` | Output JSON format (AI-friendly) | `false` |
| `--quiet` | `-q` | Quiet mode, output only key results | `false` |
| `--yes` | `-y` | Skip all confirmation prompts | `false` |
| `--profile` | `-p` | Specify config profile | `default` |
| `--region` | `-r` | Specify region | `cn-hangzhou` |
| `--verbose` | `-v` | Verbose output | `false` |
| `--no-color` | | Disable colors | `false` |
| `--timeout` | `-t` | Timeout (seconds) | `300` |

### 5.2 Natural Language Creation

```bash
# Natural language description → auto-infer template and config
ebx create "run python, run codex"
# ✓ Inference result:
#   Template: code-interpreter
#   CPU: 2 cores  |  Memory: 4096 MB
#   Confidence: 0.95
#   Inference source: Server-side AI / Qwen CLI / Rule matching
# → Creating... Done! sandbox-id: sb-a1b2c3d4

ebx create "start a Node.js Web service"
# ✓ Inference result: Template: node-web, CPU: 1 core, Memory: 2048 MB, Port: 3000

# View inference result only, don't actually create
ebx create "need TensorFlow GPU environment" --dry-run

# Natural language inference + manual override
ebx create "python data analysis" --memory 8192 --region cn-shanghai

# Traditional template mode — 100% backward compatible
ebx create --template code-interpreter
```

### 5.3 Project Direct Deployment (ebx build / ebx deploy)

```bash
# Build image from current directory
ebx build . --name my-app --tag v1.0

# Deploy project directly to a running sandbox
ebx deploy ./my-flask-app --name api-server
# ✓ Detected project type: Python (requirements.txt + app.py)
# ✓ Detected framework: Flask
# ✓ Selected template: python-base
# ✓ Created sandbox: sb-x7y8z9
# ✓ Uploaded source: 42 files, 1.2MB
# ✓ Installing dependencies: pip install -r requirements.txt
# ✓ Starting service: python app.py
# ✓ Service ready: https://api-server.sandbox.alicloud.com

# Development mode: local file changes auto-sync to sandbox
ebx deploy . --watch
```

**Automatic Project Detection**:

| Signature File | Detected As | Selected Template |
|---------------|-------------|-------------------|
| `package.json` + `next.config` | Next.js | node-web |
| `package.json` + `vite.config` | Vite | node-web |
| `requirements.txt` + `manage.py` | Django | python-base |
| `requirements.txt` + `app.py` | Flask | python-base |
| `go.mod` | Go | go-dev |
| `pom.xml` / `build.gradle` | Java | java-dev |
| `Dockerfile` | Docker | Use directly |
| `sandbox.yaml` | Declarative config | Highest priority |

### 5.4 Core Workflows

#### Workflow 1: Quick Experiment

```bash
ebx create "python data analysis, need pandas and matplotlib"
# → sb-abc123
ebx exec sb-abc123 "python -c 'import pandas; print(pandas.__version__)'"
ebx kill sb-abc123
```

#### Workflow 2: Project Development

```bash
ebx deploy ./my-api --name api-dev --watch --expose 8080
ebx logs api-dev --follow        # Another terminal (⚠️ experimental)
ebx exec api-dev "pytest tests/ -v"
ebx kill api-dev
```

#### Workflow 3: AI Agent Integration

```bash
ebx mcp install --target cursor
ebx create "full-stack development environment" --name agent-env
# AI Agent automatically uses sandbox via MCP
```

#### Workflow 4: Template Customization

```bash
ebx template build ./my-template --name my-ml-env
ebx create --template my-ml-env
ebx template push my-ml-env --tag v1.0
```

### 5.5 AI-Friendly Design Principles

1. **Structured Output** — All commands support `--json`, output strict JSON
2. **Idempotent Operations** — Duplicate creation of same-named sandbox returns existing one, duplicate destruction silently succeeds
3. **Deterministic Exit Codes** — `0` success, `1` general error, `2` parameter error, `3` auth failure, `4` resource not found, `5` timeout, `6` quota exceeded
4. **Non-Interactive Mode** — `--yes` skips confirmations, `--quiet` minimizes output
5. **Composable Pipelines** — `ID=$(ebx create "python" --quiet)` directly gets ID
6. **Self-Describing Help** — Error messages include fix suggestions
7. **Progress Feedback** — Human mode has progress bars, AI mode (`--json`) outputs structured events
8. **Natural Language Tolerance** — Fuzzy descriptions get best-effort inference, failures provide guidance

---

## 6. Session Management ★Enhanced★

### 6.1 Session Concept

A Session is the context for user interaction with a sandbox. A Session binds together a sandbox instance reference, execution history, file state, environment variables, etc., forming a named, recoverable, manageable work unit.

Relationship between Session and Sandbox:
- One Session corresponds to one sandbox instance
- Session is the "client reference" to a sandbox — recording how to find, connect to, and recover a sandbox
- Sandboxes may disappear due to timeout/destruction; Sessions record enough information to rebuild

### 6.2 SDK Automatic Session Management

```python
from easy_sandbox import Sandbox

# SDK automatically tracks sessions
sb = await Sandbox.create(template="python", name="my-work")
# Session automatically created, ID saved to ~/.ebx/sessions/

# Can be resumed directly next time
sb = await Sandbox.connect("my-work")  # Connect by name
sb = await Sandbox.last()              # Connect to most recent session
```

Sessions are transparent in the SDK — users don't need to explicitly manage Sessions; the SDK automatically maintains Session state during `create()` and `connect()`.

> **Enhancement**: `Sandbox.connect()` first verifies with the cloud that the sandbox is still alive, avoiding connection to non-existent sandboxes that would cause state inconsistency.

```python
# View all active sessions
sessions = await Sandbox.sessions.list()
for s in sessions:
    print(f"{s.name}: {s.state} (sandbox={s.sandbox_id})")

# Filter by state
running = await Sandbox.sessions.list(state="running")
```

### 6.3 CLI Session Commands

```bash
# Start a named session (create sandbox + register session)
ebx start my-project
ebx start my-project --template python-data-science --cpu 2

# List all active sessions
ebx sessions list
ebx sessions list --all  # Include disconnected

# Connect to existing session
ebx connect my-project
ebx connect _            # Most recent session (shortcut)

# Session info
ebx sessions info my-project
# ╭─── Session: my-project ──────────────────────╮
# │  Sandbox ID:  sbx-abc123                     │
# │  Template:    python-data-science            │
# │  State:       running                        │
# │  Created:     2026-09-01 10:00:00            │
# │  Last Access: 2026-09-01 15:00:00            │
# │  Ports:       8080, 3000                     │
# ╰──────────────────────────────────────────────╯

# Session operations
ebx sessions rename old-name new-name     # Rename
ebx sessions export my-project            # Export session config (JSON format, shareable)
ebx sessions import session-config.json   # Restore session from config file
ebx sessions clean                        # Clean expired sessions
ebx sessions clean --dry-run              # Preview cleanup
```

> **Note**: `sessions export/import` exports Session configuration information (template, resource specs, environment variables, etc.), not sandbox state snapshots. This ensures that identical sandboxes can be rebuilt from the config in any environment.

### 6.4 Storage Backend (Pluggable Design)

Session metadata storage uses a pluggable design supporting multiple storage backends:

```python
from easy_sandbox.session import (
    SessionStore,          # Abstract base class
    LocalSessionStore,     # Local file (default)
    OSSSessionStore,       # Alibaba Cloud OSS
    DatabaseSessionStore,  # Database (Redis/MySQL)
)

# Default: local file storage
# Session data stored in ~/.ebx/sessions/

# Multi-machine sharing: OSS storage
from easy_sandbox import Config
Config.set(session_store=OSSSessionStore(
    bucket="my-team-sessions",
    prefix="sandbox-sessions/",
))

# Team collaboration: database storage
Config.set(session_store=DatabaseSessionStore(
    url="redis://localhost:6379/0",
    # or url="mysql://user:pass@host/db",
))

# Custom implementation
class MySessionStore(SessionStore):
    async def save(self, session: SessionInfo) -> None: ...
    async def load(self, name: str) -> SessionInfo | None: ...
    async def list(self, **filters) -> list[SessionInfo]: ...
    async def delete(self, name: str) -> None: ...
```

**Concurrency Control**:
- `SessionStore` interface adds optional optimistic locking semantics: `save(session, expected_version=None)`
- `LocalSessionStore`: Uses `filelock` library for file-level locking
- `OSSSessionStore`: Uses OSS conditional writes (If-Match ETag) for optimistic locking
- `DatabaseSessionStore`: Uses database transactions + version field
- GC operations use a "mark then delete" two-phase process to avoid accidentally deleting active Sessions

#### Local Storage Directory Structure (Default)

```
~/.ebx/sessions/
├── my-project.toml          # Session metadata
├── my-project.history       # Command history
└── my-project.env           # Environment variable snapshot
```

**Session TOML Format**:

```toml
# ~/.ebx/sessions/my-project.toml
sandbox_id = "sbx-abc123"
template = "python-data-science"
created_at = "2026-09-01T10:00:00Z"
last_accessed = "2026-09-01T15:00:00Z"
state = "running"            # running / dead
region = "cn-hangzhou"

[resources]
cpu = 2
memory = 4096

[ports]
exposed = [8080, 3000]

[tags]
project = "my-project"
team = "data-science"
```

**Command History** (`.history` file):

```
# ~/.ebx/sessions/my-project.history
2026-09-01T10:00:05Z  pip install pandas numpy
2026-09-01T10:01:00Z  python train.py
2026-09-01T10:15:00Z  python evaluate.py --model /app/model.pkl
```

### 6.5 Lifecycle Configuration

| Config Item | Description | Default |
|-------------|-------------|---------|
| `session_ttl` | Session expiration time | `7d` |
| `auto_cleanup` | Auto-clean expired Sessions | `true` |
| `sync_interval` | Cloud state sync interval | `300s` |
| `on_orphan` | Orphan Session handling strategy | `warn` |

```bash
# Configure session strategy
ebx config set session.session_ttl 7d            # Expire after 7 days
ebx config set session.auto_cleanup true          # Enable auto-cleanup
ebx config set session.sync_interval 300          # Sync cloud state every 300 seconds
ebx config set session.on_orphan warn             # Orphan Sessions: warn/cleanup/ignore
```

**Orphan Session Handling**: When a local Session references a sandbox that no longer exists in the cloud:
- `warn` (default): Mark as dead and prompt on next `sessions list`
- `cleanup`: Automatically delete local Session files
- `ignore`: Take no action

### 6.6 Auto-Management Strategies

| Strategy | Description | Configuration |
|----------|-------------|---------------|
| **Auto-naming** | Uses `sbox-{timestamp}` format when no name specified | Enabled by default |
| **Auto-cleanup** | `ebx sessions clean` cleans dead sessions older than `session_ttl` | `session_ttl = 7d` |
| **Cloud verification** | Verifies sandbox is alive before `connect` | Enabled by default |
| **GC strategy** | Periodically cleans local session files referencing non-existent sandboxes | `sync_interval = 300s` |

**GC Flow**:

```mermaid
flowchart TD
    A["Scheduled trigger / ebx sessions clean"] --> B["Read all Sessions from Session store"]
    B --> C{"Iterate each Session"}
    C --> D["Query remote sandbox status"]
    D --> E{"Sandbox exists?"}
    E -- Does not exist --> F["Mark state = dead"]
    E -- Exists --> H["Update last_checked timestamp"]
    F --> G{"state = dead and past session_ttl?"}
    G -- Yes --> I["Handle per on_orphan strategy"]
    G -- No --> H
    I --> H
    H --> J{"More Sessions?"}
    J -- Yes --> C
    J -- No --> K["Output cleanup report"]
```

### 6.7 Multi-Session Concurrency

```python
import asyncio
from easy_sandbox import Sandbox

# Manage multiple sessions simultaneously
sessions = await Sandbox.sessions.list()
for s in sessions:
    print(f"{s.name}: {s.state}")

# Concurrent task execution
async def run_task(name: str, code: str):
    sb = await Sandbox.connect(name)
    return await sb.run_code(code)

results = await asyncio.gather(
    run_task("worker-1", "process_batch_1()"),
    run_task("worker-2", "process_batch_2()"),
    run_task("worker-3", "process_batch_3()"),
)
```

```bash
# CLI concurrent management
ebx start worker-1 --template python-base
ebx start worker-2 --template python-base
ebx start worker-3 --template python-base

ebx sessions list
#   NAME       TEMPLATE       STATE     CREATED
#   worker-1   python-base    running   2 min ago
#   worker-2   python-base    running   1 min ago
#   worker-3   python-base    running   30s ago

# Batch operations
ebx kill worker-1 worker-2 worker-3
```

---

## 7. Template System

### 7.1 Template Sources (GitHub Tarball API as Core)

The core distribution mechanism is based on the **GitHub tarball API (fetched by tag/branch/sha, no Release required)**, similar to Go modules / GitHub Actions reference style. The SDK resolves template sources in priority order:

```
Template source priority:
1. Built-in templates (Tier 1 templates bundled with SDK)
2. GitHub tarball templates (owner/repo format; GitHub tarball API fetched by tag/branch/sha, no Release needed)
3. Local templates (file paths)
4. Alibaba Cloud ACR images (registry URLs)
```

**Template Name Resolution Rules**:

```python
"python"                → Built-in python template
"code-interpreter"      → Built-in code-interpreter template
"hello/world"           → github.com/hello/world default branch
"hello/world@v1.0"      → github.com/hello/world ref v1.0 (tag/branch/sha)
"./my-template"         → my-template in current directory
"acr://registry.cn-hangzhou.aliyuncs.com/ns/image:tag" → Alibaba Cloud Container Registry
```

> **Security Note**: When pulling templates remotely, the SDK validates the template package checksum (SHA-256) to prevent man-in-the-middle tampering. `ebx template info <template>` shows template checksum info. On checksum validation failure, download is aborted by default with an error; a `--skip-verify` flag is provided for development environments to skip validation.

### 7.2 Official Core Templates

#### Tier 1 — Launch Templates (5)

| Template | Description | Base | Default Resources |
|----------|-------------|------|-------------------|
| `base` | Minimal Linux environment | debian:bookworm-slim | 1C/2G/10G |
| `python-base` | Python development environment | base + pip/venv/poetry | 1C/2G/10G |
| `python-data-science` | Full data science suite | python-base + pandas/numpy/matplotlib/sklearn | 2C/4G/20G |
| `node-web` | Node.js web development | base + node20/npm/yarn/pnpm | 1C/2G/10G |
| `code-interpreter` | Multi-language code interpreter | python-data-science + node/go/rust + Rich Output | 2C/4G/20G |

#### Tier 2 — Extension Templates (5)

| Template | Description | Default Resources |
|----------|-------------|-------------------|
| `browser-automation` | Playwright + Chromium browser automation | 2C/4G/15G |
| `full-stack` | Frontend + backend + PostgreSQL + Redis + Nginx | 4C/8G/30G |
| `go-dev` | Go 1.22 + golangci-lint + dlv + air | 2C/4G/15G |
| `java-dev` | JDK 21 + Maven 3.9 + Gradle 8.x | 2C/4G/20G |
| `ml-gpu` | CUDA 12.1 + PyTorch + TensorFlow | 4C/16G/50G + GPU |

> **Note**: GPU support depends on underlying platform capabilities; the `ml-gpu` template is currently a future plan.

#### Agent Templates (AI CLI Pre-installed)

| Template | Description | Pre-installed Tools | Default Resources |
|----------|-------------|--------------------|--------------------|
| `codex` | Codex CLI Code Agent | OpenAI Codex CLI | 2C/4G/20G |
| `qwen-browser` | Qwen Browser Agent | Qwen CLI + Playwright | 2C/4G/15G |
| `qwen-code` | Qwen Code Agent | Qwen CLI + multi-language runtimes | 2C/4G/20G |

> **Note**: AI CLI tool authentication in Agent templates is pre-configured (injected via sandbox environment variables); users don't need to configure additional API Keys.

### 7.3 Template Specification (template.yaml)

`template.yaml` is the standardized declaration file for templates, defining the complete specification.

```yaml
# template.yaml — Template Specification v1
version: "1"

metadata:
  name: python-data-science
  display_name: "Python Data Science"
  description: "Data analysis environment pre-installed with pandas/numpy/matplotlib"
  version: "1.2.0"
  author: "easy-sandbox"
  tags: ["python", "data-science", "jupyter"]
  category: "data-science"
  checksum: "sha256:a1b2c3..."     # Template package integrity check

base:
  image: "ubuntu:22.04"               # Mutually exclusive with from
  # from: "owner/repo@tag"            # Inherit from another template

build:
  apt_install: [build-essential, libpq-dev]
  pip_install: ["pandas>=2.0", numpy, matplotlib]
  npm_install: [typescript]
  env:
    PYTHONUNBUFFERED: "1"
  run: ["jupyter notebook --generate-config"]
  copy:
    - src: "./config/"
      dest: "/app/config/"

resources:
  cpu: 2
  memory: 4096
  disk: 15360
  gpu: null
  timeout: 600
  idle_timeout: 300

network:
  ports: [8888]
  public: false

sandbox:
  mode: "ephemeral"
  workdir: "/workspace"
  user: "sandbox"
  shell: "/bin/bash"
  readiness_probe:
    type: "tcp"
    port: 8888
    timeout: 30

skills:
  bundled: ["jupyter", "pandas-stack"]
  recommended: ["matplotlib-extra"]

agent:
  description: "Suitable for data analysis, CSV processing, statistical computation, and chart generation"
  triggers: ["data analysis", "pandas", "CSV", "charts"]
  instructions: |
    1. Place data files in /workspace/data/
    2. Place output files in /workspace/output/
    3. When generating charts with matplotlib, save as PNG

healthcheck:
  command: "python3 -c 'import pandas'"
  interval: 30
  timeout: 5
  retries: 3
```

### 7.4 Custom Templates

**Method 1: SDK Programmatic**

```python
from easy_sandbox import Image

image = (
    Image.from_template("python-base")
    .pip_install("flask", "sqlalchemy", "celery")
    .apt_install("postgresql-client", "redis-tools")
    .copy_local("./config/", "/app/config/")
    .env(FLASK_ENV="production")
    .expose(5000, 6379)
    .entrypoint("python /app/main.py")
)

template_id = await image.build_and_push(name="my-flask-app", tag="v1.0")
```

**Method 2: CLI + Dockerfile**

```bash
ebx template build . --name my-flask-app --tag v1.0
ebx template push my-flask-app:v1.0
```

**Method 3: sandbox.yaml Declarative**

```yaml
name: my-flask-app
version: "1.0"
base: python-base
packages:
  pip: [flask==3.0, sqlalchemy==2.0, celery==5.3]
  apt: [postgresql-client, redis-tools]
env:
  FLASK_ENV: production
ports: [5000, 6379]
resources: {cpu: 2, memory: 4096}
entrypoint: python /app/main.py
```

**Method 4: Publish to GitHub (fetched by tag/branch/sha, no Release needed)**

```bash
ebx template init my-template          # Initialize scaffolding
ebx create ./my-template               # Local testing
cd my-template && git tag v1.0.0
git push origin v1.0.0                 # Push git tag, no Release needed
# Others: ebx create yourname/my-template (default branch) or ebx create yourname/my-template@v1.0.0
```

### 7.5 Template Cache Management

```
~/.ebx/templates/
├── hello/
│   └── world/
│       ├── v1.0.0/
│       │   ├── template.yaml
│       │   └── Dockerfile
│       └── v1.2.0/
│           └── ...
└── myorg/
    └── python-ml/
        └── latest/
```

```bash
ebx template cache list                      # View cache
ebx template cache clean                     # Clean all cache
ebx template cache clean hello/world         # Clean specific
ebx create hello/world --no-cache            # Skip cache
```


---

## 8. Skills System

### 8.1 Skill Definition and Structure

Skills are Easy Sandbox's reusable capability packages, encapsulating "sandbox environment configuration + Agent usage instructions + MCP Tools extensions" into a distributable unit.

```
Skill = Sandbox Environment Config + Agent Usage Instructions + MCP Tools Extensions
        ─────────────────────────   ──────────────────────────   ───────────────────
        sandbox.yaml                 SKILL.md                     mcp-tools.json
        Dockerfile                   (structured document)        (tool definitions)
        scripts/
```

**Skill Directory Structure**:

```
my-skill/
├── SKILL.md              # Skill documentation (AI-readable)
├── sandbox.yaml          # Sandbox environment config
├── Dockerfile            # Optional: custom image
├── scripts/              # Optional: tool scripts
│   ├── setup.sh
│   └── tools/
│       ├── analyze.py
│       └── visualize.py
├── mcp-tools.json        # Optional: MCP tool definitions
├── examples/             # Usage examples
├── tests/                # Tests
└── skill.lock            # Dependency lock (auto-generated)
```

### 8.2 Category System

| Category | Skills | Description |
|----------|--------|-------------|
| **Language Runtimes** | `python-base`, `node-base`, `go-base`, `java-base`, `rust-base` | Basic development environments |
| **Data Science** | `data-analysis`, `ml-sklearn`, `ml-pytorch`, `ml-tensorflow`, `jupyter` | Data analysis and machine learning |
| **Web Development** | `nextjs`, `vue`, `flask-api`, `fastapi`, `express` | Frontend and backend frameworks |
| **Browser Automation** | `playwright`, `puppeteer`, `web-scraper`, `screenshot` | Scraping and automation |
| **AI/ML** | `llm-inference`, `embedding`, `image-gen`, `speech`, `ocr` | AI capabilities |
| **Database** | `postgres`, `mysql`, `redis`, `sqlite`, `mongodb` | Data storage |
| **DevOps** | `docker-in-sandbox`, `k8s-tools`, `terraform`, `ansible` | Operations tools |
| **Security** | `code-audit`, `pentest`, `vulnerability-scan` | Security auditing |

### 8.3 CLI Commands

```bash
# Search Skills
ebx skill search "data science"
ebx skill search python --category ai-ml

# Install Skill
ebx skill install data-analysis                     # Install to project
ebx skill install data-analysis --global            # Install globally
ebx skill install data-analysis --target cursor     # Install to Cursor
ebx skill install data-analysis@1.2.0               # Specific version
ebx skill install https://github.com/user/my-skill  # Install from Git
ebx skill install ./my-local-skill --link           # Local development mode

# List installed
ebx skill list
ebx skill list --target cursor

# Create and publish
ebx skill create my-awesome-skill
ebx skill publish ./my-skill
ebx skill publish ./my-skill --dry-run
```

### 8.4 Installation Targets

| Target | Command | Effect |
|--------|---------|--------|
| Project | `--scope project` | Writes to `sandbox.yaml`, project-level |
| Global | `--global` | Writes to `~/.ebx/skills/`, global |
| Cursor | `--target cursor` | Writes to Cursor MCP config |
| Claude Desktop | `--target claude` | Writes to Claude Desktop config |
| VS Code | `--target vscode` | Writes to VS Code settings |
| Qoder | `--target qoder` | Writes to Qoder config |

### 8.5 Integration with MCP/Agent

When an AI Agent connects to Easy Sandbox via MCP, installed Skills are automatically registered as MCP Tools:

```
Agent (Cursor/Claude)
  │
  ▼
MCP Server
  │
  ├── Built-in Tools (create_sandbox, run_code, ...)
  │
  └── Skill Tools (auto-registered)
      ├── data-analysis → analyze_data(), create_chart()
      ├── playwright   → browse_url(), screenshot()
      └── code-audit   → audit_code(), scan_vulnerabilities()
```

---

## 9. MCP Server

### 9.1 Tools Definition

#### P0 — Core Tools (7)

| Tool Name | Description | Key Parameters |
|-----------|-------------|----------------|
| `create_sandbox` | Create sandbox (natural language support) | `description`, `template`, `timeout` |
| `run_code` | Execute code | `code`, `language`, `sandbox_id`, `timeout` |
| `run_command` | Execute shell command | `command`, `sandbox_id`, `cwd` |
| `read_file` | Read file | `path`, `sandbox_id` |
| `write_file` | Write file | `path`, `content`, `sandbox_id` |
| `list_files` | List directory | `path`, `sandbox_id` |
| `kill_sandbox` | Destroy sandbox | `sandbox_id` |

#### P1 — Extension Tools (6)

| Tool Name | Description |
|-----------|-------------|
| `upload_file` | Upload local file to sandbox |
| `download_file` | Download file from sandbox |
| `list_sandboxes` | List all active sandboxes |
| `sandbox_info` | Get sandbox details |
| `get_url` | Get public URL for sandbox port |
| `install_packages` | Install packages (pip/npm/apt) |

#### P2 — Advanced Tools (3)

| Tool Name | Description |
|-----------|-------------|
| `agent_code` | Invoke sandbox AI CLI for code tasks |
| `agent_browse` | Invoke sandbox AI CLI for browser tasks |
| `deploy_project` | Deploy project to sandbox |

#### 🔮 Future Plan Tools

| Tool Name | Description | Notes |
|-----------|-------------|-------|
| `snapshot_sandbox` | Create sandbox snapshot | Pending platform Snapshot capability |
| `hibernate_sandbox` | Hibernate sandbox | Pending platform hibernation capability |
| `wake_sandbox` | Wake hibernated sandbox | Pending platform hibernation capability |

### 9.2 Session Binding

MCP Server introduces the "default sandbox" concept:

1. On first call to any tool requiring a sandbox, if `sandbox_id` is not specified, a default sandbox is auto-created
2. Default sandbox uses the `code-interpreter` template
3. Subsequent calls automatically reuse the default sandbox
4. Default sandbox is auto-destroyed when the session ends

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant MCP as MCP Server
    participant SB1 as "Default Sandbox sb-001"
    participant SB2 as "New Sandbox sb-002"

    Note over Client,MCP: Session starts
    Client->>MCP: run_code("print(1)")
    MCP->>SB1: Auto-create default sandbox
    SB1-->>Client: Execution result
    Client->>MCP: run_code("print(2)")
    MCP->>SB1: Reuse default sandbox
    SB1-->>Client: Execution result
    Client->>MCP: create_sandbox(template=...)
    MCP->>SB2: Create new sandbox
    Client->>MCP: run_code("...", sandbox=002)
    MCP->>SB2: Use specified sandbox
    SB2-->>Client: Execution result
    Client->>MCP: run_code("print(3)")
    MCP->>SB1: Still use default sandbox
    SB1-->>Client: Execution result
    Note over Client,MCP: Session ends
    MCP->>SB1: Auto-destroy default sandbox
```

**Transport Methods**:

| Method | Use Case | Startup |
|--------|----------|---------|
| STDIO | Local IDE (Cursor/Claude/VS Code) | Auto-started by IDE config |
| HTTP + SSE | Remote service, multi-client sharing | `ebx mcp start --transport http --port 8765` |

> **⚠️ Security Requirement**: HTTP transport mode must configure Bearer Token authentication. Set via `--auth-token` parameter or `SANDBOX_MCP_AUTH_TOKEN` environment variable. STDIO mode runs locally and does not require additional authentication.

### 9.3 Installation Methods

```bash
# One-click install to IDE
ebx mcp install --target cursor
ebx mcp install --target claude
ebx mcp install --target vscode
ebx mcp install --target qoder

# Install with specific Skills
ebx mcp install --target cursor --skills data-analysis,playwright
```

**Generated Config Example** (Cursor):

```json
{
  "mcpServers": {
    "easy-sandbox": {
      "command": "ebx",
      "args": ["mcp", "start"],
      "env": {
        "SANDBOX_API_KEY": "your-api-key"
      }
    }
  }
}
```

---

## 10. Built-in Agents

### 10.1 Design Philosophy

Built-in Agents use a **minimal architecture**: sandbox templates pre-install AI CLI tools (Codex, Qwen CLI, etc.), and the SDK Agent API is just syntactic sugar wrapping `commands.run()`.

**Core Advantages**:
- **SDK has zero LLM dependencies**: Stays lightweight, no LLM client libraries introduced
- **No additional API Keys needed**: AI tool authentication is pre-configured in sandbox templates
- **Hot-updatable**: Upgrade AI CLI version in templates to gain new capabilities without SDK upgrades
- **User choice**: Codex template / Qwen template / custom template, flexible switching

### 10.2 Agent Types and Implementation Mapping

| Agent Method | Actual Execution | Template Used |
|-------------|-----------------|---------------|
| `sb.agent.code("fix bug")` | `sb.commands.run("codex 'fix bug'")` | `codex` |
| `sb.agent.browse("open Baidu")` | `sb.commands.run("qwen-cli browse 'open Baidu'")` | `qwen-browser` |
| `sb.agent.shell("install nginx")` | `sb.commands.run("codex 'install nginx and configure'")` | `codex` |
| `sb.agent.analyze("analyze data")` | `sb.commands.run("qwen-cli analyze 'analyze data'")` | `qwen-code` |

### 10.3 Usage Examples

```python
from easy_sandbox import Sandbox

# === Code Agent ===
sb = await Sandbox.create(template="codex")
result = await sb.agent.code("Analyze complexity of this code and suggest optimizations", context={"file": "/app/main.py"})
print(result.output)

# === Browser Agent ===
sb = await Sandbox.create(template="qwen-browser")
result = await sb.agent.browse("Visit https://example.com and take a screenshot of the homepage")
print(result.output)

# === Shell Automation ===
sb = await Sandbox.create(template="codex")
result = await sb.agent.shell("Install nginx and configure reverse proxy to port 8080")
print(result.output)

# === Data Analysis ===
sb = await Sandbox.create(template="qwen-code")
await sb.files.write("/app/data.csv", csv_content)
result = await sb.agent.analyze("Perform trend analysis on this CSV and generate charts")
print(result.output)
```

### 10.4 AgentModule SDK API

```python
class AgentModule:
    """Agent syntactic sugar — underlying calls to commands.run()"""

    async def code(self, task: str, *, context: dict | None = None, timeout: int = 120) -> AgentResult:
        """Code analysis/generation/fix"""
        cmd = self._build_command("code", task, context)
        return await self._execute(cmd, timeout)

    async def browse(self, task: str, *, timeout: int = 120) -> AgentResult:
        """Browser automation"""
        cmd = self._build_command("browse", task)
        return await self._execute(cmd, timeout)

    async def shell(self, task: str, *, timeout: int = 120) -> AgentResult:
        """Shell automation"""
        cmd = self._build_command("shell", task)
        return await self._execute(cmd, timeout)

    async def analyze(self, task: str, *, timeout: int = 120) -> AgentResult:
        """Data analysis"""
        cmd = self._build_command("analyze", task)
        return await self._execute(cmd, timeout)

    def _build_command(self, action: str, task: str, context: dict | None = None) -> str:
        """Build CLI command based on template type

        ⚠️ Security requirement: prevent command injection
        - All user input must be escaped via shlex.quote() before concatenation
        - Or use argument list mode (not shell string) to pass to commands.run()
        """
        import shlex
        # Determine codex / qwen-cli / other based on sandbox template
        # Example: sb.commands.run(f"codex {shlex.quote(task)}")
        # Not: sb.commands.run(f"codex '{task}'")  ← injection risk
        ...

    async def _execute(self, cmd: str, timeout: int) -> AgentResult:
        """Execute command and parse result"""
        result = await self._sandbox.commands.run(cmd, timeout=timeout)
        return AgentResult(output=result.stdout, exit_code=result.exit_code)
```

### 10.5 Natural Language Inference (Simplified Implementation)

Natural language sandbox creation inference logic is no longer implemented by an internal SDK InferAgent, but via external calls:

```mermaid
flowchart TD
    A["Natural language description"] --> B{"Server-side AI inference endpoint"}
    B -- Available --> P["SandboxPlan(template, cpu, memory, gpu, confidence, reasoning)"]
    B -- Unavailable/timeout --> C{"Local Qwen CLI / DashScope API"}
    C -- Available --> P
    C -- Unavailable/timeout --> D["Keyword rule matching (fully offline)"]
    D --> P
```

**Rule Matching Examples** (offline fallback):

| Keywords | Inferred Template | Inferred Resources |
|----------|------------------|--------------------|
| python, pandas, data analysis, CSV | python-data-science | 2C/4G |
| node, web, frontend, react, vue | node-web | 1C/2G |
| playwright, browser, scraping, screenshot | browser-automation | 2C/4G |
| GPU, CUDA, tensorflow, pytorch | ml-gpu | 4C/16G+GPU |
| codex, code generation, fix bug | codex | 2C/4G |

---

## 11. Agent Framework Integration

### Tool Schema Export

Sandbox operation tools follow OpenAI function calling format and can be directly exported as Tool Schemas for LangChain / CrewAI / AutoGen and other frameworks:

```python
from easy_sandbox.agent import get_tool_schema

# Export as OpenAI format
tools = get_tool_schema(format="openai")

# Export as LangChain format
tools = get_tool_schema(format="langchain")
```

### LangChain Adapter

```python
from easy_sandbox.integrations import LangChainToolkit

toolkit = LangChainToolkit(sandbox_config={"template": "code-interpreter"})
tools = toolkit.get_tools()

# Use in LangChain Agent
from langchain.agents import AgentExecutor
agent = AgentExecutor(tools=tools, llm=llm)
```

### CrewAI Adapter

```python
from easy_sandbox.integrations import CrewAIToolkit

toolkit = CrewAIToolkit()
tools = toolkit.get_tools()
```

> **Note**: The framework integration layer only exports Tool Schemas and provides adapters; it does not include LLM Provider adaptation. LLM selection and configuration are handled by users in their respective Agent frameworks.

---

## 12. Technology Stack

| Domain | Choice | Rationale |
|--------|--------|-----------|
| HTTP Client | `httpx` | Native async support, HTTP/2, core for E2B compatible protocol implementation |
| WebSocket | `websockets` | Mature and stable, async native, used for PTY/streaming scenarios |
| CLI Framework | `click` + `rich` | Rich UI components, tables/progress bars |
| Serialization | `cloudpickle` + `msgpack` | Python object serialization + high-performance binary |
| Config Management | `pydantic` | Type-safe configuration validation |
| Testing | `pytest` + `pytest-asyncio` | Standard async testing solution |
| Package Management | `hatch` / `pdm` | Modern Python project management |

> **Note**: No dependency on `e2b` SDK. L2 Core Protocol layer self-implements E2B compatible protocol, built directly on httpx + websockets.

---

## 13. Project Structure

```
src/easy_sandbox/
├── __init__.py                    # Top-level exports: Sandbox, Image, sandbox
├── _version.py                    # Version number
│
├── transport/                     # L1 — Transport & Auth Layer
│   ├── __init__.py
│   ├── http.py                    #   httpx HTTPS client, connection pool
│   ├── ws.py                      #   websockets long connections, heartbeat keep-alive
│   ├── auth.py                    #   API Key auth + AK/SK exchange
│   └── config.py                  #   Config loading (code params → env vars → .env → config.toml → defaults)
│
├── protocol/                      # L2 — Core Protocol Layer (self-implemented E2B compatible)
│   ├── __init__.py
│   ├── sandbox.py                 #   Sandbox lifecycle API (HTTP REST)
│   ├── process.py                 #   Remote process management (HTTP + WebSocket streaming)
│   ├── filesystem.py              #   Remote filesystem operations (HTTP REST)
│   ├── terminal.py                #   PTY terminal multiplexing (WebSocket)
│   └── port.py                    #   Port forwarding management (HTTP REST)
│
├── extensions/                    # L3 — Alibaba Cloud Extension Layer
│   ├── __init__.py
│   ├── vpc.py                     #   VPC network configuration
│   ├── oss.py                     #   OSS mount and file sync
│   ├── domain.py                  #   Custom domain binding
│   ├── nas.py                     #   NAS filesystem mount
│   └── log.py                     #   SLS log integration
│
├── api/                           # L4 — High-Level API
│   ├── __init__.py
│   ├── sandbox.py                 #   Sandbox core class
│   ├── pool.py                    #   SandboxPool
│   ├── image.py                   #   Image chained builder
│   ├── files.py                   #   High-level file operations
│   ├── code.py                    #   Code execution engine
│   └── session.py                 #   Session management
│
├── declarative/                   # L5 — Declarative API Layer
│   ├── __init__.py
│   ├── decorator.py               #   @sandbox decorator
│   ├── config.py                  #   sandbox.yaml parsing
│   ├── serializer.py              #   Parameter serialization
│   └── scheduler.py               #   Task scheduling
│
├── agent/                         # L6 — AI Integration Layer (lightweight wrappers)
│   ├── __init__.py
│   ├── builtin.py                 #   AgentModule — commands.run() syntactic sugar
│   ├── tools.py                   #   Agent tool set (OpenAI function calling format)
│   ├── infer.py                   #   Natural language inference (external calls to Server/Qwen CLI/rule matching)
│   └── mcp.py                     #   MCP Server implementation
│
├── session/                       # Session storage backends
│   ├── __init__.py
│   ├── base.py                    #   SessionStore abstract base class
│   ├── local.py                   #   LocalSessionStore — local files
│   ├── oss.py                     #   OSSSessionStore — Alibaba Cloud OSS
│   └── database.py                #   DatabaseSessionStore — Redis/MySQL
│
├── compat/                        # E2B migration helper layer (not transparent compat, requires async call adjustment)
│   ├── __init__.py                #   from easy_sandbox.compat import Sandbox
│   └── sandbox.py                 #   E2B compatible Sandbox wrapper
│
├── integrations/                  # Agent framework integration
│   ├── __init__.py
│   ├── langchain.py               #   LangChain adapter
│   ├── crewai.py                  #   CrewAI adapter
│   └── autogen.py                 #   AutoGen adapter
│
├── cli/                           # CLI command-line tool
│   ├── __init__.py
│   ├── main.py                    #   CLI entry point (ebx command)
│   ├── commands/                  #   Subcommand implementations
│   │   ├── sandbox.py             #     create/list/kill/...
│   │   ├── session.py             #     sessions/start/connect
│   │   ├── template.py            #     template build/push/list/...
│   │   ├── skill.py               #     skill search/install/...
│   │   ├── secret.py              #     secret create/list/delete/inject
│   │   ├── mcp.py                 #     mcp install/start/...
│   │   └── deploy.py              #     build/deploy
│   └── formatters.py              #   Output formatting (table/json/quiet)
│
├── models/                        # Data models
│   ├── __init__.py
│   ├── sandbox.py                 #   SandboxInfo, SandboxConfig
│   ├── session.py                 #   SessionInfo, SessionConfig
│   ├── process.py                 #   ProcessResult, ProcessConfig
│   ├── filesystem.py              #   FileInfo, WatchEvent
│   └── errors.py                  #   Exception class hierarchy
│
└── utils/                         # Utility functions
    ├── __init__.py
    ├── retry.py                   #   Retry strategies
    ├── logging.py                 #   Logging utilities
    └── keychain.py                #   System Keychain integration (macOS/Linux)
```

---

## 14. Phased Roadmap

```mermaid
graph LR
    P1["Phase 1 MVP\n6 weeks\nCore SDK / CLI basic commands\nEphemeral sandbox / E2B compat protocol\nSession basics / Tier 1 templates"]
    P2["Phase 2 Enhancement\n6 weeks\nFC Extensions / MCP Server\nNatural language creation / Full Sessions\nSandbox pool / Tier 2 templates"]
    P3["Phase 3 Ecosystem\n8 weeks\nSkills system / Agent template integration\nTemplate marketplace / Project deployment\nCommunity ecosystem / Agent templates"]
    P4["Phase 4 Advanced\nOngoing\nGPU support / Enterprise features\nPersistent/Hibernated sandbox / Snapshot\nMulti-region / Web Console"]
    P1 --> P2 --> P3 --> P4
```

### Phase 1 — MVP (6 Weeks)

**Goal**: Usable core SDK + CLI, supporting ephemeral sandboxes, E2B compatible protocol.

| Week | Deliverables |
|------|-------------|
| 1-2 | L1 Transport & Auth (API Key + AK/SK dual auth), L2 Core Protocol minimal subset (Sandbox lifecycle + Process run + Filesystem read/write, ~8-10 endpoints), project scaffolding, CI/CD |
| 3-4 | L2 complete protocol implementation (remaining endpoints), `Sandbox.create()`, `kill()`, `run_code()`, `commands.*`, `files.*`, Context Manager, sync API |
| 5-6 | CLI `ebx create/exec/list/kill/shell`, Tier 1 templates ×5, Session basic management, E2B migration helper layer, PyPI release, documentation site |

**Milestone**:

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(template="code-interpreter") as sb:
    result = await sb.run_code("import pandas as pd; print(pd.__version__)")
    print(result.text)
```

### Phase 2 — Enhancement (6 Weeks)

**Goal**: MCP Server, natural language creation, complete Session management, FC Extensions.

| Week | Deliverables |
|------|-------------|
| 7-8 | VPC/OSS/Domain Extensions, SandboxPool, Image builder |
| 9-10 | Session complete features (pluggable storage, lifecycle management), Secret management |
| 11-12 | MCP Server P0 Tools, STDIO transport, `ebx mcp install`, natural language creation (three-level fallback), Tier 2 ×3 |

**Milestone**:

```bash
ebx create "run Python data analysis, need pandas"
ebx mcp install --target cursor
ebx start my-project
ebx sessions list
```

### Phase 3 — Ecosystem (8 Weeks)

**Goal**: Skills system, Agent template integration, template marketplace, direct project deployment.

| Week | Deliverables |
|------|-------------|
| 13-15 | Skill specification, `ebx skill` CLI, official Skills ×10, installation targets, Skill Registry |
| 16-17 | `@sandbox` decorator, Agent templates (codex/qwen-browser/qwen-code), AgentModule SDK API |
| 18-20 | Template marketplace, `ebx build/deploy`, hot reload, MCP P1 Tools, HTTP+SSE (with Bearer Token auth), Tier 2 completion |

### Phase 4 — Advanced (Ongoing)

| Deliverable | Expected Timeline |
|-------------|-------------------|
| GPU templates (A10/V100/A100) | Week 21-22 |
| Persistent sandbox 🔮 (pending platform support) | Week 23-24 |
| Hibernate/Snapshot 🔮 (pending platform support) | Week 25-26 |
| Enterprise SSO (SAML/OIDC) | Week 27-28 |
| Multi-region (cn-shanghai, cn-shenzhen) | Week 29-30 |
| Audit logs + team management | Week 31-32 |
| MCP P2 Tools + NAS mount | Week 33-34 |
| Web Console | Week 35-38 |
| Terraform Provider | Week 39-40 |

### Key Metrics

| Metric | Phase 1 | Phase 2 | Phase 3 |
|--------|---------|---------|---------|
| SDK downloads | 1,000/month | 5,000/month | 20,000/month |
| MCP installs | — | 500 | 3,000 |
| Skills count | — | — | 30+ |
| Community templates | — | — | 20+ |
| Sandbox creations | 10,000/month | 50,000/month | 200,000/month |
| P95 cold start | < 3s | < 2s | < 1.5s |
| API availability | 99.5% | 99.9% | 99.95% |

---

## 15. Secrets Management

### 15.1 Design Overview

Secrets management provides a secure storage and injection mechanism for sensitive information, avoiding plaintext storage of API Keys, database passwords, and other sensitive data in code and configuration files.

### 15.2 Storage Methods

| Storage Method | Security Level | Scenario |
|----------------|---------------|----------|
| **System Keychain** (recommended) | High | macOS Keychain / Linux Secret Service, local development |
| **Encrypted file** | Medium | `~/.ebx/secrets.enc` (AES-256 encrypted, requires master password) |
| **Environment variables** | Low | CI/CD scenarios, injected via `SANDBOX_SECRET_*` prefix |

### 15.3 CLI Commands

```bash
# Create Secret
ebx secret create DB_PASSWORD "my-secret-password"
ebx secret create API_KEY "sk-xxx" --store keychain

# List Secrets (shows names only, not values)
ebx secret list
#   NAME          STORE      CREATED
#   DB_PASSWORD   keychain   2 days ago
#   API_KEY       keychain   1 hour ago

# Delete Secret
ebx secret delete DB_PASSWORD

# Inject Secrets into sandbox
ebx secret inject sb-abc123 --names DB_PASSWORD,API_KEY
```

### 15.4 SDK Integration

```python
from easy_sandbox import Sandbox

# Inject Secrets when creating sandbox
sb = await Sandbox.create(
    template="python-base",
    secrets=["DB_PASSWORD", "API_KEY"],  # Read from Secrets store and inject
)

# Access via environment variables inside sandbox
result = await sb.commands.run("echo $DB_PASSWORD")
```

---

## 16. Rejected Alternatives

| Alternative | Rejection Reason |
|-------------|-----------------|
| Self-hosted template Registry (similar to npm registry) | High operational cost; GitHub tarball API (fetch by tag/branch/sha, no Release needed) is a zero-ops solution familiar to the community |
| CLI command using `sandbox` (full name) | Too long, low efficiency for daily use |
| CLI command using `ss` (two letters) | High collision risk with system commands/common abbreviations; `ebx` is semantically clearer |
| Template building via Dockerfile only | Not declarative enough; chained Image API + template.yaml is more user-friendly |
| No E2B API compatibility | Abandoning the E2B ecosystem would lose potential users; compatibility first |
| Wrapping E2B SDK as L2 core implementation | Introduces unnecessary dependencies and version coupling; self-implementing the protocol is more controllable |
| Claiming "zero-modification migration" to replace E2B SDK | Unclear product positioning; should emphasize unique value rather than replacing competitors |
| SDK built-in LLM Provider adapters (OpenAI/Anthropic/Qwen) | Increases package size and dependency complexity; Agent capability changed to pre-installed CLI tools in sandbox templates |
| Complex Agent orchestration (AgentChain/FanOut/DAG) | Over-engineering; 90% of scenarios only need a single Agent |
| Storing Session info in the cloud | Increases server-side complexity and latency; changed to pluggable design (local/OSS/database) |
| Using gRPC instead of WebSocket | Poor browser compatibility; WebSocket is more universal |

---

## 17. Future Vision

### `ebx start <anything>` — Cloud Universal Launcher

The ultimate form of Easy Sandbox: **one command to start anything**.

```bash
# Start applications
ebx start openclaw              # Start an application named openclaw
ebx start redis                 # Start a Redis instance
ebx start jupyter               # Start Jupyter Notebook
ebx start postgres              # Start a PostgreSQL database
ebx start nginx                 # Start an Nginx server

# Natural language startup
ebx start "I need an ML training environment"
ebx start "Help me set up a Flask + Redis + PostgreSQL backend"
ebx start "Run this GitHub repo: https://github.com/user/repo"

# Everything is Serverless
# - Created on demand, billed per second
# - No need to worry about servers, containers, images
# - Use and go, or hibernate and wait for next wake-up
```

**Vision**: Developers no longer need to understand Docker, Kubernetes, or cloud servers. They just need to tell `ebx` what they want, and Easy Sandbox takes care of running everything. From a code snippet to a complete distributed application, from a temporary experiment to a long-running service — everything is `ebx start`.
