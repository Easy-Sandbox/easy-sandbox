# Awesome Easy Sandbox Templates

开箱即用的 **Easy Sandbox** 沙箱模板集合。

这个目录（或者说这个仓库）刻意保持**极简形态**：

```
.
├── README.md                 ← 你正在看的文件，也是唯一的模板索引
├── browser-automation/
├── claude-code/
├── codex/
├── deepseek-harness/
├── hermes-agent/
├── node-web/
├── openclaw/
├── python-hello/
├── qoder/
└── qwen-code/
```

**一个 README + 一堆模板文件夹**，没有 registry.json、没有 index.json、没有多层 manifest。
新增一个模板 = 新增一个文件夹；下线一个模板 = 删掉一个文件夹。索引就是本文件里的表格，
并由离线测试（`tests/test_templates/test_template_catalog.py`）保证表格与 YAML 不漂移。

> 本目录既可以留在主仓库 `easy-sandbox` 内（路径 `examples/templates/`），
> 也可以**整份原样**拎出去作为独立仓库 `awesome-easy-sandbox-templates`。
> 两种形态下，本文档的描述与命令都成立——差别只在于 install 时使用的引用（ref）格式，
> 下文[安装](#安装)一节会同时给出两种写法。

---

## 模板总览

图例：`` `run(task*)` `` 中 `*` 表示该参数为**必填**（`required: true`）；未标注的参数带默认值，可省略。

| 模板 | 描述 | 关键词 | base 镜像 | resources | capabilities | custom commands |
|------|------|--------|-----------|-----------|--------------|-----------------|
| [`browser-automation`](./browser-automation/) | 浏览器自动化沙箱环境 - 预装 Playwright + Chromium，支持网页抓取与 UI 测试 | `browser` `playwright` `chromium` `automation` `web-scraping` | `mcr.microsoft.com/playwright/python:v1.40.0-jammy` | 2 CPU / 4096 MB<br>端口: 9000 | `shell` `files` `code` `ports` | `run(script)` |
| [`claude-code`](./claude-code/) | Claude Code Agent 运行环境 - Anthropic Claude 驱动的 AI 编程助手 | `claude` `anthropic` `ai-coding` `ai-agent` | `ubuntu:22.04` | 2 CPU / 4096 MB<br>端口: 9000 | `shell` `files` `code` `terminal` `ports` | `run(task*)` |
| [`codex`](./codex/) | OpenAI Codex CLI Agent 运行环境 - 支持 AI 驱动的代码生成和执行 | `codex` `openai` `ai-agent` `code-generation` | `ubuntu:22.04` | 2 CPU / 4096 MB<br>端口: 9000 | `shell` `files` `code` `ports` | `run(prompt*)` |
| [`deepseek-harness`](./deepseek-harness/) | DeepSeek Agent Runtime 运行环境 - DeepSeek 模型驱动的 AI 编程 Agent | `deepseek` `ai-agent` `ai-coding` `code-generation` | `ubuntu:22.04` | 2 CPU / 4096 MB<br>端口: 9000 | `shell` `files` `code` `ports` | `run(script)` |
| [`hermes-agent`](./hermes-agent/) | Hermes Agent 运行环境 - NousResearch Hermes 系列模型驱动的 AI Agent | `hermes` `nousresearch` `ai-agent` `tool-calling` | `ubuntu:22.04` | 2 CPU / 4096 MB<br>端口: 9000 | `shell` `files` `code` `ports` | `run(script)` |
| [`node-web`](./node-web/) | Node.js Web 服务运行环境 - 支持 Express、Fastify 等框架的快速开发与部署 | `nodejs` `web` `express` `api` `javascript` | `node:20-slim` | 1 CPU / 2048 MB<br>端口: 3000, 9000 | `shell` `files` `ports` | `dev()` `build()` `start()` |
| [`openclaw`](./openclaw/) | OpenClaw AI Agent 运行环境 - 开源 AI 编程 Agent 网关与运行时 | `openclaw` `ai-agent` `ai-coding` `gateway` | `ubuntu:22.04` | 2 CPU / 4096 MB<br>端口: 18789, 9000 | `shell` `files` `ports` | `start()` |
| [`python-hello`](./python-hello/) | A minimal Python hello world template for testing | `python` `hello-world` `example` | `ubuntu:22.04` | 未声明（平台默认）<br>端口: 9000 | `shell` `files` `code` `ports` | `run(file)` `test(path)` |
| [`qoder`](./qoder/) | Qoder AI 编程助手运行环境 - 集成 Python 与 Node.js 的智能开发沙箱 | `qoder` `ai-coding` `ai-agent` `development` | `ubuntu:22.04` | 2 CPU / 4096 MB<br>端口: 9000 | `shell` `files` `code` `terminal` `ports` | `run(script)` |
| [`qwen-code`](./qwen-code/) | 通义千问编码 Agent 运行环境 - 支持 qwen-code 驱动的 AI 自主部署 | `qwen` `qwen-code` `dashscope` `ai-coding` `ai-agent` `deploy` | `ubuntu:22.04` | 2 CPU / 4096 MB<br>端口: 8080, 9000 | `shell` `files` `code` `ports` | `run(script)` `deploy(prompt* max_turns)` |

> **说明**
> - `关键词` 一列取自各模板 `template.yaml` 的 `tags` 字段，也是自然语言推断
>   （`ebx create "……"`）时的命中依据之一。
> - `resources` 一列取自 `resources.cpu` / `resources.memory`；`python-hello` 未声明该块，
>   运行时使用平台默认规格。
> - `capabilities` 与 `custom commands` 直接来自 YAML，**必须**与文件内容一致；
>   离线测试会逐模板比对，改 YAML 不改表格会 CI 失败。

---

## 安装

`install` 做的事情是：解析引用 → 拉取模板目录 → 读取 `template.yaml` →
生成 Dockerfile → 提交平台构建。安装完成后会得到一个 `TemplateID` 与 `Alias`，
后续用 `ebx create --template <alias>` 创建沙箱。

### 方式一：从本地目录安装（`--registry-type local`）

适用于本目录留在主仓库内、或你已经 clone 了模板仓库的情况。`<path>` 指向**单个模板文件夹**：

```bash
# 主仓库内（相对仓库根目录执行）
ebx install ./examples/templates/node-web --registry-type local

# 独立仓库 clone 到本地后
ebx install ./awesome-easy-sandbox-templates/node-web --registry-type local

# 绝对路径同样可用
ebx install /abs/path/to/node-web --registry-type local
```

> `--registry-type local` 显式声明本地来源；若省略，以 `./` 或 `/` 开头的引用、
> 以及当前文件系统上确实存在的路径，也会被自动识别为本地模板。

也可以指定别名，避免与同名模板冲突：

```bash
ebx install ./examples/templates/node-web --registry-type local --alias my-node-web
```

### 方式二：从 GitHub 安装（`--registry-type github`）

`<ref>` 采用 Terraform 风格的双斜杠子目录语法：

```
owner/repo                              # 整个仓库（模板必须位于仓库根，默认分支）
owner/repo@v1.0.0                       # 整个仓库 + 指定 ref(tag/branch/sha)
owner/repo//path/to/template            # 仓库内子目录（默认分支）
owner/repo//path/to/template@v1.0.0     # 仓库内子目录 + 指定 ref(tag/branch/sha)
```

本集合中每个模板都是仓库根下的一个子目录，因此使用 `//<模板文件夹名>` 形式：

```bash
# 本目录作为独立仓库发布时
ebx install anycodes/awesome-easy-sandbox-templates//node-web \
  --registry-type github \
  --registry-url https://github.com

# 锁定版本（tag / branch / commit sha 均可）
ebx install anycodes/awesome-easy-sandbox-templates//node-web@v1.0.0 \
  --registry-type github \
  --registry-url https://github.com

# 私有仓库需要令牌
ebx install anycodes/awesome-easy-sandbox-templates//codex \
  --registry-type github \
  --registry-url https://github.com \
  --token "$GITHUB_TOKEN"
```

`--registry-url` 默认即 `https://github.com`，仅在指向 GitHub Enterprise 或镜像源时必须显式给出。
客户端会把 `github.com` 替换为 `api.github.com`，通过 **GitHub tarball API 按 tag/branch/sha 拉取**
（`GET /repos/{owner}/{repo}/tarball[/{ref}]`）。**无需发布 GitHub Release**：只推 git tag、
用某个分支名、甚至指定 commit sha 都能安装；不带 `@ref` 时拉取默认分支。

拉取结果会缓存到本地（无 ref 时以 `default` 占位）：

```
~/.ebx/templates/<owner>/<repo>/<ref>/[<path>/]
```

命中缓存时不会重复下载。查看与清理缓存：

```bash
ebx template cache            # 列出已缓存模板
ebx template cache --clear    # 清空缓存
```

---

## 使用

### 创建沙箱

```bash
ebx create --template node-web
# → sbx-xxxxxxxxxxxx
```

也可以用自然语言，让推断引擎从上表关键词中挑选模板：

```bash
ebx create "启动一个 Node.js Web 服务"
```

### `ebx run` vs `ebx exec`：两条不同的执行路径

这是使用模板时最容易混淆的一点，二者**不等价**：

| | `ebx run <sandbox_id> <command_name>` | `ebx exec <sandbox_id> "<shell>"` |
|---|---|---|
| 命令来源 | 模板 `custom_commands` 中**预先声明**的具名命令 | 调用方**临时拼写**的原始 shell 字符串 |
| 参数 | `--arg key=value`，填充 `cmd` 中的 `{placeholder}` | 无参数模型，全部自己写在字符串里 |
| `cwd` / `env` / `timeout` | 取自模板声明，无需重复指定 | 需通过 `--cwd` / `--timeout` 显式传（`env` 不可传） |
| 参数转义 | 运行时用 `shlex.quote` 自动转义，注入安全 | 由调用方自行负责 |
| 可发现性 | `sandbox.list_commands()` 可枚举，模板自带文档 | 不可枚举，靠口口相传 |
| 失败模式 | 命令名不存在 / 必填参数缺失 / 占位符未填充 → 明确报错 | shell 语法错误、退出码非 0 |

**`ebx run`：跑模板自定义命令**

```bash
# node-web 声明了 dev / build / start 三个命令，且都固定 cwd=/app、timeout=120
ebx run sbx-xxxxxxxxxxxx dev
ebx run sbx-xxxxxxxxxxxx build
ebx run sbx-xxxxxxxxxxxx start

# 带参数：browser-automation 的 run(script)，默认 main.py
ebx run sbx-xxxxxxxxxxxx run --arg script=scrape.py

# 必填参数（codex 的 run(prompt*)）不传会直接报错
ebx run sbx-xxxxxxxxxxxx run --arg prompt="写一个快速排序"

# claude-code 同理
ebx run sbx-xxxxxxxxxxxx run --arg task="重构 utils 模块并补测试"
```

**`ebx exec`：跑原始 shell**

```bash
ebx exec sbx-xxxxxxxxxxxx "ls -la /app"
ebx exec sbx-xxxxxxxxxxxx "npm install express" --cwd /workspace --timeout 300
```

**经验法则**：模板作者已经想清楚、需要固定 `cwd`/`env`/`timeout` 的可复用动作 → 声明成
`custom_commands` 并用 `ebx run`；一次性的探索、调试、临时命令 → 用 `ebx exec`。

SDK 侧等价写法：

```python
from easy_sandbox import Sandbox

sandbox = Sandbox.create(template="node-web")

# 等价于 ebx run
print(sandbox.list_commands())                 # [{'name': 'dev', 'description': ...}, ...]
result = sandbox.run("start")                  # 具名自定义命令
result = sandbox.run("run", script="app.py")   # 带参数填充

# 等价于 ebx exec
result = sandbox.commands.run("ls -la /app", timeout=30, cwd="/app")
```

> `ebx run` 依赖模板声明的 `custom_commands` 能被解析到（见下节 capabilities），
> 若模板未声明该命令，会报 `Unknown custom command 'xxx'; available commands: ...`。

---

## 模板目录约定

每个模板文件夹**必须**包含以下三个文件（缺一不可，离线测试会逐个断言）：

| 文件 | 必需 | 作用 |
|------|------|------|
| `template.yaml` | ✅ | 模板的**权威定义**：镜像、依赖、资源、capabilities、custom commands。`ebx install` 由它生成 Dockerfile |
| `Dockerfile` | ✅ | 与 YAML 等价的可独立构建产物，供 `docker build` 直接验证、以及 `ebx template build -f` 使用 |
| `README.md` | ✅ | 该模板的人类可读说明：环境内容、安装方式、使用示例、注意事项 |

命名约定：

- 文件夹名 == `template.yaml` 里的 `name` 字段 == 安装后的默认 `alias`。
  三者一致，`resolve_capabilities()` 才能按名字在 `~/.ebx/templates/` 里反查到模板。
- 使用小写 + 连字符（kebab-case），不要空格、不要下划线。

推荐（非必需）的附加文件：示例代码、`requirements.txt`、`.dockerignore` 等，
通过 YAML 的 `copy_files` 映射进镜像。

---

## `template.yaml` 完整 Schema

权威定义在 SDK 源码的 `src/easy_sandbox/models/template.py`
（`SandboxTemplate` / `CustomCommand` / `CustomCommandArg` / `STANDARD_CAPABILITIES` /
`DEFAULT_CAPABILITIES`），加载入口是 `src/easy_sandbox/utils/registry.py`
的 `load_template_from_yaml()`。

- 本目录位于主仓库内时：[`models/template.py`](../../src/easy_sandbox/models/template.py)、
  [`utils/registry.py`](../../src/easy_sandbox/utils/registry.py)。
- 本目录已抽出为独立仓库时：到 SDK 仓库
  [`anycodes/easy-sandbox`](https://github.com/anycodes/easy-sandbox)
  的同名路径下查看，或直接读已安装包的源码：
  `python -c "import easy_sandbox.models.template as m; print(m.__file__)"`。

下文列出的字段名、默认值与校验规则均以这两个文件为准；如与本文描述不一致，**以源码为准**。

### 顶层字段

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | `str` | ✅ | — | 模板唯一标识，**必须**与所在文件夹同名 |
| `version` | `str` | | `"1.0.0"` | 语义化版本，建议与仓库的 git tag/ref 对齐 |
| `description` | `str` | | `""` | 一句话描述，会展示在索引表与 CLI 输出中 |
| `base` | `str` | | `"ubuntu:22.04"` | 基础镜像，成为生成 Dockerfile 的 `FROM` |
| `system_packages` | `list[str]` | | `[]` | apt 包 → `RUN apt-get update && apt-get install -y …` |
| `python_packages` | `list[str]` | | `[]` | pip 包 → `RUN pip install --no-cache-dir …` |
| `node_packages` | `list[str]` | | `[]` | npm 全局包 → `RUN npm install -g …` |
| `commands` | `list[str]` | | `[]` | 构建期任意 shell，按顺序各生成一行 `RUN` |
| `env` | `dict[str, str]` | | `{}` | 环境变量 → `ENV K=V`。留空字符串表示"运行时由调用方注入" |
| `copy_files` | `dict[str, str]` | | `{}` | `src -> dst` 映射 → `COPY src dst` |
| `resources.cpu` | `int` | | `null` | CPU 核数（YAML 用嵌套 `resources:` 块，加载时映射为 `cpu_count`） |
| `resources.memory` | `int` | | `null` | 内存 MB（加载时映射为 `memory_mb`） |
| `ports` | `list[int]` | | `[]` | 声明暴露端口。**注意**：声明端口不等于开启 `ports` capability，需同时在 `capabilities` 里列出 `ports` |
| `author` | `str` | | `""` | 作者 / 维护方 |
| `license` | `str` | | `""` | 许可证标识，如 `Apache-2.0` |
| `tags` | `list[str]` | | `[]` | 关键词，供检索与自然语言推断命中 |
| `capabilities` | `list[str]` 或 `null` | | `null` | 运行时能力集，见下节 |
| `custom_commands` | `dict[str, CustomCommand]` | | `{}` | 具名命令表，见下节 |

> `resources` 是 YAML 层的**嵌套语法糖**：`load_template_from_yaml()` 会把它 pop 出来，
> 写成扁平的 `cpu_count` / `memory_mb` 再交给 Pydantic。因此两种写法都可以，
> 但请统一使用 `resources:` 嵌套块（本集合全部如此）。

### `capabilities` 词汇表

能力模型（Capability Model Phase 1）用一个封闭词汇表描述"这个模板的运行环境支持哪些交互面"。
`STANDARD_CAPABILITIES` 是当前**全部**合法取值：

| capability | 含义 | 被门控的 SDK/CLI 面 |
|------------|------|---------------------|
| `shell` | 允许执行原始 shell 命令 | `sandbox.commands.*`、`ebx exec` |
| `files` | 允许读写文件系统 | `sandbox.files.*`、`ebx upload` / `ebx download` |
| `code` | 允许代码解释器会话（有状态执行） | `sandbox.code.*` |
| `terminal` | 允许交互式 PTY 终端 | `sandbox.terminal` / `TerminalSession`、`ebx connect` |
| `ports` | 允许端口暴露与公网访问 | `sandbox.network.*` / host 解析 |

规则：

- `capabilities: null`（即 YAML 中**完全省略该字段**）→ 继承
  `DEFAULT_CAPABILITIES = {shell, files, code}`。
- 一旦显式写出列表，就是**完全覆盖**而非增量合并：写 `capabilities: [shell, files, ports]`
  意味着**放弃** `code`（见 `node-web`、`openclaw`）。
- `terminal` 与 `ports` **永不**默认开启，必须显式声明。
- 词汇表外的取值会让 `SandboxTemplate` 校验直接失败：
  `Unknown capability 'xxx'; allowed: ['code', 'files', 'ports', 'shell', 'terminal']`。
- 运行时解析顺序见 `api/capability.py::resolve_capabilities()`：显式 YAML 路径 →
  扫描 `~/.ebx/templates/` 按 `name` 匹配 → 回落到 `DEFAULT_CAPABILITIES`（并打 warning）。
  这就是"文件夹名 == `name`"约定重要的原因。

本集合的分布：

| capabilities | 模板 |
|--------------|------|
| `shell` `files` `code` `ports` | `browser-automation`、`codex`、`deepseek-harness`、`hermes-agent`、`python-hello` |
| `shell` `files` `code` `terminal` `ports` | `claude-code`、`qoder` |
| `shell` `files` `code` `ports` | `qwen-code` |
| `shell` `files` `ports` | `node-web`、`openclaw` |

### `custom_commands` 结构

`custom_commands` 是 `命令名 -> CustomCommand` 的映射。命令名即 `ebx run <sandbox_id> <命令名>`
中的 `<命令名>`，也是 SDK `sandbox.run("<命令名>")` 的入参。

**`CustomCommand`**

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `cmd` | `str` | ✅ | — | 实际执行的 shell 命令，可含 `{placeholder}` 占位符 |
| `description` | `str` | | `""` | 人类可读说明，`list_commands()` 会返回它 |
| `cwd` | `str` | | `"/app"` | 工作目录 |
| `env` | `dict[str, str]` | | `{}` | 该命令专属的环境变量（叠加在模板 `env` 之上） |
| `timeout` | `int` | | `60` | 超时秒数 |
| `args` | `list[CustomCommandArg]` | | `[]` | 占位符参数声明，顺序即文档顺序 |

**`CustomCommandArg`**

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | `str` | ✅ | — | 参数名，对应 `cmd` 中的 `{name}`，也对应 `--arg name=value` 的 key |
| `default` | `str` 或 `null` | | `null` | 缺省值。调用方未传时用它填充 |
| `required` | `bool` | | `false` | 是否必填 |
| `description` | `str` | | `""` | 参数说明 |

**运行时填充规则**（`api/sandbox.py::Sandbox.run()`）：

1. 命令名不在 `custom_commands` 中 → `ValueError: Unknown custom command …`。
2. `required: true` 且 `default` 为 `null` 且调用方未传 → `ValueError: Required argument … missing`。
3. 调用方传入值优先，其次 `default`；所有值经 `shlex.quote()` 转义后替换 `{name}`。
4. 替换完仍有未填充占位符 → `ValueError: Unfilled placeholders in command …`。

**完整示例**

```yaml
custom_commands:
  # 无参数命令：直接固定行为
  dev:
    cmd: "npm run dev"
    description: "Start development server with hot reload"
    cwd: "/app"
    timeout: 120

  # 带默认值参数：ebx run <id> run            → python3 main.py
  #                ebx run <id> run -a script=x.py → python3 x.py
  run:
    cmd: "python3 {script}"
    description: "Run a Python script"
    cwd: "/app"
    timeout: 60
    env:
      PYTHONUNBUFFERED: "1"
    args:
      - name: script
        default: "main.py"
        description: "Python script to execute"

  # 必填参数：不传 --arg task=... 会直接报错
  agent:
    cmd: "claude-code {task}"
    description: "Run the agent with a task"
    cwd: "/workspace"
    timeout: 300
    args:
      - name: task
        required: true
        description: "Task description for the agent"
```

### 一份可直接复制的最小模板

```yaml
name: my-template                 # == 文件夹名
version: "1.0.0"
description: "一句话说明这个模板解决什么问题"
author: "Your Name"
license: "Apache-2.0"
tags:
  - keyword-one
  - keyword-two

base: ubuntu:22.04

system_packages:
  - curl
  - git

python_packages:
  - httpx

commands:
  - mkdir -p /app

env:
  LANG: C.UTF-8

resources:
  cpu: 1
  memory: 2048

capabilities:
  - shell
  - files
  - code

custom_commands:
  run:
    cmd: "python3 {script}"
    description: "Run a Python script"
    cwd: "/app"
    timeout: 60
    args:
      - name: script
        default: "main.py"
        description: "Python script to execute"
```

对应的 `Dockerfile`（与上面 YAML 等价）：

```dockerfile
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir httpx
RUN mkdir -p /app
ENV LANG=C.UTF-8
WORKDIR /app
```

---

## 贡献模板

### 1. 建目录

```bash
cp -r python-hello my-template      # 从最小模板起步
cd my-template
```

三个必需文件：`template.yaml`、`Dockerfile`、`README.md`。

### 2. 写 `template.yaml`

- `name` 改成 `my-template`，**与文件夹名严格一致**。
- 显式写出 `capabilities`（哪怕就是默认的三项），让能力边界一目了然。
- 把可复用动作声明为 `custom_commands`，而不是让用户去猜 shell 字符串。
- 需要交互终端才加 `terminal`；需要对外暴露端口才加 `ports`，并同时在顶层 `ports:` 列出端口号。
- 敏感信息（API Key 等）在 `env` 里留**空字符串**占位，由运行时注入，绝不写死。

### 3. 写 `Dockerfile`

必须与 YAML 语义等价（`FROM base` → apt → pip → npm → commands → env → copy）。
它的价值在于让人可以脱离平台先本地验证：

```bash
docker build -t my-template ./my-template
docker run --rm my-template echo ok
```

### 4. 写 `README.md`

至少覆盖：环境说明（镜像 / 预装内容 / 资源 / 端口）、安装方式（local + github 两种）、
使用示例（CLI 与 SDK）、环境变量表、注意事项。参考 [`node-web/README.md`](./node-web/README.md)。

### 5. 更新本文件的总览表

在[模板总览](#模板总览)表格里按字母序插入一行，字段与 YAML 保持一致。
**这一步不能省**：离线测试会把表格与每个 YAML 逐字段比对，漂移即失败。

### 6. 本地验证

```bash
# 离线校验：schema、必需文件、capabilities 合法性、索引一致性
python -m pytest tests/test_templates/test_template_catalog.py -q

# 本地 install 端到端（只 mock 后端构建边界，解析/缓存走真实代码）
python -m pytest tests/test_templates/test_local_install.py -q

# 真实安装一次
ebx install ./my-template --registry-type local
```

> 若本集合已被抽出为独立仓库，上面两条命令依然可用——只需把 `tests/test_templates/`
> 一并 vendor 过去，并把 `conftest.py` 里的 `TEMPLATES_DIR` 指向仓库根即可。
> 测试只依赖 `pydantic` + `pyyaml` + `click` + `pytest` + `easy-sandbox[cli]`，
> 全流程离线。完整说明见主仓库的 `docs/design/templates-catalog.md`
> （在主仓库内可直接点开：[templates-catalog.md](../../docs/design/templates-catalog.md)）。

### 7. 提交

- 一个模板一个 commit / PR，标题形如 `feat(templates): add my-template`。
- 不要修改其他模板的文件夹名（主仓库的 `agent/infer.py::TEMPLATE_CATALOG` 与
  文档都按名字引用它们）。

---

## License

各模板目录默认沿用主项目的 **Apache-2.0** 许可证；如某模板另有许可，
在其 `template.yaml` 的 `license` 字段与 `README.md` 中单独声明。
