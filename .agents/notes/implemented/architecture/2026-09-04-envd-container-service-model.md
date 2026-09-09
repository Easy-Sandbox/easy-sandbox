# Decision: envd 两层容器服务模型（Image-Baked envd/Gateway + User Opt-in Server Module）

Status: implemented
Task: #94, #105, #118

## Problem
SDK 与容器内服务进程之间的职责边界不清晰。核心问题：谁负责提供容器内的 files/process/code/PTY/ports 服务？是用户/模板自带，还是平台侧提供？以及用户若需要长驻服务（如自建 HTTP server），应如何暴露——是替代 envd，还是在 envd 之上叠加？

## Decision
采用**镜像烤入 envd/Gateway + 用户 opt-in server 模块**的两层模型。

### 第一层：envd 与 Gateway 烤进 FC 官方基础镜像，由 entrypoint 启动

> **⚠ 关键事实修正（2026-09-05）**：原 ADR 错误描述 envd 为"平台运行时注入"或"构建期注入"。经实拉官方镜像检查（见 `docs/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`），已确认 envd 和 Gateway 是**烤进（baked into）FC 官方基础镜像**的静态 Go 二进制，而非平台运行时或构建期动态注入。

1. **容器内有两个 Go server，均为静态链接二进制，烤进 FC 官方基础镜像**：
   - **Gateway**（`/.fce2b/entrypoint`，端口 5000）：反向代理 + PID1 进程管理器。作为 `ENTRYPOINT` 启动，管理所有子进程生命周期（包括启动 envd），并通过 `proxy.(*Router)` 将请求路由到 envd、Code Interpreter 或动态端口服务。
   - **envd**（`/.fce2b/envd`，端口 49983）：E2B 标准守护进程（v0.1.14），提供 files（HTTP REST + Connect）、process（Connect streaming）、code（Connect）、terminal/PTY（WebSocket）等标准协议面。
