# 配置参考

本文档列出 Easy Sandbox 的所有配置项、环境变量、默认值和优先级规则。

---

## 配置优先级

配置按以下优先级加载（从高到低）：

```text
1. 代码参数（api_key=, api_url= 等）          ← 最高
2. 环境变量（E2B_* 优先于 SANDBOX_*）
3. .env 文件（./.env 或 ~/.ebx/.env）
4. ~/.ebx/config.toml
5. 内置默认值                                  ← 最低
```

在同一优先级层中，E2B 系变量优先于 SANDBOX 系变量。

`.env` 文件按**键**合并。同一个键两边都有时，`./.env` 优先于 `~/.ebx/.env`。项目文件里没有的键，仍然来自 `~/.ebx/.env`。

空白或只含空格的值不算已配置，也不会挡住下一层。

## 凭证解析

每项凭证在真正使用时都按这个顺序。`ebx config list` 会标出来源：`(env)`、`(user)`、`(default)` 或 `(not set)`。

| 要用的值 | 1. 显式参数 | 2. 进程环境变量 | 3. `./.env` | 4. `~/.ebx` | 5. 默认 |
|---|---|---|---|---|---|
| 沙箱 API Key | `api_key=` | `E2B_API_KEY`，然后 `SANDBOX_API_KEY` | 同名变量 | `~/.ebx/.env`（`ebx config set sandbox_api_key`） | 无 |
| 阿里云 AK/SK | `access_key_id=` / `access_key_secret=` | `ALICLOUD_ACCESS_KEY_ID` / `ALICLOUD_ACCESS_KEY_SECRET`，然后 `AccessKey` / `AccessSecret` | 同名变量 | `~/.ebx/.env` | 无 |
| ACR 命名空间 | `--acr-namespace` | `ACR_NAMESPACE` | `ACR_NAMESPACE` | `~/.ebx/.env`（`ebx config set acr_namespace`） | 无 |
| GitHub token | `--token` | `GITHUB_TOKEN` | `GITHUB_TOKEN` | `~/.ebx/.env`（`ebx config set github_token`） | 无 |
| LLM API Key | `llm_api_key=` | `EBX_LLM_API_KEY`，然后 `BAILIAN_CODING_PLAN_API_KEY`、`DASHSCOPE_API_KEY`、`OPENAI_API_KEY` | 同名变量 | `~/.ebx/.env`（`ebx config set llm_api_key`） | 无 |
| LLM 地址 | `openai_base_url=` | `EBX_LLM_BASE_URL`，然后 `OPENAI_BASE_URL` | 同名变量 | `~/.ebx/config.toml` 的 `llm_base_url` | DashScope 兼容模式 |
| LLM 模型 | `openai_model=` | `EBX_LLM_MODEL`，然后 `OPENAI_MODEL` | 同名变量 | `~/.ebx/config.toml` 的 `llm_model` | `qwen3-coder-plus` |
| 区域 | 命令 `--region` | `SANDBOX_REGION` | `SANDBOX_REGION` | `~/.ebx/config.toml` 的 `region` | `cn-hangzhou` |

下面这些调用读的是同一条链：

- `Sandbox.create` 以及其他 SDK 客户端（`load_config`）
- `Sandbox.deploy`（`resolve_llm_env`）
- 自然语言 `ebx create`（编码代理）
- `ebx template install` / `ebx template search`（GitHub token）
- `ebx mcp install`（写入编辑器配置的沙箱 API Key）

旧的 `EBX_QWEN_CODE_API_KEY` 只在 `llm_api_key` 未设置时才当作该键使用。进程环境里它排在 `OPENAI_API_KEY` 之后。`~/.ebx` 里它排在 `EBX_LLM_API_KEY` 和 config.toml 里遗留的 `llm_api_key` 之后。

`ebx mcp install` 把这条链解析出的沙箱 API Key 写入 Cursor 和 Claude 的配置。`E2B_API_URL` 和 `SANDBOX_REGION` 只有在进程环境变量里设置了才会写进同一份文件。`ebx mcp start` 会再次读取 `~/.ebx`，所以用 `ebx config set region` 保存的区域在编辑器启动 server 时仍然生效。

