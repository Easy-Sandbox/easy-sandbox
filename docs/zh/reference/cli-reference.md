# CLI 参考手册

## 命令总览

```
ebx
├── 顶层快捷方式（11 个）
│   create / list / info / kill / exec / connect / run / upload / download / deploy / install
├── sandbox 子组（17 个）
│   ├── files: list / stat / mkdir / rm / mv / search
│   ├── process: list / start / info / signal
│   ├── system: info / env / ports / packages / metrics
│   ├── capabilities
│   └── shell-stream
├── template（10 个）
│   init / deploy / build / push / create / install / list / info / delete / search
├── config（5 个）
│   init / get / set / list / reset
└── mcp（4 个）
    install / start / status / deploy
```

### 已移除的命令组（0.1.0 之前迁移）

早期预发布版本中的以下命令组在首个正式版 `0.1.0` 之前已被移除——它们属于 **breaking change**，均有明确的替代路径：

| 已移除 | 替代路径 |
|--------|----------|
| `ebx auth login/logout/status/switch` | 用 `ebx config set api_key <value>` 持久化凭证，或直接使用 `E2B_API_KEY` / `SANDBOX_API_KEY` 环境变量；用 `ebx config list` 查看生效状态 |
| `ebx secret create/list/delete/inject` | 用环境变量或 `.env` 文件管理凭证与密钥；沙箱环境注入用 `ebx create --env KEY=VALUE` |
| `ebx session` / `ebx sessions list/info/rename/export/import/clean` | 会话数据仍由 `LocalSessionStore` 存储在本地 `~/.ebx/sessions/`；在程序中用 SDK 的 `Sandbox.connect()`（交互式 REPL `ebx connect <SANDBOX_ID>` 仍可用） |
| `ebx skill search/install/list/create/publish` | 模板是当前的能力分发机制（`ebx template search` / `ebx template install`）；仓库根目录的 `SKILL.md` 面向 Agent 使用说明 |

完整的 breaking change 清单与迁移说明见仓库 `CHANGELOG.md` 的 `Unreleased` 节。

### 该用哪个命令？—— `config init`、`template init` 与 `create`

| 目标 | 命令 | 做什么 | 访问云端？ |
|------|------|--------|-----------|
| 首次使用前存储凭证与端点 | `ebx config init` | 交互式引导向导（平台 API Key、区域、Qwen Code 凭证）；非 TTY 或加 `--yes` 时打印等效的 `ebx config set` 命令 | 否 |
| 脚手架生成本地模板工程 | `ebx template init [DIRECTORY]` | 在本地目录生成可编辑的 `template.yaml` + `Dockerfile`（及 `commands.py`）；不构建、不部署。顶层 `ebx init` 是委托到完全相同命令对象的快捷方式 | 否 |
| 创建云端沙箱 | `ebx create --template <名称>` / `ebx create "描述"` | `--template 名称` 直接启动已有模板（默认沙箱用 `base`）；仅提供自然语言描述时先走 research-first 澄清流程（Agent 自行检索公开事实，交互下每轮只问一个无法自行推断的问题），再走 Qwen Code 生成模板 → 构建部署 → 创建。裸 `ebx create`（无 `--template` 也无描述）会报显式用法错误，不会隐式启动 `base` | 是 |

