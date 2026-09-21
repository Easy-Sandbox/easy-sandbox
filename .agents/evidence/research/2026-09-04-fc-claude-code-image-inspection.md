# FC Claude Code 镜像实地检查

> 检查日期: 2026-09-04
> 镜像: `fc-e2b-registry.cn-hangzhou.cr.aliyuncs.com/runtime/claude-code:v0.0.44`

## 拉取结果

- **状态**: 成功拉取
- **镜像地域**: cn-hangzhou (杭州)
- **镜像大小**: 2071.8 MB (约 2 GB)
- **Digest**: `sha256:276ed3b8592a502bcc92159fcf84a1497d4bd6a9f19d48e315357f4f7c27fbb0`
- **基础 OS**: Ubuntu 25.04
- **架构**: linux/amd64
- **构建方式**: BuildKit, 从 scratch 复制整个 rootfs (`COPY / /`)

## 镜像元数据

| 项目 | 值 |
|------|-----|
| **CMD** | `None` (无 CMD) |
| **ENTRYPOINT** | `["/.fce2b/entrypoint"]` |
| **EXPOSED PORTS** | `49983/tcp`, `5000/tcp`, `50005/tcp` |
| **WORKDIR** | `/home/user` |
| **USER** | `root` (Dockerfile 中先设为 user，但运行时需 root 权限启动 entrypoint) |
| **VOLUMES** | 无 |

### 环境变量

| 变量名 | 值 | 说明 |
|--------|-----|------|
| `ENVD_BIN` | `/.fce2b/envd` | envd 守护进程二进制路径 |
| `ENVD_PORT` | `49983` | envd HTTP API 监听端口 |
| `ENTRYPOINT_PORT` | `5000` | Gateway 入口端口 |
| `GATEWAY_LISTEN` | `0.0.0.0:5000` | Gateway 监听地址 |
| `CODE_INTERPRETER_BIN` | `/.fce2b/sandbox-code-interpreter` | Code Interpreter 二进制路径 |
| `CODE_INTERPRETER_PORT` | `49999` | Code Interpreter 端口 |
| `FC_E2B_CODE_INTERPRETER_ENABLED` | `false` | Claude Code 模板禁用了 Code Interpreter |
| `MCP_PORT` | `50005` | MCP 服务端口 |
| `IMAGE_VARIANT` | `claude` | 镜像变体标识 |
| `HTTP_PROXY` / `HTTPS_PROXY` | (空) | 代理已清空 |
| `PATH` | `/home/user/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/.fce2b` | 包含 claude CLI 和 fce2b 工具路径 |

### Labels

| Label | 值 |
|-------|-----|
| `layer` | `claude-code` |
| `maintainer` | `Aliyun FC Sandbox Team` |
| `description` | `Claude Code: E2B 兼容沙箱，预装 Anthropic Claude Code CLI` |

## 容器内文件结构

### 核心二进制文件 (`/.fce2b/`)

```
/.fce2b/
├── entrypoint              # Go 静态链接 ELF x86-64, Gateway 进程管理器
├── envd                    # Go 静态链接 ELF x86-64, E2B envd 守护进程 (v0.1.14)
└── sandbox-code-interpreter # Go 静态链接 ELF x86-64, Code Interpreter (本模板中未启用)
```

三个均为 **Go 编译的静态链接二进制文件**，无外部依赖。

### Claude Code 安装位置

```
/home/user/.local/bin/claude                              # Claude Code CLI 入口
/home/user/.local/lib/node_modules/@anthropic-ai/claude-code/
├── package.json              # @anthropic-ai/claude-code v2.1.211
├── cli-wrapper.cjs
├── install.cjs
├── sdk-tools.d.ts
├── bin/claude.exe            # Windows 二进制 (不适用)
└── node_modules/@anthropic-ai/claude-code-linux-x64/
    └── claude                # Linux x64 原生二进制
```

**Claude Code 版本**: `@anthropic-ai/claude-code@2.1.211`

### 预装开发工具

| 工具 | 路径 |
|------|------|
| Node.js | `/usr/bin/node`, `/usr/local/bin/node` |
| npm | `/usr/local/bin/npm` |
| npx | `/usr/local/bin/npx` |
| Go | `/usr/local/go/bin/go` |
| Python 3.13 | 系统自带 (Ubuntu 25.04) |
| pip | `/usr/lib/python3/dist-packages/pip/` |
| Bun | `/usr/local/bin/bun` |
| pnpm | `/usr/local/bin/pnpm` |
| git | 系统安装 |

