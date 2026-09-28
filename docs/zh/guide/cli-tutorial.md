# CLI 教程

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

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

### 使用默认模板

```bash
ebx create --template base
# 输出类似：
# ✓ Sandbox created: sbx-xxxx
```

### 自然语言创建

```bash
ebx create "一个 Python 数据分析环境"
# SDK 通过 LLM 推断最佳模板和配置
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
# 进入交互模式，输入命令后回车执行
# 输入 exit、quit 或 Ctrl+D 退出
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

# 重置
ebx config reset --yes
```

可用配置键：`api_key`、`api_url`、`region`、`http_timeout`、`max_retries`、`domain`、`llm_api_key`、`llm_model`、`llm_base_url`。

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

详细全局选项列表（含 `--verbose`、`--log-level`、`--timeout`、`--region` 等）参见 [CLI 参考手册 — 全局选项](../reference/cli-reference.md#全局选项)。

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
