# Hermes Agent 运行环境模板

NousResearch Hermes 系列模型驱动的 AI Agent 沙箱运行环境，支持工具调用（Tool Calling）和多模态任务。

## 环境说明

本模板预装以下工具和依赖：

| 类别 | 内容 |
|------|------|
| **操作系统** | Ubuntu 22.04 |
| **Python** | Python 3.11 + venv 虚拟环境（位于 `/opt/venv`） |
| **Node.js** | Node.js 22.x + npm |
| **Python 包** | `uv`、`openai>=1.0`、`httpx`、`rich`、`pyyaml` |
| **系统工具** | git、curl、xz-utils、build-essential、ripgrep、ffmpeg |
| **资源配置** | 2 CPU / 4096 MB 内存（建议 8192 MB 带浏览器场景） |

## 安装方式

**从本地安装：**

```bash
ebx install ./examples/templates/hermes-agent --registry-type local
```

**从 GitHub 安装：**

```bash
ebx install Easy-Sandbox/awesome-templates//hermes-agent
```

## 使用示例

创建沙箱实例并传入 LLM 配置：

```bash
ebx create --template hermes-agent \
    --env OPENAI_API_KEY=sk-xxx \
    --env OPENAI_BASE_URL=https://api.your-provider.com/v1
```

使用 uv 快速安装 Agent 框架：

```bash
ebx exec <sandbox-id> -- uv pip install langchain langgraph
```

通过 OpenAI 兼容接口调用 Hermes 模型：

```bash
ebx exec <sandbox-id> -- python3 -c "
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(
    model='NousResearch/Hermes-3-Llama-3.1-8B',
    messages=[{'role': 'user', 'content': '编写一个文件搜索工具'}],
    tools=[{
        'type': 'function',
        'function': {
            'name': 'search_files',
            'description': '搜索文件',
            'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}}
        }
    }]
)
print(response.choices[0].message)
"
```

使用 Python SDK：

```python
from easy_sandbox import Sandbox

sandbox = Sandbox.create(
    template="hermes-agent",
    env={
        "OPENAI_API_KEY": "sk-xxx",
        "OPENAI_BASE_URL": "https://api.your-provider.com/v1"
    }
)

result = sandbox.commands.run("python3 --version && uv --version")
print(result.stdout)
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `OPENAI_API_KEY` | LLM 提供商 API 密钥 | 是 |
| `OPENAI_BASE_URL` | LLM API 基础 URL（用于自部署或第三方托管） | 否 |
| `WORKSPACE` | 工作目录路径，默认 `/workspace` | 否 |

### 使用 uv 管理依赖

本模板预装 `uv` 作为高性能 Python 包管理器，建议使用 `uv` 替代 `pip`：

```bash
# 使用 uv 安装包（速度远快于 pip）
ebx exec <sandbox-id> -- uv pip install <package-name>

# 使用 uv 创建项目
ebx exec <sandbox-id> -- uv init my-agent-project
```

## 注意事项

- **API Key 安全**：请勿将 API Key 硬编码到模板中，始终通过 `--env` 参数或环境变量注入。
- **模型兼容**：Hermes 模型通过 OpenAI 兼容接口访问，需配置 `OPENAI_BASE_URL` 指向实际托管地址。
- **资源建议**：基础 Agent 任务使用 4096 MB 内存即可；涉及浏览器自动化或多媒体处理时建议 8192 MB。
- **ffmpeg 支持**：已预装 ffmpeg，支持音视频处理任务。
- **虚拟环境**：Python 包安装在 `/opt/venv` 中，使用时无需手动激活，`PATH` 已自动配置。
