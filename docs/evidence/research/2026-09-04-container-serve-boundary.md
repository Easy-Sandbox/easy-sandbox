# 容器内服务边界 (envd) 与"注册式自定义命令"可行性研究

日期: 2026-09-04 | 任务: #94 | 性质: 只读架构研究, 未修改任何产品代码

证据基准: 结论以稳定层 `transport/` `protocol/` `compat/` `session/`
+ `pyproject.toml` + `examples/` 为准。`api/` `models/template.py`
`docs/design/` 正被 #85/#87 并行编辑, 引用处均标注"可能在变"。

---

## 0. 摘要判定 (Summary Verdict)

| # | 问题 | 判定 | 置信度 |
|---|------|------|--------|
| Q1 | 项目性质 | 纯客户端 SDK + CLI，**不自管/不自启容器** | 高（代码 + 依赖双证） |
| Q2 | 容器内承接方 | 平台侧 **envd**（+ gatewayd），**本仓库零服务端代码** | 高 |
| **Q3** | **envd 来源** | **平台在模板构建期注入（builder 模式）；非本仓库、非模板作者职责** | **中高**（官方文档明确；仓库内**无**直接证据） |
| Q4 | ports 隧道 | 纯客户端本地字符串拼接，网关按 `{port}-` 前缀路由 | 高 |
| Q5 | custom_commands | 就是占位符替换后的 **shell 字符串**，走 envd process API | 高 |
| Q6 | 用户设想 | 断言"没有这个 server sandbox 无法运行"**方向错误** | 高 |

### Q3 关键判定（一句话）

对任意自定义/空镜像，envd **由阿里云 FC 平台在模板构建阶段注入**
（`X-E2B-Template-Build-Mode: builder` —— 官方原文："构建时，平台会临时启动一个
FC 函数，由这个 builder 函数拉取源镜像、**加入云沙箱运行所需的依赖**，并推送为目标镜像"）。
因此 `upload / download / runshell / code` 在自定义镜像上**开箱即用**，但**有硬性前提**：

- 硬性：架构 `linux/amd64`；ACR 镜像未开镜像加速
- 硬性：`/etc/passwd`、`/etc/group` 为标准文件且**可写** —— 否则 "gatewayd 无法初始化默认用户，容器启动失败"
- 条件：镜像内存在**固定路径** `/bin/bash` —— 否则 "commands.run、PTY 失败"
- 条件：PATH 中有 `python3`/`python` —— 否则 "Python run_code 不可用"；有 `node` 否则 JS run_code 不可用

反之，`direct` 模式**不注入**："不执行镜像转换，直接把源镜像作为 custom-container
模板函数镜像。**源镜像需要已经具备 E2B 运行依赖**。" 官方镜像
`fc-e2b-registry.{region}.cr.aliyuncs.com/runtime/base|code-interpreter-v1` 属于
"已经注入 envd 等运行依赖"的 E2B 兼容镜像。

> **诚实声明（重要）**：本仓库代码**无法自证** envd 是"平台注入"还是"镜像自带"。
> 仓库只把 `envdUrl` / `envdAccessToken` / `envdVersion` 当作平台返回值**消费**，
> 既不含 envd 实现，也不含任何注入逻辑。上述 Q3 判定来自**阿里云官方文档 +
> E2B 官方 OpenAPI**（外部事实），不是来自本仓库代码。若要落地为产品结论，
> 必须做一次真实 `sbox template build` + `sbox exec` 的实测闭环（见 §7 开放问题 O1）。

### 推荐设计选项

**推荐 (c) + (a) 组合**：以"平台已注入 envd、标准能力开箱即用"为**前提事实**（需实测确认），
在此之上，用户的 `@sandbox.register` 应实现为 **(a) 纯客户端的命令定义生成器** ——
复用 envd 既有 process/code 执行，**不引入任何新的容器内 server**。
仅当用户需要**长驻服务**（如 codex 自建 HTTP server）时，才叠加 **(b) ports 暴露**，
且 (b) 也**不需要新 server 框架**，只需 `commands.start()` 后台进程 + `network.get_url(port)`。

---

## 1. Q1 —— 客户端 SDK，不自管容器

**判定：纯客户端 SDK + CLI。** 三条独立证据。

### 1.1 依赖清单里没有任何容器/服务端运行时

`pyproject.toml:28-33`（稳定文件）：

```toml
dependencies = [
    "httpx[http2]>=0.27",
    "websockets>=12.0",
    "pydantic>=2.0",
    "python-dotenv>=1.0",
]
```

无 `docker`、无 `fastapi`/`uvicorn`/`aiohttp`、无 `firecracker`/`containerd` 客户端。
`pyproject.toml:69-70` 只暴露一个 CLI 入口：`sbox = "serverless_sandbox.cli.main:cli"`。
在 `src/` 全量 grep `uvicorn|FastAPI(|app.route|@app.|BaseHTTPRequestHandler|asyncio.start_server`
→ **0 命中**。仓库内不存在任何可被容器内进程运行的 HTTP/WS server 实现。

### 1.2 base URL 与端点构造：两个远程平面，均在阿里云

`src/serverless_sandbox/transport/config.py:37-46`（稳定）：

```python
api_url: str = Field(
    default="https://api.cn-hangzhou.e2b.fc.aliyuncs.com",
    description="Platform API URL",
)
domain: str = Field(
    default="cn-hangzhou.e2b.fc.aliyuncs.com",
    description="Data-plane domain",
)
```

- **控制面 / Platform API**：`api_url` → `transport/http.py:42-55`
  `_get_platform_client()` 用它作 `httpx.AsyncClient(base_url=self._config.api_url)`。
- **数据面 / envd**：`transport/config.py:19-20` `ENVD_PORT: int = 49983`（注释"envd 数据平面固定端口（已实测验证）"），
  `transport/config.py:81-86`：

```python
def build_envd_url(self, sandbox_id: str) -> str:
    """构建 envd 数据平面 URL（已实测验证）。
    格式: https://{ENVD_PORT}-{sandbox_id}.{domain}
    """
    return f"https://{ENVD_PORT}-{sandbox_id}.{self.domain}"
```

- 地域自动推导：`transport/config.py:248-250`
  `merged.setdefault("api_url", f"https://api.{merged['region']}.e2b.fc.aliyuncs.com")` /
  `merged.setdefault("domain", f"{merged['region']}.e2b.fc.aliyuncs.com")`。
- 与 `models/config.py:27-35` 的 `api_url_for_region()` / `domain_for_region()` 一致。

### 1.3 生命周期全部委托给远端 REST；session/ 只是本地元数据

`protocol/sandbox.py:1-7` docstring："Platform API protocol — sandbox lifecycle
management (REST) … 路径无 /api/v1 前缀（已实测验证）"。逐个方法都是 HTTP 调用，
没有本地容器操作：

| 操作 | 证据 | 请求 |
|------|------|------|
| create | `protocol/sandbox.py:35,44` | `POST /sandboxes` → 201 |
| list | `protocol/sandbox.py:60,67` | `GET /sandboxes` |
| get_info | `protocol/sandbox.py:96,99` | `GET /sandboxes/{id}` |
| kill | `protocol/sandbox.py:106,110` | `DELETE /sandboxes/{id}` → 204 |
| set_timeout | `protocol/sandbox.py:120-127` | `POST /sandboxes/{id}/timeout` |
| pause/resume | `protocol/sandbox.py:150-172` | `POST /sandboxes/{id}/pause\|resume`（标注"逆向推断"） |

`session/` 层（稳定）**不是**容器编排，只是客户端侧的会话元数据持久化：
`session/local.py:1-5` "Sessions are persisted as JSON files under `~/.sbox/sessions/`"；
`session/database.py:1-4` "支持 SQLite (本地) 和 PostgreSQL (远程)"；
`session/oss.py:1-4` "OSS Session 存储后端"。

`compat/sandbox.py:1-9` 自我定位为 "E2B SDK compatibility layer … drop-in
replacement for `e2b.Sandbox`"，并在 `:44` 直接 `from serverless_sandbox.api.sandbox import Sandbox`
—— 兼容层只是再导出，无独立运行时。

---

## 2. Q2 —— 谁在容器内"承接"？边界精确定位

**判定：平台侧 `envd`（in-container daemon）承接 files/process/code/terminal；
端口访问由平台网关按 host 前缀路由到容器内任意监听进程（不经过 envd）。
本仓库/模板不需要、也没有 ship 任何 server 进程。**

### 2.1 边界的物理位置：一个 per-sandbox 的 envd base URL

`transport/http.py:1-7` docstring（稳定）：

```
"""Async HTTP client for Platform API and sandbox envd API.
…
envd URL 格式: https://49983-{sandbox_id}.{domain}（已实测验证）
"""
```

`transport/http.py:57-68` `_create_envd_client()`：
`httpx.AsyncClient(base_url=envd_url, http2=…, timeout=…)`，按 URL 分池缓存
（`self._envd_clients: dict[str, httpx.AsyncClient]`，`:40`）。
注释 `:26-28` 明说 "envd clients are created on demand (different sandboxes may
have different base URLs)"。

**这个 base URL 从哪来？** `api/sandbox.py:138-141`（⚠️ 正在被 #85 编辑）：

```python
@property
def url(self) -> str:
    """The envd URL for this sandbox."""
    return self._info.envd_url or ""
```

`models/sandbox.py:101`：`envd_url: str | None = Field(default=None, alias="envdUrl")`。
即 **envd 地址由平台在 create/get 响应里下发**，客户端只是消费。

### 2.2 认证与路由 header：证明"网关 → 容器内 envd:49983"

`transport/auth.py:25-30`（稳定，全部标注"已实测验证"）：

```python
PLATFORM_AUTH_HEADER = "Authorization"   # 已实测验证：Bearer token 认证
ENVD_AUTH_HEADER = "X-Access-Token"
ENVD_SANDBOX_ID_HEADER = "E2b-Sandbox-Id"
ENVD_SANDBOX_PORT_HEADER = "E2b-Sandbox-Port"
_ENVD_BASIC_AUTH = base64.b64encode(b"user:").decode("ascii")  # 已实测验证
```

`transport/auth.py:132-184` `EnvdTokenManager`：

```
envd 认证需要四个 header（已实测验证）：
- X-Access-Token: {envd_access_token}
- E2b-Sandbox-Id: {sandbox_id}
- E2b-Sandbox-Port: 49983
- Authorization: Basic {base64("user:")}
```

`:177-184` 实际构造，其中 `headers[ENVD_SANDBOX_PORT_HEADER] = "49983"`（硬编码）。

**这三个 header 就是边界的语义**：`E2b-Sandbox-Id` 告诉网关"哪个沙箱"，
`E2b-Sandbox-Port: 49983` 告诉网关"转给容器内监听 49983 的那个进程"——即 envd。
`Authorization: Basic base64("user:")`（空密码 + 用户名 `user`）指定容器内 OS 用户。

外部权威印证（E2B 官方 OpenAPI，`/process.Process/Start`）：
- "Sandbox endpoints (envd) are served on the **shared sandbox host** …
  target a specific sandbox with the `E2b-Sandbox-Id` and `E2b-Sandbox-Port` headers."
- `E2b-Sandbox-Port`: "**Port envd listens on inside the sandbox (default 49983)**"
- `SandboxUserAuth` (http basic): "Optional system user for the operation. Sets file
  ownership and resolves relative paths. **Pass the desired username with no password.**"
  → 精确解释 `_ENVD_BASIC_AUTH = base64("user:")`。
- `SandboxAccessTokenAuth`: apiKey in header `X-Access-Token` = `envdAccessToken`，
  由 `POST /sandboxes`、`GET /sandboxes/{id}` 等返回。

envd token 的来源链：`protocol/sandbox.py:38` 响应体含 `envdAccessToken, envdVersion`
→ `models/sandbox.py:83-84` `envd_access_token` / `envd_version` 字段
→ `api/sandbox.py:285` `EnvdTokenManager(info.envd_access_token, sandbox_id=info.sandbox_id)`
（connect 路径同：`api/sandbox.py:336`）。
`transport/auth.py:5-8` 概括："After sandbox creation, envd API uses envdAccessToken
from create response, sent via multiple headers (X-Access-Token, E2b-Sandbox-Id, etc. 已实测验证)."

### 2.3 每个能力发往哪个 base URL / 端点 / 协议（逐项定位）

`transport/http.py` 提供**四种**出站方法，恰好对应四种协议形态：

| 方法 | 行号 | 目标 | 形态 |
|------|------|------|------|
| `platform_request` | `:70-108` | `config.api_url`（Platform API） | 普通 REST + `Authorization: Bearer` |
| `envd_request` | `:110-156` | per-sandbox `envd_url` | Connect unary RPC，`Content-Type: application/connect+json`（`:135`） |
| `envd_stream` | `:158-207` | 同上 | Connect **server-streaming**，二进制信封分帧 |
| `envd_http_request` | `:209-249` | 同上 | **纯 HTTP（非 Connect）**，docstring `:221-225`："Used for file upload/download which use standard HTTP rather than Connect protocol (已实测验证)" |

**逐能力落点**：

