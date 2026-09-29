# 自带 Agent（BYO）集成指南

本指南面向** Agent CLI 的拥有者**：Qwen Code、Codex、Claude Code、Qoder CLI、自研 Agent 框架，或任何你希望**在 Easy Sandbox 内**运行的命令行 Agent。

> **事实核验说明：** 下文所有命令、标志、环境变量与许可声明均于 2026-09-29 对照官方文档或经真实 CLI 行为核验（来源见文末）。厂商 CLI 迭代很快——锁定版本前请先复核所链接的页面。

该模式即 **Bring Your Own Agent（BYO，自带 Agent）**：Easy Sandbox 不为你的 Agent 做规划、推理或工具循环。它提供隔离运行时与操作面，Agent 二进制提供这条线之上的全部能力。

---

## 1. 职责边界

| Easy Sandbox 提供 | Agent CLI 自行提供 |
|-------------------|---------------------|
| 隔离运行时 —— 由模板镜像启动的 FC 沙箱 | 规划与推理（Agent 自己的 LLM 调用） |
| 生命周期 —— 创建、TTL、销毁（`ebx create --timeout`、`ebx kill <id>`） | Prompt 理解与任务拆解 |
| 文件 —— SDK/CLI 的上传、下载、读写 | 代码生成与修改 |
| 命令 —— shell 执行（`ebx exec`、`sb.commands.run()`） | 内部工具循环（Agent 自己的文件/执行/MCP 工具） |
| 网络 —— 出网与端口暴露（`ports` 能力） | 选用哪个模型、哪些工具与提示词 |
| MCP —— Easy Sandbox MCP Server 让对话型 Agent 远程驱动沙箱 | — |
| 凭证 —— 创建时按环境变量注入（`ebx create --env KEY=...`） | 产出机器可读结果与真实的退出码 |
| 模板 —— 构建/部署流水线与 `template.yaml` 契约 | 在镜像内被安装、锁定版本、探测与调用 |

两条需要明确强调的结论：

- **SDK 不新增任何 LLM 客户端依赖，也不内置 Agent 运行时。** `easy_sandbox` 中没有规划器、没有推理循环、没有编排引擎。Agent 能力 = 沙箱内的一个 CLI 二进制，通过 `commands.run()` / `ebx exec` / `ebx run`（命名命令）调用。
- **SDK 刻意保持轻薄。** 增加一个 Agent 意味着构建模板或命令，而不是扩展 SDK。

---

## 2. 两条彼此独立的轴：宿主机侧生成与沙箱内 Agent

这两个概念经常被混为一谈。它们是**两条彼此独立的轴**，生命周期、凭证与目的都不同：

| | 轴 A —— 宿主机侧生成 | 轴 B —— 沙箱内 Agent（本指南） |
|---|---|---|
| **谁在运行** | 你**本机**上的 Qwen Code CLI | 沙箱**内部**的任意 Agent CLI |
| **为什么** | `ebx create "<自然语言描述>"` 在构建前生成 `Dockerfile` + `template.yaml` | 在沙箱内完成实际的编码/部署工作 |
| **凭证来源** | 宿主机的 Qwen Code / DashScope 配置（`ebx config set`） | 模板白名单，按沙箱注入（`ebx create --env`） |
| **生命周期** | 每次 create 一个宿主进程 | 每次沙箱回合一个进程；受沙箱 TTL 约束 |
| **可替换** | 是——宿主后端可插拔（Qwen Code 为默认） | 是——BYO 模板，无需改 SDK |

轴 A 的细节见 [CLI 设计 §3 —— 自然语言创建](../design/cli-design.md)与 [CLI 参考](../reference/cli-reference.md)。**轴 B 不依赖轴 A**；轴 A 也不是沙箱内嵌 Agent：它在宿主机运行、生成模板文件后即退出。

### 默认基础镜像不预装任何 Agent CLI

`base` 等通用模板刻意保持「无 Agent」：它们只带 shell、文件与 Python/Node 运行时——不包含 Qwen Code、Codex、Claude Code 或 Qoder CLI。这让镜像更小、更可审计、许可更干净。

