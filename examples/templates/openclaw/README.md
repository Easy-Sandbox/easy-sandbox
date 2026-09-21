# OpenClaw AI Agent 运行环境模板

OpenClaw 开源 AI 编程 Agent 的沙箱运行环境，提供 Agent 网关与运行时支持。

## 环境说明

本模板预装以下工具和依赖：

| 类别 | 内容 |
|------|------|
| **操作系统** | Ubuntu 22.04 |
| **Node.js** | Node.js 22.x + npm（核心运行时） |
| **Node 包** | `openclaw` |
| **系统工具** | git、curl |
| **端口** | 18789（Gateway） |
| **资源配置** | 2 CPU / 4096 MB 内存 |

## 安装方式

**从本地安装：**

```bash
ebx install ./examples/templates/openclaw --registry-type local
```

**从 GitHub 安装：**

```bash
ebx install Easy-Sandbox/awesome-templates//openclaw
```

## 使用示例

创建沙箱实例并传入 API Key：

```bash
ebx create --template openclaw --env ANTHROPIC_API_KEY=sk-ant-xxx
```

也可以使用 OpenAI 作为后端：

```bash
ebx create --template openclaw --env OPENAI_API_KEY=sk-xxx
```

在沙箱中启动 OpenClaw：

```bash
ebx exec <sandbox-id> -- openclaw --help
```

使用 Python SDK：

```python
from easy_sandbox import Sandbox

sandbox = Sandbox.create(
    template="openclaw",
    env={"ANTHROPIC_API_KEY": "sk-ant-xxx"}
)

result = sandbox.commands.run("openclaw --version")
print(result.stdout)
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | 二选一 |
| `OPENAI_API_KEY` | OpenAI API 密钥 | 二选一 |
| `WORKSPACE` | 工作目录路径，默认 `/workspace` | 否 |

### 端口说明

| 端口 | 说明 |
|------|------|
| 18789 | OpenClaw Gateway 服务端口 |

### 自定义配置

如需在模板基础上安装额外依赖，可在创建沙箱后执行：

```bash
ebx exec <sandbox-id> -- npm install -g <package-name>
```

## 注意事项

- **API Key 安全**：请勿将 API Key 硬编码到模板中，始终通过 `--env` 参数或环境变量注入。
- **多模型支持**：OpenClaw 支持 Anthropic 和 OpenAI 等多种 LLM 后端，按需配置对应的 API Key。
- **Gateway 端口**：默认监听 18789 端口，可通过沙箱端口映射访问。
- **网络访问**：需要访问 LLM 提供商 API，确保沙箱具备外网连接能力。
