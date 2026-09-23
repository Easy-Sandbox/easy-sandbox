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

### 交互式登录

```bash
ebx auth login
# 按提示输入 API Key，保存到 ~/.ebx/.env
```

### 验证状态

```bash
ebx auth status
# 输出示例：
#   API Key: abcd****efgh
#   Source: /Users/you/.ebx/.env
#   Auth Mode: api_key
```

### 或通过环境变量

```bash
export E2B_API_KEY="your-api-key"
```

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

如果模板定义了自定义命令（或通过 `@sandbox.register` 注册），可以用 `ebx run` 执行：

```bash
# 查看可用命令
ebx run sbx-xxxx --help

# 执行命令
ebx run sbx-xxxx dev --arg file=tests/
ebx run sbx-xxxx demo --x 1 --y hello
```

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

---

## 会话管理

会话（session）将沙箱与一个名称关联，方便反复连接：

```bash
# 启动会话
ebx session start my-project --template base

# 连接到会话
ebx session connect my-project

# 列出所有会话
ebx session list

# 查看会话信息
ebx session info my-project

# 停止会话
ebx session stop my-project
```

---

## 密钥管理

```bash
# 创建密钥（安全输入）
ebx secret create MY_TOKEN

# 列出密钥
ebx secret list

# 注入到沙箱
ebx secret inject sbx-xxxx -s MY_TOKEN -s ANOTHER_SECRET

# 删除密钥
ebx secret delete MY_TOKEN
```

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

将 Easy Sandbox 作为 MCP Server 提供给 AI IDE 使用：

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
