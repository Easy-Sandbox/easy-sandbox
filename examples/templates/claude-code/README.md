# Claude Code Agent 运行环境模板

Anthropic Claude Code 的沙箱运行环境，预装 Claude Code CLI，支持 AI 驱动的代码编写、调试和重构。

## 环境说明

本模板预装以下工具和依赖：

| 类别 | 内容 |
|------|------|
| **操作系统** | Ubuntu 22.04 |
| **Node.js** | Node.js 22.x + npm（核心运行时） |
| **Python** | Python 3.11 + venv 虚拟环境（位于 `/opt/venv`） |
| **Node 包** | `@anthropic-ai/claude-code` |
| **Python 包** | `anthropic`、`httpx`、`rich` |
| **系统工具** | git、curl、ripgrep、build-essential |
| **资源配置** | 2 CPU / 4096 MB 内存 |

## 安装方式

**从本地安装：**

```bash
sbox install ./examples/templates/claude-code --registry-type local
```

**从 GitHub 安装：**

```bash
sbox install Serverless-Sandbox/awesome-templates//claude-code
```

## 使用示例

创建沙箱实例并传入 API Key：

```bash
sbox create --template claude-code --env ANTHROPIC_API_KEY=sk-ant-xxx
```

在沙箱中启动 Claude Code：

```bash
sbox exec <sandbox-id> -- claude "编写一个 Python HTTP 服务器"
```

非交互模式执行任务：

```bash
sbox exec <sandbox-id> -- claude -p "重构这个函数以提高性能" --allowedTools "Edit,Read,Write"
```

使用 Python SDK：

```python
from serverless_sandbox import Sandbox

sandbox = Sandbox.create(
    template="claude-code",
    env={"ANTHROPIC_API_KEY": "sk-ant-xxx"}
)

result = sandbox.commands.run("claude -p '生成一个 REST API 框架'")
print(result.stdout)
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | 是 |
| `WORKSPACE` | 工作目录路径，默认 `/workspace` | 否 |

### 自定义配置

如需在模板基础上安装额外依赖，可在创建沙箱后执行：

```bash
sbox exec <sandbox-id> -- pip install <package-name>
sbox exec <sandbox-id> -- npm install -g <package-name>
```

## 注意事项

- **API Key 安全**：请勿将 `ANTHROPIC_API_KEY` 硬编码到模板中，始终通过 `--env` 参数或环境变量注入。
- **网络访问**：Claude Code 需要访问 Anthropic API，确保沙箱具备外网连接能力。
- **Node.js 核心**：Claude Code CLI 基于 Node.js 运行，Node.js 22 为核心依赖。
- **资源消耗**：AI 代码生成任务可能消耗较多内存，建议保持 4096 MB 以上的内存配置。
- **虚拟环境**：Python 包安装在 `/opt/venv` 中，使用时无需手动激活，`PATH` 已自动配置。