### 配置文件

- `/home/user/.claude.json` — 空 JSON 配置 (需用户初始化)
- `/home/user/.claude/` — Claude 数据目录 (含 debug/, downloads/ 子目录)
- `/home/user/.config/pip/pip.conf` — pip 配置，index-url 指向阿里云镜像
- `/etc/profile.d/e2b-path.sh` — PATH 注入脚本，确保 `/.fce2b` 和 `~/.local/bin` 在 PATH 中
- `/etc/ssl/certs/e2b-ca.pem` — E2B 自签 CA 证书

## Server 发现

### 1. Gateway / Entrypoint (端口 5000)

**二进制**: `/.fce2b/entrypoint`
**语言**: Go (静态链接)
**包路径**: `entrypoint/cmd/gatewayd`

这是一个 **反向代理 Gateway**，包含以下核心组件（从二进制字符串提取的 Go 包路径）：

| 组件 | Go 包路径 | 功能 |
|------|-----------|------|
| **Router** | `entrypoint/internal/gateway/proxy.(*Router).ServeHTTP` | HTTP 路由分发 |
| **Envd Proxy** | `proxy.(*Router).routeEnvd` | 代理请求到 envd (49983) |
| **CI Proxy** | `proxy.(*Router).routeCI` | 代理请求到 Code Interpreter (49999) |
| **Dynamic Port Proxy** | `proxy.(*Router).routeDynamic` | 代理动态端口请求 |
| **Process Manager** | `process.(*Manager).StartAll` | 启动和监管子进程 |
| **Process Reaper** | `process.(*Reaper).Start` | 僵尸进程回收 |
| **Startup Guard** | `proxy.(*StartupGuard).WaitForBackend` | 等待后端就绪 |
| **Config** | `config.LoadFromEnv` | 从环境变量加载配置 |

