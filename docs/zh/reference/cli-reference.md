# CLI 参考手册

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

## 命令总览

```
ebx
├── 顶层快捷方式（12 个）
│   create / list / info / kill / exec / connect / run / upload / download / deploy / install / init
├── sandbox 子组（17 个）
│   ├── files: list / stat / mkdir / rm / mv / search
│   ├── process: list / start / info / signal
│   ├── system: info / env / ports / packages / metrics
│   ├── capabilities
│   └── shell-stream
├── template（10 个）
│   init / deploy / build / push / create / install / list / info / delete / search
├── config（4 个）
│   get / set / list / reset
└── mcp（4 个）
    install / start / status / deploy
```

---

## 全局选项

```text
ebx [全局选项] <子命令> [子命令选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--json` | `-j` | 以 JSON 格式输出 |
| `--quiet` | `-q` | 最小化输出 |
| `--verbose` | `-v` | 详细输出（DEBUG 级别日志） |
| `--no-color` | | 禁用彩色输出 |
| `--log-level` | | 设置日志级别：`DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `--ci` | | CI/CD 模式（等同 `--quiet --no-color --json`） |
| `--timeout` | `-t` | 默认超时秒数（默认 300） |
| `--region` | `-r` | 区域（默认 cn-hangzhou） |
| `--profile` | `-p` | [预留] 配置文件 |
| `--version` | | 显示版本号 |

---

## 沙箱生命周期命令

### ebx create

创建新沙箱。可选提供自然语言描述以自动推断模板。

```bash
ebx create [DESCRIPTION] [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--template` | `-T` | 沙箱模板名称 |
| `--upload` | `-u` | 创建后自动上传的本地文件/目录 |
| `--timeout` | `-t` | 超时秒数 |
| `--env` | `-e` | 环境变量 `KEY=VALUE`（可重复） |
| `--metadata` | `-m` | 元数据 `KEY=VALUE`（可重复） |

```bash
# 使用默认模板创建
ebx create --template base

# 自然语言创建
ebx create "一个 Python 数据分析环境"

# 创建并上传文件
ebx create --template base --upload ./project/ --env MY_KEY=value
```

### ebx list

列出沙箱。

```bash
ebx list [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--status` | `-s` | 按状态过滤：`running`/`stopped`/`creating`/`paused`/`error` |
| `--limit` | `-l` | 最大结果数（默认 20） |

### ebx info

查看沙箱详情。

```bash
ebx info <SANDBOX_ID>
```

### ebx kill

销毁沙箱。

```bash
ebx kill <SANDBOX_ID> [选项]
ebx kill --all [选项]
```

| 选项 | 说明 |
|------|------|
| `--all` | 销毁所有运行中的沙箱 |
| `--yes` / `-y` | 跳过确认 |

### ebx exec

在沙箱中执行命令。

```bash
ebx exec <SANDBOX_ID> <COMMAND> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--timeout` | `-t` | 超时秒数（默认 60） |
| `--cwd` | | 工作目录 |

```bash
ebx exec sbx-xxxx "echo hello"
ebx exec sbx-xxxx "pip install flask" --timeout 120
```

### ebx connect

交互式连接到沙箱（类似 SSH）。

```bash
ebx connect <SANDBOX_ID>
```

输入 `exit`、`quit` 或 `Ctrl+D` 断开连接。每条交互命令有 30 秒超时限制。每条命令在独立进程中执行。

---

## 文件操作命令

### ebx upload

上传本地文件或目录到沙箱。

```bash
ebx upload <SANDBOX_ID> <LOCAL_PATH> <REMOTE_PATH>
```

```bash
ebx upload sbx-xxxx ./script.py /app/script.py
ebx upload sbx-xxxx ./data/ /app/data/
```

### ebx download

从沙箱下载文件到本地。

```bash
ebx download <SANDBOX_ID> <REMOTE_PATH> <LOCAL_PATH>
```

```bash
ebx download sbx-xxxx /app/result.csv ./result.csv
ebx download sbx-xxxx /app/output.log .
```

---

## 自定义命令

### ebx run

执行模板定义的自定义命令或通过 `@registry.command` 注册的命令。

```bash
ebx run <SANDBOX_ID> <COMMAND_NAME> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--arg` | `-a` | 参数 `KEY=VALUE`（可重复） |

支持两种参数风格：

```bash
# Legacy 风格
ebx run sbx-xxxx dev --arg file=tests/

# 新风格（透传 --key value）
ebx run sbx-xxxx demo --x 1 --y hello
```

#### 自定义命令的两种机制

**机制 A：template.yaml 声明式**

在 `template.yaml` 中通过 `custom_commands` 定义简单 Shell 命令，使用占位符传参：

```yaml
custom_commands:
  dev:
    command: "npm run dev"
  test:
    command: "pytest {file} -v"
    description: "Run tests"
```

执行示例：

```bash
ebx run sbx-xxxx test --arg file=tests/test_api.py
# 实际执行: pytest tests/test_api.py -v
```

**机制 B：@registry.command 注册式**

在沙箱内运行的 Python 代码中通过装饰器注册自定义命令，支持带类型的参数和复杂逻辑：

```python
from easy_sandbox.server.registry import registry

@registry.command("greet")
def greet(name: str) -> str:
    return f"Hello, {name}!"

registry.freeze()
```

执行示例：

```bash
ebx run sbx-xxxx greet --name World
```

**解析逻辑**：`ebx run` 调用 `Sandbox.custom()`，先尝试机制 A（模板 `custom_commands`），若命令未找到则自动回退到机制 B（SandboxServer 上的 `@registry.command`），对用户透明。统一返回类型为 `CommandResult`，包含 `value`、`stdout`、`stderr`、`exit_code`、`execution_time` 和 `source`（`"template"` 或 `"server"`）。

---

## 配置命令 — ebx config

### ebx config get

```bash
ebx config get <KEY>
```

可用配置键：`api_key`、`api_url`、`region`、`http_timeout`、`max_retries`、`domain`、`llm_api_key`、`llm_model`、`llm_base_url`。

### ebx config set

```bash
ebx config set <KEY> <VALUE>
```

### ebx config list

```bash
ebx config list
```

显示所有配置值及其来源（user/default）。

### ebx config reset

```bash
ebx config reset [--yes/-y]
```

---

## 模板命令 — ebx template

### ebx template init

从内置案例脚手架生成一个新模板目录，无需手写 `template.yaml` / `Dockerfile` / `commands.py`。

```bash
ebx template init [DIRECTORY] [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--template` | `-t` | 内置脚手架案例（`python`、`node`、`minimal`） |
| `--from` | | 从 registry 引用拉取模板源码 |
| `--name` | | 模板名称 |
| `--list` | | 列出可用脚手架案例 |
| `--force` | | 覆盖已存在的文件 |

**DIRECTORY 行为**：省略 `DIRECTORY` 时，会在当前工作目录下新建 `./<name>` 子目录。`<name>` 按以下优先级解析：

1. `--name` 的值（最高优先级）
2. 脚手架案例名（`-t/--template` 的值，如 `python`）
3. `--from` 拉取到的模板名

```bash
# 列出可用脚手架案例
ebx template init --list

# Python 模板，省略 DIRECTORY → 创建 ./python/
ebx template init -t python

# 指定 --name → 创建 ./myapp/
ebx template init -t python --name myapp

# 显式指定 DIRECTORY → 使用该目录
ebx template init -t python ./my-template

# 从 registry 引用拉取，省略 DIRECTORY → 创建 ./<template-name>/
ebx template init --from owner/repo
```

`--list` 输出示例：

```
  python       Python 3.11 sandbox with shell, files, and code capabilities
  node         Node.js 20 sandbox with shell, files, and code capabilities
  minimal      Bare-minimum template with only template.yaml + Dockerfile
```

脚手架会打印创建的文件和后续步骤：

```
✅ Template 'my-template' created in ./my-template
Created files:
  Dockerfile
  README.md
  commands.py
  template.yaml

Next steps:
  ebx template deploy ./my-template --acr-namespace <ns>
  ebx install ./my-template --acr-namespace <ns>
```

### ebx init（快捷方式）

`ebx template init` 的顶层快捷方式，行为完全一致（包括省略 DIRECTORY 时自动新建子目录，参见上文）：

```text
Usage: ebx init [OPTIONS] [DIRECTORY]

  Scaffold a new template (shortcut for 'ebx template init').

Options:
  -t, --template TEXT  Built-in scaffold case (python, node, minimal)
  --from TEXT          Fetch template source from a registry ref
  --name TEXT          Template name
  --list               List available scaffold cases
  --force              Overwrite existing files
  --help               Show this message and exit.
```

### ebx template deploy

一键部署：本地 Docker 构建 → ACR 推送 → 创建沙箱模板（即 build + push + create 的端到端流水线）。

默认使用**官方 CreateTemplate API**（需要 AK/SK 和 `easy-sandbox[alicloud]`；若尚未安装 CLI 请用 `pip install "easy-sandbox[cli,alicloud]"`）。
旧脚本请使用 `--legacy-api` 切换回 v3/v2 API。

```bash
ebx template deploy <TEMPLATE_DIR> [选项]
```

| 选项 | 说明 |
|------|------|
| `--acr-registry` | ACR 注册中心主机（默认 `registry.cn-hangzhou.aliyuncs.com`） |
| `--acr-namespace` | ACR 命名空间（CLI > 环境变量 > `.env` 文件解析；均未找到时报错，参见下方「参数默认值与优先级」） |
| `--acr-repo` | ACR 仓库名（默认读取模板目录 `template.yaml` 的 `name` 字段，其次为模板目录名） |
| `--acr-username` / `--acr-password` | ACR 凭证（默认从 .env 读取 AK/SK） |
| `--acree-instance-id` | ACR EE 实例 ID |
| `--tag` / `-t` | Docker 镜像标签（默认 `latest`） |
| `--platform` | 目标平台（默认 `linux/amd64`） |
| `--cpu` | CPU 核数（默认读取 `template.yaml` 的 `resources.cpu`，缺省 2） |
| `--memory` | 内存 MB（默认读取 `template.yaml` 的 `resources.memory`，缺省 2048） |
| `--disk-size` | 磁盘大小 MB（仅官方 API） |
| `--internet-access/--no-internet-access` | 联网访问（仅官方 API） |
| `--official-api/--legacy-api` | 使用官方 API（默认）或旧 v3/v2 API |
| `--team-id` | Team ID |
| `--envd-inject/--no-envd-inject` | envd 注入（默认开启） |
| `--generation` | 沙箱代数（1 = 一代 rund，2 = 二代 MicroVM Beta；默认 1；也可从 `template.yaml` 的 `generation` 字段读取） |
| `--target-image` | envd copy 的目标镜像 ref（省略时自动派生随机后缀） |
| `--dockerfile` / `-f` | 自定义 Dockerfile 路径 |
| `--start-cmd` / `--ready-cmd` | 启动/就绪命令 |
| `--timeout` | 构建超时秒数 |
| `--vpc-id` | VPC ID，用于 ACR 访问（环境变量：ACR_VPC_ID） |
| `--vswitch-ids` | VSwitch ID 列表（环境变量：ACR_VSWITCH_IDS） |
| `--security-group-id` | 安全组 ID（环境变量：ACR_SECURITY_GROUP_ID） |
| `--alias` / `-a` | 模板别名（默认与解析后的仓库名一致） |

```bash
# 一键部署（默认官方 API）
ebx template deploy ./examples/templates/python-hello \
  --acr-namespace my-ns --acr-repo python-hello

# 指定磁盘和联网
ebx template deploy ./my-template \
  --acr-namespace prod --disk-size 10240 --internet-access

# ACR EE 实例
ebx template deploy ./my-template \
  --acr-namespace prod --acree-instance-id cri-xxx

# 旧 API
ebx template deploy ./my-template \
  --acr-namespace prod --legacy-api
```

> **三条路径说明**：
> - **一键部署**（推荐）：`template deploy` → Docker 构建 → ACR 推送 → `CreateTemplate` API。
> - **分步操作**：`template build` → `template push` → `template create`，适合需要自定义中间步骤的场景。
> - **仅镜像创建**：`ebx template create <IMAGE>` 只调用 CreateTemplate API，不做本地构建。

#### 参数默认值与优先级

`template build` / `template deploy` 的参数按以下 **5 级优先级链**解析（从高到低）：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | CLI 显式传入 | 如 `--acr-namespace my-ns`（最高优先级） |
| 2 | 操作系统环境变量 | 如 `ACR_NAMESPACE` |
| 3 | 当前工作目录的 `.env` 文件 | 如 `.env` 中写入 `ACR_NAMESPACE=serverless-sandbox-test` |
| 4 | 模板目录下的 `template.yaml` | `name` → `--acr-repo`/`--alias`；`resources.cpu` → `--cpu`；`resources.memory` → `--memory` |
| 5 | 硬编码兜底值 | cpu=2、memory=2048、tag=latest、platform=linux/amd64（最低优先级） |

各参数的默认值来源：

| 参数 | 默认值解析顺序 |
|------|----------------|
| `--acr-namespace` | CLI > 环境变量 `ACR_NAMESPACE` > `.env` 文件；均未找到时抛出友好的 `UsageError`（该参数仍为**事实上的必填项**，只是不再强制要求出现在命令行上） |
| `--acr-repo` | CLI > `template.yaml` 的 `name` > 模板目录名 |
| `--alias` | CLI > 解析后的仓库名 |
| `--cpu` | CLI > `template.yaml` 的 `resources.cpu` > `2` |
| `--memory` | CLI > `template.yaml` 的 `resources.memory` > `2048` |
| `--tag` | CLI > `latest` |
| `--platform` | CLI > `linux/amd64` |

`template.yaml` 中参与解析的字段示例：

```yaml
name: node-web          # → --acr-repo / --alias
resources:
  cpu: 2                # → --cpu
  memory: 2048          # → --memory
```

#### `.env` 文件支持

CLI 会自动读取**当前工作目录**下的 `.env` 文件，可用于提供 `ACR_NAMESPACE` 等配置：

```bash
# .env
ACR_NAMESPACE=serverless-sandbox-test
```

- 操作系统环境变量的优先级高于 `.env` 文件。
- 建议将 `.env` 加入 `.gitignore`，避免泄露配置。

#### 最简用法

得益于 `template.yaml` 与 `.env` 的自动解析，大多数参数可以省略：

```bash
# .env 中已配置 ACR_NAMESPACE 时，只需传模板目录：
ebx template deploy ./examples/templates/node-web
ebx template build ./examples/templates/node-web

# 没有 .env 时，也可以在命令行内联指定命名空间：
ebx template deploy ./examples/templates/node-web --acr-namespace serverless-sandbox-test
```

仓库名、别名、CPU、内存等参数会自动从模板目录的 `template.yaml` 读取，无需重复指定。

### ebx template build

只构建 Docker 镜像并推送到 ACR + 注册模板（与 `deploy` 参数相同）。

```bash
ebx template build <TEMPLATE_DIR> [选项]
```

参数与 `template deploy` 相同（包括 `--target-image` 和 `--generation`），参见上方选项表及「参数默认值与优先级」小节。

### ebx template push

只推送已有本地镜像到 ACR。

```bash
ebx template push <IMAGE> [选项]
```

| 选项 | 说明 |
|------|------|
| `--acr-registry` | ACR 注册中心主机（默认 `registry.cn-hangzhou.aliyuncs.com`） |
| `--acr-namespace` | ACR 命名空间（必需） |
| `--acr-username` / `--acr-password` | ACR 凭证 |
| `--acree-instance-id` | ACR EE 实例 ID |

### ebx template create

从已有容器镜像创建沙箱模板。使用阿里云 FCSandbox 官方 CreateTemplate API。

> **前置条件**：需要 AK/SK 凭证和 `pip install "easy-sandbox[alicloud]"` SDK 扩展（或直接安装 `pip install "easy-sandbox[cli,alicloud]"`）。

```bash
ebx template create <IMAGE> --name <NAME> [选项]
```

| 选项 | 说明 |
|------|------|
| `--name` / `-n` | 模板名称（必需） |
| `--team-id` | Team ID（或环境变量 `TEAM_ID` / `E2B_TEAM_ID`，缺省自动解析） |
| `--cpu` | CPU 核数（默认 2） |
| `--memory` | 内存 MB（默认 2048） |
| `--disk-size` | 磁盘大小 MB |
| `--internet-access/--no-internet-access` | 联网访问（默认由平台决定） |
| `--generation` | 沙箱代数（1 = 一代 rund，2 = 二代 MicroVM Beta；默认 1；也可从 `template.yaml` 的 `generation` 字段读取） |
| `--target-image` | envd copy 的目标镜像 ref（省略时自动派生随机后缀） |
| `--envd-inject/--no-envd-inject` | 启用 envd 注入 |
| `--registry-type` | 镜像仓库类型：`acr` / `acree`（自动检测） |
| `--acree-instance-id` | ACR EE 实例 ID |
| `--registry-username` | 镜像仓库用户名 |
| `--registry-password` | 镜像仓库密码 |
| `--start-cmd` | 容器启动命令 |
| `--ready-cmd` | 容器就绪检查命令 |

```bash
# 从已推送的 ACR 镜像创建
ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag --name my-template

# 指定资源和参数
ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \
  --name my-tpl --cpu 4 --memory 4096 --disk-size 10240 --internet-access
```

### ebx template install

下载模板并（默认）构建 + 部署。默认情况下，`install` 先下载模板，然后执行 docker build、推送到 ACR、并通过官方 API 创建沙箱模板。使用 `--download-only` 跳过构建/部署步骤，仅下载到本地缓存（`~/.ebx/templates/`）。

```bash
ebx template install <TEMPLATE_REF> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--registry-url` | | Registry URL（默认 GitHub） |
| `--registry-type` | | `github` / `local`（未指定时自动检测） |
| `--token` | | 私有仓库访问令牌 |
| `--alias` | `-a` | 模板别名 |
| `--download-only` | | 仅下载到本地缓存（跳过构建和部署） |
| `--dir` | | 将模板源码下载到自定义目录，而非默认缓存路径（`~/.ebx/templates`） |
| `--acr-namespace` | | 部署使用的 ACR 命名空间（环境变量 `ACR_NAMESPACE`，或在 `.env` 中设置） |
| `--cpu` | | CPU 核数（默认：来自 `template.yaml` 或 2） |
| `--memory` | | 内存 MB（默认：来自 `template.yaml` 或 2048） |
| `--yes` | `-y` | 跳过确认提示 |

```bash
ebx install owner/repo --acr-namespace my-ns    # 下载 + 构建 + 部署
ebx install owner/repo --download-only          # 仅下载
ebx install owner/repo//subdir --download-only  # 仓库子目录
ebx install ./my-template --acr-namespace ns    # 本地目录 + 部署
ebx install owner/repo@v1.0 --yes               # 跳过确认
```

> ⚠️ **成本与安全**：不带 `--download-only` 时，`install` 会向 ACR 推送镜像并调用官方 `CreateTemplate` API——这些操作可能在你的阿里云账号上产生费用。若未解析到 ACR 命名空间（通过 `--acr-namespace`、`ACR_NAMESPACE` 或 `.env`），install 会在构建前停下并提示如何提供。

### ebx install（快捷方式）

`ebx template install` 的顶层快捷方式（选项——包括 `--dir`——与默认完整流水线行为完全一致）：

```bash
ebx install owner/repo --acr-namespace my-ns
ebx install owner/repo --download-only
```

### ebx template list

列出可用模板。

```bash
ebx template list [选项]
```

| 选项 | 说明 |
|------|------|
| `--official-api/--no-official-api` | 使用阿里云官方 API（默认 false） |

### ebx template info

查看模板详情。

```bash
ebx template info <TEMPLATE_ID> [选项]
```

| 参数/选项 | 说明 |
|-----------|------|
| `TEMPLATE_ID` | 模板 ID（必需） |
| `--official-api/--no-official-api` | 使用阿里云官方 API |

### ebx template delete

删除模板。

```bash
ebx template delete <TEMPLATE_ID>
```

### ebx template search

搜索模板。

```bash
ebx template search <QUERY> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--tag` | `-t` | 按标签过滤 |
| `--status` | `-s` | 按状态过滤 |

---

## MCP 命令 — ebx mcp

### ebx mcp install

```bash
ebx mcp install --target <cursor|claude|vscode>
```

将 MCP Server 配置写入目标 IDE 的配置文件。

### ebx mcp start

```bash
ebx mcp start [选项]
```

| 选项 | 说明 |
|------|------|
| `--template` | 默认模板（默认 code-interpreter-v1） |
| `--api-key` | API Key 覆盖 |
| `--api-url` | API URL 覆盖 |
| `--domain` | Domain 覆盖 |

以 STDIO 模式启动本地 MCP Server（通常由 IDE 自动调用）。此模式不需要 HTTP 传输依赖。

### ebx mcp status

```bash
ebx mcp status
```

显示 MCP Server 状态、可用工具数量、各 IDE 安装状态。

### ebx mcp deploy

```bash
ebx mcp deploy [选项]
```

生成用于手动部署远程 MCP Server 到阿里云函数计算（FC）的产物，使用 MCP Streamable HTTP（2025-06-18）。此命令不会调用 FC 部署 API。HTTP 运行时需要安装 `easy-sandbox[mcp]`；若缺少 Starlette，创建应用时会抛出明确的 `RuntimeError`。

| 选项 | 说明 |
|------|------|
| `--name` | FC 函数名（默认 easy-sandbox-mcp） |
| `--region` | FC 区域（默认 cn-hangzhou） |
| `--template` | 默认沙箱模板 |
| `--memory` | FC 函数内存（MB，默认 512） |
| `--timeout` | FC 函数超时（秒，默认 600） |
| `--auth-token-file` | Bearer Token 文件路径 |
| `--generate-token` | 自动生成随机 Bearer Token |
| `--enable-session-affinity/--no-session-affinity` | 启用 Mcp-Session-Id 会话亲和（默认开启） |
| `--api-key` | 注入到 FC 环境变量的 E2B_API_KEY |
| `--custom-domain` | 自定义域名 |
| `--output-dir` | 将 FC 部署产物写到指定目录 |

**示例：**

```bash
# 使用自动生成的 token 创建部署产物
ebx mcp deploy --generate-token --api-key $E2B_API_KEY \
  --output-dir ./deploy-artifact

# 使用 token 文件创建部署产物
ebx mcp deploy --auth-token-file ./token.txt --region cn-shanghai \
  --output-dir ./deploy-artifact
```

命令会写出 `requirements.txt`、`app.py` 和 `config.yaml`，并输出手动部署步骤。`config.yaml` 是与平台 API 无关的部署清单，不是 FC API 请求体。请使用阿里云 FC 官方控制台或 SDK 打包产物、创建函数与 HTTP Trigger，并将清单设置转换为官方配置。部署后，将 IDE 模板中的 `<FC_HTTP_TRIGGER_URL>` 和 `<BEARER_TOKEN>` 替换为实际值。

`POST /mcp` 处理请求，`DELETE /mcp` 终止会话；客户端结束时应调用 `DELETE /mcp`。`GET /mcp` 当前返回 501，SSE 服务端通知留待 Phase 2 实现。会话亲和要求 FC 能将相同 `Mcp-Session-Id` 的请求路由到同一实例。

`config.yaml` 可能以明文包含 `E2B_API_KEY` 和 Bearer Token。请勿将部署产物或填入真实令牌后的 IDE 配置提交到版本库。

---

## 部署命令 — ebx deploy

```bash
ebx deploy [PATH] [INSTRUCTION] [选项]
```

使用 qwen-code agent 自动部署项目。详见 [部署与构建](../guide/deploy-and-build.md)。

| 参数/选项 | 简写 | 说明 |
|-----------|------|------|
| `PATH` | | 项目路径（可选） |
| `INSTRUCTION` | | 自然语言部署指令（可选） |
| `--instruction` | `-i` | 自然语言部署指令（替代位置参数 INSTRUCTION） |
| `--max-wall-time` | | qwen-code agent 最大执行时间（默认 "10m"） |
| `--max-tool-calls` | | qwen-code agent 最大工具调用次数（默认 100） |
| `--alias` | `-a` | 模板别名（传统模式） |
| `--watch` | | 监听文件变更并自动重新部署（传统模式） |
| `--traditional` | | 使用传统 build+run 模式替代 AI 部署 |

---

## sandbox 子命令组

`ebx sandbox` 提供与顶层命令相同的沙箱操作，外加扩展子组：

```bash
ebx sandbox create / list / info / kill / exec / connect / upload / download / run
```

### ebx sandbox files — 扩展文件操作

| 子命令 | 说明 | 主要参数 |
|--------|------|----------|
| `list` | 列出目录内容 | `SANDBOX_ID`、`--path -p`（默认 /home/user）、`--recursive -r` |
| `stat` | 查看文件/目录信息 | `SANDBOX_ID`、`--path -p`（必选） |
| `mkdir` | 创建目录（含父目录） | `SANDBOX_ID`、`--path -p`（必选） |
| `rm` | 删除文件/目录 | `SANDBOX_ID`、`--path -p`（必选）、`--yes -y` |
| `mv` | 移动/重命名文件 | `SANDBOX_ID`、`--source -s`（必选）、`--dest -d`（必选） |
| `search` | 按 glob 模式搜索文件 | `SANDBOX_ID`、`--path -p`（必选）、`--pattern`（必选）、`--max-depth`（默认 5） |

```bash
ebx sandbox files list sbx-xxxx --path /app --recursive
ebx sandbox files stat sbx-xxxx --path /app/main.py
ebx sandbox files mkdir sbx-xxxx --path /app/data
ebx sandbox files rm sbx-xxxx --path /app/temp.log --yes
ebx sandbox files mv sbx-xxxx --source /app/old.py --dest /app/new.py
ebx sandbox files search sbx-xxxx --path /home/user --pattern "*.py"
ebx sandbox files search sbx-xxxx --path /app --pattern "*.log" --max-depth 3
```

### ebx sandbox process — 进程管理

| 子命令 | 说明 | 主要参数 |
|--------|------|----------|
| `list` | 列出运行中的进程 | `SANDBOX_ID` |
| `start` | 同步执行命令 | `SANDBOX_ID`、`--command -c`（必选）、`--timeout -t`（默认 300）、`--cwd` |
| `info` | 查看指定 PID 的进程详情 | `SANDBOX_ID`、`PID` |
| `signal` | 向进程发送信号 | `SANDBOX_ID`、`PID`、`--signal -s`（默认 15/SIGTERM） |

```bash
ebx sandbox process list sbx-xxxx
ebx sandbox process start sbx-xxxx --command "python app.py" --cwd /app
ebx sandbox process start sbx-xxxx -c "make build" --timeout 600
ebx sandbox process info sbx-xxxx 1234
ebx sandbox process signal sbx-xxxx 1234 --signal 9
```

### ebx sandbox system — 系统信息

| 子命令 | 说明 | 主要参数 |
|--------|------|----------|
| `info` | 查看系统信息（OS、CPU、内存、磁盘） | `SANDBOX_ID` |
| `env` | 查看环境变量（自动过滤敏感信息） | `SANDBOX_ID`、`--filter -f` |
| `ports` | 查看监听中的 TCP 端口 | `SANDBOX_ID` |
| `packages` | 列出已安装包（pip/npm） | `SANDBOX_ID`、`--manager -m`（默认 pip） |
| `metrics` | 查看资源使用情况（CPU 负载、磁盘用量） | `SANDBOX_ID` |

```bash
ebx sandbox system info sbx-xxxx
ebx sandbox system env sbx-xxxx --filter PATH
ebx sandbox system ports sbx-xxxx
ebx sandbox system packages sbx-xxxx --manager npm
ebx sandbox system metrics sbx-xxxx
```

### ebx sandbox capabilities — 能力组状态

查看沙箱当前启用的能力组（如 shell、files、code、terminal 等）。

```bash
ebx sandbox capabilities <SANDBOX_ID>
```

### ebx sandbox shell-stream — HTTP 流式 Shell

以 HTTP streaming 方式实时输出命令执行结果（与 `exec` 不同，输出逐行打印）。

```bash
ebx sandbox shell-stream <SANDBOX_ID> --command "pip install numpy"
ebx sandbox shell-stream <SANDBOX_ID> -c "make build" --cwd /app
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--command` | `-c` | 要执行的命令（必选） |
| `--timeout` | `-t` | 超时秒数（默认 300） |
| `--cwd` | | 工作目录 |

---

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数错误 |
| 3 | 认证失败 |
| 4 | 资源未找到 |
| 5 | 超时 |
| 6 | 配额超限 |
