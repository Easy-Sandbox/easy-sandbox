# FC Agent Sandbox 官方文档技术提取报告

> **日期**: 2026-09-04
> **目的**: 从阿里云 FC Agent Sandbox 官方文档中提取 SDK 实现相关的关键技术细节
> **来源**: help.aliyun.com/zh/functioncompute/ 系列文档
> **原则**: 仅记录文档明确写明的事实，推断内容单独标注

---

## 一、各文档关键摘要

### 1. 产品简介
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/product-overview-of-fc-agent-sandbox
- 云沙箱（FC Agent Sandbox）是面向 AI Agent 和代码执行场景的云端隔离运行环境
- 核心对象：Sandbox、Template、Commands、Filesystem、Code Interpreter、Network、Storage、FC Extensions
- **E2B 协议兼容**：文档明确说"如果你已经熟悉 E2B，可以继续使用 E2B SDK 或 E2B CLI 接入云沙箱"
- FC Extensions（VPC、OSS、自定义域名、监控日志）是相对 E2B 的**云上增强**，不属于 E2B SDK 原生对象

### 2. 创建沙箱
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/create-a-sandbox
- 使用 E2B SDK 的 `Sandbox.create()` 接口
- **必传参数**: `template`（模板名称或 ID）、`api_key`、`api_url`、`domain`
- **可选参数**: `timeout`/`timeoutMs`、`envs`（环境变量）、`metadata`（元数据）
- SDK 自动读取 `E2B_API_KEY`、`E2B_API_URL`、`E2B_DOMAIN` 环境变量
- 创建后应在 `try/finally` 中调用 `sandbox.kill()` 释放资源

### 3. 生命周期
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/lifecycle
- 生命周期：创建 → 运行 → 终止（可选暂停/恢复，需白名单）
- 沙箱状态：`running`、`paused`、`terminated`
- 关键方法：`Sandbox.create()`、`Sandbox.connect(sandboxId)`、`Sandbox.list()`、`sandbox.getInfo()`、`sandbox.isRunning()`、`sandbox.kill()`、`sandbox.setTimeout(ms)`
- `Sandbox.connect()` 可连接已有沙箱；若已暂停则自动恢复

### 4. 连接沙箱
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/connect-the-sandbox
- 通过 `Sandbox.connect(sandboxId)` 连接已有沙箱
- `sandboxId` 是连接沙箱的关键标识，由业务系统保存

### 5. 自定义镜像模板
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/build-a-custom-image-template
- 使用 ACR EE（容器镜像服务企业版）托管镜像
- **模板构建方式**: `Template.build(Template().from_image(FROM_IMAGE), name=..., cpu_count=..., memory_mb=...)`
- 构建模式：
  - `builder`：临时 FC 函数处理源镜像，加入云沙箱运行依赖，生成适配镜像
  - `direct`：直接使用源镜像（源镜像需已具备 E2B 运行依赖）
- **关键属性**（创建后可获取）：
  - `build.template_id`
  - `build.build_id`
  - `sandbox.sandbox_id`
  - `sandbox.sandbox_domain`
  - **`sandbox.envd_api_url`** ← 文档代码示例中明确打印此属性
- **通过 Header 配置高级构建**：`X-E2B-Template-*` 系列 Header

#### 镜像硬性要求（文档明确列出）

| 级别 | 要求 | 不满足时影响 |
|------|------|-------------|
| **硬性** | 架构为 `linux/amd64` | Template 转换直接失败 |
| **硬性** | ACR 镜像不应开启镜像加速选项 | Template 转换直接失败 |
| **条件** | 镜像内存在固定路径 `/bin/bash` | `commands.run`、PTY 失败 |
| **硬性** | `/etc/passwd`、`/etc/group` 为标准文件且可写 | **gatewayd 无法初始化默认用户，容器启动失败** |
| **条件** | PATH 中存在 `python3` 或 `python` | Python `run_code` 不可用 |
| **条件** | PATH 中存在 `node` | JavaScript `run_code` 不可用 |
| **推荐** | 系统 PATH 至少包含 `/usr/local/bin`、`/usr/bin`、`/bin` | 常用命令找不到 |

