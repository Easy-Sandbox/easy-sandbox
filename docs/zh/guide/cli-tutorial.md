# CLI 教程

本教程带你从安装开始，逐步掌握 `ebx` CLI 的完整沙箱生命周期、模板使用和 MCP 集成。

---

## 第一步：安装

```bash
pip install easy-sandbox
```

安装后即可使用 `ebx` 命令：

```bash
ebx --version
```

---

## 第二步：认证

### 通过 config 设置 API Key

```bash
ebx config set sandbox_api_key your-api-key
```

### 或通过环境变量

```bash
export E2B_API_KEY="your-api-key"
```

> 更多认证方式（AK/SK、.env 文件、config.toml 等）详见 [认证详解](authentication.md)。

---

## 第三步：创建沙箱

### 快速区分：`config init`、`template init` 与 `create`

| 我想要…… | 命令 |
|----------|------|
| 存储凭证与端点（首次使用先执行） | `ebx config init` —— 交互式引导向导 |
| 创建云端沙箱（默认模板、已有模板或 AI 生成） | `ebx create [DESCRIPTION]` |
| 脚手架生成本地可编辑的模板工程 | `ebx template init [DIRECTORY]` 或 `ebx template init "描述"` —— 只写本地文件，不构建、不部署。描述会先询问项目目录（回车保持 `./<name>/`） |
| 把已有项目变成模板 | `ebx template init --adopt [DIRECTORY]` —— 在原目录补上模板文件；不构建、不部署 |

### 使用默认模板

```bash
ebx create --template base
# 输出类似：
# ✓ Sandbox created: sbx-xxxx
```

### 自然语言创建（AI 生成模板）

```bash
# 首次使用：引导式配置凭证、区域、ACR 命名空间与 LLM Key
# ebx config init

# Qwen Code 生成 Dockerfile、commands.py（HTTP 服务）与 template.yaml → 构建部署 → 创建沙箱。
# 交互式终端会先询问是否改走 template init（只留本地文件）。--yes 保持完整流程。
ebx create "一个 Python 数据分析环境"

# 只生成模板文件 —— 不构建、不推送、不部署、不创建沙箱
ebx template init "一个 Python 数据分析环境"
```

生成之前，Agent 会先自行检索描述中**可公开查证的事实**——工具是否基于 Node.js、官方安装方式、常见运行时与依赖——再评估描述完整度（目标 80%）。只有用户偏好、私有约束和无法推断的业务决策才会成为问题，**每次只问一个**，以 `Question 1`、`Question 2` 逐次编号（不显示总数）；直接回车即可取消：

```text
Description is about 40% complete. I'll ask for the missing details one question at a time — press Enter to cancel.
Question 1: Which region and resource size should the sandbox use?
```

回答“你自己决定”“采用默认”等即视为授权 Agent 处理（采用安全合理默认值），已回答过的主题不会再次提问。

非交互环境（CI、管道输入）必须加 `-y` 跳过确认与澄清评估，否则安装/凭证/构建环节会直接报错并打印 Quick Setup；描述低于完整度阈值时则以 `E2008` 快速失败（附带缺失项与可直接套用的示例描述）：

```bash
# ebx create -y "a node.js api server"
# ebx create "run python"    # 非交互、描述不完整 → E2008
```

显式 `--template` 会跳过 AI 生成，走直接模板路径（`ebx create --template <名称>`）。`DESCRIPTION` 与 `--template` 互斥 —— 同时提供会被拒绝（用法错误），而不是静默忽略其中一个：

```bash
# ebx create "a node.js api server" --template base   # 拒绝执行（退出码 1）
```

### 创建时上传文件

```bash
ebx create --template base --upload ./project/ --env MY_KEY=value
```

---

## 第四步：查看与管理沙箱

### 列出所有沙箱

```bash
ebx list
ebx list --status running
ebx list --limit 5
```

### 查看详情

```bash
ebx info sbx-xxxx
```

---

## 第五步：在沙箱中执行命令

### 执行单条命令

```bash
ebx exec sbx-xxxx "echo Hello World"
ebx exec sbx-xxxx "pip install flask" --timeout 120
```

### 交互式连接

```bash
ebx connect sbx-xxxx
```

