# Decision: Server 模块能力全面扩充（6→26+ 端点）

Status: proposed

## Problem
当前 `serverless_sandbox.server` 模块仅提供 6 个基础端点（health、commands、upload、download、shell、run command），能力覆盖有限。要使 Server 成为完整的沙箱内服务层，需要扩展到覆盖文件系统 CRUD、进程管理、PTY 终端、流式输出、系统信息、环境变量管理、Git 操作、Code Interpreter 等能力，同时保持架构可控——端点可按能力组开关，避免不需要的能力暴露攻击面。

## Decision
引入声明式 **RouteTable** + **CapabilityGroup** 能力分组开关机制，将端点从 6 个扩充到 26+ 个，按 7 个能力组分类管理。

### 7 个能力组

| Group | 端点示例 | 默认状态 |
|-------|---------|---------|
| `core` | `/health`, `/commands`, `/commands/{name}` | 始终启用 |
| `commands` | 用户注册命令 | 启用 |
| `file_ops` | `/files/read`, `/files/write`, `/files/list`, `/files/delete`, `/files/mkdir` | 启用 |
| `process` | `/process/start`, `/process/kill`, `/process/list` | 启用 |
| `terminal` | `/terminal/ws` (WebSocket PTY) | 禁用（需显式启用） |
| `system` | `/system/info`, `/system/env`, `/system/env/set` | 启用 |
| `dev_tools` | `/git/status`, `/git/diff`, `/code/execute` | 禁用（需显式启用） |

### 架构改进

1. **声明式 RouteTable**：每个路由定义为 `(method, path_pattern, handler, capability_group)` 元组，启动时根据启用的 CapabilityGroup 自动注册。替代当前 `handle_*` 函数在 `do_GET`/`do_POST` 中的硬编码 if/elif 分支。

2. **除 `/health` 外全部可开关**：`/health` 端点始终可用（用于健康检查），其他所有端点均可通过 CapabilityGroup 启用/禁用。

3. **命令隐藏（hidden）**：`RegisteredCommand` 支持 `hidden=True` 属性，隐藏的命令不出现在 `GET /commands` 发现端点中，但仍可通过 `POST /commands/{name}` 调用。

4. **按域拆分路由文件**：当前 `routes.py` 承载所有路由处理函数，扩充后按域拆分为独立模块（`routes_files.py`、`routes_process.py`、`routes_terminal.py` 等），`routes.py` 仅保留核心路由和 RouteTable 注册逻辑。

5. **WebSocket PTY 终端**：使用 Python 标准库 `pty` + 已有核心依赖 `websockets`（SDK 已依赖），提供交互式终端能力。通过 `GET /terminal/ws` WebSocket 升级连接。

6. **流式 Shell（SSE）**：`POST /shell/stream` 返回 Server-Sent Events 流，实时输出 shell 命令的 stdout/stderr。

### 5 个 Phase 渐进实施

- **Phase 1**：RouteTable + CapabilityGroup 框架 + 现有端点迁移
- **Phase 2**：file_ops 组（文件系统 CRUD 5 个端点）
- **Phase 3**：process 组 + system 组（进程管理 + 系统信息 6 个端点）
- **Phase 4**：terminal 组（WebSocket PTY）
- **Phase 5**：dev_tools 组（Git 操作 + Code Interpreter）

## API Design
```python
# server/types.py — 扩展
@dataclasses.dataclass
class RouteEntry:
    method: str                    # "GET", "POST", "WS"
    pattern: re.Pattern[str]
    handler: Callable
    group: str                     # CapabilityGroup 名

class RouteTable:
    def register(self, entry: RouteEntry) -> None: ...
    def enable_group(self, group: str) -> None: ...
    def disable_group(self, group: str) -> None: ...
    def match(self, method: str, path: str) -> tuple[Callable, dict] | None: ...

# 端点示例
# file_ops 组
POST /files/write    {"path": "/app/main.py", "content": "..."}
GET  /files/read     ?path=/app/main.py
GET  /files/list     ?path=/app&recursive=true
POST /files/delete   {"path": "/app/tmp.txt"}
POST /files/mkdir    {"path": "/app/output"}

# process 组
POST /process/start  {"cmd": "python main.py", "background": true}
POST /process/kill   {"pid": 1234}
GET  /process/list

# terminal 组
WS   /terminal/ws    (WebSocket PTY，双向字节流)

# system 组
GET  /system/info    → {"os": "linux", "arch": "amd64", "python": "3.11.4", ...}
GET  /system/env     → {"HOME": "/home/user", ...}
POST /system/env/set {"KEY": "VALUE"}

# dev_tools 组
GET  /git/status     → {"branch": "main", "modified": [...], ...}
GET  /git/diff       ?file=main.py
POST /code/execute   {"code": "print(1+1)", "language": "python"}
```

```python
# 启动时配置
server = SandboxServer(
    port=8080,
    enabled_groups={"core", "commands", "file_ops", "process", "system"},
    # terminal 和 dev_tools 需显式启用
)
```

## Alternatives considered
- **保留 if/elif 硬编码路由分发** — 26+ 端点的 if/elif 链可读性极差，新增端点需修改核心分发逻辑。Rejected。
- **换用 FastAPI 框架** — 引入第三方依赖，违反 server 模块 stdlib-only 原则。Rejected。
- **PTY 终端与 HTTP 共用同一端口（HTTP Upgrade）** — `http.server` 不支持 WebSocket 升级，需额外实现协议升级逻辑。使用 `websockets` 库在独立端口提供 PTY 更简洁。Rejected（同端口方案）。
- **前缀树路由（Trie-based router）** — 26 个端点规模下前缀树收益有限，正则匹配 + dict 查找足够。Rejected（过度工程化）。

## Dependencies
- `server/registry.py`（现有命令注册表）
- `server/routes.py`（现有路由处理，将拆分）
- `server/app.py`（`SandboxServer` 接受 `enabled_groups` 参数）
- `server/types.py`（`RouteEntry`、`RouteTable` 定义）
- `websockets`（SDK 已有核心依赖，用于 PTY 终端）
- `2026-09-09-server-command-registry.md`（CommandRegistry 解耦）
- `2026-09-05-sandbox-server-module.md`（server 模块总体架构）

## Test Strategy
- RouteTable：注册→匹配→未匹配 404；启用/禁用 group 后路由可达性变化。
- file_ops：write→read 往返一致性；list 递归/非递归；delete 后 read 报错；mkdir 幂等。
- process：start 后 list 包含 PID；kill 后进程终止。
- terminal：WebSocket 连接→发送命令→接收输出→断开。
- system：info 返回正确 OS/arch；env/set 后 env 包含新变量。
- 能力组开关：禁用 file_ops 后 `/files/read` 返回 403/404。
- hidden 命令：`GET /commands` 不包含 hidden 命令，但 `POST /commands/{name}` 可调用。

## Acceptance criteria
- RouteTable + CapabilityGroup 框架替代 if/elif 硬编码。
- 7 个能力组，26+ 端点，除 `/health` 外全部可开关。
- WebSocket PTY 终端使用 `websockets` 核心依赖，不引入新第三方包。
- 5 个 Phase 可独立实施和验证。
- 实现后，此 ADR 从 `proposed/` 移至 `implemented/`。