```bash
# 1. 引导式凭证配置（首次使用先执行）
ebx config init

# 2. 用默认模板创建沙箱
ebx create

# 3. 用已有模板创建（不经过 AI 生成）
ebx create --template python-hello

# 4. 用自然语言创建（Qwen Code 生成并部署模板）
ebx create "一个预装 pandas 和 jupyter 的 Python 数据分析环境"

# 5. 脚手架生成本地模板工程，自行编辑与部署
ebx template init -t python ./my-template
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
| `--log-level` | | 设置日志级别：`debug`/`info`/`warning`/`error` |
| `--ci` | | CI/CD 模式（等同 `--quiet --no-color --json`） |
| `--timeout` | `-t` | 默认沙箱生命周期秒数（正整数，默认 300） |
| `--profile` | `-p` | [预留] 配置文件 |
| `--version` | | 显示版本号 |
| `--help` | `-h` | 显示帮助并退出（所有命令与子命令组均可用） |

> **`-h` / `--help` 在每个层级均可用**：别名在根命令处集中启用一次，并由整棵命令树继承，因此 `ebx -h`、`ebx sandbox -h`、`ebx sandbox files list -h` 都会显示所指向命令的帮助。若某命令自身占用了 `-h` 参数，该参数保持不变——Click 只在那一处移除别名，`--help` 仍然可用。

> **区域是命令级选项，而非全局选项**：只有访问区域控制面的命令才接受 `--region`/`-r` —— [`ebx list`](#ebx-list)、[`ebx kill`](#ebx-kill)、模板控制面命令（`list`/`info`/`create`/`push`/`build`/`install`/`delete`）以及 [`ebx mcp deploy`](#ebx-mcp-deploy)。解析优先级：命令 `--region` > `ebx config set region` / `SANDBOX_REGION` 环境变量 > `cn-hangzhou`。持久默认值请通过 `ebx config set region` 设置。

---

## 沙箱生命周期命令

### ebx create

创建新沙箱。

**路由规则**（决定走哪条路径）：

| 调用方式 | 路径 |
|---------|------|
| `ebx create`（无参数） | **拒绝执行** —— 显式用法错误（退出码 2），列出三种合法路由选项；裸 create 不再默认 `base` |
| `ebx create --template <名称>` | 直接模板路径（不经过 AI 生成） |
| `ebx create "自然语言描述"` | AI 路径：research-first 澄清（Agent 在自身原生会话上先检索公开事实，交互下每轮只问一个无法自行推断的问题）→ Qwen Code 生成 Dockerfile + template.yaml → 构建部署 → 创建沙箱 |
| `ebx create "描述" --template <名称>` | **拒绝执行** —— `DESCRIPTION` 与 `--template` 互斥；抛出用法错误（退出码 1），绝不静默忽略描述 |

互斥是有意设计：否则必须静默丢弃描述或模板中的一个，因此 CLI 直接拒绝该组合。

AI 路径需要本机可用的 Qwen Code CLI 与 DashScope/ModelStudio 凭证。未安装时会在交互式终端提示安装官方 standalone 版本（经 SHA256 校验后安装到 `~/.ebx/bin`）；非交互环境必须显式传入 `--yes`。

生成之前，Agent 会在同一个原生会话上执行两阶段澄清：先跑一轮普通**检索轮**（用它自己的工具确认可公开查证的事实——工具技术栈、官方安装方式、常见依赖；检索不到时采用安全合理默认值），再做一次**结构化评估**（完整度目标 80%）。低于阈值时，交互式会话每轮只问 **一个问题**，以 `Question 1`、`Question 2` 逐次编号（不显示总数；内部 5 轮上限仅在触达时提示）；每次回答都恢复同一会话并基于完整描述 + 全部问答历史重新评估，已问过的主题不会重复，回答“你自己决定”“采用默认”等授权语义会让 Agent 自行采用安全合理默认值。非交互会话未传 `--yes` 时快速失败并抛 `E2008`，列出缺失项与可直接套用的示例描述；`--yes` 完全跳过检索与评估。评估不可用（超时、崩溃、无法解析）时打印 warning 并直接生成。

```bash
ebx create [DESCRIPTION] [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--template` | `-T` | 模板 ID 或别名（默认 `base`）；提供后跳过 AI 生成；不能与 DESCRIPTION 同时使用 |
| `--upload` | `-u` | 创建后自动上传的本地文件/目录 |
| `--timeout` | `-t` | 沙箱生命周期秒数（正整数，默认全局 `--timeout`） |
| `--request-timeout` | | HTTP 请求超时秒数（下限 120s 或已配置的 `http_timeout`） |
| `--env` | `-e` | 环境变量 `KEY=VALUE`（可重复） |
| `--metadata` | `-m` | 元数据 `KEY=VALUE`（可重复） |
| `--yes` | `-y` | 跳过交互确认与 research-first 澄清流程（Qwen Code 安装、凭证输入、描述检索/评估、构建/部署确认）；非交互环境必填 |
| `--acr-namespace` | | AI 生成模板构建推送所用的 ACR 命名空间（env: `ACR_NAMESPACE`） |
| `--verbose` | `-v` | 详细输出（DEBUG 级别） |

```bash
# 使用默认 base 模板创建沙箱
ebx create --template base

# AI 生成模板并创建（交互式；非交互环境需 -y）
ebx create "一个 Python 数据分析环境"
ebx create -y "a node.js api server"

# 非交互下描述不完整 → E2008（缺失项 + 示例）
# ebx create "run python"

# 创建并上传文件
ebx create --upload ./app --timeout 600 --env MY_KEY=value

# 拒绝：DESCRIPTION 与 --template 不能同时提供（退出码 1）
# ebx create "a node.js api server" --template base

# 拒绝：裸 `ebx create`（无 --template 也无描述，退出码 2）
# ebx create
```

AI 路径失败（未安装 `E2005`、缺少凭证 `E2006`、生成失败 `E2007`）时不会静默降级为 `base`，而是打印 Quick Setup 与下一步命令。

### ebx list

列出沙箱，可按生命周期状态过滤。

```bash
ebx list [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--status` | `-s` | 按状态过滤：`running`/`stopped`/`creating`/`paused`/`error` |
| `--limit` | `-l` | 最大结果数（正整数，默认 20） |
| `--region` | `-r` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

### ebx info

查看沙箱状态、模板、区域、超时和 URL。

```bash
ebx info <SANDBOX_ID>
```

### ebx kill

永久销毁一个沙箱或所有运行中的沙箱。需要确认，除非传入 `--yes`。

```bash
ebx kill [SANDBOX_ID] [选项]
ebx kill --all [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--all` | | 销毁所有运行中的沙箱 |
| `--yes` | `-y` | 跳过确认 |
| `--region` | `-r` | `--all` 控制面调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

### ebx exec

在沙箱中执行一条命令并返回其退出码。

```bash
ebx exec <SANDBOX_ID> <COMMAND> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--timeout` | `-t` | 超时秒数（正整数，默认 60） |
| `--cwd` | | 工作目录 |
| `--verbose` | `-v` | 详细输出（DEBUG 级别） |

```bash
ebx exec abc123 "python --version"
ebx exec abc123 "pytest -q" --cwd /app --timeout 300
```

### ebx connect

连接到沙箱的交互式命令 REPL。这是**逐行** REPL，不是 PTY 也不是完整 SSH 会话：每行命令在新进程中执行（30 秒超时），`cd`、环境变量等 shell 状态不会跨命令保持（请使用 `cd /path && <cmd>` 单行写法，或 `ebx exec --cwd`）。

在支持行编辑的交互式终端上会启用基础行编辑与历史快捷键（Up/Down 历史、Ctrl+R 搜索、Ctrl+A/E）。输入 `exit`/`quit` 或按 `Ctrl+D` 断开连接；`Ctrl+C` 也会断开。命令失败时只给出一条友好提示，不会显示原始 HTTP 错误、完整沙箱 URL 或 MDN 链接。

```bash
ebx connect <SANDBOX_ID>
```

```bash
ebx connect abc123
```

---

## 文件操作命令

### ebx upload

上传本地文件或目录到沙箱。

```bash
ebx upload <SANDBOX_ID> <LOCAL_PATH> <REMOTE_PATH>
```

```bash
ebx upload abc123 ./script.py /app/script.py
ebx upload abc123 ./data/ /app/data/
```

### ebx download

从沙箱下载文件到本地。

```bash
ebx download <SANDBOX_ID> <REMOTE_PATH> <LOCAL_PATH>
```

```bash
ebx download abc123 /app/result.csv ./result.csv
ebx download abc123 /app/output.log .
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
| `--arg` | `-a` | 参数 `KEY=VALUE`（可重复，Legacy 风格） |

支持两种参数风格：

```bash
# Legacy 风格
ebx run abc123 test --arg file=tests/

# 新风格（透传 --key value）
ebx run abc123 demo --x 1 --y hello
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

管理持久化凭证和 CLI 默认配置。值存储在 `~/.ebx/config.toml` 和 `~/.ebx/.env` 中。运行时环境变量仍可覆盖已存储的配置。

### ebx config get

```bash
ebx config get <KEY>
```

可用配置键：

| 键 | 说明 |
|---|------|
| `api_key` | E2B API Key（存储在 `~/.ebx/.env`，输出时脱敏） |
| `access_key_id` | 阿里云 AccessKey ID（模板部署、ACR 推送） |
| `access_key_secret` | 阿里云 AccessKey Secret（输出时脱敏） |
| `api_url` | 平台 API URL |
| `domain` | envd 数据面域名 |
| `region` | 默认区域 |
| `http_timeout` | HTTP 请求超时秒数 |
| `http2` | 启用 HTTP/2（true/false） |
| `max_retries` | 最大重试次数 |
| `llm_api_key` | LLM API Key（NL 推断用，输出时脱敏；亦作为 Qwen Code 凭证的兼容回退） |
| `llm_model` | LLM 模型名称 |
| `llm_base_url` | LLM API 基地址（OpenAI 兼容） |
| `qwen_code_api_key` | Qwen Code API Key（AI 模板生成用，存储在 `~/.ebx/.env`，输出时脱敏） |
| `qwen_code_base_url` | Qwen Code OpenAI 兼容 Base URL（默认 DashScope compatible-mode） |
| `qwen_code_model` | Qwen Code 模型名称（默认 `qwen3-coder-plus`） |
| `github_token` | 模板下载用 GitHub 令牌（`ebx template install` / `ebx template search`；存储在 `~/.ebx/.env`，映射 `GITHUB_TOKEN`，输出脱敏） |

### ebx config init

引导式配置向导：平台 API Key、默认区域、Qwen Code（AI）凭证。

```bash
ebx config init
ebx config init --yes   # 非交互：打印等效的 ebx config set 命令
```

- 交互式终端中依次提示三项；敏感值（API Key）在终端支持时以星号反馈（每个字符一个 `*`，绝不回显原文），不支持时安全降级为无回显输入并明确提示。密钥存储到 `~/.ebx/.env`（`E2B_API_KEY`、`EBX_QWEN_CODE_API_KEY`），区域写入 `~/.ebx/config.toml`。
- Enter 接受当前值/跳过提示，退格编辑，Ctrl-C / EOF（Ctrl-D）干净地中止向导。
- 非 TTY 环境（CI、管道输入）或传入 `--yes` 时不阻塞：打印等效的非交互 `ebx config set` 命令并以 0 退出。

```bash
ebx config init
# 1/3 Platform API key (E2B_API_KEY, input masked)
# 2/3 Region (默认 cn-hangzhou)
# 3/3 Qwen Code API key (DashScope/ModelStudio, input masked)
```

### ebx config set

```bash
ebx config set <KEY> <VALUE>
```

配置存储在 `~/.ebx/config.toml`，凭证（`api_key`、`access_key_id`、`access_key_secret`、`qwen_code_api_key`、`github_token`）写入 `~/.ebx/.env`（权限 600）。

传入空 `<VALUE>` 时改为清除该键的持久化值：回落到内置业务默认值或变为 not set。 空字符串绝不会作为凭证或覆盖值写入。若仍有环境变量在运行时覆盖该键，命令会明确提示（但不打印其值）。

交互终端下可省略 `<VALUE>`：敏感键（`github_token`、`api_key`、`access_key_secret`、`qwen_code_api_key`）改用星号（脱敏）输入且不回显输入内容，其他键使用可见输入。在提示处直接回车则取消且不修改任何值；非交互环境必须显式传入 `<VALUE>`（否则以退出码 2 结束并提示等效命令）。

```bash
ebx config set api_key YOUR_API_KEY
ebx config set access_key_id YOUR_ACCESS_KEY_ID
ebx config set region cn-hangzhou
ebx config set http_timeout 120
ebx config set region ""        # 清除已存储的 region（回落默认）
ebx config set api_key ""       # 删除已存储的 API Key（变为 not set）
ebx config set github_token            # 星号脱敏输入（交互终端可省略 VALUE）
ebx config set github_token YOUR_GITHUB_TOKEN
ebx config set github_token ""         # 删除已存储的 token
```

### ebx config list

```bash
ebx config list
```

显示所有生效的配置值及其来源：`(env)` 进程环境变量、`(user)` 通过 `ebx config set` 存储的值、`(default)` 内置业务默认值、`(not set)` 任何来源都无值。有真实业务默认的键（如 `qwen_code_base_url`、`qwen_code_model`）显示具体默认值；无默认的键（`llm_api_key`、`llm_base_url`、`llm_model`）显示 `(not set)`。敏感值始终脱敏。

### 清除已存储的值

不存在 `ebx config reset` 命令。使用 `ebx config set KEY ""` 逐键清除——空字符串绝不会作为凭证写入——该键回到业务默认值或 not set。

---

## 模板命令 — ebx template

发现、脚手架、构建和管理沙箱模板。

### ebx template init

从内置案例脚手架生成新模板目录。

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

**DIRECTORY 行为**：省略时在当前目录下新建 `./<name>` 子目录。`<name>` 按优先级：`--name` > 脚手架案例名 > `--from` 拉取到的模板名。

```bash
ebx template init --list
ebx template init -t python
ebx template init -t python --name myapp
ebx template init -t python ./my-template
ebx template init --from owner/repo
```

> 顶层 `ebx init` 快捷方式**存在**：它与 `ebx template init` 是同一个命令对象（选项不变）。引导式凭证配置是 `ebx config init`。
>
> 未知顶层命令会得到针对性提示：拼写相近时给出 `Did you mean '…'?` 建议；否则错误信息指向模板 `custom_commands`（在 `template.yaml` 中声明），并通过 `ebx run COMMAND` 调用。

### ebx template deploy

一键部署：本地 Docker 构建 → ACR 推送 → 创建沙箱模板（`template build` 的别名）。

> **云端副作用与成本**：ACR 推送与远端模板注册是云端操作，可能产生阿里云费用（ACR 存储/流量、模板资源）。任何云端操作开始前都需要交互确认（或 `--yes`）；非交互环境会快速失败而不是静默部署。

需要：Docker daemon 运行中、ACR 凭证、ACR 命名空间。AK/SK 凭证从 `ALICLOUD_ACCESS_KEY_ID` / `ALICLOUD_ACCESS_KEY_SECRET` 读取（当 `--acr-username`/`--acr-password` 未传时）。

```bash
ebx template deploy <TEMPLATE_DIR> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--acr-registry` | | ACR 注册中心主机 |
| `--acr-namespace` | | ACR 命名空间（CLI > 环境变量 `ACR_NAMESPACE` > `.env`） |
| `--acr-repo` | | ACR 仓库名（默认 `template.yaml` 的 `name` 或目录名） |
| `--acr-username` / `--acr-password` | | ACR 凭证 |
| `--acree-instance-id` | | ACR EE 实例 ID |
| `--vpc-id` | | VPC ID |
| `--vswitch-ids` | | VSwitch ID 列表（逗号分隔） |
| `--security-group-id` | | 安全组 ID |
| `--alias` | `-a` | 模板别名 |
| `--tag` | `-t` | Docker 镜像标签 |
| `--platform` | | 目标平台 |
| `--cpu` | | CPU 核数（默认 `template.yaml` → 2） |
| `--memory` | | 内存 MB（默认 `template.yaml` → 2048） |
| `--start-cmd` / `--ready-cmd` | | 启动/就绪命令 |
| `--timeout` | | 构建超时秒数 |
| `--dockerfile` | `-f` | 自定义 Dockerfile 路径 |
| `--disk-size` | | 磁盘大小 MB（仅官方 API） |
| `--internet-access/--no-internet-access` | | 联网访问（仅官方 API） |
| `--official-api/--legacy-api` | | 使用官方 API（默认）或旧 v3/v2 API |
| `--team-id` | | Team ID |
| `--envd-inject/--no-envd-inject` | | envd 注入（默认关闭） |
| `--generation` | | 沙箱代数（1=一代 rund，2=二代 MicroVM；默认 `template.yaml` → 1） |
| `--target-image` | | envd copy 目标镜像 ref |
| `--yes` | `-y` | 跳过确认 |
| `--verbose` | `-v` | 详细输出 |
| `--region` | `-r` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

```bash
ebx template deploy ./examples/templates/python-hello \
  --acr-namespace my-ns --acr-repo python-hello

ebx template deploy ./my-template --acr-namespace prod --yes
```

#### 参数默认值与优先级

`template build` / `template deploy` 的参数按 **5 级优先级链**解析（从高到低）：

| 优先级 | 来源 |
|--------|------|
| 1 | CLI 显式传入 |
| 2 | 操作系统环境变量 |
| 3 | 当前工作目录的 `.env` 文件 |
| 4 | 模板目录下的 `template.yaml` |
| 5 | 硬编码兜底值 |

> **自动化 / CI**：请在命令行显式传入 `--acr-namespace` 与模板目录，而不是依赖 `ACR_NAMESPACE` / `EBX_TEMPLATE_DIR` 环境变量或 `.env` 文件，避免构建随环境漂移。对 `template install` / `install`，要么显式传 `--acr-namespace`，要么在流程不应触碰云端时使用 `--download-only`。

### ebx template build

构建 Docker 镜像 + 推送到 ACR + 创建沙箱模板。

> **云端副作用与成本**：默认流水线为本地 Docker 构建 → ACR 推送 → 官方 CreateTemplate API 注册模板。ACR 推送与远端注册是云端操作，可能产生阿里云费用（ACR 存储/流量、模板资源）。云端操作开始前需要交互确认（或 `--yes`）。

支持两种模式：`--official-api`（默认，需 AK/SK 和 `easy-sandbox[alicloud]`）和 `--legacy-api`（旧 v3/v2 平台 API——保留在显式 flag 之后，非默认）。旧命令名 `ebx template build-local` 已在 `0.1.0` 之前移除，替代命令为 `ebx template build`（同一流水线、同一选项）。

```bash
ebx template build <TEMPLATE_DIR> [选项]
```

参数与 `template deploy` 相同。

### ebx template push

推送已有本地镜像到 ACR。

```bash
ebx template push <IMAGE> [选项]
```

| 选项 | 说明 |
|------|------|
| `--acr-registry` | ACR 注册中心主机 |
| `--acr-namespace` | ACR 命名空间 |
| `--acr-username` / `--acr-password` | ACR 凭证 |
| `--acree-instance-id` | ACR EE 实例 ID |
| `--region` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

```bash
ebx template push python-hello:latest --acr-namespace my-ns
```

### ebx template create

从已有容器镜像创建沙箱模板。使用阿里云 FCSandbox 官方 CreateTemplate API（需 AK/SK 和 `easy-sandbox[alicloud]`）。

```bash
ebx template create <IMAGE> --name <NAME> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--name` | `-n` | 模板名称（必需） |
| `--team-id` | | Team ID |
| `--cpu` | | CPU 核数（默认 2，FLOAT） |
| `--memory` | | 内存 MB（默认 2048） |
| `--disk-size` | | 磁盘大小 MB |
| `--internet-access/--no-internet-access` | | 联网访问 |
| `--generation` | | 沙箱代数 |
| `--envd-inject/--no-envd-inject` | | envd 注入 |
| `--target-image` | | envd copy 目标镜像 ref |
| `--registry-type` | | 镜像仓库类型：`acr` / `acree`（自动检测） |
| `--acree-instance-id` | | ACR EE 实例 ID |
| `--registry-username` | | 镜像仓库用户名 |
| `--registry-password` | | 镜像仓库密码 |
| `--start-cmd` | | 容器启动命令 |
| `--ready-cmd` | | 容器就绪检查命令 |
| `--region` | `-r` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

```bash
ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag --name my-template

ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \
  --name my-tpl --cpu 4 --memory 4096 --disk-size 10240 --internet-access
```

### ebx template install

下载模板并（默认）构建 + 部署。使用 `--download-only` 仅下载到本地缓存（`~/.ebx/templates/`）。使用 `--dir` 下载到自定义目录。

默认的构建 + 部署步骤会执行本地 Docker 构建、ACR 推送与 CreateTemplate 注册——这些云端操作可能产生阿里云费用（ACR 存储/流量、模板资源）；`--download-only` 可完全跳过。云端操作开始前需要交互确认（或 `--yes`）；非交互环境下前置条件缺失时会快速失败并提示 `--download-only`。

`TEMPLATE_REF` 可以是远程索引中的**裸模板名**（来自真源仓库 `Easy-Sandbox/awesome-templates`），也可以是 registry 引用（`owner/repo[//subdir][@ref]`）。裸名解析顺序：本地路径 → 内置模板（`base` / `code-interpreter-v1`，不触网）→ 远程索引（命中后打印 `Resolved '<name>' via the template index: ...`）。索引条目可声明 `ref` 锁定版本，锁定值会被遵守；裸名未命中时会强制刷新一次索引，新发布模板无需等待缓存过期。

```bash
ebx template install <TEMPLATE_REF> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--registry-url` | | Registry URL（默认 GitHub） |
| `--registry-type` | | `github` / `local`（自动检测） |
| `--token` | | GitHub 令牌：私有仓库访问 + 远程索引限流额度提升（环境变量：`GITHUB_TOKEN`）。仅作临时覆盖 —— 推荐 `ebx config set github_token`；`--token` 可能泄漏到 shell history 或进程列表 |
| `--alias` | `-a` | 模板别名 |
| `--download-only` | | 仅下载（跳过构建和部署） |
| `--dir` | | 下载到自定义目录 |
| `--acr-namespace` | | 部署用 ACR 命名空间 |
| `--cpu` | | CPU 核数 |
| `--memory` | | 内存 MB |
| `--yes` | `-y` | 跳过确认 |
| `--region` | `-r` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

```bash
ebx install owner/repo --acr-namespace my-ns    # 下载 + 构建 + 部署
ebx install owner/repo --download-only          # 仅下载
ebx install owner/repo//subdir --dir ./local    # 子目录 + 自定义路径
ebx install node-web --download-only            # 裸名经远程索引解析
ebx install Easy-Sandbox/awesome-templates//node-web@v1.0.0 --download-only  # 锁定版本
```

token 优先级：`--token` > 进程环境变量 `GITHUB_TOKEN` > 持久化的 `github_token`（`ebx config set github_token`；星号脱敏输入，存储在 `~/.ebx/.env`）> 无 token。匿名限流（E5000）时错误信息完整保留 `owner/repo//subdir@ref`（含子目录与锁定版本），并展示经官方文档核验的 fine-grained PAT 预填 URL（公共仓库无需额外权限，建议 90 天有效期）。仅在交互终端下引导一次星号（脱敏）配置 `github_token`，并 **只自动重试一次**；CI / 非交互环境则提示通过 Secret 注入 `GITHUB_TOKEN` 或在交互终端执行 `ebx config set github_token`。token 不会被打印或记录。

### ebx install（快捷方式）

`ebx template install` 的顶层快捷方式，选项和行为完全一致。

### ebx template list

列出当前账号注册的自定义模板。默认查询平台端点；传入 `--official-api` 使用阿里云 FCSandbox API（AK/SK）。

```bash
ebx template list [选项]
```

| 选项 | 说明 |
|------|------|
| `--official-api` | 使用阿里云官方 FCSandbox API（AK/SK） |
| `--region` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

### ebx template info

查看模板详情。传入 `--official-api` 使用阿里云 FCSandbox GetTemplate API。

```bash
ebx template info <TEMPLATE_ID> [选项]
```

| 选项 | 说明 |
|------|------|
| `--official-api` | 使用阿里云官方 FCSandbox API（AK/SK） |
| `--region` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

### ebx template delete

删除远端自定义模板（不可逆）。不移除本地缓存。需要确认。

```bash
ebx template delete <TEMPLATE_ID> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--yes` | `-y` | 跳过确认 |
| `--region` | `-r` | 本次调用的区域覆盖（默认：`ebx config set region` 值，否则 cn-hangzhou） |

### ebx template search

按名称、标签或描述搜索模板，查询真源仓库 [`Easy-Sandbox/awesome-templates`](https://github.com/Easy-Sandbox/awesome-templates) 的 `awesome-templates.yaml` 索引 。索引缓存于 `~/.ebx/index/`（TTL 1 小时，新鲜缓存不触网）；网络失败/限流时回退 过期缓存并打印 warning。无缓存时，匿名限流（E5000）给出统一引导 —— `ebx config set github_token` / `GITHUB_TOKEN`、fine-grained PAT 预填 URL、`--token` 泄漏提醒与镜像提示；仅在交互终端下引导一次星号（脱敏）配置并只自动重试一次（绝不循环）；非交互环境提示通过 Secret 注入或在交互终端执行 `ebx config set github_token`。

```bash
ebx template search <QUERY> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--tag` | `-t` | 按标签过滤 |
| `--status` | `-s` | 按状态过滤：`official` / `community` / `experimental` |
| `--index-url` | | 索引位置：HTTP(S) URL 或本地文件路径（环境变量：`EBX_TEMPLATE_INDEX_URL`；默认：官方远程索引） |
| `--token` | | GitHub 令牌（私有镜像 / 提升限流额度；环境变量：`GITHUB_TOKEN`）。仅作临时覆盖 —— 推荐 `ebx config set github_token` |
| `--refresh` | | 强制重新拉取索引，忽略本地缓存 |

```bash
ebx template search python
ebx template search browser --status official
ebx template search qwen --tag deploy
ebx template search python --refresh              # 绕过本地缓存
ebx template search web --index-url https://mirror.example/idx.yaml  # 内网镜像
```

---

## MCP 命令 — ebx mcp

配置和运行 Easy Sandbox MCP Server。支持本地 STDIO 传输（IDE 集成）和 Streamable HTTP 部署产物（手动部署到 FC）。

### ebx mcp install

将 MCP Server 配置写入目标 IDE 的配置文件。

```bash
ebx mcp install --target <cursor|claude|vscode>
```

| 选项 | 说明 |
|------|------|
| `--target` | 目标 IDE（`cursor` / `claude` / `vscode`，必选） |

### ebx mcp start

以 STDIO 模式启动本地 MCP Server（通常由 IDE 自动调用）。

```bash
ebx mcp start [选项]
```

| 选项 | 说明 |
|------|------|
| `--template` | 默认沙箱模板（默认 `code-interpreter-v1`） |
| `--api-key` | API Key 覆盖 |
| `--api-url` | API URL 覆盖 |
| `--domain` | Domain 覆盖 |

### ebx mcp status

显示 MCP 工具列表、认证状态和各 IDE 安装状态。

```bash
ebx mcp status
```

### ebx mcp deploy

生成阿里云 FC 部署产物（Streamable HTTP ASGI）。不调用 FC 部署 API。

`POST /mcp` 处理请求，`DELETE /mcp` 终止会话。`GET /mcp` 当前返回 501（SSE 通知留待 Phase 2）。

```bash
ebx mcp deploy [选项]
```

| 选项 | 说明 |
|------|------|
| `--name` | FC 函数名（默认 `easy-sandbox-mcp`） |
| `--region` | FC 区域（命令级覆盖；回退到 `ebx config set region` / `SANDBOX_REGION`，否则 `cn-hangzhou`） |
| `--template` | 默认沙箱模板 |
| `--memory` | FC 函数内存 MB |
| `--timeout` | FC 函数超时秒数 |
| `--auth-token-file` | Bearer Token 文件路径 |
| `--generate-token` | 自动生成随机 Bearer Token |
| `--enable-session-affinity/--no-session-affinity` | Mcp-Session-Id 会话亲和（默认开启） |
| `--api-key` | 注入到 FC 环境变量的 E2B_API_KEY |
| `--custom-domain` | 自定义域名 |
| `--output-dir` | 部署产物输出目录 |

```bash
ebx mcp deploy --generate-token --api-key $E2B_API_KEY --output-dir ./deploy-artifact
ebx mcp deploy --auth-token-file ./token.txt --region cn-shanghai --output-dir ./artifact
```

---

## 部署命令 — ebx deploy

使用 AI agent 或传统模式部署本地项目到沙箱。

```bash
ebx deploy [PATH] [INSTRUCTION] [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--instruction` | `-i` | 自然语言部署指令 |
| `--max-wall-time` | | qwen-code agent 最大执行时间（默认 `10m`） |
| `--max-session-turns` | | qwen-code 会话轮次上限（默认 100） |
| `--alias` | `-a` | 模板别名（传统模式） |
| `--watch` | | 监听文件变更自动重新部署（传统模式） |
| `--traditional` | | 使用传统 build+run 模式 |

```bash
ebx deploy ./my-project "deploy this FastAPI app on port 8080"
ebx deploy ./my-project --traditional --alias my-app
```

---

## sandbox 子命令组

`ebx sandbox` 提供与顶层命令相同的沙箱操作（create / list / info / kill / exec / connect / upload / download / run），外加以下扩展子组。

### ebx sandbox files — 文件操作

| 子命令 | 说明 | 主要选项 |
|--------|------|----------|
| `list` | 列出目录内容 | `--path -p`、`--recursive -r` |
| `stat` | 查看文件/目录信息 | `--path -p`（必选） |
| `mkdir` | 创建目录（含父目录） | `--path -p`（必选） |
| `rm` | 删除文件/目录 | `--path -p`（必选）、`--yes -y` |
| `mv` | 移动/重命名 | `--source -s`（必选）、`--dest -d`（必选） |
| `search` | 按 glob 搜索 | `--path -p`（必选）、`--pattern`（必选）、`--max-depth`（默认 5） |

```bash
ebx sandbox files list abc123 --path /app --recursive
ebx sandbox files stat abc123 --path /app/main.py
ebx sandbox files mkdir abc123 --path /app/data
ebx sandbox files rm abc123 --path /app/temp.log --yes
ebx sandbox files mv abc123 --source /app/old.py --dest /app/new.py
ebx sandbox files search abc123 --path /app --pattern "*.py"
```

### ebx sandbox process — 进程管理

| 子命令 | 说明 | 主要选项 |
|--------|------|----------|
| `list` | 列出运行中的进程 | — |
| `start` | 同步执行命令 | `--command -c`（必选）、`--timeout -t`（默认 300）、`--cwd` |
| `info` | 查看 PID 进程详情 | `PID` |
| `signal` | 发送信号 | `PID`、`--signal -s`（默认 15/SIGTERM） |

```bash
ebx sandbox process list abc123
ebx sandbox process start abc123 --command "python app.py" --cwd /app
ebx sandbox process info abc123 1234
ebx sandbox process signal abc123 1234 --signal 9
```

### ebx sandbox system — 系统信息

| 子命令 | 说明 | 主要选项 |
|--------|------|----------|
| `info` | 系统信息（OS、CPU、内存、磁盘） | — |
| `env` | 环境变量（自动过滤敏感信息） | `--filter -f`（逗号分隔变量名） |
| `ports` | 监听中的 TCP 端口 | — |
| `packages` | 已安装包（pip/npm） | `--manager -m`（默认 `pip`） |
| `metrics` | 资源使用（CPU 负载、磁盘用量） | — |

```bash
ebx sandbox system info abc123
ebx sandbox system env abc123 --filter PATH,HOME,LANG
ebx sandbox system ports abc123
ebx sandbox system packages abc123 --manager npm
ebx sandbox system metrics abc123
```

### ebx sandbox capabilities — 能力组状态

查看沙箱模板声明的能力组（shell、files、code、terminal、ports）。

```bash
ebx sandbox capabilities <SANDBOX_ID>
```

### ebx sandbox shell-stream — HTTP 流式 Shell

以 HTTP chunked streaming 方式实时输出命令执行结果。

```bash
ebx sandbox shell-stream <SANDBOX_ID> [选项]
```

| 选项 | 简写 | 说明 |
|------|------|------|
| `--command` | `-c` | 要执行的命令（必选） |
| `--timeout` | `-t` | 超时秒数（正整数，默认 300） |
| `--cwd` | | 工作目录 |

```bash
ebx sandbox shell-stream abc123 --command "pip install numpy"
ebx sandbox shell-stream abc123 -c "make build" --cwd /app
```

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
