# 通义千问编码 Agent 运行环境模板

通义千问（Qwen）编码 Agent 的沙箱运行环境，支持 qwen-code 驱动的 AI 自主部署，提供 Python 3.11 + Node.js 22 的 AI 编程基础环境。

## 环境说明

本模板预装以下工具和依赖：

| 类别 | 内容 |
|------|------|
| **操作系统** | Ubuntu 22.04 |
| **Python** | Python 3.11 + venv 虚拟环境（位于 `/opt/venv`） |
| **Node.js** | Node.js 22.x + npm |
| **Python 包** | `dashscope`、`openai>=1.0`、`httpx`、`rich` |
| **Node.js 包** | `@qwen-code/qwen-code@0.23.0` |
| **系统工具** | git、curl、wget、ripgrep、jq、build-essential |
| **资源配置** | 2 CPU / 4096 MB 内存 |

## 安装方式

**从本地安装：**

```bash
ebx install ./examples/templates/qwen-code --registry-type local
```

**从 GitHub 安装：**

```bash
ebx install Easy-Sandbox/awesome-templates//qwen-code
```

## 使用示例

创建沙箱实例并传入 API Key：

```bash
ebx create --template qwen-code --env DASHSCOPE_API_KEY=sk-xxx
```

在沙箱中通过 DashScope SDK 调用 Qwen 模型：

```bash
ebx exec <sandbox-id> -- python3 -c "
import dashscope
from dashscope import Generation
response = Generation.call(model='qwen-turbo', prompt='编写一个快速排序算法')
print(response.output.text)
"
```

也支持使用 OpenAI 兼容接口：

```bash
ebx exec <sandbox-id> -- python3 -c "
from openai import OpenAI
client = OpenAI(
    api_key='your-dashscope-key',
    base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'
)
response = client.chat.completions.create(
    model='qwen-turbo',
    messages=[{'role': 'user', 'content': '编写一个快速排序'}]
)
print(response.choices[0].message.content)
"
```

使用 Python SDK：

```python
from easy_sandbox import Sandbox

sandbox = Sandbox.create(
    template="qwen-code",
    env={"DASHSCOPE_API_KEY": "sk-xxx"}
)

result = sandbox.commands.run("python3 --version && node --version")
print(result.stdout)
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API 密钥 | 是 |
| `WORKSPACE` | 工作目录路径，默认 `/workspace` | 否 |

### 手动安装 AI 编码工具

本模板已预装 qwen-code CLI 工具，可直接使用：

```bash
# 使用 qwen-code 进行 NL 部署
ebx deploy ./my-project "部署这个 FastAPI 项目"

# 或在沙箱内直接使用 qwen 命令
ebx exec <sandbox-id> -- qwen -p "分析项目并部署" --yolo
```

如需安装额外工具：

```bash
# 安装额外 Python 包
ebx exec <sandbox-id> -- pip install <agent-package>

# 安装额外 Node.js 工具
ebx exec <sandbox-id> -- npm install -g <agent-tool>
```

## 注意事项

- **API Key 安全**：请勿将 `DASHSCOPE_API_KEY` 硬编码到模板中，始终通过 `--env` 参数或环境变量注入。
- **网络访问**：需要访问 DashScope API（`dashscope.aliyuncs.com`），确保沙箱具备外网连接能力。
- **兼容接口**：DashScope 提供 OpenAI 兼容模式，可通过 `openai` 库直接调用 Qwen 模型。
- **虚拟环境**：Python 包安装在 `/opt/venv` 中，使用时无需手动激活，`PATH` 已自动配置。
