# Codex Agent 运行环境模板

OpenAI Codex CLI Agent 的沙箱运行环境，支持 AI 驱动的代码生成和执行。

## 环境说明

本模板预装以下工具和依赖：

| 类别 | 内容 |
|------|------|
| **操作系统** | Ubuntu 22.04 |
| **Python** | Python 3 + venv 虚拟环境（位于 `/opt/venv`） |
| **Node.js** | Node.js 22.x + npm |
| **Python 包** | `openai>=1.0`、`rich`、`httpx` |
| **Node 包** | `@openai/codex` |
| **系统工具** | git、curl、wget、build-essential、ripgrep、jq |
| **资源配置** | 2 CPU / 4096 MB 内存 |

## 安装方式

**从本地安装：**

```bash
sbox install ./examples/templates/codex --registry-type local
```

**从 GitHub 安装：**

```bash
sbox install Serverless-Sandbox/awesome-templates//codex
```

## 使用示例

创建沙箱实例并传入 API Key：

```bash
sbox create --template codex --env OPENAI_API_KEY=sk-xxx
```

在沙箱中执行代码生成任务：

```bash
sbox exec <sandbox-id> -- codex "编写一个快速排序算法"
```

使用 Python SDK：

```python
from serverless_sandbox import Sandbox

sandbox = Sandbox.create(
    template="codex",
    env={"OPENAI_API_KEY": "sk-xxx"}
)

result = sandbox.commands.run("codex '生成一个 Flask REST API'")
print(result.stdout)
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥 | 是 |
| `CODEX_SANDBOX_MODE` | 沙箱模式标识，默认 `true` | 否 |
| `WORKSPACE` | 工作目录路径，默认 `/workspace` | 否 |

### 自定义配置

如需在模板基础上安装额外依赖，可在创建沙箱后执行：

```bash
sbox exec <sandbox-id> -- pip install <package-name>
sbox exec <sandbox-id> -- npm install -g <package-name>
```

## 注意事项

- **API Key 安全**：请勿将 `OPENAI_API_KEY` 硬编码到模板中，始终通过 `--env` 参数或环境变量注入。
- **网络访问**：Codex Agent 需要访问 OpenAI API，确保沙箱具备外网连接能力。
- **资源消耗**：AI 代码生成任务可能消耗较多内存，建议保持 4096 MB 以上的内存配置。
- **虚拟环境**：Python 包安装在 `/opt/venv` 中，使用时无需手动激活，`PATH` 已自动配置。
