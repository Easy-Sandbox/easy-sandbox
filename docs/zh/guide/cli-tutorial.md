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
ebx config set api_key your-api-key
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
| 脚手架生成本地可编辑的模板工程 | `ebx template init [DIRECTORY]` —— 只写本地文件，不构建、不部署 |

### 使用默认模板

```bash
ebx create --template base
# 输出类似：
# ✓ Sandbox created: sbx-xxxx
```

### 自然语言创建（AI 生成模板）

```bash
# 首次使用：引导式配置平台凭证与 Qwen Code
# ebx config init

# Qwen Code 生成 Dockerfile 与 template.yaml → 构建部署 → 创建沙箱
ebx create "一个 Python 数据分析环境"
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

### 下载

```bash
ebx download sbx-xxxx /app/result.csv ./result.csv
```

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

#### 交互式案例选择

- **TTY**：不带 `-t` 执行 `ebx init` / `ebx template init` 时，会出现内置案例的上下键（↑/↓）选择器；`Enter` 确认，`Ctrl+C` 中止且不写任何文件。
- **非 TTY / CI / `--json`**：选择器绝不阻塞——命令快速失败并列出可用案例（请使用 `-t python|node|minimal` 或 `--list`），保证脚本行为确定。

#### 高级用法：顶层快捷方式与自定义命令的边界

- 内置顶层快捷方式（`create`、`list`、`init`、`install`、`deploy`、`run` 等）由**项目维护者**注册在 `src/easy_sandbox/cli/main.py` 的 `lazy_subcommands` 映射中。这是内部注册点，不是面向用户的扩展机制。
- 要添加自己的命令，请在模板的 `template.yaml` 中声明 `custom_commands`，或在 SandboxServer 上注册（`@registry.command`），然后通过 `ebx run <SANDBOX_ID> <COMMAND_NAME>` 调用。
- 早期 CLI 设计草案中的 `config.toml [shortcuts]` 段**从未实现**——不要期望在 `~/.ebx/config.toml` 中声明别名会生效。
- 未知顶层命令会得到针对性提示：`ebx crate` → `Did you mean 'create'?`；无相近候选时错误信息指向 `custom_commands` + `ebx run`。

完整边界描述见 [CLI 设计文档](../design/cli-design.md)。

### 一键部署自定义模板

```bash
ebx template deploy ./my-template \
  --acr-namespace my-ns --acr-repo my-template
```

`template deploy` 会自动完成：本地 Docker 构建 → ACR 推送 → 调用 CreateTemplate API。详见 [模板编写指南](authoring-templates.md)。

---

## 配置管理

```bash
# 查看配置
ebx config list
ebx config get api_key

# 设置配置
ebx config set region cn-beijing
ebx config set http_timeout 60

# 清除单个已存储的值（回到默认值 / not set）
ebx config set region ""
```

可用配置键：`api_key`、`api_url`、`region`、`http_timeout`、`max_retries`、`domain`、`llm_api_key`、`llm_model`、`llm_base_url`、`qwen_code_api_key`、`qwen_code_base_url`、`qwen_code_model`、`github_token`、`access_key_id`、`access_key_secret`。

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

# 手动启动（通常由 IDE 自动调用）
ebx mcp start --template code-interpreter-v1
```

### 远程 MCP Server 部署产物

生成用于手动部署到阿里云 FC 的 Streamable HTTP MCP 产物。该命令不会调用 FC 部署 API：

```bash
# 使用新生成的 Bearer Token 创建产物
ebx mcp deploy --generate-token --api-key $E2B_API_KEY \
  --output-dir ./deploy-artifact
```

HTTP 运行时需安装 `easy-sandbox[mcp]`。随后使用阿里云 FC 官方控制台或 SDK 打包产物、创建函数与 HTTP Trigger。`config.yaml` 是与平台 API 无关的检查清单，不是 FC API 请求体；请通过官方界面转换其中的设置。将输出的 IDE 模板中的 URL 与 token 占位符替换为部署后的实际值。

客户端结束会话时应调用 `DELETE /mcp`。`GET /mcp` 当前返回 501，SSE 服务端通知将在 Phase 2 实现。`config.yaml` 可能包含明文凭证，请勿将部署产物或填入凭证后的 IDE 配置提交到版本库。

---

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
