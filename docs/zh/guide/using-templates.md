# 使用模板

模板是预配置的沙箱环境定义，包含基础镜像、预装软件、能力声明和自定义命令。

---

## 什么是模板

模板是一个包含 `template.yaml` 的目录，定义了沙箱的运行环境。模板可以：

- 指定基础 Docker 镜像和预装包
- 声明支持的能力（`shell`、`files`、`code`、`terminal`、`ports`）
- 定义自定义命令
- 设置默认环境变量和资源规格

当不指定模板时，SDK 使用内置的 `base` 模板，提供默认能力集 `{shell, files, code}`。

---

## 列出可用模板

目前模板列表来自本地安装的模板（位于 `~/.ebx/templates/`）。通过 `ebx template install` 安装模板。

---

## 安装模板

### 从 GitHub 安装

```bash
# 基础格式：owner/repo
ebx template install owner/repo

# 指定版本标签
ebx template install owner/repo@v1.0

# 指定子目录
ebx template install owner/repo//path/to/template

# 使用别名
ebx template install owner/repo --alias my-python

# 私有仓库 / 更高限流：一次性保存 token（星号脱敏输入）
ebx config set github_token
ebx template install owner/private-repo

# 单次命令的临时覆盖（可能泄漏到 shell history 或进程列表）
ebx template install owner/private-repo --token ghp_xxx
```

GitHub 匿名下载限流为 60 次/小时，保存 token 后提升至 5000 次/小时。推荐使用 `ebx config set github_token` 而非 `--token`——后者是单次临时覆盖，可能泄漏到 shell history 或进程列表。优先级：`--token` > `GITHUB_TOKEN` 环境变量 > 持久化的 `github_token`。未配置 token 且触发匿名限流时，交互式终端会提供引导式一次性配置（无需 `--token`）。

### 从本地目录安装

```bash
ebx template install ./my-template --registry-type local
```

### 快捷方式

`ebx install` 是 `ebx template install` 的顶层快捷命令：

```bash
ebx install owner/repo
```

---

## 按模板创建沙箱

### CLI

```bash
ebx create --template my-python
```

### SDK

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.create(template="my-python")
```

---

## 自然语言创建

当不确定使用哪个模板时，可以用自然语言描述需求：

### CLI

```bash
ebx create "一个支持 pandas 和 matplotlib 的 Python 数据分析环境"
```

### SDK

```python
sandbox = await Sandbox.create(
    description="一个支持 pandas 和 matplotlib 的 Python 数据分析环境",
)
```

SDK 会将 `description` 记录为 hint 日志条目，模板选择不发生在 `Sandbox.create()` 内部。CLI 的 `ebx create "<描述>"`（未显式传 `--template` 时）走 AI 路径：调用 Qwen Code 生成 Dockerfile + template.yaml，构建部署后用生成的模板创建沙箱。

---

## 内置模板

| 模板名 | 说明 | 默认能力 |
|--------|------|----------|
| `base` | 基础 Ubuntu 环境 | `shell`, `files`, `code` |

> **提示**：可通过 `ebx template install` 从社区获取更多模板，或参考 [编写模板](authoring-templates.md) 创建自己的模板。

---

## 能力模型

模板通过 `capabilities` 字段声明沙箱支持的能力：

| 能力 | 说明 | 默认 |
|------|------|------|
| `shell` | 执行 Shell 命令 | ✅ |
| `files` | 文件系统操作 | ✅ |
| `code` | Code Interpreter 代码执行 | ✅ |
| `terminal` | PTY 终端会话 | ❌（需显式声明） |
| `ports` | 端口 URL 访问 | ❌（需显式声明） |

当模板未声明 `capabilities` 时，使用默认能力集 `{shell, files, code}`。

---

## 自定义命令

模板可以定义自定义命令，用户通过 `ebx run` 或 `sandbox.custom()` 调用：

```bash
# CLI
ebx run sbx-xxxx dev --arg port=8080

# SDK
result = await sandbox.custom("dev", port="8080")
```

查看模板定义的命令：

```python
commands = sandbox.list_commands()
for cmd in commands:
    print(f"{cmd['name']}: {cmd['description']}")
```

---

## 下一步

- [编写模板](authoring-templates.md) — 创建自己的模板
- [CLI 教程](cli-tutorial.md) — CLI 完整使用教程
- [模板 YAML 规范](../reference/template-yaml-spec.md) — template.yaml 字段参考
