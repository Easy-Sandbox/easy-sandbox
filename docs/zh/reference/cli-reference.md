# CLI 参考手册

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

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

输入 `exit`、`quit` 或 `Ctrl+D` 断开连接。每条命令在独立进程中执行。

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

执行模板定义的自定义命令或 `@sandbox.register` 注册的命令。

```bash
ebx run <SANDBOX_ID> <COMMAND_NAME> [选项]
```

支持两种参数风格：

```bash
# Legacy 风格
ebx run sbx-xxxx dev --arg file=tests/

# 新风格
ebx run sbx-xxxx demo --x 1 --y hello
```

---

## 认证命令 — ebx auth

### ebx auth login

```bash
ebx auth login [--api-key KEY]
```

交互式输入 API Key 并保存到 `~/.ebx/.env`。

### ebx auth logout

```bash
ebx auth logout
```

删除已保存的凭证。

### ebx auth status

```bash
ebx auth status
```

显示当前认证状态（API Key / AK/SK / 未认证）。

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

### ebx template install

从 GitHub 或本地目录安装模板。

```bash
ebx template install <TEMPLATE_REF> [选项]
```

| 选项 | 说明 |
|------|------|
| `--registry-url` | Registry URL（默认 GitHub） |
| `--registry-type` | `github` / `local`（自动检测） |
| `--token` | 私有仓库访问令牌 |
| `--alias` / `-a` | 模板别名 |

```bash
ebx template install owner/repo
ebx template install owner/repo@v1.0
ebx template install owner/repo//subdir
ebx template install ./my-template --registry-type local
```

### ebx install（快捷方式）

`ebx template install` 的顶层快捷方式：

```bash
ebx install owner/repo
```

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
| `--generation` | 沙箱代数（默认 1） |
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

### ebx template build-local

本地 Docker 构建 → ACR 推送 → 创建沙箱模板。

默认使用**官方 CreateTemplate API**（需要 AK/SK 和 `easy-sandbox[alicloud]`；若尚未安装 CLI 请用 `pip install "easy-sandbox[cli,alicloud]"`）。
旧脚本请使用 `--legacy-api` 切换回 v3/v2 API。

```bash
ebx template build-local <TEMPLATE_DIR> [选项]
```

| 选项 | 说明 |
|------|------|
| `--acr-registry` | ACR 注册中心主机（默认 `registry.cn-hangzhou.aliyuncs.com`） |
| `--acr-namespace` | ACR 命名空间（必需） |
| `--acr-repo` | ACR 仓库名（默认为模板目录名） |
| `--acr-username` / `--acr-password` | ACR 凭证（默认从 .env 读取 AK/SK） |
| `--acree-instance-id` | ACR EE 实例 ID |
| `--tag` / `-t` | Docker 镜像标签（默认 `latest`） |
| `--platform` | 目标平台（默认 `linux/amd64`） |
| `--cpu` | CPU 核数 |
| `--memory` | 内存 MB |
| `--disk-size` | 磁盘大小 MB（仅官方 API） |
| `--internet-access/--no-internet-access` | 联网访问（仅官方 API） |
| `--official-api/--legacy-api` | 使用官方 API（默认）或旧 v3/v2 API |
| `--team-id` | Team ID |
| `--envd-inject/--no-envd-inject` | envd 注入（默认开启） |
| `--generation` | 沙箱代数 |
| `--dockerfile` / `-f` | 自定义 Dockerfile 路径 |
| `--start-cmd` / `--ready-cmd` | 启动/就绪命令 |
| `--timeout` | 构建超时秒数 |

```bash
# 默认官方 API
ebx template build-local ./examples/templates/python-hello \
  --acr-namespace my-ns --acr-repo python-hello

# 指定磁盘和联网
ebx template build-local ./my-template \
  --acr-namespace prod --disk-size 10240 --internet-access

# ACR EE 实例
ebx template build-local ./my-template \
  --acr-namespace prod --acree-instance-id cri-xxx

# 旧 API
ebx template build-local ./my-template \
  --acr-namespace prod --legacy-api
```

> **两条路径说明**：
> - **官方路径**（默认）：`build-local` → Docker 构建 → ACR 推送 → `CreateTemplate` API。需要 AK/SK 和 `easy-sandbox[alicloud]`，默认 region 为 `cn-hangzhou`。
> - **旧路径**：`build-local --legacy-api` → Docker 构建 → ACR 推送 → v3/v2 Platform API。需要 E2B API Key。
> - **仅镜像创建**：`ebx template create <IMAGE>` 只调用 CreateTemplate API，不做本地构建。

---

## 会话命令 — ebx session

### ebx session start