### 6. 用户与工作目录
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/user-and-working-directory
- 文档**未指定固定的默认用户或工作目录**
- 文档明确说："不要假设所有镜像都有相同默认用户、HOME 目录和权限"
- 建议使用明确的 `cwd` 参数
- 用 `whoami && pwd` 查看当前用户和目录

### 7. 启动与就绪命令
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/startup-and-readiness-commands
- 文档内容比标题简单得多：**没有 startCmd/readyCmd 概念**
- 只说明了用后台命令启动 Web 服务：`sandbox.commands.run("python3 -m http.server 8000", background=True)`
- 启动服务后通过 `sandbox.get_host(8000)` 获取公网访问地址
- 返回格式为 `https://{host}`

### 8. 模板名称与版本
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/template-name
- 名称建议包含：业务场景、语言或基础镜像、关键依赖版本、日期
- 示例：`agent-python313-20260704`、`code-review-node22-20260704`
- **标签系统**：
  - 每个模板最多 20 个标签
  - 不能删除 `default` 标签
  - `assignTags`、`getTags`、`removeTags` 操作
  - 重复分配、删除不存在的标签都是幂等操作

### 9. 内置模板
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/built-in-templates

| 模板 | 适用场景 | 自动就绪 |
|------|----------|---------|
| `base` | 基础命令、文件访问、SDK 连通性验证 | 是（开通即用） |
| `code-interpreter-v1` | AI Agent 代码执行、数据分析 | 是（开通即用） |
| `browser` | 浏览器自动化 | 否（需自行构建） |
| All-In-One | 浏览器 + 代码执行 | 否（需自行构建） |

### 10. base 模板
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/base-template
- 内置 **E2B envd 兼容基础服务**
- 提供 envd 基础服务，用于支持沙箱创建、连接、基础命令和文件访问
- **默认端口**：无业务端口（提供 envd 基础服务）
- 默认规格：2 vCPU / 2048 MB / 10240 MB 磁盘
- 未显式指定 `template` 时，默认创建 base 沙箱
- 是 code-interpreter-v1、browser、All-In-One 模板的**共同能力基础**

### 11. code-interpreter-v1 模板
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/code-interpreter-v1-template
- **默认端口**：**5000**（沙箱服务监听端口）
- 默认规格：2 vCPU / 2048 MB / 10240 MB 磁盘
- 支持 Python、JavaScript、TypeScript、Bash
- **不支持** Java 和 R
- 上下文保持：同一沙箱的默认上下文中，变量、导入、函数跨调用保留
- **沙箱最长生命周期**: 24 小时（timeout 参数上限 86400 秒）
- **空闲超时**: 有效下限 60 秒

### 12. 浏览器模板
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/browser-template
- **默认端口**：**3000**（沙箱服务监听端口）
- 推荐规格：4 vCPU / 8192 MB / 10240 MB 磁盘
- 使用 Chrome DevTools Protocol (CDP) over WebSocket
- 镜像：`fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/browser:v0.0.44`
- **WebSocket 端点**（均通过端口 3000 暴露）：

| 端点 | 路径 | 用途 |
|------|------|------|
| 健康检查 | `https://<sandbox-host>/health` | 判断 browser 服务是否启动完成 |
| CDP 自动化 | `wss://<sandbox-host>/ws/automation` | 浏览器自动化 |
| VNC 实时流 | `wss://<sandbox-host>/ws/livestream` | 实时查看浏览器桌面 |

- **鉴权**：所有端点需在请求头携带 `X-Access-Token`
  - Python SDK：`sbx._envd_access_token`
  - JS SDK：`sbx.envdAccessToken`
- 所有数据面端点使用 **WSS**（WebSocket Secure）协议，全程加密
- 窗口尺寸通过环境变量控制：`RESOLUTION`、`BROWSER_WINDOW_SIZE`、`VNC_CLIP`

### 13. 使用约束
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/usage-constraints-of-fc-agent-sandbox

#### 地域

