# 从 E2B 迁移

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

Easy Sandbox 设计上与 E2B Python SDK 保持高度 API 兼容。本文档提供迁移指南。

---

## API 映射对照表

| E2B SDK | Easy Sandbox | 说明 |
|---------|-------------|------|
| `from e2b import Sandbox` | `from easy_sandbox.api.sandbox import Sandbox` | 主类导入 |
| `Sandbox.create()` | `Sandbox.create()` | ✅ 完全兼容 |
| `Sandbox.connect(id)` | `Sandbox.connect(id)` | ✅ 完全兼容 |
| `Sandbox.list()` | `Sandbox.list()` | ✅ 完全兼容 |
| `sandbox.kill()` | `sandbox.kill()` | ✅ 完全兼容 |
| `Sandbox.kill(id)` | `Sandbox.kill_by_id(id)` | ⚠️ 方法名不同 |
| `sandbox.is_running()` | `sandbox.is_running()` | ✅ 完全兼容 |
| `sandbox.pause()` | `sandbox.pause()` | ✅ 完全兼容 |
| `sandbox.set_timeout(t)` | `sandbox.set_timeout(t)` | ✅ 完全兼容 |
| `sandbox.commands.run(cmd)` | `sandbox.commands.run(cmd)` | ✅ 完全兼容 |
| `sandbox.files.read(path)` | `sandbox.files.read(path)` | ✅ 完全兼容 |
| `sandbox.files.write(path, d)` | `sandbox.files.write(path, d)` | ✅ 完全兼容 |
| `sandbox.run_code(code)` | `sandbox.run_code(code)` | ✅ 完全兼容 |
| `sandbox.get_host(port)` | `sandbox.network.get_host(port)` | ⚠️ 需通过 network 子模块 |
| `sandbox.get_upload_url(path)` | `sandbox.get_upload_url(path)` | ❌ 抛出 NotImplementedError |
| `sandbox.get_download_url(path)` | `sandbox.get_download_url(path)` | ❌ 抛出 NotImplementedError |

---

## 导入路径替换

### 直接替换

```python
# E2B
from e2b import Sandbox

# Easy Sandbox（推荐）
from easy_sandbox.api.sandbox import Sandbox
```

### 使用兼容层

```python
# 兼容层导入（最小改动）
from easy_sandbox.compat import Sandbox
```

兼容层 `easy_sandbox.compat` 重新导出 `Sandbox` 类，API 签名与 E2B SDK 一致。

---

## 兼容层详情

兼容模块 `easy_sandbox.compat.sandbox` 提供：

```python
from easy_sandbox.compat import Sandbox
from easy_sandbox.compat import E2BSandbox  # 别名
```

两者是同一个 `Sandbox` 类，仅命名不同。

---

## 环境变量兼容

Easy Sandbox 兼容 E2B 的环境变量命名：

| E2B 环境变量 | Easy Sandbox 替代 | 优先级 |
|-------------|-------------------|--------|
| `E2B_API_KEY` | `SANDBOX_API_KEY` | E2B 优先 |
| `E2B_API_URL` | `SANDBOX_API_BASE_URL` | E2B 优先 |
| `E2B_DOMAIN` | — | E2B 独有 |

当同时设置 `E2B_API_KEY` 和 `SANDBOX_API_KEY` 时，`E2B_API_KEY` 优先。

---

## 不兼容点与解决方案

### 1. `Sandbox.kill(id)` → `Sandbox.kill_by_id(id)`

E2B 中类方法 `Sandbox.kill(id)` 按 ID 销毁沙箱。Easy Sandbox 中此功能由 `Sandbox.kill_by_id(id)` 提供，`sandbox.kill()` 是实例方法。

```python
# E2B
await Sandbox.kill("sbx-xxxx")

# Easy Sandbox
await Sandbox.kill_by_id("sbx-xxxx")
```

### 2. `get_host(port)` 需通过 network 子模块

```python
# E2B
host = sandbox.get_host(8080)

# Easy Sandbox
host = sandbox.network.get_host(8080)
url = sandbox.network.get_url(8080)
```

> **注意**：`network.get_host()` 和 `network.get_url()` 需要模板声明 `ports` 能力。若未声明，会抛出 `CapabilityNotSupportedError`（E3004）。

### 3. `get_upload_url()` / `get_download_url()` 未实现

这两个方法当前抛出 `NotImplementedError`，是预留的占位符。使用 `files.write()` 和 `files.read()` 替代：

```python
# E2B
url = await sandbox.get_upload_url("/path/file.txt")

# Easy Sandbox — 使用 files 替代
await sandbox.files.write("/path/file.txt", content)
text = await sandbox.files.read("/path/file.txt")
```

### 4. 能力门禁

Easy Sandbox 引入了能力模型。某些操作需要模板声明对应能力，否则会抛出 `CapabilityNotSupportedError`（E3004）：

- `run_code()` → 需要 `code` 能力
- `commands.run()` → 需要 `shell` 能力
- `files.*` → 需要 `files` 能力
- `network.*` → 需要 `ports` 能力
- `get_terminal()` → 需要 `terminal` 能力

默认能力集 `{shell, files, code}` 覆盖大多数常用操作。

### 5. 阿里云扩展

Easy Sandbox 增加了阿里云 AK/SK 认证方式，这在 E2B 中不存在：

```python
sandbox = await Sandbox.create(
    access_key_id="your-ak",
    access_key_secret="your-sk",
)
```

---

## 迁移步骤

1. **替换依赖**：`pip install easy-sandbox`（卸载 `e2b`）
2. **替换导入**：
   - 最小改动：`from e2b import Sandbox` → `from easy_sandbox.compat import Sandbox`
   - 推荐：`from easy_sandbox.api.sandbox import Sandbox`
3. **替换 `Sandbox.kill(id)`**：改为 `Sandbox.kill_by_id(id)`
4. **替换 `get_host()`**：改为 `sandbox.network.get_host()`
5. **替换 `get_upload_url` / `get_download_url`**：改用 `files.write()` / `files.read()`
6. **保留环境变量**：`E2B_API_KEY` 等变量继续有效

---

## 下一步

- [认证详解](authentication.md) — 了解完整的认证方式
- [SDK 使用指南](sdk-usage.md) — SDK 完整使用方法
- [E2B 兼容性说明](../explanation/e2b-compatibility.md) — 设计背景与原因