| 能力 | 客户端入口 | 协议层 | 实际端点 | 形态 | 容器内承接者 |
|------|-----------|--------|---------|------|-------------|
| files 元数据（stat/list/mkdir/rm/move/watch） | `api/files.py`（⚠️#85） | `protocol/filesystem.py:90-194` | `/filesystem.Filesystem/{Stat,ListDir,MakeDir,Remove,Move,WatchDir}` | Connect unary / streaming | **envd** |
| **files upload** | `api/files.py:upload_url` → `:254` | `protocol/filesystem.py:198-218` | `POST {envd_url}/files?path={path}&username=user`（multipart，→201） | **纯 HTTP** | **envd** |
| **files download** | `api/files.py:download_url` → `:269` | `protocol/filesystem.py:220-239` | `GET {envd_url}/files?path={path}&username=user`（→200） | **纯 HTTP** | **envd** |
| process（shell/run/start/list/kill/stdin/signal） | `api/commands.py:55-248`（⚠️#85） | `protocol/process.py:109-262` | `/process.Process/{Start,List,Connect,Update,SendInput,SendSignal}` | Connect，Start/Connect 为 streaming | **envd** |
| code（run_code/contexts） | `api/code.py`（⚠️#85） | `protocol/code_interpreter.py:47-190` | `/code.CodeInterpreter/{Execute,CreateContext,ListContexts,RestartContext,RemoveContext}` | Connect unary（**标注"逆向推断"**，`:3-4,28`） | **envd**（+ 镜像内 python3/node） |
| terminal（PTY） | `api/sandbox.py:505-533`（⚠️#85） | `protocol/terminal.py:32-68` | `wss://{envd_url}/terminal`（`:48-49` 由 https→wss 拼接） | **WebSocket**，resize 用 JSON 控制帧（`:87-98`） | **envd**（⚠️ 未标注实测，见 §7 O3） |
| ports | `api/network.py:39-66`（⚠️#85） | `protocol/port.py:24-58` | **不发请求**，本地拼 `{port}-{sandbox_id}.{domain}` | 无 | **平台网关 → 容器内任意监听进程** |
| sandbox 生命周期 | `api/sandbox.py` | `protocol/sandbox.py` | Platform API REST | REST | 平台控制面（非容器内） |
| template 构建 | `api/template.py:39-113`（⚠️#85） | `protocol/template.py:44-91` | `POST /templates` body `{"dockerfile": …}` → 202 | REST | 平台构建流水线（非容器内） |

### 2.4 确认：Connect streaming 用**二进制信封分帧**，不是 NDJSON

任务给定的已知细节在代码中得到印证。`transport/codec.py:1-9`：

```
Streaming responses use binary envelope framing (已实测验证):
  flags (1 byte) + length (4 bytes big-endian) + JSON payload
  flags=0x00: data frame, flags=0x02: end-of-stream/trailer frame
```

`transport/codec.py:98-141` `parse_streaming_frames()`：`FRAME_HEADER_SIZE = 5`，
`flags = data[pos]`、`length = struct.unpack(">I", data[pos+1:pos+5])[0]`，
`if flags == 0x02: continue  # Trailer frame, skip`。
调用侧 `transport/http.py:194-202` 用 `response.aiter_bytes()` 累积原始字节后一次性解帧
（**不是** `aiter_lines()`）。

> ⚠️ **文档内部不一致（陈旧注释）**：`transport/codec.py:54-55` 的 class docstring 仍写
> "For streaming responses, each frame is a separate JSON object separated by newlines
> (NDJSON-like)"，`:74-88` 的 `decode_streaming_frame()` 也仍按 NDJSON 单行解码。
> 同样 `.agents/notes/proposed/feature/transport-streaming.md:6` 写 "in NDJSON format"。
> **实际生效路径是二进制信封**（`:98-141` + `http.py:200`），NDJSON 分支是遗留死代码/陈旧描述。
> 这与项目记忆中"FC Sandbox envd Connect streaming uses binary envelope framing not NDJSON"一致。

---

## 3. Q3 —— envd 是平台注入，还是必须 bake 进镜像？【关键判定】

### 3.1 仓库内证据：**只能证明"不是本仓库/模板作者写的"，不能证明"如何进镜像"**

**(a) 模板 Dockerfile 生成路径完全不含 envd。** `models/template.py:179-200`
（⚠️ 该文件正被 #85 编辑）`SandboxTemplate.to_dockerfile()`：

```python
lines = [f"FROM {self.base}"]
… apt-get install … / pip install … / npm install -g …
for cmd in self.commands: lines.append(f"RUN {cmd}")
for key, val in self.env.items(): lines.append(f"ENV {key}={val}")
for src, dst in self.copy_files.items(): lines.append(f"COPY {src} {dst}")
```

无 envd 二进制下载、无 ENTRYPOINT 改写、无 daemon 启动。
`api/image.py:151-174`（⚠️#85）的链式 `Image.to_dockerfile()` 同样只有
`FROM {base}` + steps + `CMD {entrypoint}`。

**(b) 构建请求只发 Dockerfile 文本，没有任何"注入运行依赖"的开关。**
`protocol/template.py:61-71`：

```python
payload: dict[str, Any] = {"dockerfile": dockerfile}
if alias is not None: payload["alias"] = alias
if cpu_count is not None: payload["cpuCount"] = cpu_count
if memory_mb is not None: payload["memoryMB"] = memory_mb
if start_cmd is not None: payload["startCmd"] = start_cmd
if ready_cmd is not None: payload["readyCmd"] = ready_cmd
```

→ `POST /templates`（`:74-76`）。**没有** `X-E2B-Template-Build-Mode` 等 header，
全仓 grep `X-E2B-Template|Build-Mode|gatewayd` → **0 命中**。

**(c) 最强的仓库内旁证：`examples/templates/codex/` 就是"任意镜像装 codex"这个场景，
它的 Dockerfile 里没有任何 envd。** `examples/templates/codex/Dockerfile:1` `FROM ubuntu:22.04`，
`:37` `RUN npm install -g @openai/codex`，`:48` `CMD ["bash"]` —— 全文 49 行，
**零** envd/gatewayd/daemon 相关内容，也没有 ENTRYPOINT 改写。
而同目录 `sandbox-template.yaml:36-39` 却声明：

```yaml
capabilities:
  - shell
  - files
  - code
```

这三项能力**全部**由 envd 承接（见 §2.3）。也就是说，该模板的作者在
"镜像里完全没有 envd"的前提下，**理所当然地假定 shell/files/code 可用**。
这是本仓库对 Q3 的**隐含假设**：envd 不是镜像作者的事。
`examples/templates/README.md:39-43` 的模板总览表同样显示 5 个模板 base 均为
`ubuntu:22.04` / `node:20-slim` / playwright 镜像等**普通公共镜像**，且都声明了
`shell files code`。

**(d) 能力模型的语义指向"模板声明"而非"镜像自带"。** `models/template.py:18-31`（⚠️#85）：

```python
STANDARD_CAPABILITIES: frozenset[str] = frozenset({"shell","files","code","terminal","ports"})
DEFAULT_CAPABILITIES: frozenset[str] = frozenset({"shell","files","code"})
"""System default baseline — applied when a template declares no capabilities.
``terminal`` and ``ports`` must be declared explicitly by the template."""
```

`api/capability.py:198-205`（⚠️#85）在解析不到模板时 `logger.warning("Could not
resolve capabilities for template %r; falling back to DEFAULT_CAPABILITIES")` 并
**默认放行 shell/files/code**。若 envd 需要镜像自带，这个"默认放行"会是危险的乐观假设；
项目记忆记载该模型的设计动机是"eliminate default guarantees … 当模板缺少后端服务时
会静默失败"——说明团队**已意识到**能力可用性取决于容器内是否有服务，
但**仍把 shell/files/code 设为默认基线**，等价于假定"平台总会提供 envd"。

### 3.2 仓库外权威证据（决定性）

仓库内查不到答案，因此引入两个一手来源。**这是本报告中唯一"非仓库代码"的结论来源，
已明确标注，供 leader 判断权重。**

**来源 A —— 阿里云官方文档《构建自定义镜像模板》**
`https://help.aliyun.com/zh/functioncompute/build-a-custom-image-template`
（2026-09-04 抓取）：

1. 构建模式 header：`X-E2B-Template-Build-Mode: builder | direct`
   —— "builder 会使用临时 FC 函数生成适配云沙箱的目标镜像；direct 会直接使用源镜像。"
2. **builder（默认给普通业务镜像用）**：
   > "构建时，平台会临时启动一个 FC 函数，由这个 builder 函数拉取源镜像、
   > **加入云沙箱运行所需的依赖**，并推送为目标镜像；模板最终使用这个目标镜像
   > 创建沙箱运行环境。该临时函数创建在您自己的账号下，构建期间会产生少量函数计算费用。"
3. **direct**：
   > "不执行镜像转换，直接把源镜像作为 custom-container 模板函数镜像。
   > **源镜像需要已经具备 E2B 运行依赖**。"
4. 排查章节直接点名 envd：
   > "可以临时使用已有 E2B 兼容镜像做对照验证。这类镜像**已经注入 envd 等运行依赖**，
   > 通常更容易排除镜像适配问题。"
5. 镜像要求表（决定"开箱即用"的**前提条件**）：

| 级别 | 要求 | 不满足时影响（官方原文） |
|------|------|------------------------|
| 硬性 | linux/amd64；多架构 manifest 须含 amd64 变体 | Template 转换直接失败 |
| 硬性 | ACR 镜像未开启镜像加速 | Template 转换直接失败 |
| 条件 | 镜像内存在**固定路径** `/bin/bash` | **commands.run、PTY 失败** |
| 硬性 | `/etc/passwd`、`/etc/group` 为标准文件且可写 | **gatewayd 无法初始化默认用户，容器启动失败** |
| 条件 | PATH 中有 `python3` 或 `python` | Python run_code 不可用 |
| 条件 | PATH 中有 `node` | JavaScript run_code 不可用 |

6. `run_code` 的实现方式印证"envd 只是调度者，真正执行靠镜像内解释器"：
   > "run_code 会**调用镜像的 python3 命令**执行代码，如果镜像不包含 python3
   > 或相关依赖，可能会导致执行失败。"
7. 官方 E2B 兼容镜像：`fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/base:v0.0.44`、
   `…/runtime/code-interpreter-v1:v0.0.44`。

**来源 B —— 阿里云官方文档《E2B 兼容说明》**
`https://help.aliyun.com/zh/functioncompute/e2b-compatibility-description`
（2026-09-04 抓取）。**证明云沙箱容器内确实跑着 envd，且版本由平台决定**：

> "云沙箱当前不支持通过 metadata 参数附加文件自定义元数据。以 Python SDK
> `e2b==2.31.0` 为例，方法签名虽然接受 metadata，但 **SDK 检测到 Sandbox 使用
> envd 0.5.2 后**，会在发送写入请求前抛出 `TemplateException: File metadata
> requires envd 0.6.2 or later.`"

→ envd 是**沙箱侧运行时组件**、版本随平台/镜像变化（本 SDK 的
`models/sandbox.py:84` `envd_version` 字段正是承接这一返回值）。
同文档还确认能力边界与本 SDK 的门控一致：Commands 兼容（含 `sendStdin`、PTY）、
Filesystem **部分**兼容（不支持自定义元数据）、Code Interpreter 兼容
（`language` 支持 Python/JS/TS/Bash，**不支持 Java 和 R**）、
Sandbox 兼容（`getHost(port)`、`uploadUrl`/`downloadUrl`）、
Logs / Network Config Update 受限、Snapshots / Volume / Team 暂不兼容。
另："交互式终端和依赖 TTY 的任务使用 `sandbox.pty` API" —— 见 §7 O3。

**来源 C —— E2B 官方 OpenAPI**（`https://e2b.dev/docs/api-reference/process/start`）：

> "Platform endpoints are served on api.e2b.app. **Sandbox endpoints (envd) are
> served on the shared sandbox host** (sandbox.e2b.app); target a specific sandbox
> with the `E2b-Sandbox-Id` and `E2b-Sandbox-Port` headers."
> server url `https://sandbox.{domain}` — "**Sandbox API (envd) - runs inside each sandbox**"
> `E2b-Sandbox-Port`: "**Port envd listens on inside the sandbox (default 49983)**"

→ 与本 SDK `transport/config.py:19-20` 的 `ENVD_PORT = 49983`、
`transport/auth.py:183` 的 `E2b-Sandbox-Port: 49983` **完全吻合**，
证明本 SDK 对接的确实是标准 E2B envd 协议，边界定位无误。

### 3.3 仓库内文档：有帮助但**已证实存在陈旧错误**，只作参考

- `docs/design/architecture.md:56-57`：区分 "Platform API（REST）" 与
  "Sandbox envd API（Connect 协议）：沙箱内部操作（进程、文件、终端），
  通过 HTTP + WebSocket 与沙箱 envd 通信" —— **方向正确**，与代码一致。
- `docs/DESIGN.md:155-164` 描述 envdAccessToken 双 Token 流：
  "1. X-API-KEY → Platform API (POST /sandboxes) → 返回 sandboxId + envdAccessToken
  … 3. X-Access-Token (envdAccessToken) → Sandbox envd API（进程/文件/代码执行）"
  —— **方向正确**（细节差异：`transport/auth.py:26,58` 实测为
  `Authorization: Bearer`，非文档所写 `X-API-KEY`）。
- ❌ **陈旧错误示例（说明"以代码为准"的必要性）**：
  `docs/DESIGN.md:192` 与 `docs/design/architecture.md:65` 均称
  "`protocol.port` | 端口转发与映射管理（**Platform API — HTTP REST**）"，
  但 `protocol/port.py:15-18` 实际写的是
  "端口 URL 为客户端本地计算，**不需要服务端 API 调用**。所有方法均为**纯本地计算**，
  不涉及任何网络请求"。文档与代码**直接矛盾**，代码为准。
- `docs/research/e2b-analysis.md:296-332` 的"控制面 + 数据面"双层架构描述与代码一致，
  但其 `:95-98` 给出的端点示例（`agent-sandbox.{region}.fc.aliyuncs.com`）与代码里
  实测的 `api.{region}.e2b.fc.aliyuncs.com` **不同**，该研究文档亦已陈旧。
- `.agents/notes/**` 全量 grep `envd` 只命中 5 个文件
  （`transport-http.md`、`transport-streaming.md`、`transport-auth.md`、
  `2026-09-02-dual-auth-mode.md`、`2026-09-02-self-implement-e2b-protocol.md`），
  **全部只讨论客户端如何调 envd，无一讨论 envd 从哪来**。
  即：**没有任何 ADR 回答 Q3**。
  `2026-09-02-self-implement-e2b-protocol.md:8-9` 的决策是
  "Self-implement the E2B protocol using httpx + websockets" —— 再次确认本项目定位是协议客户端。

### 3.4 Q3 判定矩阵：空/自定义镜像上各能力能否开箱即用

