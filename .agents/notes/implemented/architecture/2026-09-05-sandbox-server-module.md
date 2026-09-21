# Decision: easy_sandbox.server — 用户 Opt-in 容器内 HTTP Server 模块

Status: implemented
Implemented: 2026-09-21
Task: #118

## Problem
用户需要在沙箱容器内注册和执行自定义命令。原方案（源码投递执行：`files.write` 投递脚本 + `commands.run` 执行）每次调用都需完整链路，延迟高、无法常驻状态、不支持并发。需要一个容器内常驻 HTTP server 承载自定义命令，同时不引入第三方依赖（容器内可能没有 pip 包管理环境）。

## Decision
新增 `easy_sandbox.server` 模块，stdlib-only 零依赖的容器内 HTTP server，用户 opt-in 启动。

### 核心设计原则

1. **stdlib-only 零依赖**：仅使用 Python 标准库（`http.server`、`json`、`subprocess`、`os`、`shutil`），不依赖任何第三方包。原因：容器内环境不可控，可能没有 pip/virtualenv，不能假设用户镜像预装了任何 Python 包。

2. **用户 opt-in，非兜底 agent**：server 模块不会自动部署或启动。用户必须显式调用 `sandbox.server.start()` 才会通过 `files.write` 投递 server 源码到容器并 `commands.start` 后台启动。envd 仍是标准能力（files/process/code/PTY）的基础承载，server 模块不替代 envd。

3. **直接操作本地文件系统，不绑定 envd**：内置命令（upload/download/runshell）直接调用 Python 标准库操作容器本地文件系统和进程，不经过 envd API。原因：(a) 避免 server→envd 的额外网络跳；(b) server 运行在容器内，有直接的文件系统和进程访问权限。

4. **ports 能力门控**：server 模块需模板声明 `capabilities: [..., ports]`。`ports` ∉ `DEFAULT_CAPABILITIES = {shell, files, code}`。客户端通过 `https://{port}-{sandbox_id}.{domain}` 访问 server，依赖 Gateway 的 `routeDynamic` 动态端口路由。

### 最终实现规模

Server 模块最终扩展到 **42 个端点**，按 **8 个 CapabilityGroup** 分组管理（CORE, COMMANDS, FILE_OPS, PROCESS, SYSTEM, TERMINAL, DEV_TOOLS, BROWSER）。采用声明式 `RouteTable` + `CapabilityGroup` 机制替代 if/elif 硬编码路由。

### 内置命令

5. **upload**：上传文件到容器。请求 body 含文件内容和目标路径。
6. **download**：从容器下载文件。请求 body 含源路径，响应含文件内容。
7. **runshell**：执行 shell 命令。请求 body 含命令字符串，响应含 stdout/stderr/exit_code。

### WIRE CONTRACT（客户端↔server 通信协议）

8. **命令执行**：`POST /commands/{name}`
   - Request Content-Type: `application/json`
   - Request Body: `{"key": "value", ...}`（命令的 kwargs）
   - Success Response: `200 OK`，`{"result": <return_value>}`
   - Error Response: `4xx/5xx`，`{"error": "<message>", "type": "<exception_class>"}`

9. **命令发现**：`GET /commands`
   - Response: `200 OK`，`{"commands": [{"name": "upload", "args": [...]}, ...]}`
   > 注：早期 ADR 中示例为裸数组格式，实际实现为 `{"commands": [...]}` 对象包裹。

10. **健康检查**：`GET /health`
    - Response: `200 OK`，`{"status": "ok"}`

### 客户端 API

11. **`sandbox.server.start(port=8080)`**：投递 server 源码到容器 + 后台启动 + 等待健康检查通过。
12. **`sandbox.server.call(command_name, **kwargs)`**：发送 `POST /commands/{name}` 请求，解析 JSON 响应。
13. **`sandbox.server.discover()`**：发送 `GET /commands` 请求，返回命令列表。

## API Design
```python
# 客户端侧
from easy_sandbox import Sandbox

sandbox = await Sandbox.create(template="my-template")

# 启动容器内 server（opt-in）
await sandbox.server.start(port=8080)

# 调用内置命令
result = await sandbox.server.call("runshell", cmd="ls -la /home/user")
# → POST https://8080-{sandbox_id}.{domain}/commands/runshell
# → Body: {"cmd": "ls -la /home/user"}
# ← {"result": {"stdout": "...", "stderr": "", "exit_code": 0}}

# 上传文件
await sandbox.server.call("upload", path="/home/user/script.py", content="print('hello')")

# 下载文件
result = await sandbox.server.call("download", path="/home/user/output.txt")

# 发现所有命令
commands = await sandbox.server.discover()
# → GET https://8080-{sandbox_id}.{domain}/commands
# ← [{"name": "upload", ...}, {"name": "download", ...}, {"name": "runshell", ...}]
```