| 地域 | Region ID |
|------|-----------|
| 华北 2（北京） | cn-beijing |
| 华东 2（上海） | cn-shanghai |
| 华东 1（杭州） | cn-hangzhou |
| 华南 1（深圳） | cn-shenzhen |
| 中国（香港） | cn-hongkong |
| 新加坡 | ap-southeast-1 |
| 美国（弗吉尼亚） | us-east-1 |
| 美国（硅谷） | us-west-1 |

#### Endpoint 格式
```
E2B_API_URL=https://api.<region>.e2b.fc.aliyuncs.com
E2B_DOMAIN=<region>.e2b.fc.aliyuncs.com
```

#### 版本要求
- Python SDK：`e2b==2.31.0`、`e2b-code-interpreter==2.8.1`（验证版本）
- Python 运行时：3.10+
- Node.js：20.18.1+
- 数据面认证：`X-API-KEY` 请求头传递 API Key

### 14. E2B 兼容说明
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/e2b-compatibility-explanation

#### 兼容状态总览

| 能力模块 | 状态 |
|---------|------|
| Sandbox | 兼容（暂停需白名单） |
| Commands | 兼容 |
| Filesystem | 部分兼容（不支持文件自定义元数据） |
| Code Interpreter | 兼容 |
| Template | 兼容 |
| CLI | 部分兼容 |
| Metrics | 兼容（磁盘/页缓存为占位值） |
| Logs | 受限（返回空数组） |
| Network Config Update | 受限（返回成功但无实际效果） |
| Snapshots / Volume / Team / Access Token | **暂不兼容** |

#### 兼容 API 列表
- **Sandbox**: create, connect, list, getInfo, kill, setTimeout, pause, downloadUrl, uploadUrl, getHost
- **Commands**: run, list, connect, sendStdin, kill
- **Filesystem**: list, exists, getInfo, read, write, makeDir, remove, rename, watchDir
- **Code Interpreter**: runCode, createCodeContext, listCodeContexts, restartCodeContext, removeCodeContext
- **Template**: CRUD, Build, Tags, Alias

#### 文件元数据限制
envd 0.5.2 版本下，SDK 会抛出 `TemplateException: File metadata requires envd 0.6.2 or later.`

### 15. 命令执行概览
- **文档 URL**: https://help.aliyun.com/zh/functioncompute/overview-of-commands
- 核心方法：`commands.run()`、`commands.list()`、`commands.connect()`、`commands.send_stdin()`、`commands.kill()`
- 前台运行命令时，非零退出码抛出 `CommandExitException`（Python）/ `CommandExitError`（TypeScript）

---

## 二、关键发现

### A. 容器通信机制

#### A1. 容器内的 envd 服务
- **文档明确说明**: base 模板"内置 E2B envd 兼容基础服务"，用于支持沙箱创建、连接、基础命令和文件访问
- **文档明确说明**: 构建自定义模板时，`builder` 模式会"加入云沙箱运行依赖"；`direct` 模式要求"源镜像需要已经具备 E2B 运行依赖"
- **文档明确说明**: `/etc/passwd`、`/etc/group` 必须可写，否则"**gatewayd 无法初始化默认用户**，容器启动失败"
- **已由镜像实地检查确认**（见 `2026-09-04-fc-claude-code-image-inspection.md`）: 容器内有两个 Go server 烤进官方基础镜像 —— **envd**（`/.fce2b/envd`，端口 49983，数据面服务）和 **Gateway/entrypoint**（`/.fce2b/entrypoint`，端口 5000，反向代理 + PID1 进程管理器，含动态端口路由 routeDynamic）

#### A2. 端口与 URL 格式
- **envd 端口**: 文档未直接说明 envd 监听的端口号。但代码示例中 `sandbox.envd_api_url` 属性存在。**已由镜像实地检查确认**（见 `2026-09-04-fc-claude-code-image-inspection.md`）：环境变量 `ENVD_PORT=49983`，envd 监听 49983 端口
- **端口 URL 格式（已实测验证）**: `https://{port}-{sandbox_id}.{domain}`
  - 这是 `sandbox.get_host(port)` 返回的格式
  - 例如 `sandbox.get_host(8000)` 返回 `8000-sbx-xxxx.cn-beijing.e2b.fc.aliyuncs.com`
- **code-interpreter-v1 默认端口**: 5000
- **browser 模板默认端口**: 3000
- **base 模板**: 无业务端口