前提：走**默认 builder 模式**（普通业务镜像），镜像满足硬性要求。

| 能力 | 开箱即用？ | 依赖 | 失败条件 |
|------|-----------|------|---------|
| files upload/download | **是** | envd（平台注入） | 无镜像侧前提；envd 未注入（direct 模式 + 非 E2B 镜像）则全挂 |
| files stat/list/mkdir/rm/move/watch | **是** | envd | 同上 |
| process run/start/list/kill/stdin/signal（shell） | **是** | envd + 镜像内**固定路径** `/bin/bash` | `/bin/bash` 不存在 → 官方明示 "commands.run、PTY 失败" |
| terminal（PTY） | **条件性** | envd + `/bin/bash` | 同上；且本 SDK 的 WS `/terminal` 路径**未实测**（O3） |
| code（run_code, python） | **条件性** | envd + 镜像 PATH 内 `python3`/`python` | 官方明示 "Python run_code 不可用" |
| code（run_code, JS/TS） | **条件性** | envd + 镜像 PATH 内 `node` | 官方明示 "JavaScript run_code 不可用" |
| ports（get_host/get_url） | **是（URL 计算）／条件性（可达）** | 平台网关 + 容器内**确有进程监听该端口** | 官方明示 "调用 getHost(port) 前，需要确保 Sandbox 内已有服务监听对应端口" |
| 容器启动本身 | — | `/etc/passwd`、`/etc/group` 可写 | 官方明示 "gatewayd 无法初始化默认用户，**容器启动失败**" |

**结论**：`upload/download/runshell` 在**任意（满足硬性条件的）自定义镜像上开箱即用**，
因为 envd/gatewayd 由平台在构建期注入。**用户"没有这个 server 沙箱就跑不起来"的断言，
如果指的是"模板作者必须自己写并 ship 一个 server"，则是错的**；
如果指的是"容器内必须存在 envd 这个 server 进程"，则**是对的，但那个进程由平台提供，
不是本仓库或模板的责任**。这个区分是本报告最重要的澄清。

---

## 4. Q4 —— ports / get_host(port) 隧道机制

**判定：纯客户端本地字符串拼接（零网络请求）+ 平台泛域名网关按 `{port}-` host 前缀路由。
外部客户端访问容器内长驻服务 = `https://{port}-{sandbox_id}.{domain}` (+ secure 模式下的
`X-Access-Token`)。这条路径完全不经 envd，因此不需要任何"注册"就能暴露任意端口。**

### 4.1 代码路径

`protocol/port.py:1-6`（稳定）：

```
"""Protocol layer — 端口 URL 本地计算。
端口 URL 为客户端本地计算，不需要服务端 API 调用。
已实测验证：端口 URL 格式为 https://{port}-{sandbox_id}.{domain}
其中 sandbox_id 已包含 "sbx-" 前缀（如 "sbx-xxxx"）。"""
```

`:24-36` `get_host()` → `return f"{port}-{sandbox_id}.{domain}"`；
`:38-58` `get_port_url()` → `scheme = "https" if secure else "http"`，
`return f"{scheme}://{host}"`。类 docstring `:17-18` 强调
"所有方法均为纯本地计算，**不涉及任何网络请求**"。

`api/network.py:39-66`（⚠️#85 正在编辑）是暴露给用户的门面，三个方法都先
`check_capability(self._capabilities, "ports")` 再做同样的本地拼接：

```python
def get_host(self, port: int) -> str:
    check_capability(self._capabilities, "ports")
    return f"{port}-{self._sandbox_id}.{self._domain}"

def get_url(self, port: int) -> str:
    check_capability(self._capabilities, "ports")
    scheme = "https" if self._secure else "http"
    return f"{scheme}://{self.get_host(port)}"

def get_access_headers(self) -> dict[str, str]:
    check_capability(self._capabilities, "ports")
    if self._secure and self._access_token:
        return {"X-Access-Token": self._access_token}
    return {}
```

`access_token` 注入点：`api/sandbox.py:187`
`access_token=self._envd_token.token if self._envd_token else None`
—— 即**端口访问复用 envd 的同一个 access token**，没有独立的端口凭证体系。
`api/sandbox.py:179-189` 构造 `NetworkModule(sandbox_id, domain=self._domain, secure=self._secure, …)`。

### 4.2 关键洞察：envd 自己就是"端口 49983 的普通隧道"

对比两处 URL 构造：

- envd：`transport/config.py:86` → `f"https://{ENVD_PORT}-{sandbox_id}.{self.domain}"`（ENVD_PORT=49983）
- 用户端口：`protocol/port.py:36` → `f"{port}-{sandbox_id}.{domain}"`

**同一个模板，只是端口号不同。** 这说明平台的泛域名网关是**端口无关**的通用隧道：
`https://{任意端口}-{sandbox_id}.{domain}` 都会被路由到该容器内监听那个端口的进程。
envd 只是恰好占据 49983。**推论（对 Q6 至关重要）**：用户在容器内起一个自己的
HTTP server 监听 8080，`get_host(8080)` 立即可达，**无需 envd 参与、无需注册、
无需新增协议**。这正是 codex 自建 HTTP server 的接入方式。

### 4.3 长驻服务的完整可达链路（仓库内已有可运行示例）

`examples/03_web_service.py`（稳定）演示了全链路：

1. `:58-59` `Sandbox.create(template="node-web", …)` —— 必须用声明了 `ports` 的模板；
   `:53-57` 注释明说 "默认的 `base` 模板只回落 DEFAULT_CAPABILITIES（shell/files/code，
   不含 ports），调用 `network.*` 会抛 `CapabilityNotSupportedError(E3004)`"。
2. `:84-88` **后台启动长驻服务**：`reader = await sandbox.commands.start("node server.js", cwd="/app", timeout=300)`
   → `api/commands.py:162-194` `start()` → `protocol/process.py:109-147` → envd
   `/process.Process/Start`（streaming），返回 `StreamReader` **不阻塞**。
3. `:92` `await asyncio.sleep(3)` 等服务就绪（**没有 readiness 探测机制，靠 sleep**）。
4. `:95-96` `url = sandbox.network.get_url(3000)` / `host = sandbox.network.get_host(3000)`。
5. `:102-104` `headers = sandbox.network.get_access_headers()`；`if headers: print(f"需要 Header: {headers}")`。
6. `:107-108` 甚至可在容器内自测：`sandbox.commands.run("curl -s http://localhost:3000/")`。

模板侧声明：`examples/templates/node-web/sandbox-template.yaml:25-31`

```yaml
ports:
  - 3000
capabilities:
  - shell
  - files
  - ports
```

`examples/templates/README.md:270` 提醒："声明端口不等于开启 `ports` capability，
需同时在 `capabilities` 里列出 `ports`" —— 即 `ports:` 列表当前是**纯文档性**的，
门控只看 `capabilities`。

外部印证（阿里云《公网访问》）：官方 Python 示例即
`process = sandbox.commands.run("python3 -m http.server 8000", background=True)` →
`time.sleep(2)` → `host = sandbox.get_host(8000)` → `url = f"https://{host}"` → `urlopen(url)`。
与本 SDK 示例**同构**。官方注意事项：
"调用 getHost(port) 前，需要确保 Sandbox 内已有服务监听对应端口"；
"后台服务不会自动退出，任务完成后要主动终止进程或终止 Sandbox"；
"不要在未鉴权的端口服务中暴露敏感数据"。

---

## 5. Q5 —— custom_commands 端到端：`sbox run` 完整调用链

**判定：是。custom command 就是一个（模板声明的、经 `shlex.quote` 转义与占位符替换后的）
shell 字符串，最终通过 envd 的 `/process.Process/Start` 执行。没有任何独立的
"custom command 执行通道"，也没有容器内注册表。**

### 5.1 七跳调用链

```
[1] CLI 入口
    cli/commands/sandbox.py:489-495
      @click.command("run")
      @click.argument("sandbox_id") @click.argument("command_name")
      @click.option("--arg","-a","args", multiple=True, help="Command argument as key=value (repeatable)")
[2] 参数解析 + 连接
    cli/commands/sandbox.py:517-527  # 拆 key=value；无 "=" → print_error + sys.exit(2)
    cli/commands/sandbox.py:529      sandbox = run_sync(Sandbox.connect(sandbox_id))
[3] 连接期能力解析
    api/sandbox.py:335-341           info = await sandbox_protocol.connect(sandbox_id)
                                     envd_token = EnvdTokenManager(info.envd_access_token, sandbox_id=…)
                                     resolved = await resolve_capabilities(info.template)
    api/capability.py:141-217        # ① 显式 yaml 路径 ② 扫 ~/.sbox/templates/ ③ TODO(Phase2) 线上回落 ④ DEFAULT_CAPABILITIES
    api/capability.py:27             TEMPLATE_CACHE_DIR = Path.home()/".sbox"/"templates"
[4] CLI 调 SDK
    cli/commands/sandbox.py:530      result = run_sync(sandbox.run(command_name, **kwargs))
[5] 命令定义解析 + 占位符替换（纯客户端，无网络）
    api/sandbox.py:592-597           # 未知名 → ValueError + 列出可用命令
    api/sandbox.py:601-610           # 未声明 kwarg → ValueError（防 typo 静默丢失）
    api/sandbox.py:612-618           # 缺必填参数 → ValueError
    api/sandbox.py:620-626           subs[arg.name] = shlex.quote(str(kwargs[arg.name]))
    api/sandbox.py:633-636           cmd_str = re.sub(r"\{(\w+)\}", _sub, cmd_def.cmd)   # 单趟替换，防二次展开注入
    api/sandbox.py:641-647           # 未填充占位符 → ValueError
[6] 退化为普通 shell 执行
    api/sandbox.py:649-654           result = await self.commands.run(cmd_str, timeout=cmd_def.timeout,
                                                                       env=cmd_def.env or None, cwd=cmd_def.cwd)
    api/commands.py:88               check_capability(self._capabilities, "shell")
    api/commands.py:89 + :44-53      command, args = self._parse_cmd(cmd)  # shlex.split
    api/commands.py:94-103           reader = await self._process.start(self._envd_url, self._envd_token, cmd=…, args=…, env=…, cwd=…, timeout=…, user="user")
[7] 落到 envd
    protocol/process.py:35           _START = _codec.build_rpc_path("process","Process","Start")  # → "/process.Process/Start"
    protocol/process.py:127-145      payload = {"process": {"cmd":…, "args":…, "envVars":…, "cwd":…, "user":…}}
                                     raw_stream = self._http.envd_stream(envd_url, _START, payload=…, envd_token=…)
    transport/http.py:173-202        POST {envd_url}/process.Process/Start
                                     Content-Type: application/connect+json + envd 四 header
                                     aiter_bytes() → codec.parse_streaming_frames()（二进制信封）
    api/commands.py:109-124          async for chunk in reader: 收集 STDOUT/STDERR/EXIT → ProcessResult
[8] CLI 输出
    cli/commands/sandbox.py:532-545  --json → print_data({stdout,stderr,exit_code,execution_time})
                                     否则 stdout→click.echo, stderr→click.echo(err=True)
                                     sys.exit(result.exit_code)
```

### 5.2 命令定义模型（声明式，YAML 而非装饰器）

`models/template.py:97-118`（⚠️#85）：

```python
class CustomCommandArg(BaseModel):
    name: str; default: str | None = None; required: bool = False; description: str = ""

class CustomCommand(BaseModel):
    """``cmd`` supports ``{placeholder}`` tokens that are filled at runtime
    from the matching :class:`CustomCommandArg` entries."""
    cmd: str; description: str = ""; cwd: str = "/app"
    env: dict[str,str] = Field(default_factory=dict); timeout: int = 60
    args: list[CustomCommandArg] = Field(default_factory=list)
```

挂在模板上：`models/template.py:164-165`
`custom_commands: dict[str, CustomCommand] = Field(default_factory=dict)`。
发现 API：`api/sandbox.py:537-567` `list_commands()` → `[{name, description, args:[…]}]`；
`api/sandbox.py:148-151` `capabilities` → `frozenset[str]`。

真实声明样例 `examples/templates/codex/sandbox-template.yaml:41-50`：

```yaml
custom_commands:
  run:
    cmd: "codex {prompt}"
    description: "Run Codex CLI with a prompt"
    cwd: "/workspace"
    timeout: 120
    args:
      - name: prompt
        required: true
        description: "Natural language prompt for code generation"
```

`sbox run <sbx> run -a prompt="..."` → 客户端替换 → `codex '...'` → envd 起进程。
**这正是用户想要的效果，且已经存在、已经能跑，只是入口是 YAML 而不是 Python 装饰器。**

### 5.3 决定性先例：`@sandbox` 装饰器**已经实现了**"注册 Python 方法 → 容器内执行"，且**不需要容器内 server**

`declarative/decorator.py`（稳定层，未被 #85/#87 触及）。docstring `:1-12`：

```python
"""@sandbox 装饰器 — 声明式远程执行。
用法::
    @sandbox(template="code-interpreter-v1")
    def analyze(data):
        import pandas as pd
        df = pd.DataFrame(data)
        return df.describe().to_dict()
    # 调用时自动在远程沙箱中执行
    result = analyze({"col1": [1,2,3], "col2": [4,5,6]})
"""
```

其 `_execute()`（`:96-165`）的 6 步，就是用户设想的**无 server 实现**：

| 步 | 行号 | 动作 | 用到的能力 |
|----|------|------|-----------|
| 1 | `:103-131` | `Sandbox.connect(sandbox_id)` 或 `Sandbox.create(template=…)`（`image` 优先 → `Image.build()` 取 template_id，`:115-120`） | Platform API |
| 2 | `:134-136` | `if packages: await sb.commands.run(f"pip install {' '.join(packages)}")` | shell |
| 3 | `:138-139` | `args_data = ser.serialize({"args": list(args), "kwargs": kwargs})` | 客户端 |
| 4 | `:141-148` | `_get_function_source(fn)`（`:179-189`，`inspect.getsource` + 去掉装饰器行 + dedent）→ `_build_execution_script(...)` | 客户端 |
| 5 | `:150-152` | **`await sb.files.write("/tmp/_sandbox_exec.py", script)`** 然后 **`result = await sb.commands.run("python /tmp/_sandbox_exec.py")`** | **files + shell** |
| 6 | `:160-162` | `output = result.stdout.strip(); return ser.deserialize(output)` | shell stdout 即返回通道 |
| — | `:163-165` | `finally: if not keep_alive and not sandbox_id: await sb.kill()` | Platform API |

