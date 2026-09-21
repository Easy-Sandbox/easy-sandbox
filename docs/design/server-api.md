# Container-Side HTTP Server API Reference

> 容器内 HTTP Server（`easy_sandbox.server`）的完整 API 参考文档。
>
> 本文档的所有端点方法、路径、参数、请求体字段、响应格式均逐一读取自
> `src/easy_sandbox/server/` 下的实现代码，与源码保持一致。若代码中未明确定义某项行为，
> 文档会如实标注而非臆测。

---

## 1. 概述

### 1.1 Server 定位

容器内 HTTP Server 是一个**仅依赖 Python 标准库**（stdlib-only，零第三方依赖）的轻量级 HTTP 服务，
运行在 Sandbox 容器内部，向外部（SDK / CLI / Agent）暴露文件、进程、终端、系统信息、开发工具、
浏览器自动化等能力。

- 基于 [`http.server.ThreadingHTTPServer`](../../src/easy_sandbox/server/app.py) + 自定义 `BaseHTTPRequestHandler` 子类。
- 请求分发由数据驱动的 [`RouteTable`](../../src/easy_sandbox/server/router.py) 完成，而非硬编码的 `if/elif` 链。
- 每个路由归属一个 **能力组（CapabilityGroup）**，可整组启用/禁用。
- 请求/响应对象是 stdlib `dataclass`（[`types.py`](../../src/easy_sandbox/server/types.py)），不使用 Pydantic。

> 注意：本文所述「能力组」是 **Server 端 RouteTable 的运行时开关**，与 SDK 模板层
> （`models/template.py` / `api/capability.py`）的 `STANDARD_CAPABILITIES` 是两套独立机制，
> 不要混淆。

### 1.2 启动方式