因此推荐路径是：

1. **每个 Agent 一个专用模板** —— 在镜像构建期安装并锁定 Agent CLI 版本（见[第 3 节](#3-最小契约templateyaml-custom_commands)）。
2. **本 BYO 指南** —— 职责边界、最小 `custom_commands` 契约、凭证白名单、版本锁定与许可规则。
3. **发现已有模板** —— `ebx template search <keyword>` 从 [awesome-templates 目录](../design/templates-catalog.md)解析模板。

官方目录模板只会收录**许可允许再分发**且**可锁定版本安装**的 Agent。专有 Agent（Claude Code、Qoder CLI）仅提供**自建或社区模板**的说明——本仓库不分发任何专有二进制。

---

## 3. 最小契约：template.yaml custom_commands

最小契约**完全映射到现有的 `template.yaml` `custom_commands` 机制**上——模板声明命名命令，CLI 或 SDK 负责调用。不需要新能力、不需要新 SDK API、不需要改模板 schema。

| 契约要素 | 今天落在哪里 |
|----------|--------------|
| 安装 / 探测 | `Dockerfile`（构建期安装）+ `custom_commands` 中的探测命令 |
| headless 启动 | `custom_commands.<name>.cmd`（带 `{placeholders}` 的命令模板） |
| prompt 输入 | `custom_commands.<name>.args` 中 `required: true` 的参数 |
| JSON 输出 | 在 `description` 中说明；标志写在 `cmd` 里；由调用方解析 stdout |
| 认证环境变量白名单 | `template.yaml` 的 `env`（只写名字）+ 真实值经 `ebx create --env` 注入 |
| 工作目录 | `custom_commands.<name>.cwd`（默认 `/app`；Agent 模板约定用 `/workspace`） |
| 超时 | `custom_commands.<name>.timeout`（单回合上限，秒） |
| 资源限制 | `template.yaml` 的 `resources.cpu` / `resources.memory`；`Sandbox.create(cpu=, memory=)` 可覆盖 |
| 生命周期 | 沙箱 TTL（`ebx create --timeout`），用 `ebx kill <id>` 销毁 |
| 错误映射 | 非零退出码与 stderr；在 `CommandResult` 上以 `exit_code` / `stderr` 呈现 |
| 版本锁定 | `Dockerfile` 中的精确版本（standalone 归档另附 SHA256） |
| 许可边界 | [第 8 节](#8-版本锁定更新与许可) |

### `custom_commands` 各字段逐一说明

以下是 `CustomCommand` 模型的真实字段（详见 [template.yaml 规范](../reference/template-yaml-spec.md)）：

| 字段 | 类型 | 默认值 | Agent 契约中的用途 |
|------|------|--------|---------------------|
| `cmd` | `str`（必填） | — | 完整的 headless 调用，含 `{placeholder}` 占位符 |
| `description` | `str` | `""` | 声明输出格式（例如「stdout 为 JSON 载荷」） |
| `cwd` | `str` | `"/app"` | 在哪个工作目录运行 Agent（建议 `/workspace`） |
| `env` | `dict[str, str]` | `{}` | 仅放非密钥默认值——绝不放凭证 |
| `timeout` | `int` | `60` | 限制单个 Agent 回合（秒） |
| `args` | `list[Arg]` | `[]` | 至少包含一个必填的 prompt 参数 |

参数会先经 `shlex.quote()` 转义再填入 `{placeholders}` —— 含引号、`;` 或 `$` 的 prompt 无法逃逸出命令。请优先使用命名参数形式，而不是自己把 prompt 拼进 shell 字符串。

### 示例：一个 BYO Qwen Code 模板（示意）

> 这是**公开示例**，不是受维护的目录模板。生产模板应放在你自己的仓库（或 awesome-templates 目录）中——参见[模板编写](authoring-templates.md)。

`template.yaml`：

```yaml
name: my-qwen-agent
version: "1.0.0"
description: "BYO Qwen Code agent template (example)"

capabilities:
  - shell
  - files
  - ports

ports:
  - 9000

env:
  DASHSCOPE_API_KEY: ""        # 只写名字——真实值按沙箱注入
  PATH: "/usr/local/bin:$PATH"
  WORKSPACE: "/workspace"

custom_commands:
  agent_probe:
    cmd: "command -v qwen"
    description: "Probe that the pinned agent CLI is installed (add the vendor's version flag if documented)"
    cwd: "/workspace"
    timeout: 30

  agent_run:
    # 位置参数传 prompt —— 已弃用的旧 -p 形式不再使用。
    cmd: "qwen {prompt} --output-format json --max-session-turns {max_turns}"
    description: "One headless Qwen Code turn; stdout is a JSON payload, diagnostics go to stderr"
    cwd: "/workspace"
    timeout: 600
    args:
      - name: prompt
        type: string
        required: true
        description: "Natural-language instruction for the agent"
      - name: max_turns
        type: integer
        required: false
        default: "50"
        description: "Session turn budget"

resources:
  cpu: 2
  memory: 4096
```

`Dockerfile` —— 构建期安装，锁定精确版本：

```dockerfile
FROM node:22-bookworm-slim

# 锁定精确版本。不要使用 latest 之类的浮动标签。
RUN npm install -g @qwen-code/qwen-code@<X.Y.Z>

WORKDIR /workspace
```

随后使用你的模板：

```bash
# 构建/部署后（见「模板编写」）：
ebx create --template my-qwen-agent --env DASHSCOPE_API_KEY=<YOUR_KEY> --timeout 3600

# 探测安装是否成功
ebx run <sandbox-id> agent_probe

# 运行一个 Agent 回合；prompt 会被自动转义
ebx run <sandbox-id> agent_run --arg prompt="fix the failing test in tests/"
```

```python
from easy_sandbox import Sandbox

async with await Sandbox.create(
    template="my-qwen-agent",
    envs={"DASHSCOPE_API_KEY": "..."},
    timeout=3600,
) as sb:
    result = await sb.custom("agent_run", prompt="fix the failing test in tests/")
    print(result.exit_code, result.stdout)   # stdout 即 JSON 载荷
```

---

## 4. Agent CLI 参考（2026-09-29 核验）

每个 Agent 保留自己的 headless 方言 —— **模板适配 CLI，契约不强行统一**。必须统一的是：一个探测命令、一个带必填 prompt 参数的命名运行命令、一种有文档的输出格式、一个白名单内的认证变量。

| | Qwen Code | Codex CLI | Claude Code | Qoder CLI |
|---|---|---|---|---|
| **可做官方模板** | 可以（Apache-2.0） | 可以（Apache-2.0） | 不可以 —— 仅 BYO/社区 | 不可以 —— 仅 BYO/社区 |
| **安装渠道** | 官方 standalone（自带 Node）、npm `@qwen-code/qwen-code`（Node 22+）、Homebrew | 官方 standalone、npm `@openai/codex`、Homebrew | 官方原生安装器，以及 brew / winget / apt / dnf / apk | 厂商官网提供的官方安装器 |
| **headless 命令** | `qwen "<prompt>" --output-format json` | `codex exec "<prompt>" --json` | `claude -p "<prompt>"` | `qoder -p "<prompt>"` |
| **常用标志** | `--max-session-turns <n>` | `--sandbox workspace-write` | `--allowedTools`、`--output-format json` / `stream-json`、`--bare` | `--output-format json` / `stream-json`、`--max-turns <n>`、`--permission-mode bypass_permissions` |
| **认证环境变量** | `DASHSCOPE_API_KEY`、`BAILIAN_CODING_PLAN_API_KEY`，或 OpenAI 兼容的 `OPENAI_API_KEY` + `OPENAI_BASE_URL` | `OPENAI_API_KEY` | `ANTHROPIC_API_KEY` | `QODER_PERSONAL_ACCESS_TOKEN` |
| **备选认证** | 厂商 CLI 登录（仅宿主机侧准备） | 交互式登录（仅宿主机侧准备） | 订阅登录（仅宿主机侧准备） | 浏览器 OAuth（仅宿主机侧准备） |
| **许可** | Apache-2.0 | Apache-2.0 | 专有 | 专有 |

运维要点：

- **交互式登录无法在 headless 沙箱内完成。** 请使用白名单中的 API Key/Token 变量，在创建时注入；只有当厂商 CLI 的宿主机侧工作流需要时才在本机完成浏览器/OAuth 登录。
- **各家 headless 方言互不相同：** Qwen Code 用位置参数传 prompt，Codex 用子命令（`codex exec`），Claude Code 与 Qoder CLI 用 `-p`。不要为了「统一」而改写厂商的真实调用方式。
- **权限绕过标志只在沙箱内使用。** `--yolo`（Qwen Code）与 `--permission-mode bypass_permissions`（Qoder CLI）是为了让 Agent 非交互运行而存在；**仅**用于可丢弃的沙箱，绝不在宿主机上使用，也绝不作用于你无法承受丢失的数据（见[第 9 节](#9-安全边界)）。
- **自定义 Agent**（自研二进制，或任何未列出的 CLI）适用于同一契约：在 `Dockerfile` 中安装，声明 `agent_probe` 与 `agent_run`，只白名单它真正需要的环境变量，并写明输出格式。「BYO」并不限于上述四家厂商。

---

## 5. 凭证与环境变量白名单

规则：**模板声明 Agent 可以接收哪些变量；值按沙箱逐次注入；任何东西都不烘进镜像。**

| Agent | 白名单变量（创建时注入） |
|-------|---------------------------|
| Qwen Code | `DASHSCOPE_API_KEY` / `BAILIAN_CODING_PLAN_API_KEY`，或 `OPENAI_API_KEY` + `OPENAI_BASE_URL` |
| Codex | `OPENAI_API_KEY` |
| Claude Code | `ANTHROPIC_API_KEY` |
| Qoder CLI | `QODER_PERSONAL_ACCESS_TOKEN` |
| 自定义 | 仅限你二进制的文档所声明的变量——不要「顺手」多加 |

```bash
# 按沙箱注入；值永远不会进入镜像或 template.yaml
ebx create --template my-qwen-agent --env DASHSCOPE_API_KEY=<YOUR_KEY>
```

```python
sb = await Sandbox.create(
    template="my-qwen-agent",
    envs={"DASHSCOPE_API_KEY": "..."},
)
```

补充规则：

- **绝不提交真实密钥**到模板、`template.yaml`、`custom_commands.env`、Dockerfile 的 `ENV` 或上传的文件。模板的 `env` 块只列**变量名**，默认值为空或非密钥值。
- **绝不打印密钥。** 掩码显示（`ebx config get api_key`）与掩码日志适用于 Easy Sandbox 自身的凭证；对 Agent 的变量请使用同样的纪律。
- **一沙箱一凭证。** 沙箱是一次性的；不要跨租户复用长期密钥，任何出现在输出或对话记录中的密钥都必须轮换。
- **先读环境变量指南**了解 envd 的直接执行语义（[环境变量](environment-variables.md)）——排查「变量明明注入了却读不到」之前，先记住：envd 中要用 shell 特性（`$VAR`、管道、重定向）必须套 `sh -c '...'`。
- `custom_commands.<name>.env` 块用于**非密钥默认值**（例如 `CODEX_MODEL`）；绝不可承载上表中的真实值。

---

## 6. 生命周期、超时与资源限制

| 控制项 | 在哪里设置 | 说明 |
|--------|------------|------|
| 沙箱 TTL | `ebx create --timeout <seconds>` / `Sandbox.create(timeout=...)` | 整个会话的兜底上限；CLI 的 `--timeout` 是沙箱存活时长，**不是** HTTP 超时 |
| 单回合超时 | `custom_commands.<name>.timeout` | 限制单次 Agent 调用（默认 `60`；Agent 运行通常用 `300`–`600`） |
| HTTP 请求超时 | `SANDBOX_HTTP_TIMEOUT` / `ebx config set http_timeout N` | 只约束控制面请求；调大它不会延长沙箱寿命 |
| 资源 | 模板中的 `resources.cpu` / `resources.memory` | 该模板所有沙箱的默认规格；`Sandbox.create(cpu=, memory=)` 可按次覆盖 |
| 销毁 | `ebx kill <id>` / `await sb.kill()` | 显式结束会话；编码类 Agent 建议一次性使用 |

Agent 任务的推荐模式：

1. 以略大于最长预期回合的 TTL 创建沙箱。
2. 每次 `agent_run` 调用跑一个 Agent 回合；解析 stdout；检查 `exit_code`。
3. 上传结果或下载产物后 `ebx kill` 沙箱。不要把一个开了绕过权限的 Agent「留着待用」。

---

## 7. 错误映射

BYO Agent 命令本质是一个程序，失败必须**机器可读**：

| 情形 | 调用方看到什么 | 契约要求 |
|------|----------------|----------|
| 成功 | 退出码 `0`；stdout 能按文档格式解析 | 把 JSON 载荷写到 stdout |
| Agent/模型失败 | 非零退出码；诊断信息在 stderr | 失败时绝不返回 `0`；保持 stdout 可解析或为空 |
| 回合超时 | 命令以超时失败 | 遵守 `custom_commands.timeout`；挂死的 Agent 不能永久拖住调用方 |
| 凭证缺失 | Agent CLI 自身的认证错误 | 在模板中写明会产出哪条消息/退出码 |
| JSON 解析失败 | 调用方解析错误 | 视为失败；不要从残缺输出里猜结果 |

`CommandResult` 暴露 `exit_code`、`stdout`、`stderr` 与 `source`（`custom_commands` 为 `template`，注册命令为 `server`）——把你的 Agent 退出码映射到这些字段，并且必须透出 stderr 而不是吞掉。沙箱层面的失败（网络、控制面认证、沙箱不存在）见[故障排查](troubleshooting.md)与[错误码参考](../reference/error-codes.md)。

---

## 8. 版本锁定、更新与许可

**版本锁定**

- Agent 在**镜像构建期**安装，而不是首次运行时下载。在沙箱内首次运行时下载既慢、又不可复现，还是供应链风险。
- 锁定**精确版本**：`npm install -g @qwen-code/qwen-code@<X.Y.Z>` / `@openai/codex@<X.Y.Z>`；standalone 归档则锁定发布 URL **并**在运行前校验官方公布的 SHA256。
- 在模板 README 中记录锁定版本，便于运维审计实际运行的组件。
- 更新 = **模板版本升级**（重新构建 → 重新部署 → 新沙箱），绝不是静默原地升级。流水线是 `ebx template build` / `ebx template deploy`。
- 升级时重新核对厂商标志：headless 标志在不同大版本之间不是稳定 API。

**许可边界**

| Agent | 许可 | 本仓库可否官方分发二进制 |
|-------|------|---------------------------|
| Qwen Code | Apache-2.0 | 可以 —— 可作为官方模板维护 |
| Codex CLI | Apache-2.0 | 可以 —— 可作为官方模板维护 |
| Claude Code | 专有 | **不可以** —— 仅提供 BYO 或社区模板说明 |
| Qoder CLI | 专有 | **不可以** —— 仅提供 BYO 或社区模板说明 |

对专有 Agent，**你**在构建安装它们的模板时即接受了厂商条款；Easy Sandbox 既不分发其二进制，也不捆绑其安装器。若你发布此类模板，请不要提交二进制文件——在构建期从厂商官方渠道安装。

**不推荐不校验的安装管道。** 本项目不推荐 `curl … | sh` 这类管道：先把安装器或归档下载为文件，锁定版本，校验哈希（`shasum -a 256`），再安装。Dockerfile 内同样适用：不要出现未锁定版本的 `curl | sh` 行。

---

## 9. 安全边界

1. **绕过权限只用于可丢弃沙箱。** `--yolo` 与 `--permission-mode bypass_permissions` 之所以可接受，完全是因为沙箱就是隔离边界。绝不要在宿主机上使用这些标志。
2. **收紧爆炸半径：** 用沙箱 TTL（`--timeout`）兜底，优先一次性沙箱，用完 `ebx kill`。
3. **不要把 Agent 端口暴露给不可信网络。** 一个开着绕过权限的 Agent 是强服务；其端口应按敏感资源对待。优先通过 SDK、CLI 或 MCP 驱动，而不是公网 URL。
4. **出网流量会离开沙箱。** 模型调用会经网络发往厂商 API；注入凭证前确认你的合规策略允许该目的地。
5. **MCP 是给驱动方的，不是 Agent 的逃生门。** Easy Sandbox MCP Server 让对话型 Agent 创建/执行/销毁沙箱；它不会给沙箱内部增加任何权限（[MCP 集成](mcp-integration.md)）。
6. **最小权限凭证。** 优先使用限定范围的 API Key，而不是账号级 Token；有任何疑似泄露立即轮换。

---

## 10. 排查清单

- **`agent_probe` 失败** → CLI 没装进镜像，或 `PATH` 少了它的安装前缀（模板 `env` 里的 `PATH` 必须包含安装路径）。
- **Agent 报认证错误** → `ebx create --env` 漏了白名单变量，或用错了变量族（Qwen Code 支持多个，选一个族即可）。
- **stdout 为空** → 对照厂商文档检查 headless 标志组合；部分 CLI 需要显式输出格式标志才会吐 JSON。
- **回合超时** → 调大 `custom_commands.timeout`，并单独检查沙箱 TTL；两者互不相关。
- **`ebx run` 报非零退出** → 先看 `stderr`；协议以退出码为准，Agent 自身的诊断是最快的信号。
- **出现交互式登录提示** → CLI 在 headless 沙箱里退回交互认证了；改用 API Key 变量，把宿主机登录留在本机完成。

平台侧更多问题见[故障排查](troubleshooting.md)。

---

## 相关文档

- [模板编写](authoring-templates.md) —— 构建、锁定并发布你的 BYO Agent 模板
- [模板使用](using-templates.md) —— 发现并安装目录中的模板
- [template.yaml 规范](../reference/template-yaml-spec.md) —— `custom_commands` 字段的精确参考
- [CLI 参考 —— ebx run](../reference/cli-reference.md) —— 命名命令的调用方式
- [SDK 使用 —— 自定义命令](sdk-usage.md) —— `sandbox.custom()` / `sandbox.list_commands()`
- [环境变量](environment-variables.md) —— 注入语义与 envd 直接执行
- [Agent Skill 安装与分发](agent-skill-installation.md) —— 另一个方向：把 Easy Sandbox Skill 装进你的 Agent
- [English version](../../en/guide/byo-agent-integration.md)

## 来源（2026-09-29 核验）

- Qwen Code —— [官方仓库](https://github.com/QwenLM/qwen-code)（npm `@qwen-code/qwen-code`、Node 22+、Homebrew、standalone）；headless 位置参数 prompt（`qwen "<prompt>"`），配合 `--output-format json` / `--max-session-turns`；Apache-2.0。
- Codex CLI —— npm `@openai/codex`、官方 standalone 与 Homebrew；headless `codex exec --json` / `--sandbox workspace-write`；Apache-2.0。
- Claude Code —— [安装文档](https://code.claude.com/docs/en/setup)（原生安装器、brew / winget / apt / dnf / apk）；headless `claude -p`、`--allowedTools`、`--output-format json` / `stream-json`、`--bare`；专有许可。
- Qoder CLI —— [官方页面](https://qoder.com/cli)与厂商文档（专有安装器）；headless `qoder -p`、`--output-format json` / `stream-json`、`--max-turns`、`--permission-mode bypass_permissions`；专有许可。
- Easy Sandbox 契约 —— `src/easy_sandbox/models/template.py`（`CustomCommand`）、[template.yaml 规范](../reference/template-yaml-spec.md)与 [awesome-templates 目录](../design/templates-catalog.md)。