生成脚本模板 `:211-260`，三种序列化器（json / pickle+cloudpickle / msgpack），形态统一：

```python
args_data = json.loads({repr(args_data)})
args = args_data["args"]; kwargs = args_data["kwargs"]
{func_source}
result = {func_name}(*args, **kwargs)
print(json.dumps(result, default=str))
```

**这直接反驳用户的核心假设。** 一个"注册式远程方法"机制**已经存在且可工作**，
它**完全不需要容器内自建 server**：函数体作为脚本经 envd `files` 写入，
经 envd `process` 执行，结果经 **stdout** 回传，序列化在客户端完成。
用户想要的 `@sandbox.register` 与这个 `@sandbox` 装饰器**在机制上同构**，
差别只在：`@sandbox` 是"运行时把闭包源码搬过去执行"，
用户设想的是"声明一个可被 `sbox run` 调用的具名命令"。后者用 `custom_commands` 已可实现（§5.2）。

⚠️ 该装饰器的两个**已知脆弱点**（与 §7 风险呼应）：
`:136` 的 `pip install` 与 `:152` 的 `python` 都硬编码解释器名，
按官方镜像要求（§3.2 表）"PATH 中存在 python3 或 python" 是**条件性**要求，
最小镜像里可能只有 `python3` 而无 `python` → 该装饰器会失败。

---

## 6. Q6 —— 设计选项与权衡（扎根真实代码）

### 6.0 先纠正前提

用户原话"没有这个 server 沙箱就跑不起来"需要**拆成两句**：

1. ✅ 正确部分：容器内**必须有一个 server 进程**（envd + gatewayd）来承接
   files/process/code/PTY；没有它，SDK 的所有 envd 调用都会
   `httpx.ConnectError` → `ConnectionError_("Failed to connect to sandbox envd: …")`
   （`transport/http.py:152-156, 203-207, 245-249`）。
2. ❌ 错误部分：**这个 server 不是用户/模板/本仓库要写的**。它由阿里云 FC 平台在
   模板构建期注入（builder 模式，§3.2）。因此"用户需要实现一个注册机制来让
   容器内出现一个 server"这个推理链**不成立**。

所以真正需要设计的**不是"容器内 server"**，而是**"客户端侧的命令声明与分发"** ——
而这一层仓库里已经有 80% 的零件（`custom_commands` + `resolve_capabilities` +
`sbox run` + `@sandbox` 装饰器）。
### 6.1 【问题 3】执行落地：一个注册的 `def demo(x, y)` 到底怎么在容器内跑？

**结论：不需要新造执行机制。仓库里已经有一条完整、可运行、且明确"不依赖任何新容器内
server"的源码投递链路 —— `@sandbox` 装饰器（§5.3 已定位）。`@sandbox.register`
应当直接复用它，而不是选 cloudpickle 或新协议。**

#### 6.1.1 现有 `@sandbox` 装饰器的真实投递机制（`declarative/decorator.py`）

逐步读出 `_execute()`（`decorator.py:96-165`）的七步：

| 步 | 代码位置 | 动作 | 依赖的能力 |
|----|---------|------|-----------|
| 1 | `:101-131` | `Sandbox.connect(sandbox_id)` 或 `Sandbox.create(template=…)` | Platform API |
| 2 | `:135-136` | 可选 `sb.commands.run(f"pip install {…}")` | `shell` |
| 3 | `:139` | `ser.serialize({"args": list(args), "kwargs": kwargs})` | 纯本地 |
| 4 | `:142` | `_get_function_source(fn)` = **`inspect.getsource(func)`** | 纯本地 |
| 5 | `:143-148` | `_build_execution_script(...)` 把**函数源码文本**内联进一段 Python 脚本 | 纯本地 |
| 6 | `:151-152` | `sb.files.write("/tmp/_sandbox_exec.py", script)` → `sb.commands.run("python /tmp/_sandbox_exec.py")` | `files` + `shell` |
| 7 | `:160-162` | 读 `result.stdout` → `ser.deserialize(...)` → 返回 | 纯本地 |

**关键机制是"源码文本投递"，不是 pickle、不是新 RPC。**
`_get_function_source()`（`:179-189`）用 `inspect.getsource` 取源码，再 `textwrap.dedent`，
并**主动跳过装饰器行**（从第一行以 `def `/`async def ` 开头处截取）。
这一点对本议题极其重要：它意味着**被 `@sandbox.register` 装饰的函数，其源码可以
干净地剥离装饰器后投递** —— 现有实现已经处理好了"装饰器不随源码进容器"这个问题。

生成的脚本形态（`_build_json_script`，`:211-224`）：

```python
import json, sys
args_data = json.loads(<repr of serialized args>)
args   = args_data["args"]
kwargs = args_data["kwargs"]

<函数源码原文，已 dedent、已去掉装饰器行>

result = <func_name>(*args, **kwargs)
print(json.dumps(result, default=str))
```

即：**函数名被当作脚本内的调用符号直接内联**（`{func_name}`，`:222`），
结果经 `stdout` 回传。这正好就是用户设想的"函数名 → 命令名"语义的**已有实现**。

#### 6.1.2 三种候选投递方式对比（扎根真实代码，不是空谈）

| 方式 | 仓库现状 | 对镜像的要求 | 判定 |
|------|---------|-------------|------|
| **A. 源码文本投递**（`inspect.getsource` + 内联脚本） | **已实现**，`decorator.py:179-224`，三种 serializer 全部走这条路 | 只需 PATH 里有 `python3`/`python`（§3.2 条件性要求） | **推荐**。零新依赖、可读可审计、失败信息直观 |
| **B. cloudpickle 序列化函数对象** | **已实现但仅用于"参数/返回值"**，不用于函数本体：`_build_pickle_script`（`:227-242`）里 `func_source` 仍是**源码文本**内联，cloudpickle 只 `loads` 参数、`dumps` 结果 | **额外要求容器内预装 `cloudpickle`**；`decorator.py:232` 直接 `import cloudpickle`，镜像没有就 `ModuleNotFoundError` | **不推荐作为主路径**。仓库自己都没用它投递函数体，说明设计者已回避其部署成本 |
| **C. 交给 envd 的 code 原语**（`sandbox.code.run(script)`） | 已实现（`api/code.py:48-90` → `/code.CodeInterpreter/Execute`） | 需 `code` 能力 + 镜像内解释器 | **可作为 A 的备选传输**，但注意 `api/code.py:30-31` 自陈"RPC 路径基于 E2B SDK 逆向推断，阿里云官方文档未公开 Code Interpreter 的底层传输细节，需实测验证" |

**为什么 A 优于 C（就本议题而言）**：A 走 `files.write` + `commands.run`，
这两个是 §3.2 官方文档明确"Commands 兼容 / Filesystem 兼容"、且 §3.4 判定为
**开箱即用**的能力；C 依赖的 Code Interpreter RPC 路径在本仓库里被标注为
"逆向推断、未实测"。用 A 落在**已实测验证**的路径上，用 C 落在**推断**的路径上。

#### 6.1.3 A 路线的两个已知脆弱点（必须写进设计约束）

1. **硬编码解释器名**：`decorator.py:136` 用 `pip install`、`:152` 用
   `python /tmp/_sandbox_exec.py`。而 §3.2 官方镜像要求表写的是"PATH 中有
   `python3` **或** `python`"——是**二选一的条件性要求**。最小镜像里可能只有
   `python3` 而无 `python`，此时 A 路线直接失败。**这是必须修的 bug 级问题**
   （建议 `sys.executable` 探测或 `python3` 优先回退 `python`）。
2. **硬编码临时路径**：`/tmp/_sandbox_exec.py` 是固定名（`:151`），
   同一沙箱内并发调用会**互相覆盖**。`@sandbox.register` 若支持并发调用，
   必须改为唯一路径（如 `/tmp/_sbox_{uuid}.py`）。

> **问题 3 一句话回答**：走**源码投递**（A）。机制已存在且已验证，
> `@sandbox.register` 的增量只是"把 `inspect.signature` 也读出来生成命令元数据"，
> 执行部分**一行都不用新写**。cloudpickle 不要作为主路径（容器内依赖成本）。

---

### 6.2 【问题 4】CLI 发现：`sbox run` 是独立进程，它怎么知道有 `demo`？

**结论：现有发现链是"连上沙箱 → 本地扫 YAML"，`demo` 这种"项目里的 Python 函数"
在当前链路上完全不可见。这是本次调研定位到的最大单点缺口。但好消息是：CLI 侧的
承接点已经存在（`sbox run` 的 `--arg` 解析处），且映射层的位置在架构上是明确的。**

#### 6.2.1 现有发现链（逐跳实证）

`sbox run` 的 CLI 实现（`cli/commands/sandbox.py:492-545`）只有 4 跳，非常薄：

1. `:517-527` 解析 `--arg k=v`（可重复）→ `kwargs: dict[str, str]`。**无类型、无校验**，
   仅做 `"=" in item` 的字符串切分，格式错则 `exit(2)`。
2. `:529` `sandbox = run_sync(Sandbox.connect(sandbox_id))`
3. `:530` `result = run_sync(sandbox.run(command_name, **kwargs))`
4. `:532-545` 打印 stdout/stderr，`sys.exit(result.exit_code)`

而第 2 跳的 `Sandbox.connect`（`api/sandbox.py:304-352`）在 `:341` 调用
`resolved = await resolve_capabilities(info.template)`，
`resolve_capabilities`（`api/capability.py:141-217`）的解析顺序是：

| 顺位 | 实现位置 | 来源 | 状态 |
|------|---------|------|------|
| 1 | `capability.py:162-190` | 显式传入的 `local_yaml_path` | 已实现，但 **CLI 从不传** |
| 2 | `capability.py:193-194` → `_find_local_template`（`:81-124`） | `~/.sbox/templates/**/sandbox-template.yaml` 目录遍历 | **已实现（唯一实际生效的路径）** |
| 3 | `capability.py:196` | `# 3. TODO(Phase2): online fallback — GET /templates/{id} metadata` | **纯注释，零实现** |
| 4 | `capability.py:199-205` | 回落 `DEFAULT_CAPABILITIES` + `logger.warning` | 已实现 |

**所以今天 `sbox run` 能发现的命令 = `~/.sbox/templates` 里某个
`sandbox-template.yaml` 的 `custom_commands:` 段。仅此一条来源。**

`_template_matches()`（`:51-78`）的匹配面刻意做得很宽：`name` 字段、
`alias`/`aliases` 字段（str 或 list 都接受）、以及**所在目录名**。
注释（`:59-63`）说明了理由：匹配太窄会静默回落 `DEFAULT_CAPABILITIES`，
从而**错误地放开**一个实际声明了 `terminal`/`ports` 的模板的门控。
`:88-92` 的 fail-closed 设计同理：匹配到但校验失败时**抛 `TemplateParseError`
而不是跳过**，因为跳过等于静默扩权。这两处安全设计值得在新增发现来源时**照抄**。

#### 6.2.2 缺口：`demo` 为什么今天不可见

用户设想 `def demo(x, y)` 写在**项目代码里**，而现有链路的唯一来源是
**`~/.sbox/templates` 下的 YAML**。两者之间没有任何桥：

- 仓库里**不存在**"扫描项目目录找带注册装饰器的 Python 模块"的代码。
  全量搜索确认：`resolve_capabilities` 只有 YAML 一条路径；
  `utils/registry.py` 的 `_fetch_local`（`:121-136`）虽然读本地目录，
  但它只认 `sandbox-template.yaml` 或 `Dockerfile`，**不导入任何 Python 模块**。
- `cli/main.py:34-51` 的 `list_commands`/`get_command` 是 **Click 框架自身的
  懒加载子命令机制**（`_lazy_subcommands` 映射到 `module:attr`），
  与"发现沙箱命令"无关 —— 不要把它误认为可复用的发现钩子。
  它的存在反而印证了 `rejected/2026-09-03-capability-model-alternatives.md`
  否决"顶层 verb 动态注册"的理由：命令命名空间已经被 Click 的懒加载占用，
  再往里塞模板命令会**污染 `--help` 与补全**。

#### 6.2.3 "函数签名 → CLI 选项"的映射应该挂在哪一层？

这是问题 4 的核心。三个候选层，逐一评估：

| 候选层 | 挂这里的后果 | 判定 |
|--------|-------------|------|
| **CLI 层**（在 `cli/commands/sandbox.py` 里动态生成 `--x`/`--y`） | 需要**先知道命令存在**才能建 Click option，即必须在 `sbox run` 之前完成一次发现；而发现今天需要 `Sandbox.connect`（一次网络往返 + 一个活沙箱）。`sbox run <id> --help` 就得先连沙箱，**离线不可用、`--help` 变慢且可能失败** | ❌ 不推荐作为唯一层 |
| **SDK 模型层**（扩展 `CustomCommandArg` 增加类型字段） | `models/template.py:97-103` 的 `CustomCommandArg` 现在只有 `name/default/required/description`，**没有 `type` 字段**（`default` 的类型是 `str \| None`）。加一个 `type: str \| None` 即可，且**向后兼容**（省略 = 字符串，与现状一致） | ✅ **推荐落点** |
| **注册装饰器层**（`@sandbox.register` 用 `inspect.signature` 生成模型） | 装饰器在**导入时**运行 `inspect.signature(fn)`，把参数名/类型注解/默认值转成 `CustomCommandArg`，产出与 YAML 解析**同构**的 `CustomCommand` 对象 | ✅ **推荐落点（生产者）** |

