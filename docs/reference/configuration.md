# 配置参考

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

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

当 `E2B_API_KEY` 和 `SANDBOX_API_KEY` 同时存在时，`E2B_API_KEY` 优先。

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
```

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
ebx config get api_key

# 设置值
ebx config set api_key your-new-key
ebx config set region cn-beijing
ebx config set http_timeout 60

# 重置所有配置
ebx config reset --yes
```

### 可通过 ebx config 设置的键

| 配置键 | 说明 |
|--------|------|
| `api_key` | API Key |
| `api_url` | 平台 API URL |
| `region` | 区域 |
| `http_timeout` | HTTP 超时秒数 |
| `max_retries` | 最大重试次数 |
| `domain` | 数据平面域名 |
| `llm_api_key` | LLM API Key（deploy 用） |
| `llm_model` | LLM 模型名称（deploy 用） |
| `llm_base_url` | LLM API Base URL（deploy 用） |

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

SDK 按顺序搜索 `.env` 文件：

1. 当前目录下的 `.env`
2. `~/.ebx/.env`

`.env` 文件格式：

```bash
E2B_API_KEY=your-api-key
SANDBOX_REGION=cn-beijing
```

`ebx auth login` 命令将 API Key 保存到 `~/.ebx/.env`（文件权限 600）。

---

## 配置文件位置汇总

| 文件 | 路径 | 说明 |
|------|------|------|
| config.toml | `~/.ebx/config.toml` | SDK 扩展配置 |
| .env | `~/.ebx/.env` | 认证凭证（auth login 写入） |
| .env（本地） | `./.env` | 项目级环境变量 |
| 会话存储 | `~/.ebx/sessions/*.json` | 本地会话数据 |
| 模板缓存 | `~/.ebx/templates/` | 已安装的模板 |