这是逐行 REPL，不是 PTY 也不是 SSH 会话：每行命令在独立进程中执行（30 秒
超时），`cd`、环境变量和 shell 状态不会跨行保持（请使用
`cd /path && <cmd>` 单行写法，或 `ebx exec --cwd`）。交互式终端支持基础行编辑
与历史快捷键（Up/Down、Ctrl+R、Ctrl+A/E）。输入 `exit`、`quit` 或按
`Ctrl+D` 退出；`Ctrl+C` 也会断开。命令失败时只给出一条友好提示。

```text
ebx:sbx-xxxx> ls /app
main.py  data/
ebx:sbx-xxxx> cd /app && python main.py
Hello from main.py
ebx:sbx-xxxx> exit
Disconnected.
```

---

## 第六步：文件操作

### 上传

```bash
ebx upload sbx-xxxx ./script.py /app/script.py
ebx upload sbx-xxxx ./data/ /app/data/
```

终端上，目录上传显示 `Uploading ... 12s`，灰色行为相对路径。不会打印文件内容。

### 下载

```bash
ebx download sbx-xxxx /app/result.csv ./result.csv
```

终端上，传输显示 `Downloading /app/result.csv... 12s`。不会打印文件内容。

---

## 第七步：执行自定义命令

`ebx run` 支持两种自定义命令机制：

### 机制 A：template.yaml 声明式

在模板的 `template.yaml` 中声明 Shell 命令：

```yaml
custom_commands:
  dev:
    command: "npm run dev"
  test:
    command: "pytest {file} -v"
    description: "Run tests"
```

执行：

```bash
ebx run sbx-xxxx dev
ebx run sbx-xxxx test --arg file=tests/test_api.py
```

### 机制 B：@registry.command 注册式

在沙箱内 Python 代码中注册自定义命令：

```python
from easy_sandbox.server.registry import registry

@registry.command("greet")
def greet(name: str) -> str:
    return f"Hello, {name}!"

registry.freeze()
```

执行：

```bash
ebx run sbx-xxxx greet --name World
```

> `ebx run` 会自动先尝试机制 A，若命令未找到则回退到机制 B，对用户完全透明。

---

## 第八步：销毁沙箱

```bash
# 销毁单个沙箱
ebx kill sbx-xxxx

# 销毁所有沙箱（需确认）
ebx kill --all

# 跳过确认
ebx kill --all --yes
```

---

## 使用模板

### 从 GitHub 安装模板

```bash
ebx template install owner/repo
ebx template install owner/repo@v1.0
ebx template install owner/repo//subdir
```

### 快捷方式

```bash
ebx install owner/repo
```

### 使用已安装的模板

```bash
ebx create --template my-template
```

### 本地脚手架生成模板

```bash
# 基于内置 python 案例生成 ./python/
ebx template init -t python

# 或生成到指定目录
ebx template init -t python ./my-template
```

顶层 `ebx init` 快捷方式与 `ebx template init` 委托到完全相同的命令（引导式凭证配置仍是 `ebx config init`）。

#### 适配已有项目

```bash
# Qwen Code 给 ./my-app 补上 Dockerfile、commands.py 和 template.yaml
ebx template init --adopt ./my-app --hint "监听 8080"

# 列出将要发送的文件。不调用模型，也不写文件
ebx template init --adopt ./my-app --dry-run

# 然后发布（无需 LLM）
ebx deploy ./my-app --acr-namespace my-ns
```