`ebx config list` 把进程环境变量标成 `(env)`，把 `./.env` 和 `~/.ebx` 标成 `(user)`。表里命中的那一列就是命令真正会用的值。

---

## 环境变量

### SDK/CLI 通用

| 环境变量 | 对应配置字段 | 系列 | 说明 |
|----------|-------------|------|------|
| `E2B_API_KEY` | `api_key` | E2B | API Key（最常用） |
| `E2B_API_URL` | `api_url` | E2B | 平台 API URL |
| `E2B_DOMAIN` | `domain` | E2B | 数据平面域名 |
| `SANDBOX_API_KEY` | `api_key` | Sandbox | API Key（备选） |
| `SANDBOX_API_BASE_URL` | `api_url` | Sandbox | 平台 API URL（备选） |
| `SANDBOX_REGION` | `region` | Sandbox | 区域 |
| `SANDBOX_HTTP_TIMEOUT` | `http_timeout` | Sandbox | HTTP 超时秒数 |
| `ALICLOUD_ACCESS_KEY_ID` | `access_key_id` | AK/SK | 阿里云 AK |
| `ALICLOUD_ACCESS_KEY_SECRET` | `access_key_secret` | AK/SK | 阿里云 SK |
| `ACR_NAMESPACE` | `acr_namespace` | ACR | ACR 命名空间（`ebx config set acr_namespace`，或 `ebx config init`） |
| `GITHUB_TOKEN` | `github_token` | GitHub | GitHub token（模板下载用；用 `ebx config set github_token` 保存，CI 以 Secret 注入） |
| `EBX_LLM_API_KEY` | `llm_api_key` | LLM | LLM API Key（用 `ebx config set llm_api_key` 保存） |
| `BAILIAN_CODING_PLAN_API_KEY` | `llm_api_key` | LLM | LLM API Key 备选 |
| `DASHSCOPE_API_KEY` | `llm_api_key` | LLM | LLM API Key 备选 |
| `OPENAI_API_KEY` | `llm_api_key` | LLM | LLM API Key 备选 |
| `EBX_LLM_BASE_URL` | `llm_base_url` | LLM | LLM 地址 |
| `OPENAI_BASE_URL` | `llm_base_url` | LLM | LLM 地址备选 |
| `EBX_LLM_MODEL` | `llm_model` | LLM | LLM 模型名 |
| `OPENAI_MODEL` | `llm_model` | LLM | LLM 模型名备选 |

当 `E2B_API_KEY` 和 `SANDBOX_API_KEY` 同时存在时，`E2B_API_KEY` 优先。CLI 里这个键叫 `sandbox_api_key`；SDK 字段仍是 `api_key`。