2. **Gateway 反代层关键能力**：
   - `routeEnvd`：代理 envd 请求（/health, /metrics, /envs, /files/* 等）到 127.0.0.1:49983
   - `routeCI`：代理 Code Interpreter 请求到 127.0.0.1:49999（如已启用）
   - **`routeDynamic`：动态端口路由**，根据 `X-Sandbox-Port` header 将请求代理到对应端口——这是用户自建 server 能被外部访问的基础机制
   - 进程管理（`process.(*Manager).StartAll`）、僵尸进程回收（`process.(*Reaper)`）、启动就绪守卫（`proxy.(*StartupGuard).WaitForBackend`）
3. **启动链路**：`docker run → /.fce2b/entrypoint (PID 1)` → 启动 envd (49983) → 启动反向代理 Router (5000) → 等待 /init 初始化。
4. **envd 二进制不可替换**。版本由镜像决定（`models/sandbox.py` 的 `envd_version` 字段只是消费平台返回值）。本仓库不含 envd 实现。
5. **builder 模式**：平台对用户源镜像执行"拉取 → 加入云沙箱运行依赖（含 envd/Gateway 二进制）→ 推送为目标镜像"。本质上是把官方基础镜像的 `/.fce2b/` 目录合入用户镜像。
6. **direct 模式不含 envd**：源镜像需已具备 E2B 运行依赖，否则所有 envd 承接的能力（files/process/code/PTY）全部不可用。

### 第二层：用户 opt-in 的 serverless_sandbox.server 模块

> **⚠ 关键事实修正（2026-09-05）**：原 ADR 声称"SDK 不 ship 容器内 server"。此决策已推翻。新增用户 opt-in 的 `serverless_sandbox.server` 模块，详见 `2026-09-05-sandbox-server-module.md`。

7. **SDK 新增 `serverless_sandbox.server` 模块**：stdlib-only 零依赖的容器内 HTTP server，用户通过 `sandbox.server.start()` 主动启动（非兜底 agent，非自动部署）。内置 `upload`/`download`/`runshell` 命令，直接操作本地文件系统（不绑定 envd API）。
8. **这不是兜底 agent**：envd 仍是标准能力的基础承载。server 模块的定位是为**用户自定义命令**提供 HTTP 端点注册，通过 `POST /commands/{name}` 调用，客户端经 `https://{port}-{sandbox_id}.{domain}` 访问。
9. **ports 能力门控**：server 模块需模板显式声明 `capabilities: [..., ports]`。`ports` 不在 `DEFAULT_CAPABILITIES = {shell, files, code}` 里。
10. **原"循环依赖"论证已不适用**：server 模块是用户主动部署的业务逻辑（经 `files.write` + `commands.start` 投递启动），其定位与"兜底替代 envd"完全不同。前者依赖 envd 是正常的上层→下层依赖，不构成循环。

## API Design
```python
# envd 标准路径（不变）
# envd:   https://49983-{sandbox_id}.{domain}

# 用户 opt-in server 模块（新增）
await sandbox.server.start()  # 启动容器内 HTTP server
result = await sandbox.server.call("runshell", cmd="ls -la")
# 经 POST https://{port}-{sandbox_id}.{domain}/commands/runshell

# 用户自建独立 server（仍支持）
reader = await sandbox.commands.start("node server.js", cwd="/app", timeout=300)
url = sandbox.network.get_url(3000)           # https://{3000}-{sandbox_id}.{domain}
headers = sandbox.network.get_access_headers() # secure 模式下 X-Access-Token
```

## Alternatives considered
- **SDK ship 一个兜底 in-container agent（替代 envd）** — 循环依赖（投递手段依赖 envd）+ 无处安放（无 envd 时 SDK 无法连入）。Rejected。
- **用户替换 envd 二进制** — envd 版本由镜像掌控，本仓库无替换通道。Rejected。
- **用户在 direct 模式下自带完整运行时** — 技术可行，但代价是失去全部标准能力开箱即用的保障。仅限高级用户。
- **FastAPI/Flask 作为 server 模块** — 引入第三方依赖，违反零依赖原则。Rejected。
- **保留源码投递执行（不引入 server）** — 每次调用都需 files.write + commands.run 完整链路，延迟高、无法常驻。Rejected in favor of persistent HTTP server。

## Dependencies
- `transport/config.py` (`ENVD_PORT = 49983`, `build_envd_url`)
- `transport/auth.py` (`EnvdTokenManager`, envd 四 header)
- `protocol/` 层全部 Connect/HTTP/WS 协议实现
- `2026-09-03-capability-model.md` (`DEFAULT_CAPABILITIES` 不含 `ports`)
- `2026-09-03-command-source-resolution.md` (内置模板无 YAML → `ports` 不可用)
- `2026-09-05-sandbox-server-module.md` (server 模块架构决策)
- 阿里云官方文档：《构建自定义镜像模板》、《E2B 兼容说明》
- `docs/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`（镜像实地检查证据）

## Test Strategy
- 真实闭环验证（O1）：`FROM ubuntu:22.04` 最小镜像 → `sbox template build` → `sbox create` → `sbox exec "echo ok"` + `files.write`。成功即证实 builder 模式合入。
- `commands.start(background=True)` + `network.get_url(port)` 端到端可达性。
- 模板未声明 `ports` 时，调用 `network.get_url()` 应抛 `CapabilityNotSupportedError(E3004)`。
- server 模块功能验证见 `2026-09-05-sandbox-server-module.md`。

## Acceptance criteria
- 清晰文档：envd/Gateway 烤进 FC 官方基础镜像（非运行时注入），由 entrypoint 进程管理器启动。
- SDK 新增 opt-in `serverless_sandbox.server` 模块，用户主动 `sandbox.server.start()` 启动。
- 用户自建 server 仍可走 `commands.start` + `network.get_url` 模式。
- 全文档不再出现"envd 由运行时注入/平台注入"的错误描述。

## Evidence
- `docs/evidence/research/2026-09-04-container-serve-boundary.md` §0–§4, §6.7
- `docs/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`（镜像实地检查，确认 envd/Gateway 为镜像烤入）