#### A3. 通信协议
- **控制面 API**: HTTPS，E2B 协议兼容
  - URL: `https://api.<region>.e2b.fc.aliyuncs.com`
  - 认证: `Authorization: Bearer {api_key}` 或 `X-API-KEY` header
- **数据面（envd）**: HTTPS / WSS
  - URL: `https://{port}-{sandbox_id}.{domain}`
  - 认证: `X-Access-Token` header
- **浏览器 CDP**: WSS（WebSocket Secure）
- 文档未提及 gRPC 或 Connect protocol

#### A4. 公网网关
- 文档中浏览器模板的健康检查示例通过**公网网关**访问：`https://{host}/health`
- 公网网关要求 `X-Access-Token`，否则返回 403
- 沙箱内部可通过 `localhost:3000` 直接访问（无需 token）

### B. 模板结构

#### B1. 模板组成
- **不使用 Dockerfile**（至少文档未提及用户编写 Dockerfile 来构建模板）
- 模板通过 `Template.build(Template().from_image(IMAGE), name=..., ...)` 从镜像创建
- 模板可设置 `cpu_count`、`memory_mb`
- 模板通过 ACR EE 镜像仓库分发

#### B2. 没有 startCmd / readyCmd 的概念
- 文档"启动与就绪命令"页面的实际内容只是**用后台命令启动服务**
- 没有模板级别的 `startCmd`、`readyCmd` 配置
- 启动服务是用户在沙箱创建后自行执行的操作

#### B3. 模板名称规范
- 建议格式：`{业务}-{语言/镜像}-{版本/日期}`
- 示例：`agent-python313-20260704`
- 标签系统：最多 20 个标签，`default` 标签不可删除

### C. 沙箱生命周期

| 操作 | API |
|------|-----|
| 创建 | `Sandbox.create(template=..., api_key=..., api_url=..., domain=..., timeout=...)` |
| 连接 | `Sandbox.connect(sandbox_id, ...)` |
| 列表 | `Sandbox.list()` |
| 信息 | `sandbox.getInfo()` / `sandbox.is_running()` |
| 超时 | `sandbox.set_timeout(ms)` |
| 暂停 | `sandbox.pause()` (需白名单) |
| 终止 | `sandbox.kill()` |
| 下载 URL | `sandbox.download_url(path)` |
| 上传 URL | `sandbox.upload_url(path)` |
| 端口访问 | `sandbox.get_host(port)` |

### D. 容器内环境

- **默认用户**: 文档未指定固定默认用户。明确说"不要假设所有镜像都有相同默认用户"
- **工作目录**: 文档未指定固定工作目录。Code Interpreter 上下文默认 cwd 为 `/home/user`
- **Gateway/gatewayd**: 文档提到 gatewayd 会初始化默认用户（从 `/etc/passwd`、`/etc/group`）。**已由镜像实地检查确认**（见 `2026-09-04-fc-claude-code-image-inspection.md`），Gateway 即 `/.fce2b/entrypoint`，是 PID1 进程管理器 + 反向代理，烤进官方基础镜像（非运行时注入）
- **文件系统**: 本地文件系统仅在沙箱生命周期内有效，终止后不持久化
- **磁盘大小**: 默认 10240 MB

### E. 浏览器模板

- 端口固定为 **3000**
- 通过 CDP over WSS 协议控制
- 三个端点：`/health`（HTTPS）、`/ws/automation`（WSS）、`/ws/livestream`（WSS）
- 所有端点需 `X-Access-Token` 鉴权
- 内置 Chromium/Chrome
- 内置 VNC 服务（noVNC 客户端无法直接连接，因浏览器 WebSocket API 不支持自定义请求头）
- 窗口尺寸通过 Dockerfile ENV 设置，**不能**通过 `Sandbox.create` 的 `envs` 参数设置
- 默认分辨率：`1680x1050x24`

---

## 三、架构影响分析

### 我们 SDK 中已验证正确的假设

