# E2B 兼容性

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

本文档说明 Easy Sandbox 对 E2B Python SDK 的兼容策略、兼容了什么、未兼容什么，以及背后的设计原因。

---

## 设计目标

Easy Sandbox 的 E2B 兼容策略是：

> **让使用 E2B SDK 的用户以最小改动迁移到 Easy Sandbox，同时不被 E2B 的历史设计约束所限制。**

具体而言：
- 核心 API 签名保持一致
- 环境变量命名兼容
- 提供 `compat` 模块简化迁移
- 新增能力不破坏兼容性

---

## 兼容了什么

### API 签名

以下 API 与 E2B Python SDK 完全兼容：

| API | 状态 |
|-----|------|
| `Sandbox.create(template, timeout, metadata, envs)` | ✅ 兼容 |
| `Sandbox.connect(sandbox_id)` | ✅ 兼容 |
| `Sandbox.list()` | ✅ 兼容 |
| `sandbox.kill()` | ✅ 兼容 |
| `sandbox.is_running()` | ✅ 兼容 |
| `sandbox.pause()` | ✅ 兼容 |
| `sandbox.set_timeout(seconds)` | ✅ 兼容 |
| `sandbox.run_code(code, language, timeout)` | ✅ 兼容 |
| `sandbox.commands.run(cmd, timeout, env, cwd)` | ✅ 兼容 |
| `sandbox.files.read(path)` | ✅ 兼容 |
| `sandbox.files.write(path, content)` | ✅ 兼容 |
| `sandbox.files.list(path)` | ✅ 兼容 |
| `sandbox.files.remove(path)` | ✅ 兼容 |
| `async with await Sandbox.create() as sb:` | ✅ 兼容 |

### 环境变量

| 变量 | 状态 |
|------|------|
| `E2B_API_KEY` | ✅ 兼容（最高优先级） |
| `E2B_API_URL` | ✅ 兼容 |
| `E2B_DOMAIN` | ✅ 兼容 |

### 兼容层

```python
from easy_sandbox.compat import Sandbox
```

`compat` 模块重新导出 `Sandbox` 类，无额外包装。

---

## 未兼容什么

### 1. `Sandbox.kill(id)` 类方法

**E2B**：`Sandbox.kill(id)` 是类方法，按 ID 销毁沙箱。

**Easy Sandbox**：类方法重命名为 `Sandbox.kill_by_id(id)`，`kill()` 保留为实例方法。

**原因**：Python 中同名的类方法和实例方法会产生歧义。将按 ID 销毁的类方法显式命名为 `kill_by_id` 更清晰，避免 `Sandbox.kill("sbx-xxxx")` 和 `sandbox.kill()` 的混淆。

### 2. `sandbox.get_host(port)` 直接方法

**E2B**：`sandbox.get_host(port)` 是 Sandbox 实例的直接方法。

**Easy Sandbox**：移到 `sandbox.network.get_host(port)` 子模块下。

**原因**：将网络相关功能聚合到 `network` 子模块，与 `commands`、`files` 等子模块保持一致的组织结构。同时，`network` 方法需要 `ports` 能力门禁检查。

### 3. `get_upload_url()` / `get_download_url()`

**E2B**：返回预签名 URL 用于直接上传/下载。

**Easy Sandbox**：这两个方法存在但抛出 `NotImplementedError`，是预留占位符。

**原因**：Easy Sandbox 使用不同的后端架构，文件操作通过 envd 代理完成。推荐使用 `files.write()` / `files.read()` / `files.upload()` / `files.download()`。

### 4. 能力门禁

**E2B**：没有能力检查机制，所有功能始终可用。

**Easy Sandbox**：引入能力模型，API 调用前检查模板是否声明了所需能力。

**原因**：
- **安全性**：限制沙箱功能范围，遵循最小权限原则
- **明确性**：在调用时立即报错（E3004），而不是在后端返回晦涩的错误
- **可扩展性**：为未来的细粒度权限控制奠定基础

### 5. 部分 RPC 路径

某些 API（`run_code`、`get_terminal` 等）的 RPC 路径基于 E2B SDK 逆向推断。这些路径在阿里云官方文档中未公开，可能存在差异。

---

## 扩展（非 E2B 功能）

Easy Sandbox 在 E2B 兼容基础上增加了以下功能：

| 功能 | 说明 |
|------|------|
| AK/SK 认证 | 阿里云 AccessKey 对认证 |
| 能力模型 | 模板级能力声明和运行时门禁 |
| 自定义命令 | template.yaml 中定义可参数化的 Shell 命令 |
| @sandbox 装饰器 | 声明式远程函数执行 |
| Image 链式 API | Modal 风格的镜像构建 |
| MCP Server | AI IDE 集成（Cursor/Claude/VS Code） |
| 会话管理 | 命名会话持久化 |
| NL 部署 | 自然语言驱动的项目部署 |
| 密钥管理 | `ebx secret` 安全存储 |
| Skill 系统 | `ebx skill` 搜索和安装 |

---

## 下一步

- [从 E2B 迁移](../guide/migrate-from-e2b.md) — 实操迁移指南
- [架构概览](architecture-overview.md) — 系统架构
- [SDK 使用指南](../guide/sdk-usage.md) — 完整 SDK 用法