**推荐架构：把"签名 → 选项"的映射放在装饰器层（生产），把类型信息存进
`CustomCommandArg`（承载），让 CLI 层只做"读 schema → 建 option / 强制类型"（消费）。**

这样做的关键收益：**YAML 声明的命令与 Python 注册的命令收敛到同一个
`CustomCommand` 模型**，下游（`Sandbox.run` 的占位符替换、`list_commands` 的
发现输出、CLI 的 `--arg` 解析）**全部零改动即可复用**。这与
`implemented/architecture/2026-09-03-sdk-capability-surface.md:12` 的既定决策
（"custom commands 统一走 `sandbox.run("name", **args)` 一个显式方法"）完全一致，
也避开了 `rejected/` 里两条被否决的路（顶层 verb 注册、`__getattr__` 魔法属性）。

#### 6.2.4 一条被忽视的既有能力：`sbox run` 的未知命令报错已自带发现提示

`api/sandbox.py:592-597`：命令名不在 `_custom_commands` 里时，抛

```
Unknown custom command 'demo'; available commands: serve, migrate
```

即 **"打错命令名 → 报错里列出可用命令"** 这条最基础的发现路径**已经可用**，
零网络成本。`cli-run-vs-exec.md:28` 也把它写进了验收标准
（"Unknown `command_name` → error listing available commands"）。
`@sandbox.register` 落地后这条提示会自动带上注册的命令名，**无需额外工作**。

---

### 6.3 【问题 5】参数类型强制：哪些能做，哪些必须排除

**结论：`int/float/bool/str` 可以安全强制；`dict/list/file` 必须排除（V1）。
但要注意 —— 现有的 args 模型是"纯字符串、零类型"的，所以类型强制是净新增能力，
不是"打开一个开关"。仓库里已有一个可抄的类型化 schema 先例（MCP `TOOL_SCHEMAS`）。**

#### 6.3.1 现状：args 全程是字符串，且被刻意当作字符串处理

三处证据串起来看，类型信息在整条链路上**根本不存在**：

1. **模型层**：`models/template.py:97-103`
   `CustomCommandArg.default: str | None`。ADR
   `implemented/feature/2026-09-03-custom-commands-schema.md:39-43` 也是同一形状。
   该 ADR 的 `:65` 明确记录了**否决"每命令 JSON-schema"**的理由：
   "Over-engineered for the small, fixed arg shape."
   —— 即"无类型"是**当时的主动决策**，不是遗漏。要改就得先推翻这条否决。
2. **SDK 层**：`api/sandbox.py:569-573` 签名是 `async def run(self, name: str, **kwargs: str)`，
   `:624` 做 `shlex.quote(str(kwargs[arg.name]))` —— **无条件 `str()` 再转义**。
   即使调用方传了 `int`，也会被静默转成字符串。
3. **CLI 层**：`cli/commands/sandbox.py:518-522`，`k, v = item.split("=", 1)`，
   `v` 直接进 `dict[str, str]`。Click 的 `type=` 转换**没有用**。

#### 6.3.2 为什么 `bool` 是四个标量里唯一的坑

`int/float/str` 的强制是单射的、无歧义的。`bool` 不是：

- Python 侧 `bool("False") == True`（非空字符串恒真），**直接用 `bool()` 转换必错**。
- CLI 侧有三种互斥惯例：`--flag`（Click `is_flag=True`，无值）、
  `--x true|false`、`--x 1|0`。三者对"省略该参数"的语义也不同
  （省略 ≠ `False`，因为 `CustomCommandArg` 有 `default` 与 `required` 两个独立字段）。
- 更要紧的是**投递侧**：走 §6.1 的 A 路线时，参数最终是被 `shlex.quote` 进 shell
  命令模板（YAML 路线）或被 `json.dumps` 进脚本（装饰器路线）。
  YAML 路线下 `True` 会被引号包成字符串 `'True'`，
  容器内 Python 收到的是 `"True"` 而不是 `True`。

**建议**：`bool` 走**显式白名单解析**（`{"true","1","yes","y","on"}` → `True`；
`{"false","0","no","n","off"}` → `False`；空串/省略 → 取 `default`；其他 → 报错），
并在 `CustomCommandArg` 上区分"未提供"与"提供了 False"。

#### 6.3.3 必须排除的复杂类型，以及**为什么**（不是"暂时不做"，是"做了会破安全模型"）

| 类型 | 排除理由（扎根现有代码） |
|------|------------------------|
| `dict` / `list` | 现有投递是 `{placeholder}` 文本替换（`api/sandbox.py:636` 的 `re.sub(r"\{(\w+)\}", _sub, cmd_def.cmd)`）。一个 dict 无法安全地塞进 shell 命令模板的**单个占位符**；即便 `shlex.quote` 了整个 JSON 串，容器内还得再解析一次，等于**新增一条未经验证的解析路径**。`custom-commands-schema.md:65` 已经为"小而固定的 arg 形态"否决过 JSON-schema |
| `file` / 路径上传 | 语义上不是"参数强制"，而是"先把文件送进容器再传路径"，是**两步操作**。仓库里已有正确的原语：`files.write`/`files.upload`（`api/files.py`）。把它塞进 `--arg` 会混淆 `run` 的职责边界（`cli-run-vs-exec.md:13` 定的语义分割是 "exec = raw shell; run = template-declared named command"） |
| 任意 Python 对象 | 等价于要求 cloudpickle（§6.1.2 的 B 路线），会把容器内依赖成本重新引入 |

#### 6.3.4 现成可抄的类型化 schema：MCP `TOOL_SCHEMAS`

仓库里**已经有一套带类型、带默认值的参数 schema 实现**，就在
`agent/tools.py:19-158`（7 个工具，JSON Schema 形态）：

```python
{"name": "create_sandbox",
 "description": "创建一个云端沙箱环境。…",
 "inputSchema": {"type": "object", "properties": {
     "template": {"type": "string",  "description": "沙箱模板名称，默认 code-interpreter-v1"},
     "timeout":  {"type": "integer", "description": "沙箱超时时间（秒），默认 300", "default": 300},
     "envs":     {"type": "object",  "additionalProperties": {"type": "string"}}}}}
```

配套还有 `TOOL_SCHEMA_MAP`（`:158`，name → schema 的字典索引）与
`dispatch_tool(name, params, manager)`（`:299-326`，按名派发 + 未知名字抛
`ValueError` + 异常转结构化 error）。

**这三件套（schema 常量 / name→schema 索引 / 按名派发）就是"注册式命令 +
类型化参数 + 发现"的完整微型样板**，与用户设想的 `@sandbox.register`
在结构上一一对应：

| 用户设想 | `agent/tools.py` 里的对应物 |
|---------|---------------------------|
| 命令名 `demo` | `"name": "create_sandbox"` |
| 参数 `x` / `y` | `inputSchema.properties` 的 key |
| 参数类型 | `"type": "string"` / `"type": "integer"` |
| 参数默认值 | `"default": 300` |
| 参数说明 | `"description"` |
| `sbox run demo` | `dispatch_tool("create_sandbox", …)` |
| 列出所有命令 | `TOOL_SCHEMAS` / `TOOL_SCHEMA_MAP` |

> **问题 5 一句话回答**：V1 只做 `str/int/float/bool` 四种标量，`bool` 需显式白名单
> 解析而非 `bool()`；`dict/list/file` **必须排除**（会破坏 `{placeholder}` + `shlex.quote`
> 的注入安全模型）。类型信息加在 `CustomCommandArg` 上，schema 形状**直接抄
> `agent/tools.py` 的 JSON Schema**，不要另造一套。

---

### 6.4 【新增维度】发现 API：两层来源、envd 能不能做、以及鉴权复用

Leader 追加的 discovery 维度，拆成三个子问题逐一给证据。

#### 6.4.1 【子问题 1】envd **不能**暴露 introspection/manifest 端点 —— 这是协议级的硬约束

**判定：不能。而且不是"暂未实现"，是"结构上不可能"。运行时注册的命令若要被远程发现，
只能由用户自建的 in-container server 提供端点。**

**证据 1 —— envd 的端点面是封闭且已完整枚举的。**
仓库内实际使用的全部 envd 端点（`protocol/` 目录逐个读出）：

| 服务 | 端点 | 定义位置 |
|------|------|---------|
| Process | `/process.Process/{Start,List,Connect,Update,SendInput,SendSignal}` | `protocol/process.py:35-40` |
| Filesystem | `/filesystem.Filesystem/{Stat,MakeDir,ListDir,Remove,Move,WatchDir}` | `protocol/filesystem.py:33-38` |
| CodeInterpreter | `/code.CodeInterpreter/{Execute,CreateContext,ListContexts,RestartContext,RemoveContext}` | `protocol/code_interpreter.py:29-33` |
| File (REST) | `POST/GET {envd_url}/files?path=&username=user` | `protocol/filesystem.py:209,230` |
| Terminal (WS) | `{ws_url}/terminal` | `protocol/terminal.py:47-49` |

路径构造只有一种形态：`transport/codec.py:91-96`
`build_rpc_path(package, service, method) -> f"/{package}.{service}/{method}"`。
**没有任何"列出服务/列出方法"的构造入口。**

**证据 2 —— E2B 官方 OpenAPI 的 `Envd` tag 只有 3 个端点，全是运维性质，无一是清单。**
（`https://docs.e2b.dev/llms.txt` 文档索引，2026-09-04 抓取；与 §3.2 来源 C 同一权威面）

```
api-reference/envd/check-the-health-of-the-service   ← 健康检查
api-reference/envd/service-stats                     ← 资源统计
api-reference/envd/environment-variables             ← 环境变量
```

OpenAPI 的 tags 全集是 `Sandboxes / Templates / Tags / Volumes / Envd / Filesystem /
Process / Teams`。**`Envd` tag 下不存在任何 command/manifest/introspection/reflection
端点。** Filesystem tag 的 11 个端点、Process tag 的端点也已逐一核对，同样没有。

**证据 3 —— envd 的版本与实现由平台掌控，我们没有扩展它的通道。**
§3.2 来源 B 的官方原文：SDK "检测到 Sandbox 使用 **envd 0.5.2** 后" 会因
"File metadata requires envd 0.6.2 or later" 抛错。
→ envd 是**平台/镜像侧的固定版本二进制**，能力由平台决定（`models/sandbox.py:84`
的 `envd_version` 字段只是**消费**这个返回值）。本仓库不含 envd 实现（§3.1 已证），
因此**不存在"给 envd 加一个端点"这个选项**。

**证据 4 —— 一个必须避开的陷阱：`process.Process/List` 不是命令发现。**
它的语义是"列出沙箱内**当前正在运行的 OS 进程**"
（第三方 E2B Go 客户端文档同样描述为 "List returns all commands and PTY sessions
**currently running** in the sandbox"）。它返回的是 PID 级运行时状态，
**不是**"这个沙箱支持哪些命名命令 + 参数 schema"。把它当发现 API 用会拿到完全错误的东西。

**推论（直接回答 leader 的二选一提问）**：
因为 envd 协议固定，**运行时注册进活容器的命令，其发现端点只能由用户自建 server 提供**。
但请注意这条路的**代价**，它不是免费的：

- 自建 server 必须监听一个端口，客户端要访问它就必须用 `ports` 能力
  （`api/network.py:39-46` 的 `get_host` 与 `:58-66` 的 `get_access_headers`
  **都被 `check_capability(self._capabilities, "ports")` 门控**）。
- 而 `ports` **不在** `DEFAULT_CAPABILITIES = {shell, files, code}` 里
  （`models/template.py:27-31`；ADR `capability-model.md:12` 明确
  "`terminal` and `ports` are NOT in the baseline and must be declared explicitly"）。
- 更硬的门槛：`command-source-resolution.md:53-57` 记录了一条**已知限制** ——
  平台内置模板（`base`/`code-interpreter`）**不带本地 `sandbox-template.yaml`**，
  因此回落到 `DEFAULT_CAPABILITIES`，其 `terminal`/`ports` 能力
  "在 Phase 2 线上 metadata 兜底就绪前**不可用**"。

→ **结论：在内置模板上，"用户自建 server + ports 暴露发现端点"这条路今天走不通。**
这不是设计选择问题，是被 `ports` 门控 + 内置模板无 YAML 两个既有事实卡住的。

#### 6.4.2 【子问题 2】现有的"发现 API"是什么形态 —— `Sandbox.list_commands()`

**这就是 leader 说的"#83 提到过的发现 API"在代码里的实体。它在
ADR `implemented/architecture/2026-09-03-sdk-capability-surface.md:13` 里被正式命名为
"Discovery API"，并且已实现。**

ADR 原文（`:13`）：
> **Discovery API**: `sandbox.capabilities` returns the effective capability set
> (`frozenset[str]`); `sandbox.list_commands()` returns the template's declared
> custom commands as a **list of plain dicts** (not objects) — each dict carries
> `name` + `description` + `args`. These let users and Agents introspect what a
> sandbox can do.

实现：`api/sandbox.py:537-567`。逐项回答 leader 的三问：

**(a) 它返回什么？** 两个发现面：

1. `sandbox.capabilities` → `frozenset[str]`（`api/sandbox.py:148-151`）
   = 生效的标准能力集（`shell/files/code/terminal/ports` 的子集）
2. `sandbox.list_commands()` → `list[dict]`，每个 dict 形如：

```python
{"name": str,
 "description": str,
 "args": [{"name": str, "required": bool,
           "default": str | None, "description": str}]}
```

**(b) 是否已经有参数 schema？—— 有"半个"。有名字/必填/默认值/说明，但没有类型。**

| schema 要素 | 是否已有 | 证据 |
|------------|---------|------|
| 命令名 | ✅ | `api/sandbox.py:554` `"name": name` |
| 命令说明 | ✅ | `:555` `"description": cmd.description` |
| 参数名 | ✅ | `:558` |
| 参数是否必填 | ✅ | `:559` `"required": arg.required` |
| 参数默认值 | ✅ | `:560` `"default": arg.default` |
| 参数说明 | ✅ | `:561` |
| **参数类型** | ❌ **缺失** | 源头 `models/template.py:97-103` 的 `CustomCommandArg` **无 `type` 字段**，`default` 本身是 `str \| None` |
| 参数枚举/取值域 | ❌ 缺失 | 同上 |
| 返回类型 | ❌ 缺失 | `CustomCommand`（`models/template.py:106-118`）只有 `cmd/description/cwd/env/timeout/args` |