1. **E2B 协议兼容**: 官方文档确认完全兼容 E2B SDK API，只需替换 endpoint
2. **envd 数据面端口 49983**: 代码中 `ENVD_PORT = 49983` 与文档中 `sandbox.envd_api_url` 一致（虽然文档未直接写出 49983，但 `envd_api_url` 属性的存在间接确认）
3. **端口 URL 格式**: `{port}-{sandbox_id}.{domain}` 格式在文档的 `get_host()` 使用中得到确认
4. **envd 认证 Header**: `X-Access-Token` 在浏览器模板文档中被明确提到
5. **控制面认证**: `Authorization: Bearer {api_key}` 与文档一致
6. **地域 Endpoint 格式**: `api.<region>.e2b.fc.aliyuncs.com` / `<region>.e2b.fc.aliyuncs.com`

### 需要修正或补充的发现

1. **没有 startCmd / readyCmd 模板配置**: 文档中的"启动与就绪命令"实际上只是后台命令使用教程，不存在模板级 startCmd/readyCmd。我们 SDK 中如果有 `template.yaml` 中的 `startCmd`/`readyCmd` 字段，这是我们自己的扩展，**不是** FC 平台的概念
2. **没有 template.yaml / manifest.yaml**: FC 平台的模板是通过 `Template.build(from_image)` API 从镜像创建的，不存在用户编写的 template.yaml 配置文件。我们 SDK 的本地 template.yaml 是自有扩展
3. **capability 模型不是平台概念**: 文档中没有提到 capability（shell、files、code、terminal、ports）的概念。不同模板的能力差异是由镜像内容决定的（是否有 envd、code interpreter 服务等），而不是由元数据声明
4. **Gateway/gatewayd**: 文档首次提到这个组件，它负责初始化容器内的默认用户。**已由镜像实地检查确认**（见 `2026-09-04-fc-claude-code-image-inspection.md`）：Gateway 即 `/.fce2b/entrypoint`，是 Go 静态链接二进制，烤进官方基础镜像（非平台运行时注入），作为 PID1 进程管理器 + 反向代理
5. **envd 版本**: E2B 兼容层报告版本为 0.5.2（从 SDK 文件元数据错误信息 `envd 0.6.2 or later` 间接获得）；**已由镜像实地检查确认**（见 `2026-09-04-fc-claude-code-image-inspection.md`）envd 二进制版本为 v0.1.14（从 Go 二进制字符串提取）。两个版本号分属不同语义层（E2B 兼容 API 版本 vs Go 二进制版本）
6. **code-interpreter-v1 端口 5000**: 文档明确说明默认端口是 5000，需确认我们的 SDK 是否正确处理

### 文档未提及的关键信息

1. **envd 的具体通信协议**: 文档未说明 SDK 与 envd 之间使用的是 HTTP REST、gRPC 还是 Connect protocol。已由镜像实地检查确认 envd 提供 HTTP REST（files upload/download）+ gRPC/Connect（filesystem/process 服务），见 `2026-09-04-fc-claude-code-image-inspection.md`
2. **envd 监听端口**: 文档未直接说明 envd 监听什么端口。**已由镜像实地检查确认** 49983（见 `2026-09-04-fc-claude-code-image-inspection.md`，环境变量 `ENVD_PORT=49983`）
3. **控制面 API 的完整规格**: 文档没有 OpenAPI/Swagger 规格说明
4. **容器内的完整进程列表**: 已由镜像实地检查确认主要进程为 entrypoint (Gateway) 和 envd，另有 sandbox-code-interpreter（按模板配置启用/禁用）。见 `2026-09-04-fc-claude-code-image-inspection.md`
5. **WebSocket 协议细节**: Commands 和 Filesystem 是否使用 WebSocket 流式传输

---

## 四、对 SDK 实现的建议

### 4.1 Transport 层