LLM API Key 的环境变量顺序是 `EBX_LLM_API_KEY`，然后 `BAILIAN_CODING_PLAN_API_KEY`、`DASHSCOPE_API_KEY`、`OPENAI_API_KEY`。其中任何一个都优先于 `./.env`，`./.env` 又优先于 `~/.ebx/.env`。地址顺序是 `EBX_LLM_BASE_URL`、然后 `OPENAI_BASE_URL`、然后 `./.env` 里的同名变量、然后已保存的 `llm_base_url`。模型顺序是 `EBX_LLM_MODEL`、然后 `OPENAI_MODEL`、然后 `./.env`、然后已保存的 `llm_model`。完整顺序见 [凭证解析](#凭证解析)。

### CLI 显示

这些变量只影响终端上的显示，不会被 `ebx config` 保存。

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `EBX_ACTIVITY_LINES` | `4` | `message... 12s` 标题下方的灰色行数（整数 1–10）。部署、创建、上传、下载、拉取模板、用镜像注册模板、安装 coding-agent 和 `ebx kill --all` 都会用到。 |

`--json`、`--quiet`、`--ci`、`TERM=dumb` 和非 TTY 不画这个标题。见 [命令执行时看到什么](../guide/cli-tutorial.md#命令执行时看到什么)。

### Server 端环境变量

以下环境变量用于沙箱内部 Server 配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `EBX_SERVER_TOKEN` | — | Server 认证令牌 |
| `EBX_SERVER_BASE_DIR` | — | Server 工作基目录 |
| `EBX_SERVER_DISABLED_GROUPS` | `DEV_TOOLS,BROWSER` | 禁用的能力组（逗号分隔） |
| `EBX_PTY_PORT` | — | PTY 终端 WebSocket 端口 |
| `EBX_MAX_UPLOAD_SIZE` | — | 最大上传文件大小 |

### 部署相关

| 环境变量 | 说明 |
|----------|------|
| `BAILIAN_CODING_PLAN_API_KEY` | 百炼编码 Agent API Key（deploy 用） |
| `DASHSCOPE_API_KEY` | DashScope API Key（deploy 用） |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（deploy 用） |

---

## config.toml 配置

配置文件路径：`~/.ebx/config.toml`

```toml
[transport]
api_key = "your-api-key"
api_url = "https://api.cn-hangzhou.e2b.fc.aliyuncs.com"
domain = "cn-hangzhou.e2b.fc.aliyuncs.com"
region = "cn-hangzhou"
http_timeout = 30.0
max_retries = 3

[shortcuts]
init = "template init"          # 命令路径，不要写成 "ebx template init"
ps   = "sandbox process list"
```

`[shortcuts]` 把顶层别名映射到一条命令路径，值里不要带 `ebx` 前缀。`ebx config set shortcuts.ps "ebx sandbox process list"` 会被拒绝；应写 `"sandbox process list"`。文件里已经写错的一行会在下次启动时被跳过，其他别名仍然有效。见[快捷方式别名](cli-reference.md#快捷方式别名shortcutsalias)。

---

## TransportConfig 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_url` | `str` | `"https://api.cn-hangzhou.e2b.fc.aliyuncs.com"` | 平台 API URL |
| `domain` | `str` | `"cn-hangzhou.e2b.fc.aliyuncs.com"` | 数据平面域名 |
| `region` | `str` | `"cn-hangzhou"` | 区域 |
| `api_key` | `str \| None` | `None` | API Key |
| `access_key_id` | `str \| None` | `None` | 阿里云 AK |
| `access_key_secret` | `str \| None` | `None` | 阿里云 SK |
| `http_timeout` | `float` | `30.0` | HTTP 请求超时（秒，≥1.0） |
| `max_connections` | `int` | `100` | 最大连接数 |
| `max_keepalive_connections` | `int` | `20` | 最大保活连接数 |
| `keepalive_expiry` | `float` | `30.0` | 保活连接过期时间（秒） |
| `http2` | `bool` | `True` | 是否启用 HTTP/2 |
| `ws_ping_interval` | `float` | `30.0` | WebSocket ping 间隔（秒） |
| `max_retries` | `int` | `3` | 最大重试次数 |
| `retry_base_delay` | `float` | `1.0` | 重试基础延迟（秒） |

### 区域自动推导

当未显式设置 `api_url` 和 `domain`，但设置了 `region` 时，SDK 会自动推导：

```text
api_url = "https://api.{region}.e2b.fc.aliyuncs.com"
domain  = "{region}.e2b.fc.aliyuncs.com"
```

---

## CLI 配置命令

通过 `ebx config` 管理配置：

```bash
# 查看所有配置（含来源标注）
ebx config list

# 获取单个值
ebx config get sandbox_api_key

# 设置值
ebx config set sandbox_api_key your-new-key
ebx config set region cn-beijing
ebx config set http_timeout 60

# 模板下载用的 GitHub token（省略 VALUE → 星号脱敏提示输入）
ebx config set github_token
ebx config set github_token ghp_xxxxxxxxxxxx

# 清除单个已存储的值（回到默认值 / not set）
ebx config set region ""
ebx config set github_token ""
```

此处设置的 `region` 键是区域相关命令的**持久默认值**。单次调用可通过命令级 `--region`/`-r` 选项覆盖（`ebx list`、`ebx kill --all`、模板控制面命令与 `ebx mcp deploy` 支持）。解析优先级：命令 `--region` > `SANDBOX_REGION` > `ebx config set region` > `cn-hangzhou`。

### 可通过 ebx config 设置的键

| 配置键 | 说明 |
|--------|------|
| `sandbox_api_key` | 沙箱服务 API Key（存为 `E2B_API_KEY`；`api_key` 仍可作为 get/set 别名） |
| `api_url` | 平台 API URL |
| `region` | 区域 |
| `http_timeout` | HTTP 超时秒数 |
| `max_retries` | 最大重试次数 |
| `domain` | 数据平面域名 |
| `llm_api_key` | LLM API Key，供自然语言推理和编码代理使用（存为 `EBX_LLM_API_KEY`） |
| `llm_model` | LLM 模型名称（默认 `qwen3-coder-plus`） |
| `llm_base_url` | LLM API Base URL，OpenAI 兼容（默认 DashScope compatible-mode） |
| `access_key_id` | 阿里云 AccessKey ID（🧪 实验性 AK/SK 认证） |
| `access_key_secret` | 阿里云 AccessKey Secret（🧪 实验性 AK/SK 认证） |
| `acr_namespace` | `ebx install` / `ebx template deploy` 用的 ACR 命名空间（存为 `ACR_NAMESPACE`） |
| `github_token` | GitHub token（模板下载用，`ebx template install` / `ebx template search`；对应 `GITHUB_TOKEN`，存 `~/.ebx/.env`，脱敏显示） |

### 引导式配置（ebx config init）

```bash
ebx config init
```

交互式向导依次提示：沙箱 API Key、默认区域、LLM API Key、ACR 命名空间（`ACR_NAMESPACE`）、AccessKey ID、AccessKey Secret。直接回车跳过该项。密钥和命名空间写入 `~/.ebx/.env`，区域写入 `~/.ebx/config.toml`。非 TTY 环境或 `--yes` 下不阻塞，打印等效的 `ebx config set` 命令。

### AK/SK 认证配置（实验性）

`access_key_id` 和 `access_key_secret` 通过 `ebx config set` 设置后，存储在 `~/.ebx/.env` 中（分别对应环境变量 `ALICLOUD_ACCESS_KEY_ID` 和 `ALICLOUD_ACCESS_KEY_SECRET`）。用于 AK/SK → API Key 的 token 交换认证。

> **注意**：此功能为实验性支持，token 交换端点待 FC 平台确认。详见 [认证详解](../guide/authentication.md#aksk-阿里云扩展认证-)。

---

## SDK 参数覆盖

在代码中直接传参（最高优先级）：

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.create(
    api_key="REPLACE_ME",
    api_url="https://api.cn-beijing.e2b.fc.aliyuncs.com",
    access_key_id="REPLACE_ME",
    access_key_secret="REPLACE_ME",
)
```

---

## .env 文件

SDK 会读取这两个 `.env` 并按键合并：

1. 当前目录下的 `.env`（写了该键时优先）
2. `~/.ebx/.env`（项目文件没有的键用这里的值）

`.env` 文件格式：

```bash
E2B_API_KEY=your-api-key
SANDBOX_REGION=cn-beijing
```

`ebx config set sandbox_api_key <KEY>` 命令将 API Key 保存到 `~/.ebx/.env`（文件权限 600）。`github_token`（对应 `GITHUB_TOKEN`）等凭证键以同样方式存储。

---

## 配置文件位置汇总

| 文件 | 路径 | 说明 |
|------|------|------|
| config.toml | `~/.ebx/config.toml` | SDK 扩展配置 |
| .env | `~/.ebx/.env` | 认证凭证（auth login / `ebx config set` 写入） |
| .env（本地） | `./.env` | 项目级环境变量 |
| 会话存储 | `~/.ebx/sessions/*.json` | 本地会话数据 |
| 模板缓存 | `~/.ebx/templates/` | 已安装的模板 |