→ **"已有 vs 缺失"的精确答案**：发现 API 的**骨架已经完整可用**（命令名 + 说明 +
参数名/必填/默认值/说明，且已经是 plain-dict 的 JSON 友好形态），
**唯一缺的是参数的类型维度**。而类型维度恰好就是 §6.3 要新增的那一个字段 —— 
两件事是**同一个改动**，不是两个。

**(c) 是否已经做了鉴权门控？—— 完全没有。而且是"结构上不可能有"。**

这是本子问题最重要的发现。`list_commands()` 的三个特征：

1. **它是同步方法**（`def list_commands(self)`，`:537`，不是 `async def`）。
   对比同文件里所有真正走网络的方法：`run`（`:569` `async def`）、
   `get_terminal`（`:505` `async def`）、`create`（`:206` `async def`）。
   → **签名本身就证明它不发任何网络请求。**
2. **它读的是构造期就已固化的本地字典**：`:566` 遍历 `self._custom_commands`，
   而 `self._custom_commands` 在 `__init__`（`:122-124`）里由
   `dict(self._resolved.custom_commands)` 得到；`self._resolved` 来自
   `create()` 的 `:290` / `connect()` 的 `:341` 调用的 `resolve_capabilities(template)` ——
   即 §6.2.1 表格里那条**只扫本地 YAML** 的路径。
3. **它不调用 `check_capability`**：对比同仓库所有其他模块 —— `api/code.py:77`
   `check_capability(self._capabilities, "code")`、`api/files.py:43-45` 的 `_gate()`、
   `api/network.py:45,54,63` 三处 `"ports"`、`api/sandbox.py:524` 的 `"terminal"`。
   **`list_commands()` 与 `capabilities` 属性是全仓库唯一两个不做任何门控的公开面。**

**所以：现有发现 API = 纯本地、零网络、零鉴权、零门控。**
它的"权限"实际上等于"能不能读到 `~/.sbox/templates` 这个本地目录"。

这**符合** leader 区分的 Layer 1 语义（本地静态发现无需鉴权），
但它同时意味着：**Layer 2 的鉴权门控不是"没做好"，而是"这条链路根本不存在"。**
`capability.py:196` 那行 `# 3. TODO(Phase2)` 注释就是这条缺失链路的唯一痕迹。

#### 6.4.3 【子问题 3】鉴权复用：可以复用，但**不是** leader 指的那个函数

**判定：不需要新造任何权限体系 —— 但要点名一个必须避开的误选。**

**⚠️ 先纠正：`api/network.py` 的 `get_access_headers()` 不能用作发现 API 的鉴权来源。**

`api/network.py:58-66` 的实际实现：

```python
def get_access_headers(self) -> dict[str, str]:
    """获取端口访问所需的 HTTP headers。secure 模式下需要 X-Access-Token header。"""
    check_capability(self._capabilities, "ports")     # ← 关键
    if self._secure and self._access_token:
        return {"X-Access-Token": self._access_token}
    return {}
```

三个理由说明它是错的复用对象：

1. **它被 `ports` 能力门控**（`:63`）。而 `ports` 不在 `DEFAULT_CAPABILITIES` 里
   （§6.4.1 已证）。用它做发现 API 的鉴权 = **给发现强加一个绝大多数沙箱不具备的能力前置条件**，
   直接违反 leader 定的"发现权限 ⊆ 执行权限"原则（那会让发现权限**小于**执行权限）。
2. **它的语义是"访问用户暴露在端口上的业务服务"**，不是"访问平台/沙箱控制面"。
   `NetworkModule` 的类 docstring（`api/network.py:19-22`）自陈
   "高层网络接口 — 端口 URL 计算和访问 header 管理。**所有方法均为本地计算，
   不涉及任何网络请求**"。它是给 §4 的 ports 隧道用的凭证生成器。
3. **它在 `secure=False` 时返回空 dict**（`:64-66`），即**无鉴权**。
   把"可能返回零 header"的函数当作鉴权基座，会在非 secure 沙箱上静默变成未鉴权发现。

**✅ 正确的复用对象：两个已经存在的 L1 鉴权面，二选一对应两个发现平面。**

| 发现平面 | 复用的鉴权 | 实现位置 | header 形态 | 状态 |
|---------|-----------|---------|------------|------|
| **Platform 平面**（模板元数据 = 构建期声明的命令） | `AuthProvider.get_headers()` | `transport/auth.py:57-59`（ApiKeyAuth）/ `:113-119`（AkSkAuth） | `Authorization: Bearer <api_key 或 AK/SK 换来的临时 token>` | **已实现、已自动注入、已有 CLI 实证** |
| **envd 平面**（活沙箱内的运行时状态） | `EnvdTokenManager.get_headers()` | `transport/auth.py:166-184` | 4 个 header：`X-Access-Token` + `E2b-Sandbox-Id` + `E2b-Sandbox-Port: 49983` + `Authorization: Basic <base64("user:")>` | **已实现、已实测验证**（源码注释 `:136` "已实测验证"） |

**Platform 平面的自动注入是关键 —— 它让"发现必须鉴权"这件事零成本成立。**
`transport/http.py:70-100` 的 `platform_request()`：

```python
client = await self._get_platform_client()
auth_headers = await self._auth.get_headers()      # :84 ← 无条件注入
all_headers = {**auth_headers}
if headers: all_headers.update(headers)
response = await client.request(..., headers=all_headers)
response.raise_for_status()                        # :99 ← 401/403 直接抛
```

即：**任何走 `platform_request` 的调用都自动带 L1 凭证，且鉴权失败会抛。**
调用方无需也无法绕过。这正是 leader 要的"不需要新造一套权限体系"。

**而且这条链路已经有活的端到端实证 —— `sbox template info`：**

- `protocol/template.py:105-113`：`async def get(template_id)` →
  `platform_request("GET", f"/templates/{template_id}")`，docstring 写 `GET /templates/{id} → 200`
- `cli/commands/template.py:171-198`：`sbox template info <template_id>` 命令，
  `:184-190` 建 config+auth+http_client，`:192-194` 发 `GET /templates/{id}`，`:198` 打印
- 同类还有 `sbox template list`（`:128-168`，`GET /templates`）

**→ 所以"server 级、经鉴权的远程发现"这条链路，在传输层与 CLI 层
已经完整跑通了。`capability.py:196` 缺的只是"把 `TemplateProtocol.get()`
接进 `resolve_capabilities()` 的第 3 顺位"这一次函数调用。**

**关于"发现权限 ⊆ 执行权限"原则的现状评估（要诚实说清）：**

| 时期 | 发现路径 | 执行路径 | 不变式是否成立 |
|------|---------|---------|--------------|
| **今天** | 本地 YAML，**零鉴权**（§6.4.2） | envd，需 envdAccessToken（4 header） | **形式上被违反，但方向是安全的**：发现比执行**更宽**（无 token 也能列命令）。泄露面仅限本地 `~/.sbox/templates` 目录内容，不含任何运行时/密钥信息 |
| **接入 Layer 2 后** | `GET /templates/{id}`，`Authorization: Bearer` | 同上 | **自动成立**：发现与执行共用同一 L1 身份；token 无效则 `platform_request:99` 的 `raise_for_status()` 先抛，列不出任何东西 |

**一个必须写进设计的残留缺口**：即便接上 `GET /templates/{id}`，
"token 能跑哪些命令就只能列出哪些"这个**细粒度**不变式
仍然**不成立** —— 因为平台返回的是**模板级**清单（该模板声明的所有命令），
而"这个 token 能在这个沙箱里跑什么"是**沙箱级/凭证级**的。
要做到细粒度，必须服务端按 caller 身份过滤 `custom_commands`，
这**超出本仓库能力范围**（我们是协议客户端，§1 已判定），
需要平台侧支持。建议在文档里明确标注为"V1 只保证身份级鉴权，不保证命令级最小可见性"。

#### 6.4.4 两层发现来源：哪层现在可用、哪层是缺口（逐项判定）

**Layer 1 —— 本地静态发现（项目文件里声明的命令，CLI 本地内省，无需连服务器、无需鉴权）**

| 子路径 | 状态 | 证据 |
|--------|------|------|
| `template.yaml` 声明的命令（`~/.sbox/templates/**/sandbox-template.yaml`） | ✅ **可用** | `api/capability.py:81-124` `_find_local_template` 目录遍历 + `:141-217` `resolve_capabilities`；ADR `command-source-resolution.md:47-49` 标 "已实现（本地优先）" |
| 同上，暴露给 SDK 用户 | ✅ **可用** | `Sandbox.list_commands()`（`api/sandbox.py:537-567`）+ `Sandbox.capabilities`（`:148-151`） |
| 同上，暴露给 CLI 用户（离线） | ⚠️ **部分** | `sbox template cache`（`cli/commands/template.py:279-291`）只列 YAML **文件路径**，不解析 `custom_commands`。**没有任何 CLI 命令能离线打印"某模板有哪些命令+参数"** |
| **项目里的 Python 命令模块（`@sandbox.register` 的 `def demo`）导入内省** | ❌ **完全缺口** | 全仓库无"扫描/导入项目 Python 模块以发现命令"的代码（§6.2.2 已逐一排除 `resolve_capabilities`、`utils/registry.py:_fetch_local`、`cli/main.py` 的 Click 懒加载三处疑似点） |

**Layer 2 —— server 级远程发现（运行时注册在活容器里的命令，必须问服务器，需鉴权）**

| 子路径 | 状态 | 证据 |
|--------|------|------|
| 传输 + L1 鉴权 + CLI 命令（`GET /templates/{id}`） | ✅ **已跑通** | `protocol/template.py:105-113`；`transport/http.py:84` 自动注入 `Authorization: Bearer`；`cli/commands/template.py:171-198` 的 `sbox template info` 是活的端到端实证 |
| 把它接进能力/命令解析（`resolve_capabilities` 第 3 顺位） | ❌ **缺口（已标注）** | `api/capability.py:196` 仅一行注释 `# 3. TODO(Phase2): online fallback — GET /templates/{id} metadata`；ADR `command-source-resolution.md:50-51` 明确"线上 metadata 兜底 = Phase 2 延后…当前仅本地优先链路生效" |
| 平台响应里**携带 `custom_commands`** | ❌ **缺口（且可能受平台限制）** | `models/template.py:42-62` 的 `TemplateInfo` **无 `custom_commands` 字段**，只有泛型 `metadata: dict[str, Any]`（`:60`）。`custom_commands` 是**本仓库的客户端侧 YAML 扩展**，不是 E2B/FC 模板模型的一部分。§3.2 来源 B 官方原文还写着"云沙箱当前**不支持通过 metadata 参数附加文件自定义元数据**" —— 该句上下文是 Sandbox/文件 metadata，**能否推广到 template metadata 需实测确认**（见 §7 O5） |
| **活容器内运行时注册命令的发现端点** | ❌ **结构性不可行（经 envd）** | §6.4.1 四条证据：envd 端点面封闭、`Envd` tag 只有 health/stats/envs、envd 版本由平台掌控、`process/List` 是 OS 进程不是命令 |
| 同上，经用户自建 server | ⚠️ **理论可行但今天被门控卡死** | 需 `ports` 能力（`api/network.py:45,63`），而 `ports` ∉ `DEFAULT_CAPABILITIES`，且内置模板无本地 YAML → `command-source-resolution.md:53-57` 明示内置模板的 `ports` "Phase 2 前不可用" |

**一句话总括（直接回答 leader）**：

> **Layer 1 的 YAML 分支今天可用；Layer 1 的"Python 命令模块内省"分支完全不存在。
> Layer 2 的传输与鉴权已经跑通（`sbox template info` 就是证据），缺的只是
> ① 一次函数调用的接线（`capability.py:196`）和 ② 平台响应里是否真的带
> `custom_commands`（模型里没有该字段，需实测）。
> 而"运行时注册进活容器的命令"这一层，经 envd 是结构性不可行的，
> 只能由用户自建 server 提供，且今天被 `ports` 门控卡住。**

#### 6.4.5 因此：`@sandbox.register` 的命令应当在哪一层被"发现"？

把 §6.4.4 的判定翻译成设计结论 —— **注册式命令必须走"构建期声明"，
不能指望"运行期注册到活容器"。**

理由链（每一环都有证据）：

1. 运行期注册进活容器 → 发现只能靠用户自建 server（§6.4.1 推论）
2. 用户自建 server 需要 `ports` 能力（§6.4.4 Layer 2 倒数第一行）
3. `ports` 不在默认基线，且内置模板上 Phase 2 前不可用（`capability-model.md:12`、`command-source-resolution.md:53-57`）
4. ∴ 运行期注册在**最常见的场景（内置模板）下不可发现** → 用户设想的目标形态
   `sbox run <target> demo --x <val> --y <val>` **无法达成**

而"构建期声明"路线每一环都通：

1. `@sandbox.register` 在**导入时**用 `inspect.signature` 产出 `CustomCommand`（§6.2.3）
2. 该对象被序列化进 `sandbox-template.yaml` 的 `custom_commands:` 段（模型已支持，`models/template.py:164`）
3. `sbox template build` 把 YAML/Dockerfile 推给平台（`protocol/template.py:44-91`，`POST /templates → 202`，**已实测验证**）
4. 客户端发现走 Layer 1（本地 YAML，今天就能用）或 Layer 2（`GET /templates/{id}`，接线后即可用，自带 L1 鉴权）
5. 执行走 §6.1 的 A 路线（源码投递，已实现）

→ **这条路线全程不新增任何容器内 server，且每一环都落在"已实现或已实测"的代码上。**

---

### 6.5 最小落地路径（M1–M6，按依赖排序，每步标注复用了什么）