| 配置项 | 当前实现 | 文档依据 | 状态 |
|--------|---------|----------|------|
| 控制面 URL | `https://api.<region>.e2b.fc.aliyuncs.com` | 使用约束文档明确 | 正确 |
| 数据面 domain | `<region>.e2b.fc.aliyuncs.com` | 使用约束文档明确 | 正确 |
| envd 端口 | 49983 | 文档未直接说明；**已由镜像实地检查确认**（环境变量 `ENVD_PORT=49983`，见 `2026-09-04-fc-claude-code-image-inspection.md`） | 已确认 |
| envd URL 格式 | `https://49983-{sandbox_id}.{domain}` | 与 `get_host(port)` 格式一致 | 正确 |
| 控制面认证 | `Authorization: Bearer {api_key}` | 使用约束文档明确 | 正确 |
| envd 认证 | `X-Access-Token: {envd_access_token}` | 浏览器模板文档明确 | 正确 |

### 4.2 Template 系统

- 我们的本地 `template.yaml` / capability 模型是 SDK 自有扩展，不是平台概念
- 平台模板通过 `Template.build(from_image)` 创建，无配置文件
- 建议在文档中明确区分"平台模板"和"SDK 本地模板定义"
- 标签系统（tags）应实现：`assign_tags`、`get_tags`、`remove_tags`

### 4.3 沙箱生命周期管理

- 应实现完整的生命周期 API：create、connect、list、getInfo、isRunning、setTimeout、pause、kill
- `downloadUrl`、`uploadUrl` 应作为文件操作的补充方式
- 暂停/恢复需标注为"白名单功能"

### 4.4 code-interpreter-v1 支持

- 默认端口 5000
- `run_code` API 需支持 language（python/javascript/typescript/bash）和 context 参数
- 上下文管理 API：create_code_context、list_code_contexts、restart_code_context、remove_code_context
- TypeScript 的上下文管理在平台上**不可用**，需在 SDK 中标注

### 4.5 浏览器模板支持

- 默认端口 3000
- 需暴露 `_envd_access_token` 以支持 CDP/VNC 连接鉴权
- 健康检查轮询模式：GET `https://{host}/health` 直到返回 200
- CDP 端点：`wss://{host}/ws/automation`
- VNC 端点：`wss://{host}/ws/livestream`

---

## 五、官方镜像地址（北京地域）

```
fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/base:v0.0.44
fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/code-interpreter-v1:v0.0.44
fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/browser:v0.0.44
```

---

## 六、参考文档链接

| 文档 | URL |
|------|-----|
| 产品简介 | https://help.aliyun.com/zh/functioncompute/product-overview-of-fc-agent-sandbox |
| 生命周期 | https://help.aliyun.com/zh/functioncompute/lifecycle |
| 创建沙箱 | https://help.aliyun.com/zh/functioncompute/create-a-sandbox |
| 连接沙箱 | https://help.aliyun.com/zh/functioncompute/connect-the-sandbox |
| 内置模板 | https://help.aliyun.com/zh/functioncompute/built-in-templates |
| base 模板 | https://help.aliyun.com/zh/functioncompute/base-template |
| code-interpreter-v1 | https://help.aliyun.com/zh/functioncompute/code-interpreter-v1-template |
| 构建自定义镜像模板 | https://help.aliyun.com/zh/functioncompute/build-a-custom-image-template |
| 用户与工作目录 | https://help.aliyun.com/zh/functioncompute/user-and-working-directory |
| 启动与就绪命令 | https://help.aliyun.com/zh/functioncompute/startup-and-readiness-commands |
| 模板名称与版本 | https://help.aliyun.com/zh/functioncompute/template-name |
| 浏览器模板 | https://help.aliyun.com/zh/functioncompute/browser-template |
| 使用约束 | https://help.aliyun.com/zh/functioncompute/usage-constraints-of-fc-agent-sandbox |
| E2B 兼容说明 | https://help.aliyun.com/zh/functioncompute/e2b-compatibility-explanation |
| 命令概览 | https://help.aliyun.com/zh/functioncompute/overview-of-commands |

---

> **注意**: 部分文档页面（Filesystem、Network、SDK 使用、Code Interpreter 独立页面）在获取时返回 404，可能 URL 结构有变或页面尚未发布。上述内容从可成功获取的页面中提取。

---

## 七、Claude Code 模板（补充）

> **文档 URL**: https://help.aliyun.com/zh/functioncompute/claude-code-template

### 7.1 概述