```bash
ebx session start <NAME> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--template` | `-T` | 模板（默认 base） |
| `--timeout` | `-t` | 超时秒数 |
| `--env` | `-e` | 环境变量 `KEY=VALUE` |
| `--metadata` | `-m` | 元数据 `KEY=VALUE` |

### ebx session connect

```bash
ebx session connect <NAME>
```

### ebx session list

```bash
ebx session list
```

### ebx session stop

```bash
ebx session stop <NAME> [--keep-alive]
```

`--keep-alive` 仅取消跟踪会话，不销毁沙箱。

### ebx session info

```bash
ebx session info <NAME>
```

---

## 密钥命令 — ebx secret

### ebx secret create

```bash
ebx secret create <NAME>
```

交互式安全输入密钥值。

### ebx secret list

```bash
ebx secret list
```

### ebx secret delete

```bash
ebx secret delete <NAME>
```

### ebx secret inject

```bash
ebx secret inject <SANDBOX_ID> -s SECRET_NAME [-s ANOTHER_SECRET]
```

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

以 STDIO 模式启动 MCP Server（通常由 IDE 自动调用）。

### ebx mcp status

```bash
ebx mcp status
```

显示 MCP Server 状态、可用工具数量、各 IDE 安装状态。

---

## 部署命令 — ebx deploy

```bash
ebx deploy <PROJECT_PATH> <DESCRIPTION> [选项]
```

使用 qwen-code agent 自动部署项目。详见 [部署与构建](../guide/deploy-and-build.md)。

---

## Skill 命令 — ebx skill

### ebx skill search

```bash
ebx skill search <QUERY>
```

### ebx skill install

```bash
ebx skill install <SKILL_REF> [--target cursor|vscode|claude|project|global]
```

---

## sandbox 子命令组

`ebx sandbox` 提供与顶层命令相同的沙箱操作，外加扩展子组：

```bash
ebx sandbox create / list / info / kill / exec / connect / upload / download / run
```

### ebx sandbox files — 扩展文件操作

| 子命令 | 说明 | 主要参数 |
|--------|------|----------|
| `list` | 列出目录内容 | `SANDBOX_ID`、`--path`（默认 /home/user）、`--recursive` |
| `stat` | 查看文件/目录信息 | `SANDBOX_ID`、`--path`（必选） |
| `mkdir` | 创建目录（含父目录） | `SANDBOX_ID`、`--path`（必选） |
| `rm` | 删除文件/目录 | `SANDBOX_ID`、`--path`（必选）、`--yes` |
| `mv` | 移动/重命名文件 | `SANDBOX_ID`、`--source`、`--dest` |
| `search` | 按 glob 模式搜索文件 | `SANDBOX_ID`、`--path`、`--pattern`、`--max-depth` |

```bash
ebx sandbox files list sbx-xxxx --path /app --recursive
ebx sandbox files search sbx-xxxx --path /home/user --pattern "*.py"
```

### ebx sandbox process — 进程管理

| 子命令 | 说明 | 主要参数 |
|--------|------|----------|
| `list` | 列出运行中的进程 | `SANDBOX_ID` |
| `start` | 启动后台进程 | `SANDBOX_ID`、`--command`（必选）、`--timeout`、`--cwd` |
| `info` | 查看指定 PID 的进程详情 | `SANDBOX_ID`、`PID` |
| `signal` | 向进程发送信号 | `SANDBOX_ID`、`PID`、`--signal`（默认 15/SIGTERM） |

```bash
ebx sandbox process list sbx-xxxx
ebx sandbox process start sbx-xxxx --command "python app.py" --cwd /app
ebx sandbox process signal sbx-xxxx 1234 --signal 9
```

### ebx sandbox system — 系统信息

| 子命令 | 说明 | 主要参数 |
|--------|------|----------|
| `info` | 查看系统信息（OS、CPU、内存、磁盘） | `SANDBOX_ID` |
| `env` | 查看环境变量（自动过滤敏感信息） | `SANDBOX_ID`、`--filter` |
| `ports` | 查看监听中的 TCP 端口 | `SANDBOX_ID` |
| `packages` | 列出已安装包（pip/npm） | `SANDBOX_ID`、`--manager`（默认 pip） |
| `metrics` | 查看资源使用情况（CPU 负载、磁盘用量） | `SANDBOX_ID` |

```bash
ebx sandbox system info sbx-xxxx
ebx sandbox system packages sbx-xxxx --manager npm
ebx sandbox system metrics sbx-xxxx
```

### ebx sandbox capabilities — 能力组状态

查看沙箱当前启用的能力组（如 shell、files、code、terminal 等）。

```bash
ebx sandbox capabilities <SANDBOX_ID>
```

### ebx sandbox shell-stream — SSE 流式 Shell

以 SSE 流方式实时输出命令执行结果（与 `exec` 不同，输出逐行打印）。

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