`--adopt` 会先把项目复制到临时目录。`.env`、密钥和内容看起来像密钥的文件不会进入这份副本，预览确认后才写回模板文件。非交互终端需要 `-y`。细节见 [编写模板](authoring-templates.md#适配已有项目)。

#### 交互式案例选择

- **TTY**：不带 `-t` 执行 `ebx init` / `ebx template init` 时，会出现内置案例的上下键（↑/↓）选择器；`Enter` 确认，`Ctrl+C` 中止且不写任何文件。
- **非 TTY / CI / `--json`**：选择器绝不阻塞——命令快速失败并列出可用案例（请使用 `-t python|node|minimal` 或 `--list`），保证脚本行为确定。

#### 高级用法：顶层快捷方式与自定义命令的边界

- 内置顶层快捷方式（`create`、`list`、`init`、`install`、`deploy`、`run` 等）是用户可配置的 `[shortcuts]` 段的**系统默认配置**——并非硬编码：维护者在 `src/easy_sandbox/cli/main.py` 的 `lazy_subcommands` 映射中预置它们，用户可以通过 `~/.ebx/config.toml` 自由修改、删除或扩展（见下文）。
- CLI 别名（`[shortcuts]`）只是**重命名一条本地 CLI 路径**（`ebx <别名> [参数…]` → 已有命令）；不需要沙箱，也不需要模板。
- 要添加在**沙箱内**运行的命令，请在模板的 `template.yaml` 中声明 `custom_commands`，或在 SandboxServer 上注册（`@registry.command`），然后通过 `ebx run <SANDBOX_ID> <COMMAND_NAME>` 调用——这与 CLI 别名是不同的层。
- 未知顶层命令会得到针对性提示：`ebx crate` → `Did you mean 'create'?`；无相近候选时，错误信息给出不含 `ebx` 前缀的快捷方式示例（`ebx config set shortcuts.NAME "template init"`），并指向 `custom_commands` + `ebx run`。

#### 自定义顶层快捷方式

每个默认快捷方式都是可修改的出厂预置。使用 `ebx config` 管理别名（也可直接编辑 `~/.ebx/config.toml` 的 `[shortcuts]` 段）：

```bash
# 添加 / 修改别名（此后 `ebx ps abc123` ≡ `ebx sandbox process list abc123`）
ebx config set shortcuts.ps "sandbox process list"

# 目标只写命令路径。下面这种写法会被拒绝，且不会保存：
#   ebx config set shortcuts.init2 "ebx template init"
# 去掉 ebx 前缀（此后 `ebx init2 --list` ≡ `ebx template init --list`）：
ebx config set shortcuts.init2 "template init"

# 删除别名（空值即删除）
ebx config set shortcuts.ps ""

# 查看所有已配置的别名
ebx config get shortcuts

# 重置为默认快捷方式集 / 生成完整可编辑模板
ebx config init --reset-shortcuts
```

说明：

- 别名目标必须是已有命令路径（如 `"sandbox process list"`、`"template install"`）。不要带 `ebx` 前缀：`"ebx template init"` 以退出码 2 拒绝且不会写入，错误信息会给出可重试的 `ebx config set shortcuts.<别名> "template init"`。文件里已经写错的值会在下次启动时被跳过（`Invalid shortcut ignored`），其他别名仍然有效。别名绝不链式指向其他别名，参数原样透传。
- 保留命令名（`sandbox`、`template`、`config`、`mcp`）不可覆盖。
- `config.toml` 损坏时会输出警告并禁用该会话中的所有 shortcuts——内置命令组（`sandbox`、`config`、`mcp`、`template`）不受影响，CLI 仍可正常使用。

完整边界描述与默认别名全表见 [CLI 设计文档](../design/cli-design.md)。

### 一键部署自定义模板

```bash
ebx template deploy ./my-template \
  --acr-namespace my-ns --acr-repo my-template
```

`template deploy` 会自动完成：本地 Docker 构建 → ACR 推送 → 调用 CreateTemplate API。终端上，每一步都是会走动的 `message... 12s` 标题，下方以灰色显示最近四行日志。见 [命令执行时看到什么](#命令执行时看到什么)，模板文件见 [模板编写指南](authoring-templates.md)。

---

## 配置管理

```bash
# 查看配置
ebx config list
ebx config get sandbox_api_key

# 设置配置
ebx config set region cn-beijing
ebx config set http_timeout 60

# 清除单个已存储的值（回到默认值 / not set）
ebx config set region ""
```

可用配置键：`sandbox_api_key`、`api_url`、`region`、`http_timeout`、`max_retries`、`domain`、`llm_api_key`、`llm_model`、`llm_base_url`、`github_token`、`access_key_id`、`access_key_secret`、`acr_namespace`。`api_key` 仍可作为 `sandbox_api_key` 的别名。

> **提示：** 在使用 `ebx template search` / `ebx install` 时遇到 GitHub 匿名限流？在交互式终端执行 `ebx config set github_token`（星号掩码输入，存入 `~/.ebx/.env`），或在 CI 中以 Secret 注入 `GITHUB_TOKEN`。`--token` 优先级说明见[认证详解](authentication.md)与 CLI 参考。
>
> **本地预检：** 推送前运行 `make ci`——它在单个本地解释器上等价复刻 GitHub Actions 流水线（ruff check + format check、mypy、非 integration 全量测试、包构建、`twine check`、wheel 内 `py.typed` 校验）。

---

## MCP 集成

将 Easy Sandbox 作为本地 STDIO MCP Server 提供给 AI IDE 使用。STDIO 模式不需要 HTTP 传输依赖：

```bash
# 安装到 Cursor
ebx mcp install --target cursor

# 安装到 Claude Desktop
ebx mcp install --target claude

# 查看 MCP 状态
ebx mcp status

# 手动启动：配置写到 stderr，停在 stdin 上等 JSON-RPC
ebx mcp start --template code-interpreter-v1
# 另一个终端：ebx mcp stop
# 后台 HTTP：ebx mcp start --http --background
```

### 远程 MCP Server 部署产物

生成用于手动部署到阿里云 FC 的 Streamable HTTP MCP 产物。该命令不会调用 FC 部署 API：

```bash
# 使用新生成的 Bearer Token 创建产物
ebx mcp deploy --generate-token --api-key $E2B_API_KEY \
  --output-dir ./deploy-artifact
```

HTTP 运行时需安装 `easy-sandbox[mcp]`。随后使用阿里云 FC 官方控制台或 SDK 打包产物、创建函数与 HTTP Trigger。`config.yaml` 是与平台 API 无关的检查清单，不是 FC API 请求体；请通过官方界面转换其中的设置。将输出的 IDE 模板中的 URL 与 token 占位符替换为部署后的实际值。

客户端结束会话时应调用 `DELETE /mcp`。`GET /mcp` 返回 405，SSE 服务端通知尚未实现。`ebx mcp deploy` 在没有非空 Bearer token 时会拒绝生成产物。`config.yaml` 可能包含明文凭证，请勿将部署产物或填入凭证后的 IDE 配置提交到版本库。

---

## 命令执行时看到什么

可能停住的步骤在 **stderr** 上画一块：

```text
Building Docker image locally: my-template:latest... 12s
#5 [1/2] FROM ubuntu:22.04
#5 DONE 0.1s
```

标题上的耗时大约每秒走一次，工具暂时没有输出时也一样。灰色行是最近四行（`EBX_ACTIVITY_LINES`，1 到 10）。创建沙箱、上传、下载、拉取模板或模板索引、用镜像注册模板、安装 coding-agent CLI、`ebx kill --all`，以及部署的每个阶段（构建、推送、等到 READY），都用这一块。

灰色行只放安全文本：相对路径、安装阶段（镜像源、校验和、解压）、docker 或轮询输出，以及销毁时的 `i/N <id>`。文件内容、工具入参、ACR token 和 `--build-arg` 的值不会出现。

`--json`、`--quiet`、`--ci`、`TERM=dumb` 和非 TTY 不画这个标题。这些模式下，部署仍是每个阶段一行 progress。`--verbose` 改为打印完整的部署日志；其余命令在终端上仍保留标题。结果留在 stdout。

## 全局选项

`ebx` 命令支持以下全局选项，可在任何子命令前使用：

| 选项 | 说明 |
|------|------|
| `--json` / `-j` | 以 JSON 格式输出，方便脚本解析 |
| `--quiet` / `-q` | 最小化输出 |
| `--no-color` | 禁用彩色输出 |
| `--ci` | CI/CD 模式（等同 `--quiet --no-color --json`） |

详细全局选项列表（含 `--verbose`、`--log-level`、`--timeout` 等）参见 [CLI 参考手册 — 全局选项](../reference/cli-reference.md#全局选项)。注意 `--region`/`-r` 是命令级选项（`ebx list`、`ebx kill`、模板控制面命令与 `ebx mcp deploy` 支持），并非全局选项；持久默认值请通过 `ebx config set region` 设置。

---

## CI/CD 模式

在自动化环境中使用 `--ci` 标志：

```bash
ebx --ci create --template base
# 等同于 --quiet --no-color --json
```

结合 `--json` 可获取机器可读的输出：

```bash
ebx --json list | jq '.[] | .sandbox_id'
```

---

## 下一步

- [SDK 使用指南](sdk-usage.md) — 在 Python 代码中使用 Easy Sandbox
- [认证详解](authentication.md) — 深入了解认证方式和配置优先级
- [模板使用](using-templates.md) — 了解模板的查找、安装和使用
- [CLI 参考手册](../reference/cli-reference.md) — 所有命令的完整参考