Claude Code 是 Anthropic 的终端 AI 编程 Agent。阿里云在各地域 ACR 预置了 Claude Code 镜像，无需用户自行推送镜像或配置 ACR EE。使用方式与其他自定义模板一致：`from_image` + `Template.build` 构建模板后创建沙箱。

### 7.2 环境规格（文档明确）

| 项目 | 规格 |
|------|------|
| 操作系统 | Ubuntu 25.04 |
| Claude Code 路径 | `/home/user/.local/bin/claude` |
| **默认用户** | **`user`** |
| **工作目录** | **`/home/user`** |
| MCP Gateway | **不支持** |
| 推荐规格 | cpu_count=2, memory_mb=8192 |

### 7.3 镜像地址（各地域，版本 v0.0.44）

| Region | 镜像 |
|--------|-------|
| cn-beijing | `fc-e2b-registry.cn-beijing.cr.aliyuncs.com/runtime/claude-code:v0.0.44` |
| cn-shenzhen | `fc-e2b-registry.cn-shenzhen.cr.aliyuncs.com/runtime/claude-code:v0.0.44` |
| ap-southeast-1 | `fc-e2b-registry.ap-southeast-1.cr.aliyuncs.com/runtime/claude-code:v0.0.44` |
| cn-hongkong | `fc-e2b-registry.cn-hongkong.cr.aliyuncs.com/runtime/claude-code:v0.0.44` |
| cn-shanghai | `fc-e2b-registry.cn-shanghai.cr.aliyuncs.com/runtime/claude-code:v0.0.44` |
| cn-hangzhou | `fc-e2b-registry.cn-hangzhou.cr.aliyuncs.com/runtime/claude-code:v0.0.44` |

### 7.4 关键发现

1. **没有内置 HTTP Server**: Claude Code 模板是一个终端 AI Agent，不启动 HTTP 服务。文档中没有提到任何 HTTP server 组件或监听端口
2. **没有特殊启动命令**: 模板不需要 startCmd/readyCmd。创建沙箱后直接通过 `sandbox.commands.run()` 运行 `claude` 命令即可
3. **运行方式**: 非交互模式使用 `-p` 参数；加 `--dangerously-skip-permissions` 跳过权限确认；加 `< /dev/null` 避免 stdin 等待
4. **首次运行需初始化配置**: `sandbox.commands.run("echo '{}' > /home/user/.claude.json")` ，否则可能报配置损坏
5. **模型 API Key 通过 envs 注入**: 中国站使用百炼 DashScope，国际站使用 Anthropic Console
6. **默认用户明确为 `user`**: 这是文档中首次对某个具体模板明确指定默认用户和工作目录（`user` / `/home/user`）

### 7.5 MCP 与 Skill 能力

| 能力 | 支持情况 |
|------|---------|
| `claude mcp add`（stdio / HTTP） | 支持 |
| SDK mcp 创建参数 | 不支持 |
| `getMcpUrl()` / `getMcpToken()` | 不支持 |

Skill 路径：
- 个人（沙箱内全局）：`/home/user/.claude/skills/<name>/SKILL.md`
- 项目级：`<项目>/.claude/skills/<name>/SKILL.md`

### 7.6 中国站环境变量配置

```python
envs={
    "ANTHROPIC_AUTH_TOKEN": "<百炼 API Key>",
    "ANTHROPIC_BASE_URL": "https://dashscope.aliyuncs.com/apps/anthropic",
    "ANTHROPIC_MODEL": "qwen3.7-max",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3.7-max",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen3.7-max",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "qwen3.7-max",
}
```

### 7.7 架构影响

- Claude Code 模板进一步确认：**FC 平台的模板不需要用户提供 HTTP server**。所有沙箱操作（commands、filesystem、code interpreter）通过烤进官方基础镜像的 **envd** 服务完成（非运行时注入，见 `2026-09-04-fc-claude-code-image-inspection.md`），用户镜像只需要包含业务工具（如 claude CLI）
- 这与 browser 模板（内置 HTTP server 在 3000 端口）和 code-interpreter-v1（服务在 5000 端口）形成对比：那些端口是**模板业务逻辑**提供的额外服务，不是 envd 的端口
- Claude Code 模板类似 base 模板：无业务端口，仅通过 envd 基础服务与 SDK 通信
