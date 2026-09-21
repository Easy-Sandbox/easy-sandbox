# Decision: Server 模块能力全面扩充（6→42 端点，8 个能力组）

Status: implemented
Implemented: 2026-09-21

## Problem
当前 `easy_sandbox.server` 模块仅提供 6 个基础端点（health、commands、upload、download、shell、run command），能力覆盖有限。要使 Server 成为完整的沙箱内服务层，需要扩展到覆盖文件系统 CRUD、进程管理、PTY 终端、流式输出、系统信息、环境变量管理、Git 操作、Code Interpreter、浏览器自动化等能力，同时保持架构可控——端点可按能力组开关，避免不需要的能力暴露攻击面。

## Decision
引入声明式 **RouteTable** + **CapabilityGroup** 能力分组开关机制，将端点从 6 个扩充到 42 个，按 8 个能力组分类管理。

### 8 个能力组

| Group | 端点数 | 端点示例 | 默认状态 |
|-------|--------|---------|---------|
| `CORE` | 2 | `/health`, `/capabilities` | 始终启用，不可禁用 |
| `COMMANDS` | 2 | `GET /commands`, `POST /commands/{name}` | 启用 |
| `FILE_OPS` | 11 | `/files/list`, `/files/stat`, `/files/mkdir`, `DELETE /files`, `/files/move`, `/files/search`, `/upload`, `/download`, `/files/upload-stream`, `/files/download-stream`, `/files/archive` | 启用 |
| `PROCESS` | 6 | `/shell`, `/shell/stream`, `/process/start`, `/process/list`, `/process/{pid}`, `/process/{pid}/signal` | 启用 |
| `SYSTEM` | 6 | `/system/info`, `GET /env`, `POST /env`, `/ports`, `/packages`, `/system/metrics` | 启用 |
| `TERMINAL` | 3+WS | `POST /pty/sessions`, `GET /pty/sessions`, `DELETE /pty/sessions/{id}` + WebSocket PTY | 启用 |
| `DEV_TOOLS` | 3 | `/code/run`, `/git/status`, `/git/diff` | 禁用（需显式启用） |
| `BROWSER` | 8 | `/browser/navigate`, `/browser/screenshot`, `/browser/content`, `/browser/click`, `/browser/type`, `/browser/evaluate`, `/browser/pdf`, `/browser/console` | 禁用（需显式启用） |

### 架构改进

1. **声明式 RouteTable**：每个路由定义为 `RouteInfo` 记录，包含 method、path pattern（支持 `{param}` 占位符编译为正则）、handler、CapabilityGroup、auth_required、streaming 等属性。启动时根据启用的 CapabilityGroup 自动注册。替代当前 `handle_*` 函数在 `do_GET`/`do_POST` 中的硬编码 if/elif 分支。

2. **除 `/health` 外全部可开关**：`/health` 和 `/capabilities` 端点属于 CORE 组，始终可用且不可禁用。其他所有端点均可通过 CapabilityGroup 启用/禁用。运行时可通过 `EBX_SERVER_DISABLED_GROUPS` 环境变量配置。

3. **命令隐藏（hidden）**：`RegisteredCommand` 支持 `hidden=True` 属性，隐藏的命令不出现在 `GET /commands` 发现端点中，但仍可通过 `POST /commands/{name}` 调用。

4. **按域拆分路由文件**：路由处理函数按域拆分为独立模块：
   - `routes.py` — 核心路由（health/commands/upload/download/shell）
   - `routes_files.py` — FILE_OPS 组（9 个端点）
   - `routes_process.py` — PROCESS 组（5 个端点）
   - `routes_system.py` — SYSTEM 组 + CORE/capabilities（7 个端点）
   - `routes_pty.py` — TERMINAL 组（3 REST + WebSocket PTY）
   - `routes_browser.py` — BROWSER 组（8 个端点，Playwright-backed）
   - `routes_devtools.py` — DEV_TOOLS 组（3 个端点）

5. **WebSocket PTY 终端**：使用 Python 标准库 `pty` + 已有核心依赖 `websockets`（SDK 已依赖），提供交互式终端能力。REST API 管理会话（创建/列表/删除），WebSocket 传输 I/O。支持 input/resize/signal 消息类型。

6. **流式 Shell（SSE）**：`POST /shell/stream` 返回 Server-Sent Events 流，实时输出 shell 命令的 stdout/stderr，并在退出时发送 exit 事件。

7. **浏览器自动化（BROWSER 组）**：8 个 Playwright-backed 端点，支持页面导航、截图、DOM 内容获取、元素点击、文本输入、JavaScript 执行、PDF 生成和控制台日志收集。Playwright 惰性加载，未安装时返回 503。

### 文件安全

- `_resolve_safe_path()` 路径遍历防护，所有文件操作路径限制在 `EBX_SERVER_BASE_DIR`（默认 `/home/user`）下。
- 环境变量敏感字段（TOKEN/SECRET/KEY/PASSWORD）自动屏蔽。
- 受保护变量（PATH/HOME/USER/SHELL）不可被 `POST /env` 覆盖。
- 进程信号限制为允许列表（SIGINT/SIGKILL/SIGTERM 等），拒绝向 PID 1 或自身进程发送信号。

## API Design
```python
# 启动时配置
server = SandboxServer(
    port=8080,
    enabled_groups={"core", "commands", "file_ops", "process", "system", "terminal"},
    # dev_tools 和 browser 需显式启用
)
```

## Alternatives considered
- **保留 if/elif 硬编码路由分发** — 42 个端点的 if/elif 链可读性极差，新增端点需修改核心分发逻辑。Rejected。
- **换用 FastAPI 框架** — 引入第三方依赖，违反 server 模块 stdlib-only 原则。Rejected。
- **PTY 终端与 HTTP 共用同一端口（HTTP Upgrade）** — `http.server` 不支持 WebSocket 升级，需额外实现协议升级逻辑。使用 `websockets` 库在独立端口提供 PTY 更简洁。Rejected（同端口方案）。
- **前缀树路由（Trie-based router）** — 42 个端点规模下前缀树收益有限，正则匹配 + dict 查找足够。Rejected（过度工程化）。

## Dependencies
- `server/registry.py`（现有命令注册表）
- `server/routes.py`（现有路由处理，已拆分）
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
- browser：navigate→screenshot→content 链式操作。
- 能力组开关：禁用 file_ops 后 `/files/read` 返回 403/404。
- hidden 命令：`GET /commands` 不包含 hidden 命令，但 `POST /commands/{name}` 可调用。

## Acceptance criteria
- ✅ RouteTable + CapabilityGroup 框架替代 if/elif 硬编码。
- ✅ 8 个能力组（含 BROWSER），42 个端点，除 CORE 外全部可开关。
- ✅ WebSocket PTY 终端使用 `websockets` 核心依赖，不引入新第三方包。
- ✅ BROWSER 组 8 个 Playwright 端点实现完成。
- ✅ 路由按域拆分为 7 个模块文件。
- ✅ 此 ADR 已从 `proposed/` 移至 `implemented/`。

## Evidence
- 源码实现：`src/easy_sandbox/server/` 目录下所有路由模块。
- 测试覆盖：`tests/test_server/` 目录下对应测试文件。
