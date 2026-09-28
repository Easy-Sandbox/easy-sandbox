# 沙箱环境变量指南

本指南说明环境变量在 Easy Sandbox 中的工作方式，涵盖两种独立的进程作用域、注入方法、直接执行（direct-exec）语义以及推荐实践。

> **设计决策：** SDK 不提供 `sandbox.set_env()` API。envd 进程树和 SandboxServer 的 `os.environ` 是两个独立且不可统一的作用域，提供单一的"设置环境变量"抽象会造成误导。请使用下文描述的作用域特定注入方法。

---

## 两种进程作用域

每个沙箱容器内部有**两棵独立的进程树**，各自拥有独立的环境变量：

```text
┌─────────────────────────────────────────────────────┐
│                     沙箱容器                          │
│                                                      │
│  ┌────────────────────┐   ┌───────────────────────┐  │
│  │  envd（PID 1）     │   │  SandboxServer        │  │
│  │  ├─ commands.run() │   │ （可选，端口 9000）    │  │
│  │  ├─ run_code()     │   │  ├─ GET/POST /env     │  │
│  │  └─ 终端 PTY       │   │  ├─ POST /commands/*  │  │
│  │                     │   │  └─ 子进程            │  │
│  └────────────────────┘   └───────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

| 作用域 | 进程所有者 | 环境变量传播方式 |
|--------|-----------|----------------|
| **envd 作用域** | `envd` 守护进程（PID 1） | 变量在沙箱创建时设置或按调用传递；通过 `commands.run()`、`run_code()` 或 PTY 终端启动的所有进程均从 envd 继承。 |
| **Server 作用域** | `SandboxServer` Python 进程 | `POST /env` 修改 Server 进程的 `os.environ`；仅由 Server 派生的子进程（如 `POST /commands/{name}` 处理器）继承这些变更。 |

**关键边界：** SandboxServer 上的 `POST /env` **不会**影响通过 SDK 的 `commands.run()` 或 `run_code()` 启动的进程——这些进程经由 envd 启动，拥有独立的环境。两个作用域完全隔离。

---

## envd 作用域 — SDK 与 CLI 注入

### 创建时注入

创建时传入的变量会注入到 envd 根进程，被**所有**后续命令继承：

**SDK：**

```python
sandbox = await Sandbox.create(
    template="base",
    envs={"DATABASE_URL": "postgres://...", "APP_ENV": "staging"},
)
```

**CLI：**

```bash
ebx create --template base --env DATABASE_URL=postgres://... --env APP_ENV=staging
```

**`@sandbox` 装饰器：**

```python
@sandbox(template="base", envs={"DATABASE_URL": "postgres://..."})
def my_task():
    import os
    return os.environ["DATABASE_URL"]
```

### 按调用覆盖

每次执行调用可传入额外的环境变量，**仅对该次调用生效**：

```python
# commands.run — 使用 `env=`（单数，dict）
result = await sandbox.commands.run(
    "printenv MY_VAR",
    env={"MY_VAR": "hello"},
)

# run_code — 使用 `envs=`（复数，dict）
result = await sandbox.run_code(
    "import os; print(os.environ['MY_VAR'])",
    envs={"MY_VAR": "hello"},
)
```

> **注意参数命名差异：** `commands.run()` 使用 `env=`（单数）；`run_code()` 使用 `envs=`（复数）。这遵循 E2B 兼容约定。

### 通过 `sandbox.run()` 快捷调用

`sandbox.run()` 是 `sandbox.commands.run()` 的顶层快捷方式：

```python
result = await sandbox.run("printenv MY_VAR", env={"MY_VAR": "hello"})
```

---

## 直接执行语义

通过 envd 发送的命令默认以 **直接 `exec`** 方式执行。但 `commands.run()`、`commands.stream()` 和 `commands.start()` 会**自动检测未加引号的 shell 运算符**（`|`、`;`、`&&`、`||`、`>`、`<`、`(...)`、`$(...)`）并透明地将命令包裹在 `sh -c` 中。

### 自动 Shell 运算符包裹

管道、重定向、分号和逻辑运算符现在**无需**手动使用 `sh -c` 即可工作：

```python
# ✅ 可用 — 管道被自动检测并包裹
result = await sandbox.run("ls /tmp | grep log")

# ✅ 可用 — 重定向被自动检测并包裹
result = await sandbox.run("echo hello > /tmp/hello.txt")

# ✅ 可用 — && 被自动检测并包裹
result = await sandbox.run("cd /app && python main.py")

# ✅ 可用 — 分号被自动检测并包裹
result = await sandbox.run("mkdir -p /tmp/out; cp file.txt /tmp/out/")
```

### 变量展开仍需手动包裹

Shell 变量展开（`$VAR`、`${VAR}`）**不会**被自动检测，因为 `$` 不是 shell 运算符字符。需要显式使用 `sh -c`：

```python
# ❌ 错误 — $HOME 作为字面字符串传递（不会触发自动包裹）
result = await sandbox.run("echo $HOME")
# stdout: "$HOME"（字面值）

# ✅ 正确 — 使用 sh -c 进行变量展开
result = await sandbox.run("sh -c 'echo $HOME'")
# stdout: "/root"

# ✅ 正确 — 使用 printenv 读取单个变量
result = await sandbox.run("printenv HOME")
# stdout: "/root"
```

### 通配符展开仍需手动包裹

```python
# ❌ 错误 — * 作为字面字符传递（不会触发自动包裹）
result = await sandbox.run("ls *.py")