**关键发现**：
- 支持 `custom-bootstrap` 模式（从字符串中提取到 `custom-bootstrap`）
- 有健康检查端点 `/health`
- 使用 `X-Sandbox-Port` 和 `E2b-Sandbox-Id` HTTP 头
- 错误消息含 `"Sandbox is starting, please retry"` — 说明有启动就绪检测
- 含 CA 证书注入逻辑 (`CA cert injection`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`)

### 2. envd 守护进程 (端口 49983)

**二进制**: `/.fce2b/envd`
**语言**: Go (静态链接)
**版本**: v0.1.14 (从字符串提取)
**源码**: 与 [e2b-dev/infra](https://github.com/e2b-dev/infra/tree/main/packages/envd) 的 envd 同源

这是 E2B 标准的 **sandbox 内守护进程**，提供如下 HTTP API（从 OpenAPI spec `envd.yaml` 确认）：

| 端点 | 方法 | 功能 | 对外开放 |
|------|------|------|----------|
| `/health` | GET | 健康检查 | 是 |
| `/metrics` | GET | 资源使用指标 (CPU, 内存, 磁盘) | 是 |
| `/envs` | GET | 获取环境变量 | 是 |
| `/files` | GET | **下载文件** | 是 |
| `/files` | POST | **上传文件** (multipart/form-data 或 octet-stream) | 是 |
| `/files/compose` | POST | 零拷贝文件合并 | 是 |
| `/init` | POST | 初始化沙箱 (设置 access token, 环境变量, 用户等) | 否 (内部) |
| `/freeze` | POST | 冻结工作负载 cgroup | 否 (内部) |
| `/unfreeze` | POST | 解冻工作负载 cgroup | 否 (内部) |
| `/collapse` | POST | 堆内存整理 | 否 (内部) |
| `/fsfreeze` | POST | 冻结文件系统 | 否 (内部) |
| `/fsthaw` | POST | 解冻文件系统 | 否 (内部) |
| `/upgrade` | POST | envd 热升级 | 否 (内部) |

**额外的 gRPC/Connect 服务**（从 envd Go 包结构确认）：
- `services/filesystem` — 文件系统操作 (gRPC via Connect)
- `services/process` — 进程管理 (gRPC via Connect)

认证方式：`X-Access-Token` HTTP header。

### 3. Code Interpreter (端口 49999) — 本模板未启用

**二进制**: `/.fce2b/sandbox-code-interpreter`
**状态**: `FC_E2B_CODE_INTERPRETER_ENABLED=false`

在 Claude Code 模板中被显式禁用。

### 4. MCP 端口 (50005) — 暴露但实际能力有限

环境变量中声明了 `MCP_PORT=50005`，端口已暴露，但根据官方文档：
- `getMcpUrl()` / `getMcpToken()` **不支持**
- SDK MCP 创建参数 **不支持**
- 仅支持通过 `claude mcp add` 手动注册 MCP Server

## 启动链路

```
docker run → /.fce2b/entrypoint (PID 1, Gateway 进程管理器)
  ├── 1. 加载环境变量配置 (config.LoadFromEnv)
  ├── 2. 启动子进程管理器 (process.(*Manager).StartAll)
  │     ├── 启动 /.fce2b/envd -port 49983
  │     │     └── envd 监听 0.0.0.0:49983
  │     │     └── 提供文件操作 / 进程管理 / 指标 HTTP+gRPC API
  │     └── (如果 FC_E2B_CODE_INTERPRETER_ENABLED=true)
  │           └── 启动 /.fce2b/sandbox-code-interpreter (本模板跳过)
  ├── 3. 启动 HTTP 反向代理 Router
  │     └── 监听 0.0.0.0:5000 (GATEWAY_LISTEN)
  │     └── 路由规则:
  │           ├── /health, /metrics, /envs, /files/* → envd (127.0.0.1:49983)
  │           ├── /init, /freeze, /unfreeze 等内部路由 → envd
  │           ├── Code Interpreter 路由 → 127.0.0.1:49999 (如已启用)
  │           └── 动态端口路由 (X-Sandbox-Port) → 对应端口
  ├── 4. 僵尸进程回收器 (process.(*Reaper))
  └── 5. 等待 orchestrator 调用 /init 完成初始化
        └── /init 设置 access token、环境变量、默认用户等
```

**对外暴露的最终监听进程**:
- **端口 5000**: Gateway (entrypoint) — 所有外部请求的入口
- **端口 49983**: envd — 直接的 sandbox API (通常通过 Gateway 访问)
- **端口 50005**: MCP (暴露但功能受限)

## 关键结论

1. **容器内有 HTTP server**: 有两个。
   - **Gateway** (`/.fce2b/entrypoint`): Go 编写的反向代理，监听 **5000 端口**，是所有外部请求的入口。
   - **envd** (`/.fce2b/envd`): Go 编写的 E2B sandbox 守护进程，监听 **49983 端口**，提供文件上传/下载、进程管理、指标查询等 API。

2. **Server 提供的 API**:
   - 文件上传/下载 (`GET/POST /files`)
   - 文件合并 (`POST /files/compose`)
   - 环境变量查询 (`GET /envs`)
   - 资源指标 (`GET /metrics`)
   - 健康检查 (`GET /health`)
   - 文件系统和进程管理 (gRPC/Connect 协议)
   - 沙箱生命周期管理 (`/init`, `/freeze`, `/unfreeze`, `/upgrade` — 内部接口)

3. **这个 server 是 envd**: 是的，envd v0.1.14，与 E2B 开源基础设施 ([e2b-dev/infra](https://github.com/e2b-dev/infra)) 中的 envd 同源。但阿里云额外加了一层 **Gateway (entrypoint)** 作为反向代理层，这是 FC 平台特有的。

4. **启动链路**: `entrypoint` (Gateway) 是 PID 1，它作为进程管理器启动 `envd`，然后作为反向代理将请求分发给 envd 和其他后端服务。外部通过端口 5000 访问所有功能。

5. **没有我们 SDK 的代码**: 镜像内没有任何 Python SDK（无 `serverless-sandbox`、无 `e2b` SDK）。镜像中的 Python 仅有系统自带的 Python 3.13 + pip，没有额外安装的 Python 包。**SDK 运行在客户端侧**，通过 HTTP 与容器内的 envd API 通信。

6. **Claude Code 是通过 npm 全局安装的**: `@anthropic-ai/claude-code@2.1.211`，包含一个预编译的 Linux x64 原生二进制。CLI 入口在 `/home/user/.local/bin/claude`。Claude Code 本身不是一个 server，它是一个 CLI 工具，由 SDK 通过 `sandbox.commands.run('claude ...')` 调用。

7. **Code Interpreter 在本模板中被禁用** (`FC_E2B_CODE_INTERPRETER_ENABLED=false`)。

8. **镜像预装了丰富的开发工具**: Node.js, Go, Python 3.13, Bun, pnpm, npm, git 等，pip 配置使用阿里云镜像源。