```python
# 容器内 server 模块（easy_sandbox/server/）
# 纯 stdlib，零依赖

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, subprocess, os, shutil

class SandboxHandler(BaseHTTPRequestHandler):
    """处理 /commands/{name}、/commands、/health 请求"""
    ...

class SandboxServer:
    """命令注册 + HTTP server 生命周期管理"""
    def register(self, name: str, handler: Callable) -> None: ...
    def start(self, host: str = "0.0.0.0", port: int = 8080) -> None: ...
```

## Alternatives considered
- **FastAPI / Flask 作为 server 框架** — 引入第三方依赖，容器内可能没有 pip 环境，部署成本高。Rejected。
- **复用 envd files/process API（server 作为 envd 客户端）** — 增加额外网络跳（server→envd→本地文件系统），且 server 运行在容器内已有直接文件系统访问权限，绕 envd 无意义。Rejected。
- **保留源码投递执行（不引入 server）** — 每次调用需 files.write + commands.run 完整链路，延迟高、无常驻状态、不支持并发。Rejected。
- **直接 FROM 官方镜像构建（内含 envd，不需要 server）** — envd 的端点面封闭且不可扩展（由镜像掌控），用户无法注册自定义命令到 envd。server 模块解决的是"用户自定义命令"的承载问题，与 envd 互补而非替代。Rejected as sole solution。
- **gRPC / Connect protocol 作为通信协议** — 需要 protobuf 编译工具链和运行时库，违反零依赖原则。Rejected。

## Dependencies
- `api/sandbox.py`（`Sandbox` 类，挂载 `server` 属性）
- `api/network.py`（`NetworkModule.get_url(port)` 构建访问 URL）
- `api/files.py`（`files.write` 投递 server 源码到容器）
- `api/commands.py`（`commands.start` 后台启动 server 进程）
- `transport/auth.py`（`EnvdTokenManager` 获取 `X-Access-Token`）
- `2026-09-03-capability-model.md`（`ports` 能力门控）
- `2026-09-04-envd-container-service-model.md`（两层模型：envd 基础层 + server opt-in 层）
- `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`（确认 Gateway routeDynamic 支持动态端口路由，是 server 可达性的基础）

## Test Strategy
- 单元测试：server 模块的命令注册、请求路由、JSON 序列化/反序列化。
- 集成测试：`sandbox.server.start()` → 健康检查 → `call("runshell", cmd="echo ok")` → 验证响应。
- 内置命令：upload + download 往返一致性；runshell 返回正确 stdout/stderr/exit_code。
- 能力门控：模板未声明 `ports` 时，`sandbox.server.start()` 应抛 `CapabilityNotSupportedError(E3004)`。
- 发现端点：`GET /commands` 返回所有内置命令 + 用户注册命令的完整 schema。
- 错误处理：无效命令名 → 404；命令执行异常 → `{"error", "type"}` 响应。
- 零依赖验证：server 模块源码不含任何 `import` 第三方包。

## Acceptance criteria
- ✅ `easy_sandbox.server` 模块仅使用 Python 标准库，零第三方依赖。
- ✅ 内置 upload/download/runshell 三个命令，直接操作本地文件系统。
- ✅ WIRE CONTRACT 稳定：`POST /commands/{name}` + JSON body → `{"result"}` 或 `{"error","type"}`。
- ✅ `GET /commands` 发现端点返回所有已注册命令及参数 schema。
- ✅ `ports` 能力门控：未声明 `ports` 时 `start()` 报错。
- ✅ 客户端 API：`sandbox.server.start()` / `.call()` / `.discover()` 功能完整。
- ✅ Server 从 6 个端点扩展到 42 个端点，8 个能力组（含 BROWSER）。
- ✅ 此 ADR 已从 `proposed/` 移至 `implemented/`。

## Evidence
- `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`（Gateway routeDynamic 确认动态端口路由可行）
- `.agents/evidence/research/2026-09-04-fc-sandbox-official-docs.md`（端口 URL 格式 `{port}-{sandbox_id}.{domain}` 确认）