前提：§6.4.5 已判定走"构建期声明 + 客户端源码投递"路线。以下每步都**不新增容器内 server**。

| 步 | 改动 | 复用的既有件 | 新增代码量估计 | 阻塞关系 |
|----|------|-------------|--------------|---------|
| **M1** | `CustomCommandArg` 增加 `type: str \| None = None`（省略 = 字符串，**向后兼容**） | `models/template.py:97-103`；schema 形状抄 `agent/tools.py:26-44` 的 JSON Schema | 极小（1 字段 + 1 validator） | 无 |
| **M2** | 修 `decorator.py` 两个脆弱点：解释器名探测（`python3`→`python` 回退）、临时脚本唯一路径 | `declarative/decorator.py:136,151,152` | 小 | 无（可与 M1 并行） |
| **M3** | 新增 `@sandbox.register`：导入时 `inspect.signature` → 产出 `CustomCommand`（含 M1 的 `type`） | `decorator.py:179-189` 的 `_get_function_source`（**已能干净剥离装饰器行**）；`inspect` 已在 `decorator.py:18` 导入 | 中 | 依赖 M1 |
| **M4** | 注册表落盘：把 M3 产出的 `CustomCommand` 序列化进 `sandbox-template.yaml` 的 `custom_commands:` | `models/template.py:164` 字段已存在；Pydantic 序列化已可用（ADR `custom-commands-schema.md:75` 的"模型往返"测试项） | 小 | 依赖 M3 |
| **M5** | 类型强制：CLI `--arg k=v` 解析后按 `type` 转换（`bool` 用白名单，不用 `bool()`）；SDK `run()` 的 `str()` 无条件转换改为按 `type` 分派 | `cli/commands/sandbox.py:517-527`；`api/sandbox.py:620-627` 的 `subs` 构造处；`shlex.quote` 防注入保持不变 | 中 | 依赖 M1 |
| **M6** | 发现增强（**可选，两条独立**）：<br>(a) CLI 离线发现 —— 新增 `sbox commands <template>`，本地扫 YAML 打印命令+参数，**零网络零鉴权**<br>(b) Layer 2 接线 —— `resolve_capabilities` 第 3 顺位调 `TemplateProtocol.get()` | (a) `capability.py:81-124` + `list_commands()` 的输出形状<br>(b) `protocol/template.py:105-113` + `transport/http.py:84` 的自动 L1 鉴权，**已跑通** | (a) 小 (b) 小 | (a) 依赖 M4；(b) 依赖 §7 O5 实测结论 |

**关键路径**：M1 → M3 → M4 →（M5 ∥ M6a）。M2 独立且应当**先做**（它是现存 bug）。
M6b 被外部事实（平台是否返回 `custom_commands`）阻塞，不应放进关键路径。

**这条路径上"新造"的东西只有一件**：`@sandbox.register` 装饰器本身（M3）。
执行（M2 修既有）、模型（M1 加字段）、序列化（M4 复用）、CLI 派发（M5 改既有）、
发现（M6 复用既有）—— **全部是对既有件的扩展，没有一处是新子系统。**

### 6.6 与既有 ADR 的一致性检查（有没有踩已否决的路）

| 既定决策 | 出处 | M1–M6 是否违反 |
|---------|------|--------------|
| 不做 `sbox <template>:<cmd>` 顶层 verb 动态注册 | `rejected/2026-09-03-capability-model-alternatives.md` 第 1 条；`cli-run-vs-exec.md:34` | ✅ 不违反。M6a 新增的是 `sbox commands <template>`（**查询**命令），派发仍是 `sbox run <id> <cmd>` |
| 不做 SDK `__getattr__` 魔法属性 | 同上第 2 条；`sdk-capability-surface.md:12,49` | ✅ 不违反。M3 的 `@sandbox.register` 是**模块级装饰器**，产出数据；调用仍是显式 `sandbox.run("demo", **args)` |
| 省略 `capabilities` 继承 `DEFAULT_CAPABILITIES`（不收紧） | 同上第 3 条；`capability-model.md:12` | ✅ 不违反。M1–M6 不动能力基线 |
| 发现 API 返回 **plain dicts**（不是对象） | `sdk-capability-surface.md:13,23-29` | ✅ 不违反。M6a 直接复用 `list_commands()` 的输出形状 |
| 参数用 `shlex.quote()` 转义，只填已声明占位符 | `custom-commands-schema.md:34`；`api/sandbox.py:620-647` | ⚠️ **M5 有破坏风险**。类型转换必须在 `shlex.quote` **之前**完成，且转换失败要 fail-fast，绝不能"转不了就当字符串塞进去" |
| `custom-commands-schema.md:65` 否决过"每命令 JSON-schema" | 同 ADR | ⚠️ **M1 部分推翻该否决**。推翻的理由要写清：当时否决的前提是"small, fixed arg shape"，而 `@sandbox.register` 引入了**函数签名这个天然多类型的来源**，前提已变。建议同步更新该 ADR，否则文档与代码会矛盾 |
| MCP 工具按 capabilities 过滤 = Phase 2 延后 | `sdk-capability-surface.md:43-46` | ✅ 不违反，但**M1 的 `type` 字段让这件事变得可行**：`custom_commands` 一旦带类型，就能自动映射成 MCP `inputSchema`，这是 M1 的一个额外收益，值得在 Phase 2 规划里记下 |

---

### 6.7 【决策 1 复核】"用户可改/覆盖 envd"与"用户自建 server"是否有真实机制支撑

Leader 的决策 1 断言了两件事。逐一对照证据，**一条成立、一条需要重新表述**。

#### 6.7.1 "模板场景 envd 已注入" —— ✅ 成立（§3.2 已证）

builder 模式（默认）由平台临时 FC 函数"拉取源镜像、**加入云沙箱运行所需的依赖**、
推送为目标镜像"；官方排查章节直接点名"这类镜像**已经注入 envd 等运行依赖**"。

#### 6.7.2 "用户可以自己改/覆盖 envd" —— ⚠️ **部分成立，但机制不是"改 envd"**

必须把"改 envd"拆成三种不同强度的操作，它们的可行性天差地别：

| 操作强度 | 是否有真实机制 | 证据 |
|---------|--------------|------|
| **改 envd 二进制本身** | ❌ **没有** | 仓库不含 envd 实现（§3.1）；envd 版本由平台返回并决定能力（§3.2 来源 B 的 `envd 0.5.2` / `requires envd 0.6.2 or later`）；本 SDK 只在 `models/sandbox.py:84` **消费** `envd_version`。没有任何 API 能替换它 |
| **改容器启动命令 / 就绪探针** | ✅ **有** | `protocol/template.py:50-51,68-71` 的 `start_cmd` → `startCmd`、`ready_cmd` → `readyCmd` 是 `POST /templates` 的正式 payload 字段。用户可以用它启动**自己的**进程（与 envd 并存），这是"用户可自定义容器内行为"的**唯一真实入口** |
| **绕过 envd 注入（用自己的镜像原样跑）** | ✅ **有，但代价是失去全部能力** | `X-E2B-Template-Build-Mode: direct` —— "不执行镜像转换，直接把源镜像作为 custom-container 模板函数镜像。**源镜像需要已经具备 E2B 运行依赖**"。即：direct 模式下若镜像没有 envd，§3.4 判定矩阵里**所有** envd 承接的能力（files/process/code/PTY）全挂 |
| **在自己的镜像里预装 envd 兼容层** | ✅ **有** | 官方提供 E2B 兼容镜像 `fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/base:v0.0.44` / `…/runtime/code-interpreter-v1:v0.0.44`，可作为 `FROM` 基底或对照验证镜像 |

> **重新表述建议**：把决策 1 的第一句从"用户可以自己改/覆盖 envd"改为
> **"envd 由平台注入且不可替换；用户可覆盖的是容器启动命令（`startCmd`/`readyCmd`）
> 与镜像内容，从而在 envd 之外并存自己的进程"**。
> 这个表述与证据一致，且不会误导实施者去找一个不存在的"替换 envd"API。

⚠️ 另需标注：`X-E2B-Template-Build-Mode` 这个 header **本 SDK 完全没有实现** ——
§3.1(b) 已证"全仓 grep `X-E2B-Template|Build-Mode|gatewayd` → **0 命中**"。
即：**用户今天无法通过本 SDK 选择 builder 还是 direct 模式**，只能用平台默认（builder）。
这本身是一条独立的产品缺口（见 §7 O2）。

#### 6.7.3 "非模板场景用户可自定义 in-container server" —— ✅ 机制存在，但**不需要 SDK ship 兜底 agent**

Leader 的问题 2 问："我们的 SDK 是否需要 ship 一个基础的 in-container agent 作为兜底？"

**判定：不需要。而且 ship 一个反而是错的。** 三条理由：

1. **兜底对象已经由平台提供。** §3.4 的判定矩阵显示：在 builder 模式 + 满足硬性条件的
   **任意**自定义镜像上，`files`/`process` 开箱即用，`code` 条件性可用（只需镜像内有解释器）。
   即"兜底 agent"这个角色**已经被 envd 占了**，SDK 再 ship 一个是重复建设。
2. **SDK ship 的 agent 无法自己进容器。** 要把一个 agent 放进容器，只有两条路：
   (a) 写进 Dockerfile（`models/template.py:179-200` 的 `to_dockerfile()` 支持 `RUN`/`COPY`，
   技术上可行）—— 但那就**变成了模板场景**，与"非模板场景"的前提矛盾；
   (b) 运行时用 `files.write` + `commands.start` 投递并后台拉起 —— 而这两个原语
   **本身就依赖 envd**（§2.3）。**用依赖 envd 的手段去兜底"envd 不存在"，是循环依赖。**
3. **唯一真正无 envd 的场景是 direct 模式 + 非 E2B 镜像，而该场景下 SDK 连不进去。**
   `transport/http.py:152-156, 203-207, 245-249` 会把连接失败包成
   `ConnectionError_("Failed to connect to sandbox envd: …")`。
   **没有任何通道可以在"无 envd 的容器"里执行代码**，所以兜底 agent 无处安放。

**那么"非模板场景用户自建 server"的现实机制是什么？** 答案是：
它**不是**"替代 envd"，而是"**在 envd 之上，用 envd 的原语拉起并暴露自己的 server**"。
仓库里已有一个完整可运行的先例（§4.3 已定位）：

```
commands.start(cmd, background=True)   # 用 envd 的 process 原语后台拉起自己的 server
  → network.get_url(port)              # 本地拼出 https://{port}-{sandbox_id}.{domain}
  → network.get_access_headers()       # secure 模式下取 X-Access-Token
  → 外部经平台网关访问该端口
```

这条链**每一环都已实现**，且 §4.2 揭示了一个关键洞察：**envd 自己就是"端口 49983
的普通隧道"**（`transport/auth.py:183` 硬编码 `E2b-Sandbox-Port: 49983`）。
所以用户的 server 与 envd 在暴露方式上是**同构的**，不需要任何新框架。

**代价（必须写进设计文档）**：这条路需要 `ports` 能力，而 `ports` ∉ `DEFAULT_CAPABILITIES`，
必须由模板**显式声明**（`capability-model.md:12`）。且内置模板上 Phase 2 前不可用
（`command-source-resolution.md:53-57`）。

> **决策 1 复核一句话总结**：envd 平台注入 ✅ 成立；"用户可改 envd" ❌ 应改述为
> "用户可覆盖 `startCmd`/`readyCmd` 与镜像内容"；"用户自建 server" ✅ 机制存在且
> 已有可运行先例，但它是**基于 envd 而非替代 envd**；SDK **不需要也不应该** ship
> 兜底 agent（循环依赖 + 无处安放）。

---

## 7. 风险与开放问题

### 7.1 风险（实施 M1–M6 时会踩的坑）

| # | 风险 | 证据 | 影响 | 缓解 |
|---|------|------|------|------|
| **R1** | **硬编码解释器名 `python`** | `declarative/decorator.py:152` `"python /tmp/_sandbox_exec.py"`；`:136` `pip install` | §3.2 官方镜像要求是"PATH 中有 `python3` **或** `python`"（**二选一**）。只有 `python3` 的最小镜像上，源码投递路线**直接失败** | M2：探测后回退（`python3` 优先），或用 `command -v` 预检 |
| **R2** | **硬编码临时脚本路径** | `decorator.py:151` 固定写 `/tmp/_sandbox_exec.py` | 同一沙箱内并发调用互相覆盖，产生**难以复现的错误结果**（不是崩溃，是静默串味） | M2：唯一路径 `/tmp/_sbox_{uuid4().hex}.py` + 用后清理 |
| **R3** | **类型强制破坏注入安全模型** | `api/sandbox.py:620-647`：`shlex.quote` + 单趟 `re.sub` + 未填占位符检测，三件套构成完整的防注入设计（`:628-632` 的注释专门说明为何用 `re.sub` 而非累积 `str.replace`） | M5 若在 `shlex.quote` **之后**做类型转换，或转换失败时"退化成字符串塞进去"，会**重新打开**该 ADR 明确关闭的注入面 | 类型转换必须在 quote 之前；转换失败 **fail-fast**，禁止静默降级 |
| **R4** | **发现权限宽于执行权限（现状）** | §6.4.2(c)：`list_commands()` 零鉴权零门控，是全仓库唯一两个无门控的公开面之一 | 今天泄露面仅限本地 `~/.sbox/templates`，**风险低**；但一旦 M6b 接上远程发现而不带鉴权，就会变成真实的未授权枚举 | M6b 必须走 `platform_request`（`transport/http.py:84` 自动注入 L1），**禁止**另建 httpx client |
| **R5** | **`ports` 门控挡住自建 server 路线** | `api/network.py:45,54,63` 三处 `check_capability(…, "ports")`；`models/template.py:27-31` `ports` ∉ 默认基线 | 用户按 §6.7.3 自建 server 后，调 `get_url`/`get_access_headers` 会拿到 `CapabilityNotSupportedError` (E3004)，**即使容器里 server 确实在跑** | 模板必须显式声明 `capabilities: [..., ports]`；文档需前置说明 |
| **R6** | **内置模板无本地 YAML → 能力回落** | `command-source-resolution.md:53-57`：内置模板（`base`/`code-interpreter`）不带 `sandbox-template.yaml`，回落 `DEFAULT_CAPABILITIES`，其 `terminal`/`ports` "Phase 2 前不可用" | 在最常见场景下，`custom_commands` 为**空**，`list_commands()` 返回 `[]`，`sbox run` 任何命令都报 unknown | 要么用户改用显式声明能力的模板，要么先做 M6b |
| **R7** | **ADR 引用路径已失效** | `rejected/2026-09-03-capability-model-alternatives.md` 三处引用 `proposed/architecture/2026-09-03-{cli-run-vs-exec,sdk-capability-surface,capability-model}.md`，但 `proposed/architecture/` **只有 `.gitkeep`**；三个文件实际在 `implemented/architecture/` 下 | ADR 从 proposed 晋升到 implemented 后**引用未更新**。实施者按引用路径找文件会以为决策缺失 | 见 §8 |