**便捷函数** —
[`start()`](../../src/easy_sandbox/server/app.py#L320-L334)：

```python
from easy_sandbox.server import start

start(9000)  # 监听 0.0.0.0:9000，阻塞运行
```

**类接口** —
[`SandboxServer`](../../src/easy_sandbox/server/app.py#L215-L317)（可注入自定义 `registry` / `route_table`）：

```python
from easy_sandbox.server import SandboxServer, CommandRegistry

registry = CommandRegistry()
# ... 注册自定义命令 ...
server = SandboxServer(host="0.0.0.0", registry=registry)
server.serve(port=9000)  # 阻塞直到 KeyboardInterrupt / shutdown()
```

`serve()` 会在启动时调用 `registry.freeze()` 冻结命令注册表，随后开始接受请求。

### 1.3 两端口架构

Server 使用两个端口：

| 端口 | 协议 | 用途 | 默认值 | 覆盖变量 |
|------|------|------|--------|----------|
| HTTP 端口 | HTTP/1.1 | 全部 REST / SSE 端点 | `9000`（`serve(port=...)` 参数） | — |
| PTY 端口 | WebSocket | 交互式终端（PTY） | `9001` | `EBX_PTY_PORT` |

PTY WebSocket 服务仅在 `TERMINAL` 能力组启用时，于后台守护线程中启动（见
[`SandboxServer.serve`](../../src/easy_sandbox/server/app.py#L254-L280)）。`TERMINAL` 默认启用，因此 PTY 服务默认随主服务一起启动。

---

## 2. 能力组（Capability Groups）

能力组定义于枚举
[`CapabilityGroup`](../../src/easy_sandbox/server/router.py#L50-L64)，
共 **8 组**。每组是一族可作为整体启用/禁用的端点。

| 能力组 | 枚举值 | 端点数 | 默认状态 | 说明 |
|--------|--------|:------:|:--------:|------|
| `CORE` | `core` | 2 | **始终启用**（不可禁用） | 健康检查、能力查询 |
| `COMMANDS` | `commands` | 2 | 启用 | 自定义命令列举与执行 |
| `FILE_OPS` | `file_ops` | 11 | 启用 | 文件上传/下载/列举/搜索/归档等 |
| `PROCESS` | `process` | 6 | 启用 | shell 执行、SSE 流式 shell、后台进程管理 |
| `TERMINAL` | `terminal` | 3 REST + WS | 启用 | PTY 会话管理 + WebSocket 交互终端 |
| `SYSTEM` | `system` | 6 | 启用 | 系统信息、环境变量、端口、包、指标 |
| `DEV_TOOLS` | `dev_tools` | 3 | **默认禁用** | 代码执行、Git 检查 |
| `BROWSER` | `browser` | 8 | **默认禁用** | Playwright 浏览器自动化 |

### 2.1 默认禁用集合

来自 [`router.py`](../../src/easy_sandbox/server/router.py#L68) 的定义：

```python
_DEFAULT_DISABLED = frozenset({CapabilityGroup.DEV_TOOLS, CapabilityGroup.BROWSER})
```

> **准确性说明**：源码中默认禁用的仅有 `DEV_TOOLS` 与 `BROWSER` 两组。`TERMINAL` **默认启用**
> （因此 PTY WebSocket 服务默认启动）。任务大纲中「TERMINAL 默认禁用」的表述与当前代码不符，
> 本文以代码为准。

`CORE` 始终启用，调用 `disable_group(CapabilityGroup.CORE)` 会抛出 `ValueError`；
`enable_group(CapabilityGroup.CORE)` 是 no-op。

### 2.2 环境变量控制

`RouteTable` 在实例化时读取环境变量
[`EBX_SERVER_DISABLED_GROUPS`](../../src/easy_sandbox/server/router.py#L112-L126)，
其值为逗号分隔的能力组枚举值（如 `system,process`），用于在进程启动时额外禁用若干组：

```bash
# 在默认禁用（dev_tools, browser）之外，再禁用 system 与 process 组
export EBX_SERVER_DISABLED_GROUPS="system,process"
```

解析规则：

- 逐项 `strip()` 后按枚举值匹配；无法识别的值被静默忽略。
- `core` 会被显式跳过（无法通过环境变量禁用 CORE）。

### 2.3 运行时切换 API

`RouteTable` 提供运行时开关（见
[`router.py`](../../src/easy_sandbox/server/router.py#L240-L265)）：

| 方法 | 说明 |
|------|------|
| `enable_group(group)` | 启用能力组（对 `CORE` 为 no-op） |
| `disable_group(group)` | 禁用能力组（对 `CORE` 抛 `ValueError`） |
| `is_group_enabled(group) -> bool` | 查询能力组是否启用 |
| `list_groups() -> dict[str, bool]` | 返回 `{枚举值: 是否启用}` 映射 |

模板作者示例（来自
[`python-hello/commands.py`](../../examples/templates/python-hello/commands.py#L23-L26)）：

```python
from easy_sandbox.server import CapabilityGroup, default_table

table = default_table()
table.enable_group(CapabilityGroup.FILE_OPS)
table.enable_group(CapabilityGroup.PROCESS)
table.enable_group(CapabilityGroup.SYSTEM)
```

> 兼容层：历史 API `enable_builtin("upload"|"download"|"shell")` /
> `disable_builtin(...)` 仍可用，内部映射到对应能力组
> （`upload`/`download` → `FILE_OPS`，`shell` → `PROCESS`），见
> [`_compat.py`](../../src/easy_sandbox/server/_compat.py#L30-L34)。

---

## 3. 认证

认证逻辑位于
[`SandboxRequestHandler._check_auth`](../../src/easy_sandbox/server/app.py#L66-L81)。

- Server 启动时读取环境变量 `EBX_SERVER_TOKEN`（`os.environ.get("EBX_SERVER_TOKEN") or None`）。
- **未设置 token**：`auth_token is None`，视为本地模式，**所有请求免认证**。
- **已设置 token**：需在请求头携带 `X-Access-Token`，且使用 `hmac.compare_digest` 与配置值恒定时间比对。
  - 缺失或不匹配 → `401`，响应体 `{"error": "unauthorized", "type": "AuthError"}`。

### 3.1 免认证端点

以下路由注册时 `auth_required=False`，即使配置了 token 也无需认证：

| 端点 | 能力组 | 源码 |
|------|--------|------|
| `GET /health` | `CORE` | [routes.py#L442-L445](../../src/easy_sandbox/server/routes.py#L442-L445) |
| `GET /capabilities` | `CORE` | [routes_system.py#L411-L414](../../src/easy_sandbox/server/routes_system.py#L411-L414) |

请求携带 token 示例：

```bash
curl -H "X-Access-Token: $EBX_SERVER_TOKEN" http://localhost:9000/system/info
```

### 3.2 分发顺序

[`_dispatch`](../../src/easy_sandbox/server/app.py#L134-L179) 的处理顺序为：

1. 路径归一化：`urlparse` 后 `path.rstrip("/") or "/"`（去除尾部斜杠）。
2. `RouteTable.match(method, path)`：无匹配 → `404 {"error": "Not found: <path>", "type": "ValueError"}`。
3. 若 `route.auth_required` 且认证失败 → `401`（此步在能力组门禁**之前**）。
4. 能力组门禁：若 `route.group` 被禁用 → `404 {"error": "Built-in route '<name>' is disabled", "type": "ValueError"}`。
5. 对 `POST/PUT/PATCH/DELETE` 读取 JSON 请求体（解析失败 → `400`）。
6. 调用 handler；`streaming=True` 走 SSE 分发路径。

> 仅实现了 `do_GET` / `do_POST` / `do_DELETE`。`PUT` / `PATCH` 无对应入口，由 stdlib 返回 `501`。

---

## 3.3 请求/响应数据模型

路由 handler 的输入输出使用标准库 `dataclass` 定义（非 Pydantic），源码位于
[`types.py`](../../src/easy_sandbox/server/types.py)。

#### `ServerRequest`

经 `_dispatch` 解析后传入 handler 的请求对象。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `method` | `str` | — | HTTP 方法（大写，如 `"GET"`、`"POST"`） |
| `path` | `str` | — | URL 路径（如 `"/commands/greet"`） |
| `query` | `dict[str, list[str]]` | `{}` | 查询参数，每个 key 映射到值列表（支持重复 key） |
| `headers` | `dict[str, str]` | `{}` | 请求头（单值） |
| `body` | `dict[str, Any] \| None` | `None` | 解析后的 JSON 请求体；无体或非 JSON 时为 `None` |
| `path_params` | `dict[str, str]` | `{}` | 由 `{param}` 路由模板提取的路径参数 |
| `context` | `dict[str, Any]` | `{}` | 调度器注入的请求上下文（如 `"registry"` 键下的 `CommandRegistry`） |

#### `ServerResponse`

普通（非流式）handler 的返回类型。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | `int` | — | HTTP 状态码（如 `200`、`404`） |
| `body` | `dict[str, Any]` | `{}` | JSON 可序列化的响应体 |
| `headers` | `dict[str, str]` | `{}` | 额外响应头 |

工厂方法：

| 方法 | 返回 | 说明 |
|------|------|------|
| `ServerResponse.ok(data)` | `ServerResponse(200, data)` | 成功响应 |
| `ServerResponse.error(status, message, error_type="ValueError")` | `ServerResponse(status, {"error": message, "type": error_type})` | 错误响应 |

#### `SSEResponse`

SSE 流式 handler（`streaming=True` 路由）的返回类型。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | `int` | `200` | HTTP 状态码 |
| `headers` | `dict[str, str]` | `{"Content-Type": "text/event-stream"}` | 响应头 |
| `event_iterator` | `Any` | `None` | 维生成 SSE 事件负载（`str` 或 `bytes`）的迭代器，逐条 flush 给客户端 |

---

## 4. 端点参考

响应体统一为 JSON。成功一般为 `200`；错误体统一形如
`{"error": "<message>", "type": "<ExceptionName>"}`（见
[`ServerResponse.error`](../../src/easy_sandbox/server/types.py#L70-L88)）。

### 4.1 CORE（2）

#### `GET /health`

健康检查，始终返回 `200`，免认证。

响应：

```json
{"status": "ok"}
```

```bash
curl http://localhost:9000/health
```

#### `GET /capabilities`

列出全部能力组及其启用状态，免认证。

响应（`groups` 为 `{枚举值: bool}`）：

```json
{
  "groups": {
    "core": true,
    "commands": true,
    "file_ops": true,
    "process": true,
    "terminal": true,
    "system": true,
    "dev_tools": false,
    "browser": false
  }
}
```

---

### 4.2 COMMANDS（2）

#### `GET /commands`

列出注册表中**可见**（非 `hidden`）的命令及其参数定义。

响应：

```json
{
  "commands": [
    {
      "name": "hello",
      "args": [
        {"name": "name", "type": "string", "required": false, "default": "World", "description": ""}
      ]
    }
  ]
}
```

参数字段来自
[`handle_list_commands`](../../src/easy_sandbox/server/routes.py#L96-L119)：
`name` / `type` / `required` / `default` / `description`。

#### `POST /commands/{name}`

执行一个已注册命令。请求体为该命令的关键字参数（kwargs）。

请求体示例：

```json
{"name": "Qoder"}
```

处理流程（见
[`handle_run_command`](../../src/easy_sandbox/server/routes.py#L229-L269)）：

1. 命令不存在 → `404 {"error": "Unknown command '<name>'; available: ...", "type": "ValueError"}`。
2. 参数校验/类型转换失败 → `400`（缺少必填参数、传入未声明参数、类型无法转换）。
3. 命令函数抛异常 → `500 {"error": "...", "type": "<ExceptionName>"}`。
4. 成功 → `200 {"result": <返回值>}`。

类型强制转换支持 `string` / `integer` / `float` / `boolean`；布尔可接受
`true/false/yes/no/1/0`（见
[`_parse_boolean`](../../src/easy_sandbox/server/routes.py#L130-L152)）。

```bash
curl -X POST http://localhost:9000/commands/hello \
  -H "Content-Type: application/json" \
  -d '{"name": "Qoder"}'
# -> {"result": "Hello, Qoder!"}
```

---

### 4.3 FILE_OPS（11）

包含 2 个「传统」上传/下载端点（`/upload`、`/download`，注册于
[`routes.py`](../../src/easy_sandbox/server/routes.py#L454-L461)）与 9 个扩展文件操作端点（注册于
[`routes_files.py`](../../src/easy_sandbox/server/routes_files.py#L528-L565)）。所有路径都会经过
[`_resolve_safe_path`](../../src/easy_sandbox/server/routes.py#L58-L84) 的路径遍历防护（见 §8.1）。

#### `POST /upload`

写入 base64 编码内容到本地文件。

请求体：

```json
{"path": "/home/user/file.txt", "content_base64": "<base64>"}
```

响应：`{"path": "<解析后的绝对路径>", "bytes": <字节数>}`。

错误：缺失/非法 `path` 或 `content_base64` → `400`；base64 非法 → `400`；写入失败 → `500`；
路径逃逸 base 目录 → `400 {"error": "Path escapes base directory", ...}`。

#### `GET /download?path=...`

读取文件，返回 base64 内容。

响应：

```json
{"path": "/home/user/file.txt", "content_base64": "<base64>"}
```

错误：缺失 `path` → `400`；文件不存在 → `404 {"type": "FileNotFoundError"}`；读取失败 → `500`。

#### `GET /files/list?path=...`

列出目录内容。查询参数：

| 参数 | 默认 | 说明 |
|------|------|------|
| `path` | （必填） | 目录路径 |
| `recursive` | `false` | `true/yes/1` 递归；递归最大深度 `3`（`_DEFAULT_MAX_DEPTH`） |
| `max_entries` | `1000` | 上限被裁剪至 `1000`（`_DEFAULT_MAX_ENTRIES`） |

响应：

```json
{
  "entries": [
    {"name": "a.txt", "type": "file", "size": 12, "modified": "2026-09-21T00:00:00+00:00"}
  ]
}
```

`type` 为 `file` 或 `directory`；`modified` 为 ISO 8601 UTC。指向 base 目录外的符号链接会被跳过。
目录不存在 → `404`。

#### `GET /files/stat?path=...`

返回单个文件/目录的元信息。文件不存在时仍返回 `200`，`exists=false`：

```json
{"name": "x", "path": "/home/user/x", "type": "unknown", "size": 0, "permissions": "", "modified": "", "exists": false}
```

存在时：`type` 为 `file`/`directory`/`symlink`，`permissions` 为八进制后三位（如 `"644"`），
`modified` 为 ISO 8601 UTC，`exists=true`。

#### `POST /files/mkdir`

创建目录（含父目录，`exist_ok=True`）。请求体 `{"path": "..."}`；成功
`{"path": "...", "created": true}`。

#### `DELETE /files?path=...`

删除文件或目录（目录用 `shutil.rmtree`）。成功 `{"path": "...", "deleted": true}`；
不存在 → `404`。

#### `POST /files/move`

移动/重命名。请求体：

```json
{"source": "/home/user/a.txt", "destination": "/home/user/b.txt"}
```

响应 `{"source": "...", "destination": "..."}`；源不存在 → `404`；`source`/`destination`
路径逃逸时错误前缀分别为 `source: ` / `destination: `。

#### `POST /files/search`

按 glob 模式（`fnmatch`）搜索文件。请求体：

| 字段 | 默认 | 说明 |
|------|------|------|
| `path` | （必填） | 搜索根目录 |
| `pattern` | （必填） | glob 模式，如 `*.py` |
| `max_depth` | `5`（`_SEARCH_MAX_DEPTH`） | 最大递归深度 |
| `max_results` | `100`（`_SEARCH_MAX_RESULTS`） | 最大结果数 |

超时上限 `10` 秒（`_SEARCH_TIMEOUT_SECONDS`，由定时器线程实现）。响应：

```json
{"results": [{"name": "app.py", "path": "/home/user/app.py"}], "timed_out": false}
```

#### `POST /files/upload-stream`

分块（64 KB）写入的 base64 上传，带大小上限。请求体
`{"path": "...", "content_base64": "..."}`。超过上限（默认 100 MB，可由
`EBX_MAX_UPLOAD_SIZE` 覆盖）→ `413`。成功 `{"path": "...", "bytes": N}`。

#### `GET /files/download-stream?path=...`

分块读取后返回 base64，额外带 `bytes` 字段：

```json
{"path": "...", "content_base64": "<base64>", "bytes": 1024}
```

文件不存在 → `404`。

#### `POST /files/archive`

将多个路径打包为归档并返回 base64。请求体：

```json
{"paths": ["/home/user/dir", "/home/user/a.txt"], "format": "tar.gz"}
```

`format` 支持 `tar.gz`（默认）或 `zip`；其他值 → `400`。限制：文件总数
`10000`（`_ARCHIVE_MAX_FILES`）、归档大小 `100 MB`（`_ARCHIVE_MAX_SIZE`，超出 → `413`）。
路径不存在 → `404`。响应：

```json
{"content_base64": "<base64>", "format": "tar.gz", "bytes": 2048}
```

---

### 4.4 PROCESS（6）

包含 `/shell`（注册于 [routes.py](../../src/easy_sandbox/server/routes.py#L462-L465)）以及 SSE 流式 shell 与后台进程管理（注册于
[routes_process.py](../../src/easy_sandbox/server/routes_process.py#L268-L288)）。

#### `POST /shell`

同步执行 shell 命令（`shlex.split` + `shell=False`），300 秒超时。请求体：

```json
{"command": "ls -la /tmp"}
```

响应：

```json
{"stdout": "...", "stderr": "...", "exit_code": 0}
```

缺失/非法 `command` → `400`；超时 → `500 {"type": "TimeoutError"}`。

#### `POST /shell/stream`

执行命令并通过 **SSE** 流式返回输出（`streaming=True`）。请求体：

| 字段 | 默认 | 说明 |
|------|------|------|
| `command` | （必填） | 命令字符串 |
| `timeout` | `300` | 秒；`<=0` 或非法回退为 `300` |
| `cwd` | （空） | 工作目录，空则为 `None` |

SSE 事件格式见 §6。缺失/非法 `command` 或 `shlex` 解析失败 → `400`（普通 JSON 响应）。

#### `POST /process/start`

启动后台进程（`subprocess.Popen`）。请求体 `{"command": "...", "cwd": "..."}`。
进程数上限 `100`（`_MAX_PROCESSES`，超出 → `429 {"type": "ResourceError"}`）。成功：

```json
{"pid": 12345, "command": "sleep 60"}
```

#### `GET /process/list`

列出受管后台进程（列举前会清理已退出进程）。响应：

```json
{"processes": [{"pid": 12345, "command": "sleep 60", "state": "running", "started_at": 1758412800.0}]}
```

`state` 为 `running` 或 `exited`。

#### `GET /process/{pid}`

单进程详情。`pid` 非整数 → `400`；未受管 → `404 {"type": "NotFoundError"}`。响应：

```json
{"pid": 12345, "command": "sleep 60", "state": "exited", "started_at": 1758412800.0, "exit_code": 0}
```

`state=running` 时 `exit_code` 为 `null`。

#### `POST /process/{pid}/signal`

向受管进程发送信号。请求体 `{"signal": 15}`。

- 允许的信号白名单 `_ALLOWED_SIGNALS = {2, 9, 15, 18, 20}`（SIGINT/SIGKILL/SIGTERM/SIGCONT/SIGTSTP）；
  其他 → `400`。
- 拒绝对 `pid == 1` 或 Server 自身进程发信号 → `403 {"type": "PermissionError"}`。
- `pid` 非整数或缺失 `signal` → `400`；未受管 → `404`。

成功 `{"pid": 12345, "signal": 15}`。

---

### 4.5 TERMINAL（3 REST + WebSocket）

PTY 会话管理端点（注册于
[routes_pty.py](../../src/easy_sandbox/server/routes_pty.py#L398-L410)）。WebSocket 交互协议见 §5。

> PTY 依赖 Unix `pty` 模块；非 Unix 平台上创建会话会抛 `OSError`（→ `500`）。会话上限
> `MAX_SESSIONS = 10`，空闲超时 `IDLE_TIMEOUT = 1800` 秒。

#### `POST /pty/sessions`

创建 PTY 会话。请求体（全部可选）：

| 字段 | 默认 | 说明 |
|------|------|------|
| `shell` | `/bin/bash` | shell 可执行文件 |
| `cols` | `80` | 终端列数 |
| `rows` | `24` | 终端行数 |
| `env` | `null` | 追加的环境变量映射 |

响应：

```json
{"session_id": "a1b2c3d4e5f6", "ws_url": "ws://localhost:9001/pty?session_id=a1b2c3d4e5f6", "pid": 4321}
```

`cols`/`rows` 非整数 → `400`；达到会话上限 → `429 {"type": "RuntimeError"}`；PTY 创建失败 →
`500 {"type": "OSError"}`。`ws_url` 中端口来自 `EBX_PTY_PORT`（默认 `9001`）。

#### `GET /pty/sessions`

列出活动会话（会先回收已死会话）。响应：

```json
{
  "sessions": [
    {"id": "a1b2c3d4e5f6", "pid": 4321, "created_at": 1758412800.0, "cols": 80, "rows": 24, "alive": true}
  ]
}
```

#### `DELETE /pty/sessions/{id}`

关闭并销毁会话。成功 `{"status": "closed", "session_id": "<id>"}`；缺失 id → `400`；
不存在 → `404`。

---

### 4.6 SYSTEM（6）

系统信息端点（注册于
[routes_system.py](../../src/easy_sandbox/server/routes_system.py#L416-L440)）。全部仅用标准库实现（无 `psutil`）。

#### `GET /system/info`

OS / CPU / 内存 / 磁盘 / Python 版本：

```json
{
  "os": "Linux",
  "arch": "x86_64",
  "cpu_count": 4,
  "memory_total_mb": 8192,
  "memory_available_mb": 4096,
  "disk_total_gb": 40.0,
  "disk_free_gb": 25.5,
  "python_version": "3.11.5",
  "hostname": "sandbox-01"
}
```

内存优先解析 `/proc/meminfo`，非 Linux 回退到 `resource` 模块（较粗略）。

#### `GET /env`

列出环境变量。查询参数 `filter` 为逗号分隔白名单（仅返回其中的变量）。**名称包含
敏感 token（`TOKEN`/`SECRET`/`KEY`/`PASSWORD`/`CREDENTIAL`）的变量始终被排除**（见 §8.3）。

```json
{"variables": {"LANG": "C.UTF-8", "PWD": "/home/user"}}
```

#### `POST /env`

设置环境变量。请求体 `{"vars": {"KEY": "value"}}`。**受保护变量**
（`PATH`/`HOME`/`USER`/`SHELL`/`EBX_SERVER_TOKEN`）不可覆盖 → `403 {"type": "PermissionError"}`；
`vars` 非对象 → `400`。成功 `{"updated": ["KEY1", "KEY2"]}`（已排序）。

#### `GET /ports`

列出监听中的 TCP 端口。优先解析 `/proc/net/tcp` 与 `/proc/net/tcp6`（状态 `0A` = LISTEN），
为空时回退 `ss -tlnp`。响应：

```json
{"listening": [{"port": 8080, "protocol": "tcp", "address": "0.0.0.0", "pid": null}]}
```

> `pid` 在无 root 权限时通常为 `null`。

#### `GET /packages`

列出已安装包。查询参数 `manager` 为 `pip`（默认）或 `npm`；其他值 → `400`。
命令不存在（`FileNotFoundError`）时返回空列表而非报错；超时 → `500 {"type": "TimeoutError"}`。

```json
{"manager": "pip", "packages": [{"name": "requests", "version": "2.32.0"}]}
```

#### `GET /system/metrics`

实时资源指标：

```json
{
  "cpu_load_1m": 0.15, "cpu_load_5m": 0.10, "cpu_load_15m": 0.05,
  "memory_used_mb": 2048, "memory_total_mb": 8192, "memory_percent": 25.0,
  "disk_used_gb": 14.5, "disk_total_gb": 40.0, "disk_percent": 36.3,
  "uptime_seconds": 123.4
}
```

`uptime_seconds` 相对进程导入时刻（`_BOOT_TIME`）。

---

### 4.7 DEV_TOOLS（3）— 默认禁用

代码执行与 Git 检查（注册于
[routes_devtools.py](../../src/easy_sandbox/server/routes_devtools.py#L385-L397)）。使用前需
`default_table().enable_group(CapabilityGroup.DEV_TOOLS)`，否则请求返回 `404`（组被禁用）。

#### `POST /code/run`

在子进程中执行代码。请求体：

| 字段 | 默认 | 说明 |
|------|------|------|
| `code` | （必填） | 源代码字符串 |
| `language` | `python` | `python` / `node` / `bash`；其他 → `400` |
| `timeout` | `30` | 秒；上限 `300`（`_MAX_TIMEOUT`），`<=0` 回退 `30` |

语言映射：`python`→`python3 -c`，`node`→`node -e`，`bash`→`bash -c`。响应：

```json
{"stdout": "hello\n", "stderr": "", "exit_code": 0, "language": "python", "execution_time_ms": 42.5}
```

超时 → `408 {"type": "TimeoutError"}`；运行时缺失 → `500 {"type": "FileNotFoundError"}`。

#### `GET /git/status?path=...`

解析 `git status --porcelain -b`。查询参数 `path`（默认 `.`）。路径含 `..` 段 → `400`。
git 未安装 → `500`；超时 → `408`；git 返回非零 → `400 {"type": "GitError"}`。响应：

```json
{"branch": "main", "clean": false, "files": [{"path": "app.py", "status": "modified"}]}
```

`status` 取值：`modified`/`added`/`deleted`/`renamed`/`untracked`/`copied`/`unmerged`。

#### `GET /git/diff?path=...`

返回 `git diff` 文本与统计。查询参数：

| 参数 | 默认 | 说明 |
|------|------|------|
| `path` | `.` | 工作目录（含 `..` → `400`） |
| `staged` | `false` | `true` 时使用 `--staged` |
| `file` | （空） | 限定单个文件（含 `..` → `400`） |

diff 文本超过 1 MB（`_MAX_DIFF_BYTES`）会被截断并追加 `... (truncated at 1MB)`。响应：

```json
{"diff": "diff --git ...", "stats": {"files_changed": 3, "insertions": 10, "deletions": 2}}
```

---

### 4.8 BROWSER（8）— 默认禁用

Playwright 无头浏览器控制（注册于
[routes_browser.py](../../src/easy_sandbox/server/routes_browser.py#L484-L516)）。使用前需
`default_table().enable_group(CapabilityGroup.BROWSER)`。

> **Playwright 懒加载与 503 降级**：Playwright 在首次使用时才导入并启动
> （[`_get_playwright`](../../src/easy_sandbox/server/routes_browser.py#L60-L96)）。
> 若未安装 `playwright`，所有浏览器端点返回
> `503 {"error": "Playwright is not installed. ...", "type": "RuntimeError"}`。
> 页面为进程内共享单例（同一 `page`），操作受 `_browser_lock` 串行化。

#### `POST /browser/navigate`

导航到 URL。请求体：

| 字段 | 默认 | 说明 |
|------|------|------|
| `url` | （必填） | 目标 URL |
| `wait_until` | `networkidle` | Playwright 等待条件 |
| `timeout` | `30000` | 毫秒；`<=0` 回退 `30000` |

响应 `{"url": "...", "title": "...", "status": 200}`。

#### `POST /browser/screenshot`

截图。请求体：

| 字段 | 默认 | 说明 |
|------|------|------|
| `selector` | `null` | 指定则截该元素；元素不存在 → `404` |
| `full_page` | `true` | 整页截图（无 selector 时） |
| `format` | `png` | `png` 或 `jpeg`（其他回退 `png`） |

响应 `{"image_base64": "...", "width": 1280, "height": 720}`。

#### `GET /browser/content?type=...`

获取页面内容。查询参数 `type`：`html`（默认，`page.content()`）或 `text`
（`page.inner_text("body")`）。响应 `{"content": "...", "url": "...", "title": "..."}`。

#### `POST /browser/click`

点击元素。请求体 `{"selector": "#btn", "timeout": 5000}`（`timeout` 毫秒，`<=0` 回退 `5000`）。
响应 `{"clicked": true, "selector": "#btn"}`。

#### `POST /browser/type`

向元素输入文本。请求体：

| 字段 | 默认 | 说明 |
|------|------|------|
| `selector` | （必填） | 目标选择器 |
| `text` | （必填） | 输入文本 |
| `delay` | `50` | 每字符延迟（毫秒），`<0` 回退 `50` |
| `clear` | `false` | 输入前是否先清空（`page.fill("")`） |

响应 `{"typed": true, "selector": "...", "text": "..."}`。

#### `POST /browser/evaluate`

执行 JavaScript。请求体 `{"script": "document.title", "timeout": 10000}`
（`timeout` 毫秒，作为默认超时，`<=0` 回退 `10000`）。响应 `{"result": <JS 返回值>}`。

#### `POST /browser/pdf`

生成 PDF。请求体 `{"format": "A4", "landscape": false}`。响应
`{"pdf_base64": "...", "pages": 1}`（`pages` 依据 `/Type /Page` 出现次数粗略统计，至少 `1`）。

#### `GET /browser/console`

返回已收集的 console 日志并**清空缓冲**。响应：

```json
{"logs": [{"type": "log", "text": "hello", "timestamp": 1758412800.0}]}
```

日志缓冲上限 `1000` 条（`_MAX_CONSOLE_LOGS`）。

---

## 5. WebSocket PTY 终端协议

实现见
[`pty_ws_handler`](../../src/easy_sandbox/server/routes_pty.py#L426-L503)
与 [`start_pty_server`](../../src/easy_sandbox/server/routes_pty.py#L546-L571)。
WebSocket 服务依赖 `websockets` 库，运行在独立端口（默认 `9001`）。

### 5.1 连接 URL

```
ws://<host>:<pty_port>/pty?session_id=<session_id>
```

`session_id` 必须来自先前的 `POST /pty/sessions`。缺失 `session_id` → 服务端以关闭码
`1008` 关闭并附 `"Missing session_id parameter"`；未知会话 → `1008` + `"Unknown session: <id>"`。

### 5.2 客户端 → 服务端消息（JSON 文本帧）

| `type` | 字段 | 说明 |
|--------|------|------|
| `input` | `data`（字符串） | 向 shell 写入的输入（会 UTF-8 编码） |
| `resize` | `cols`、`rows`（整数） | 调整终端尺寸；非整数则忽略该消息 |
| `signal` | `signal`（字符串） | 向 shell 进程组发送信号 |

`signal` 取值映射（`_SIGNAL_MAP`）：`SIGINT` / `SIGTERM` / `SIGKILL` / `SIGHUP` / `SIGQUIT`；
未识别的信号名会被忽略。非法 JSON 帧被静默丢弃。

```json
{"type": "input",  "data": "ls -la\n"}
{"type": "resize", "cols": 120, "rows": 40}
{"type": "signal", "signal": "SIGINT"}
```

### 5.3 服务端 → 客户端消息（JSON 文本帧）

| `type` | 字段 | 说明 |
|--------|------|------|
| `output` | `data`（字符串） | PTY 输出（UTF-8，`errors="replace"`） |
| `event` | `event`、`session_id`、`pid`? | 生命周期事件 |

`event` 取值：

- `started`：连接建立后立即发送，附 `session_id` 与 `pid`。
- `exited`：shell 进程结束后发送，附 `session_id`。

```json
{"type": "output", "data": "total 0\n"}
{"type": "event",  "event": "started", "session_id": "a1b2c3d4e5f6", "pid": 4321}
{"type": "event",  "event": "exited",  "session_id": "a1b2c3d4e5f6"}
```

### 5.4 会话生命周期

1. `POST /pty/sessions` 创建会话，取得 `session_id` 与 `ws_url`。
2. 连接 `ws_url`；服务端推送 `started` 事件后，后台读循环持续转发 `output`。
3. 客户端发送 `input`/`resize`/`signal` 消息。
4. shell 退出时推送 `exited`；或调用 `DELETE /pty/sessions/{id}` 主动销毁。

---

## 6. SSE 流式 Shell

端点：`POST /shell/stream`（PROCESS 组）。实现见
[`_handle_shell_stream`](../../src/easy_sandbox/server/routes_process.py#L64-L121)。
响应 `Content-Type: text/event-stream`（[`SSEResponse`](../../src/easy_sandbox/server/types.py#L91-L107)），
事件以标准 SSE 帧 `event: <name>\ndata: <json>\n\n` 逐条 flush。

### 6.1 事件类型（来自代码确认）

| `event` | `data` 结构 | 触发时机 |
|---------|-------------|----------|
| `stdout` | `{"data": "<行文本>"}` | 每读到一行标准输出（已去除结尾 `\n`） |
| `stderr` | `{"data": "<行文本>"}` | stdout 读完后，逐行读取标准错误 |
| `error` | `{"error": "<message>"}` | 进程启动失败，或超时（`{"error": "timeout"}`） |
| `exit` | `{"exit_code": <int>}` | 进程结束（超时后也会补发一条 `exit`） |

> 实现说明：stdout 与 stderr 是**先读完 stdout 全部行，再读 stderr**，而非实时交错。
> 超时判断基于 stdout 读取循环内的 `time.monotonic()`。

### 6.2 示例

```bash
curl -N -X POST http://localhost:9000/shell/stream \
  -H "Content-Type: application/json" \
  -d '{"command": "echo hello && echo err >&2", "timeout": 30}'
```

```
event: stdout
data: {"data": "hello"}

event: stderr
data: {"data": "err"}

event: exit
data: {"exit_code": 0}

```

---

## 7. 扩展性（模板作者指南）

Server 的路由与命令均可由模板 `commands.py` 扩展，无需修改 SDK 源码。完整示例见
[`examples/templates/python-hello/commands.py`](../../examples/templates/python-hello/commands.py)。

### 7.1 注册自定义 HTTP 路由

使用 [`RouteTable.route()`](../../src/easy_sandbox/server/router.py#L175-L204) 装饰器（或 `register()`）。
路径模板支持 `{param}` 占位符，编译为命名捕获组 `(?P<param>[^/]+)`，通过
`request.path_params` 取用：

```python
from easy_sandbox.server import CapabilityGroup, ServerResponse, default_table

table = default_table()

@table.route("GET", "/hello/{name}", group=CapabilityGroup.COMMANDS)
def hello_route(request) -> ServerResponse:
    name = getattr(request, "path_params", {}).get("name", "World")
    return ServerResponse.ok({"greeting": f"Hello, {name}!"})
```

`route()` / `register()` 关键字参数：`group`（必填）、`auth_required`（默认 `True`）、
`streaming`（默认 `False`）、`name`（默认 `"<METHOD> <path>"`）。路由按注册顺序匹配。

#### 自定义 SSE 流式端点

当路由注册时指定 `streaming=True`，handler 应返回
[`SSEResponse`](../../src/easy_sandbox/server/types.py#L91-L107)，其
`event_iterator` 维生成标准 SSE 帧格式的字符串（参考
[`routes_process.py`](../../src/easy_sandbox/server/routes_process.py#L64-L121) 的实现）：

```python
import json
from easy_sandbox.server import CapabilityGroup, default_table
from easy_sandbox.server.types import SSEResponse, ServerResponse

table = default_table()

@table.route("POST", "/my/stream", group=CapabilityGroup.COMMANDS, streaming=True)
def my_stream(request) -> SSEResponse | ServerResponse:
    body = request.body or {}
    count = body.get("count", 3)
    if not isinstance(count, int) or count <= 0:
        return ServerResponse.error(400, "Invalid 'count'", "ValueError")

    def event_gen():
        for i in range(count):
            yield f"event: progress\ndata: {json.dumps({'step': i + 1})}\n\n"
        yield f"event: done\ndata: {json.dumps({'total': count})}\n\n"

    return SSEResponse(event_iterator=event_gen())
```

客户端将收到 `Content-Type: text/event-stream` 响应，事件逐条 flush。

#### 免认证端点

设置 `auth_required=False` 可使端点在配置了 `EBX_SERVER_TOKEN` 时也无需认证（内置的
`GET /health` 与 `GET /capabilities` 即使用此模式）：

```python
from easy_sandbox.server import CapabilityGroup, ServerResponse, default_table

table = default_table()

@table.route("GET", "/public/status", group=CapabilityGroup.COMMANDS, auth_required=False)
def public_status(request) -> ServerResponse:
    return ServerResponse.ok({"status": "running", "public": True})
```

> 注意：免认证端点仍受能力组门禁约束，若其所属能力组被禁用则返回 `404`。

### 7.2 注册自定义命令

使用 [`CommandRegistry.command()`](../../src/easy_sandbox/server/registry.py#L163-L234) 装饰器；
未显式提供 `args` 时会**从函数签名推断**参数类型（`int`→`integer`、`float`→`float`、
`bool`→`boolean`，其余 `string`）与是否必填（无默认值即必填）：

```python
from easy_sandbox.server import CommandRegistry, SandboxServer

registry = CommandRegistry()

@registry.command("hello", description="Say hello.")
def hello(name: str = "World") -> str:
    return f"Hello, {name}!"

@registry.command(hidden=True)          # 可执行但不在 GET /commands 列出
def _debug_info() -> dict:
    import platform
    return {"python": platform.python_version()}

registry.freeze()                        # 冻结后再注册将抛 RuntimeError
server = SandboxServer(registry=registry)
server.serve(port=9000)
```

- `hidden=True`：命令仍可通过 `POST /commands/{name}` 执行，但被
  [`list_visible`](../../src/easy_sandbox/server/registry.py#L268-L276) 从 `GET /commands` 列表中排除。
- `freeze()`：锁定注册表，防止启动后再变更；`serve()` 内部也会调用一次。
- 也可用编程式 `registry.register(name, fn, args=[CommandArg(...)], description=..., hidden=...)`。

`CommandArg` 的 `type` 必须是 `string`/`integer`/`float`/`boolean` 之一，否则构造时抛
`ValueError`。

---

## 8. 安全模型

### 8.1 路径遍历防护

[`_resolve_safe_path`](../../src/easy_sandbox/server/routes.py#L58-L84)
对所有文件端点的路径做归一化（`os.path.realpath` + `normpath`），并校验解析结果必须等于
base 目录或位于其下（`resolved == base_dir or resolved.startswith(base_dir + os.sep)`），
否则抛 `ValueError`（→ `400 {"error": "Path escapes base directory"}`）。

- base 目录来自 `EBX_SERVER_BASE_DIR`，默认 `/home/user`。
- `/files/list` 额外跳过指向 base 目录之外的符号链接。
- Git 端点（`/git/status`、`/git/diff`）使用独立的 `..` 段拒绝检查
  （[`_validate_git_path`](../../src/easy_sandbox/server/routes_devtools.py#L62-L70)），
  而非 `_resolve_safe_path`。

### 8.2 信号白名单

- `POST /process/{pid}/signal` 仅允许 `_ALLOWED_SIGNALS = {2, 9, 15, 18, 20}`；
  并拒绝对 `pid == 1` 或 Server 自身进程发信号（`403`）。
- WebSocket PTY 的 `signal` 消息仅接受 `_SIGNAL_MAP` 中的
  `SIGINT`/`SIGTERM`/`SIGKILL`/`SIGHUP`/`SIGQUIT`，且作用于 shell 进程组。

### 8.3 环境变量保护与脱敏

- **脱敏（`GET /env`）**：名称包含 `_ENV_BLACKLIST_TOKENS`
  （`TOKEN`/`SECRET`/`KEY`/`PASSWORD`/`CREDENTIAL`，大小写不敏感）的变量始终不返回。
- **保护（`POST /env`）**：`_PROTECTED_ENV_VARS`
  （`PATH`/`HOME`/`USER`/`SHELL`/`EBX_SERVER_TOKEN`）不可覆盖，命中即 `403`。

### 8.4 其他限制

| 限制项 | 值 | 位置 |
|--------|-----|------|
| shell / code / git 命令 | `shell=False` + 参数向量执行 | 各 handler |
| `/shell` 超时 | 300s | routes.py |
| `/code/run` 超时 | 默认 30s，上限 300s | routes_devtools.py |
| 上传大小上限 | 100 MB（`EBX_MAX_UPLOAD_SIZE` 可调） | routes_files.py |
| 归档文件数/大小 | 10000 / 100 MB | routes_files.py |
| 后台进程上限 | 100 | routes_process.py |
| PTY 会话上限 / 空闲超时 | 10 / 1800s | routes_pty.py |
| 认证比较 | `hmac.compare_digest`（恒定时间） | app.py |

---

## 9. 配置参考（环境变量总表）

| 环境变量 | 默认值 | 作用 | 读取位置 |
|----------|--------|------|----------|
| `EBX_SERVER_TOKEN` | （未设置 = 免认证） | 认证 token；设置后需 `X-Access-Token` 头匹配 | [app.py#L43](../../src/easy_sandbox/server/app.py#L43) |
| `EBX_SERVER_BASE_DIR` | `/home/user` | 文件端点路径安全根目录 | [routes.py#L54-L55](../../src/easy_sandbox/server/routes.py#L54-L55) |
| `EBX_SERVER_DISABLED_GROUPS` | （空） | 逗号分隔，在默认禁用之外额外禁用能力组 | [router.py#L71](../../src/easy_sandbox/server/router.py#L71) |
| `EBX_PTY_PORT` | `9001` | PTY WebSocket 端口，并写入 `ws_url` | [app.py#L247](../../src/easy_sandbox/server/app.py#L247) / [routes_pty.py#L362](../../src/easy_sandbox/server/routes_pty.py#L362) |
| `EBX_MAX_UPLOAD_SIZE` | `104857600`（100 MB） | `/files/upload-stream` 上传字节上限 | [routes_files.py#L39](../../src/easy_sandbox/server/routes_files.py#L39) |

> HTTP 端口不由环境变量控制，而是 `start(port=...)` / `SandboxServer.serve(port=...)` 参数（默认 `9000`）。

---

## 附录：端点数量核对

| 能力组 | 端点数 | 端点 |
|--------|:------:|------|
| CORE | 2 | `GET /health`、`GET /capabilities` |
| COMMANDS | 2 | `GET /commands`、`POST /commands/{name}` |
| FILE_OPS | 11 | `POST /upload`、`GET /download`、`GET /files/list`、`GET /files/stat`、`POST /files/mkdir`、`DELETE /files`、`POST /files/move`、`POST /files/search`、`POST /files/upload-stream`、`GET /files/download-stream`、`POST /files/archive` |
| PROCESS | 6 | `POST /shell`、`POST /shell/stream`、`POST /process/start`、`GET /process/list`、`GET /process/{pid}`、`POST /process/{pid}/signal` |
| TERMINAL | 3 REST | `POST /pty/sessions`、`GET /pty/sessions`、`DELETE /pty/sessions/{id}` |
| SYSTEM | 6 | `GET /system/info`、`GET /env`、`POST /env`、`GET /ports`、`GET /packages`、`GET /system/metrics` |
| DEV_TOOLS | 3 | `POST /code/run`、`GET /git/status`、`GET /git/diff` |
| BROWSER | 8 | `POST /browser/navigate`、`POST /browser/screenshot`、`GET /browser/content`、`POST /browser/click`、`POST /browser/type`、`POST /browser/evaluate`、`POST /browser/pdf`、`GET /browser/console` |
| **HTTP 合计** | **41** | |
| WebSocket | 1 | `ws://host:9001/pty?session_id=...` |
| **总计** | **42** | |

> 41 个 HTTP 路由与源码中 `_table.register(...)` 调用总数一致（`CORE 2 + COMMANDS 2 +
> FILE_OPS 11 + PROCESS 6 + TERMINAL 3 + SYSTEM 6 + DEV_TOOLS 3 + BROWSER 8 = 41`），加 1 个
> PTY WebSocket 端点共 **42 个端点**。