# ✅ 正确
result = await sandbox.run("sh -c 'ls *.py'")
```

### 经验法则

**自动包裹**（无需手动使用 `sh -c`）：
- 管道（`|`）
- 重定向（`>`、`>>`、`<`）
- 逻辑运算符（`&&`、`||`）
- 命令分隔符（`;`）
- 子 shell（`(...)`）
- 命令替换（`$(...)`）

**仍需显式使用 `sh -c '...'`**：
- 变量展开（`$VAR`、`${VAR}`）
- 反引号替换（`` `cmd` ``）
- 通配符（`*`、`?`、`[...]`）

如果只需**读取**单个环境变量的值，推荐使用 `printenv VAR`——更简单且避免 shell 引号问题。

---

## Server 作用域 — `GET/POST /env`

当沙箱内运行了 `SandboxServer`（通常监听端口 9000）时，`/env` 端点管理的是 **Server 进程的** `os.environ`：

### 读取变量

```python
import httpx

url = sandbox.network.get_url(9000)
headers = sandbox.network.get_access_headers()

resp = httpx.get(f"{url}/env", headers=headers)
print(resp.json()["variables"])
# 仅返回非敏感变量（名称中包含 TOKEN、SECRET、KEY、
# PASSWORD、CREDENTIAL 的变量会被隐藏）
```

### 设置变量

```python
resp = httpx.post(
    f"{url}/env",
    headers={**headers, "Content-Type": "application/json"},
    json={"vars": {"MY_CONFIG": "new_value"}},
)
print(resp.json()["updated"])  # ["MY_CONFIG"]
```

### Server 作用域边界

- `POST /env` **仅**修改 SandboxServer 进程的 `os.environ`。
- 由 Server 派生的子进程（如通过 `POST /commands/{name}` 执行的自定义命令处理器）会继承这些变更。
- 通过 `commands.run()`、`run_code()` 或 PTY 终端启动的进程**不受影响**——它们在 envd 下运行，拥有独立的环境。

### 受保护变量

Server 拒绝覆写以下变量：

- 系统变量：`PATH`、`HOME`、`USER`、`SHELL`
- SDK 内部变量：任何以 `EBX_` 开头的变量（包括 `EBX_SERVER_TOKEN`）

---

## 推荐模式

### 模式 1：创建时注入（最常用）

适用于需要在整个沙箱生命周期内可用的变量：

```python
sandbox = await Sandbox.create(
    template="base",
    envs={
        "DATABASE_URL": db_url,
        "API_KEY": api_key,
        "APP_ENV": "production",
    },
)

# 后续所有命令都能看到这些变量
result = await sandbox.run("printenv DATABASE_URL")
```

### 模式 2：按调用传 env Dict（局部覆盖）

适用于每次调用不同的变量：

```python
env = {"BATCH_ID": "batch-001", "DRY_RUN": "true"}

result = await sandbox.run("sh -c 'python process.py'", env=env)
```

### 模式 3：复用 env Dict 对象

维护一个共享 dict 并传给每次调用：

```python
shared_env = {"DATABASE_URL": db_url, "LOG_LEVEL": "DEBUG"}

await sandbox.run("sh -c 'python migrate.py'", env=shared_env)
await sandbox.run("sh -c 'python seed.py'", env=shared_env)
await sandbox.run_code("import os; print(os.environ['LOG_LEVEL'])", envs=shared_env)
```

### 模式 4：Server 作用域配置（仅 SandboxServer）

使用 SandboxServer 的自定义命令时，通过 `POST /env` 设置仅 Server 需要的运行时配置：

```python
import httpx

url = sandbox.network.get_url(9000)
headers = sandbox.network.get_access_headers()

httpx.post(
    f"{url}/env",
    headers={**headers, "Content-Type": "application/json"},
    json={"vars": {"FEATURE_FLAG_X": "enabled"}},
)

# 该变量现在对 Server 命令处理器可见：
result = await sandbox.custom("my_handler")
```

---

## 安全注意事项

1. **envs 中的密钥**：通过 `envs=` 在创建时传入的环境变量会传输到平台 API。确保传输使用 HTTPS（默认值）。避免在日志中输出包含密钥的 env dict。

2. **`GET /env` 脱敏**：Server 的 `GET /env` 端点自动隐藏名称中包含 `TOKEN`、`SECRET`、`KEY`、`PASSWORD` 或 `CREDENTIAL` 的变量。

3. **受保护的 Server 变量**：`POST /env` 禁止写入 `PATH`、`HOME`、`USER`、`SHELL` 及所有 `EBX_*` 变量，防止意外破坏。

4. **无跨作用域泄漏**：通过 `POST /env` 在 Server 上设置的变量对 envd 进程不可见，反之亦然。这是安全特性，而非缺陷。

5. **推荐 `printenv`** 而非 `echo $VAR`：由于 envd 使用直接执行，`echo $VAR` 会输出字面字符串 `$VAR`。请使用 `printenv VAR` 或 `sh -c 'echo $VAR'`。

---

## 速查表

| 方法 | 参数 | 作用域 | 生命周期 |
|------|------|--------|---------|
| `Sandbox.create(envs=)` | `envs` | envd | 沙箱生命周期 |
| `commands.run(env=)` | `env` | envd | 单次命令 |
| `run_code(envs=)` | `envs` | envd | 单次执行 |
| `@sandbox(envs=)` | `envs` | envd | 装饰器调用 |
| CLI `--env KEY=VAL` | `--env` | envd | 沙箱生命周期 |
| `POST /env` | `vars` | Server | Server 进程生命周期 |

---

## 参见

- [SDK 使用指南](sdk-usage.md) — `commands.run()` 与 `run_code()` 用法
- [声明式用法](declarative-usage.md) — `@sandbox(envs=)` 装饰器
- [CLI 教程](cli-tutorial.md) — `ebx create --env`
- [配置参考](../reference/configuration.md) — SDK/CLI 环境变量（E2B_*、SANDBOX_*）