### 7.2 开放问题（需要实测或外部确认，不能靠读代码回答）

| # | 开放问题 | 为什么代码答不了 | 建议的验证动作 |
|---|---------|----------------|--------------|
| **O1** | **envd 究竟是不是平台在构建期注入的？**（§0 的 Q3 判定只有官方文档支撑，仓库内**无**直接证据，§3.1 已诚实声明） | 仓库只把 `envdUrl`/`envdAccessToken`/`envdVersion` 当平台返回值**消费**，既无 envd 实现也无注入逻辑 | 真实闭环：拿一个**不含任何 envd** 的 `FROM ubuntu:22.04` 最小镜像 → `sbox template build` → `sbox create` → `sbox exec "echo ok"` + 一次 `files.write`。成功即证实注入；失败则 Q3 判定被推翻，整个 §6 设计前提需重估 |
| **O2** | `X-E2B-Template-Build-Mode: builder\|direct` 是否真的被阿里云 FC 接受？本 SDK 未实现该 header（§3.1(b) grep 0 命中） | 官方文档写了，但仓库没实现过，无法从代码判断平台是否强制/默认值是什么 | 手工 `curl -H "X-E2B-Template-Build-Mode: direct"` 打 `POST /templates`，观察是否 202 及构建结果差异 |
| **O3** | **PTY 链路未实测**：`protocol/terminal.py:47-49` 的 WS `{ws_url}/terminal` 路径是推断的；§3.2 来源 B 官方原文说"交互式终端和依赖 TTY 的任务使用 **`sandbox.pty` API**" | 官方提示的 API 名（`sandbox.pty`）与本 SDK 的实现（`get_terminal` + WS `/terminal`）**不一致**，无法从代码判断哪个对 | 实测 `sbox` 的 PTY 路径；若失败，按官方 `pty` API 重新对齐 |
| **O4** | Code Interpreter 的 RPC 路径是否真实存在？ | `api/code.py:30-31` 与 `protocol/code_interpreter.py:28` 均自陈"基于 E2B SDK 逆向推断，阿里云官方文档未公开，**需实测验证**" | 实测 `sandbox.code.run("print(1)")`；这也是 §6.1.2 判定"A 路线优于 C 路线"的依据，若 C 实测通过则可放宽 |
| **O5** | **`GET /templates/{id}` 的响应里到底有没有 `custom_commands`？**（M6b 的唯一阻塞项） | `models/template.py:42-62` 的 `TemplateInfo` **没有**该字段，只有泛型 `metadata: dict[str, Any]`（`:60`）。`custom_commands` 是本仓库的**客户端侧 YAML 扩展**，不是 E2B/FC 模板模型的一部分。§3.2 来源 B 的"云沙箱当前不支持通过 metadata 参数附加文件自定义元数据"上下文是 Sandbox/文件 metadata，**能否推广到 template metadata 未知** | `sbox template info <已构建的模板 id> --json`，看响应里是否存在 `metadata` / `customCommands` 之类字段。**这一步只要一条命令，应当立刻做** —— 它直接决定 M6b 是"接线即可"还是"需平台侧支持" |
| **O6** | `sbox install` 是否真的存在？ | ADR `minimal-template-repo.md:40` 的测试策略写"The collection can be **`sbox install`**-ed from a local path and from GitHub"，但 `cli/commands/` 下只有 `auth/config_cmd/deploy/mcp/pool_cmd/sandbox/secret/session/skill/template` **十个模块，没有 `install`**；`template.py` 的子命令是 `install/list/info/build/delete/cache`，即 **`sbox template install`** 而非 `sbox install` | ADR 措辞需更正为 `sbox template install`（属文档问题，见 §8） |
| **O7** | `@sandbox.register` 与既有 `@sandbox` 装饰器的**命名冲突** | `declarative/decorator.py:28` 已有一个名为 `sandbox` 的**函数**（装饰器工厂）。用户设想写 `@sandbox.register`，那 `sandbox` 就得是一个**既是装饰器又有 `.register` 属性**的对象 | 设计决策：要么把 `register` 挂成 `sandbox` 函数的属性（Python 允许，但可读性差、mypy 需 `cast`），要么改名（如 `@remote` + `@remote.register`）。**注意**：`sdk-capability-surface.md:67` 要求 "`mypy --strict` passes with `py.typed` intact"，挂属性方案会与此冲突 |

---

## 8. 文档一致性问题清单（本次调研附带发现，均不影响代码正确性）

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| D1 | ADR 引用路径失效：三处引用 `proposed/architecture/…`，实际文件在 `implemented/architecture/…` | `rejected/2026-09-03-capability-model-alternatives.md`（3 处）；`implemented/feature/2026-09-03-custom-commands-schema.md:69-70` 同样引用 `2026-09-03-cli-run-vs-exec.md` / `2026-09-03-sdk-capability-surface.md`（无目录前缀，尚可） | 统一改为 `implemented/architecture/…`，或在 ADR 晋升时自动改写引用 |
| D2 | `proposed/architecture/` 目录为空（只有 `.gitkeep`），但被多处引用 | `.agents/notes/proposed/architecture/` | 见 D1 |
| D3 | `sbox install` 措辞与实现不符（实为 `sbox template install`） | `implemented/feature/2026-09-03-minimal-template-repo.md:40` | 更正措辞 |
| D4 | `custom-commands-schema.md:65` 否决"每命令 JSON-schema"的前提已被 `@sandbox.register` 改变 | 同 ADR | M1 落地时同步更新该 ADR，补记"前提变更"理由 |
| D5 | `docs/DESIGN.md:192` / `docs/design/architecture.md:65` 称 `protocol.port` 走 "Platform API — HTTP REST"，与 `protocol/port.py:15-18` 的"纯本地计算，不涉及任何网络请求"**直接矛盾** | 见 §3.3 | 已在 §3.3 记录；以代码为准 |
| D6 | `docs/DESIGN.md:155-164` 称平台鉴权用 `X-API-KEY`，实测为 `Authorization: Bearer` | `transport/auth.py:26,58` | 已在 §3.3 记录；以代码为准 |
| D7 | `docs/research/e2b-analysis.md:95-98` 的端点示例 `agent-sandbox.{region}.fc.aliyuncs.com` 与代码实测的 `api.{region}.e2b.fc.aliyuncs.com` 不同 | 同文档 | 已在 §3.3 记录；该研究文档已陈旧 |
| D8 | ADR 里的 issue 编号（#76/#83/#85/#87/#94）**在 `.agents/notes/**` 全量 grep 零命中** | 全目录 | issue ↔ ADR/代码的映射只存在于 git log / 工单系统，不在 ADR 里。建议在 ADR front-matter 加 `Issue: #NN` 字段，否则后续调研每次都要重新反查 |

---

## 9. 最终判定（对 leader 三问的收敛回答）

> 本节是对 §0 摘要表的**增补与收敛**，覆盖 leader 两条消息追加的决策 1/决策 2 与 discovery 维度。

### 9.1 用户这套设计在当前代码基础上**可行吗**？

**可行 —— 但需要一次关键的重新表述。**

| 用户的设计断言 | 判定 | 依据 |
|--------------|------|------|
| 模板场景 envd 已注入 | ✅ 成立 | §3.2 官方文档 builder 模式 + §6.7.1 |
| 用户可以自己改/覆盖 envd | ⚠️ **需重新表述** → "可覆盖 `startCmd`/`readyCmd` 与镜像内容，envd 本体不可替换" | §6.7.2 |
| 非模板场景用户可自定义 in-container server | ✅ 成立，但是"**基于 envd**"而非"替代 envd" | §6.7.3；代价见 R5 |
| SDK 需 ship 兜底 in-container agent | ❌ **不需要，且不应该** | §6.7.3 三条理由（角色已被 envd 占、循环依赖、无处安放） |
| `@sandbox.register`：函数名→命令名 | ✅ **已有同构实现** | `decorator.py:222` 的 `result = {func_name}(*args, **kwargs)` 就是这个语义 |
| 函数签名→CLI 选项（`--x`/`--y`） | ⚠️ **净新增**，但落点明确 | §6.2.3；缺 `CustomCommandArg.type`（§6.3.1） |
| `sbox run <target> demo --x <val> --y <val>` | ✅ 与既定决策**方向一致** | `cli-run-vs-exec.md:10` 的 `sbox run <id> <cmd>` 正是这个形状；且避开了两条被否决的路（§6.6） |
| server 级发现 API + 必须鉴权 | ⚠️ **需拆成两层**，其中一层今天就有、另一层结构性不可行 | §6.4.4 |

### 9.2 缺哪几块？（按"缺口的真实性质"分类，这是本报告最重要的产出）

**A 类 —— 纯代码缺口，我们能自己补，工作量小：**

1. `CustomCommandArg` 没有 `type` 字段（`models/template.py:97-103`）→ **M1**
2. 没有"扫描/导入项目 Python 模块以发现命令"的任何代码 → **M3**（Layer 1 的 Python 分支，§6.4.4）
3. 没有离线查看"某模板有哪些命令+参数"的 CLI（`sbox template cache` 只列文件路径）→ **M6a**
4. `decorator.py` 硬编码 `python` 与 `/tmp/_sandbox_exec.py` → **M2**（这是**现存 bug**，不是新需求）
5. CLI/SDK 全程把 args 当字符串（`sandbox.py:624` 的无条件 `str()`；`cli/…/sandbox.py:518-522`）→ **M5**

**B 类 —— 只差一次接线，传输与鉴权已经跑通：**

6. `resolve_capabilities` 的在线兜底只有注释没有实现（`api/capability.py:196` 的
   `# 3. TODO(Phase2)`）；而 `GET /templates/{id}` 的**协议方法**
   （`protocol/template.py:105-113`）、**L1 鉴权自动注入**（`transport/http.py:84`）、
   **活的 CLI 实证**（`sbox template info`，`cli/commands/template.py:171-198`）
   **三样全都有** → **M6b 只是一次函数调用**

**C 类 —— 结构性不可行 / 受外部制约，不能靠写代码解决：**

7. **envd 不可能暴露命令清单端点**：端点面封闭（`codec.py:91-96` 只有单一构造式）、
   E2B OpenAPI 的 `Envd` tag 只有 health/stats/envs、envd 版本由平台掌控 → §6.4.1
8. **平台响应里是否携带 `custom_commands` 未知**：`TemplateInfo` 无该字段，
   且 `custom_commands` 是本仓库的**客户端侧 YAML 扩展**，不是 E2B/FC 模板模型的一部分
   → **O5，一条命令即可实测，应当立刻做**
9. **"运行时注册进活容器"的命令无法被发现**：只能靠用户自建 server，
   而自建 server 需 `ports` 能力，`ports` ∉ 默认基线且内置模板上 Phase 2 前不可用
   → §6.4.5、R5、R6
10. **命令级最小可见性（"token 能跑哪些就只能列出哪些"的细粒度形式）做不到**：
    平台返回的是**模板级**清单，细粒度过滤必须服务端按 caller 身份做，
    超出协议客户端能力范围 → §6.4.3 末段

### 9.3 最小落地路径（一句话版）

> **先做 M2（修现存 bug）→ M1（加 `type` 字段）→ M3（`@sandbox.register` 用
> `inspect.signature` 产出 `CustomCommand`）→ M4（序列化进 `sandbox-template.yaml`）
> → M5（类型强制，务必在 `shlex.quote` 之前）→ M6a（离线 `sbox commands`）。
> M6b（远程发现接线）单独排期，前置条件是 O5 的实测结论。
> 全程不新增任何容器内 server，不新造任何鉴权体系。**

关键路径上**唯一需要"新造"的只有 M3 的装饰器本身**；其余五步都是对既有件的扩展。

### 9.4 关于"发现权限 ⊆ 执行权限"这条原则的最终确认

- **鉴权体系：确认可以完全复用，无需新造。** 复用对象是
  `AuthProvider.get_headers()`（Platform 平面，`Authorization: Bearer`）
  与 `EnvdTokenManager.get_headers()`（envd 平面，4 header），
  **不是** `NetworkModule.get_access_headers()`（后者被 `ports` 门控，
  会让发现权限**小于**执行权限，且 `secure=False` 时返回空 header）→ §6.4.3
- **身份级不变式：接入 M6b 后自动成立**（发现与执行共用同一 L1 身份，
  token 无效则 `raise_for_status()` 先抛）
- **命令级不变式：今天不成立，且我们无法单方面让它成立**（需平台侧按 caller 过滤）
  → 建议在对外文档里明确写"V1 只保证身份级鉴权，不保证命令级最小可见性"
- **现状的安全评估：今天的发现是零鉴权的（R4），但方向是安全的**
  （发现面宽于执行面，且泄露内容仅限本地模板 YAML，不含运行时状态或密钥）。
  这不构成现存漏洞，但 M6b 接线时**必须**走 `platform_request` 以自动带上 L1。

---

**报告结束。** 全文为只读调研产物，未修改任何产品代码；
所有结论均标注了代码位置或外部来源，"仓库内证据"与"仓库外权威文档"已明确区分（§3.1 vs §3.2）。
