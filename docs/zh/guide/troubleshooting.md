# 常见问题（FAQ）

---

## 连接超时

### 症状

```text
[E5001] Failed to connect to sandbox service
  Suggestion: Check network connectivity and firewall rules.
```

### 排查

1. **检查网络**：确认可以访问 `api.cn-hangzhou.e2b.fc.aliyuncs.com`
   ```bash
   curl -I https://api.cn-hangzhou.e2b.fc.aliyuncs.com
   ```

2. **检查超时配置**：增大 HTTP 超时
   ```bash
   ebx config set http_timeout 60
   ```

3. **检查代理**：如果在代理环境中，确保 `https_proxy` 正确配置

4. **检查区域**：确认区域设置正确
   ```bash
   ebx config get region
   ```

---

## 认证失败

### E1001 — API Key 无效或缺失

```text
[E1001] API key cannot be empty
  Suggestion: Check your E2B_API_KEY environment variable or pass api_key parameter.
```

**解决**：
```bash
# 检查配置状态
ebx config get sandbox_api_key

# 重新设置 API Key
ebx config set sandbox_api_key your-api-key

# 或设置环境变量
export E2B_API_KEY="your-api-key"
```

### E1003 — AK/SK 凭证无效

```text
[E1003] AccessKey ID and Secret cannot be empty
```

**解决**：确保同时设置了 AK ID 和 AK Secret：
```bash
export ALICLOUD_ACCESS_KEY_ID="your-ak-id"
export ALICLOUD_ACCESS_KEY_SECRET="your-ak-secret"
```

### E1002 — Token 过期

```text
[E1002] The SDK should auto-refresh tokens. If this persists, check system clock synchronization.
```

**解决**：检查系统时钟是否准确。SDK 会自动刷新 AK/SK 临时 token（有效期 3600 秒，到期前 300 秒刷新）。

---

## 模板不存在

### E2001 — TemplateNotFoundError

```text
[E2001] Template 'my-template' not found
  Suggestion: Run 'ebx template list' to see available templates.
```

**解决**：

1. 检查模板名称拼写
2. 确认模板已安装：
   ```bash
   ebx template install owner/repo
   ```
3. 使用默认模板测试：
   ```bash
   ebx create --template base
   ```

---

## 能力不支持（E3004）

### 症状

```text
[E3004] Capability 'ports' is not supported by this sandbox template.
  Suggestion: Declare 'ports' in the template's capabilities list (template.yaml) or use a template that supports it.
```

### 解释

Easy Sandbox 使用能力模型控制沙箱功能。每个能力需要在模板中显式声明：

| 能力 | 默认包含 | 需要显式声明 |
|------|----------|-------------|
| `shell` | ✅ | — |
| `files` | ✅ | — |
| `code` | ✅ | — |
| `terminal` | ❌ | 需在 template.yaml 中声明 |
| `ports` | ❌ | 需在 template.yaml 中声明 |

### 解决

如果需要使用 `terminal` 或 `ports` 能力，使用声明了该能力的模板，或创建自定义模板：

```yaml
# template.yaml
name: my-web-template
capabilities:
  - shell
  - files
  - code
  - terminal
  - ports
```

> **Server 端能力组注意**：Server 端有 8 个能力组。其中 TERMINAL 默认启用，仅 DEV_TOOLS 和 BROWSER 默认禁用（`_DEFAULT_DISABLED = {DEV_TOOLS, BROWSER}`）。客户端能力（`capabilities` 字段）和 Server 端能力组是不同层面的控制。

---

## 配额超限

### E2002 — QuotaExceededError

```text
[E2002] Sandbox quota has been exceeded
  Suggestion: Destroy idle sandboxes or request a quota increase.
```

**解决**：

```bash
# 查看运行中的沙箱
ebx list --status running

# 销毁不需要的沙箱
ebx kill sbx-xxxx

# 批量销毁
ebx kill --all --yes
```

---

## 命令执行超时

### E3001 — CommandTimeoutError

```text
[E3001] Command execution timed out
  Suggestion: Increase the timeout parameter or check if the command is hanging.
```

**解决**：

```python
# SDK 中增加超时
result = await sandbox.commands.run("long-command", timeout=300)

# CLI 中增加超时
ebx exec sbx-xxxx "long-command" --timeout 300
```

---

## 部署相关

### E7001 — 缺少 LLM Key

> 仅 SDK 的 `Sandbox.deploy()` 会抛出。`ebx deploy` 不需要 LLM Key；CLI 的 AI 步骤（`ebx create "..."`、`ebx template init "..."`、`ebx template init --adopt`）使用 `ebx config` 中的 Qwen Code 凭据。

```text
[E7001] No LLM API key found for the qwen-code agent.
  Suggestion: Set BAILIAN_CODING_PLAN_API_KEY, DASHSCOPE_API_KEY, or OPENAI_API_KEY environment variable.
```

**解决**：设置任一 LLM API Key：

```bash
export DASHSCOPE_API_KEY="your-key"
# 或向 Sandbox.deploy(...) 传入 llm_api_key=
# CLI（create / template init）：ebx config set llm_api_key your-key
```

### 没有 Dockerfile

目录里没有 `Dockerfile` 时，`ebx deploy` 会停下，并给出三条编写命令：已有源码用 `ebx template init --adopt .`，用一句话新建项目用 `ebx template init "描述"`，脚手架用 `ebx template init -t python`。文件写好之后再执行 `ebx deploy`。

非交互的 `--adopt` 如果没带 `-y`，会停在 “Confirmation required before project files are sent to the model.”。加上 `-y` 即同时批准两次确认；`--dry-run` 只列出文件，不发送。

### 长时间步骤看起来停住了

终端上标题应持续走动（`Building Docker image locally... 12s`，然后 `13s`）。最近四行日志以灰色显示在标题下方。如果只看到一行、没有耗时，当前会话是 `--quiet`、`--json`、`--ci`、`TERM=dumb`，或者不是终端。去掉这些选项就能看到动态块。`--verbose` 改为打印完整的部署日志。`EBX_ACTIVITY_LINES`（1–10，默认 4）决定保留几行灰色文字。文件内容和凭证不会进入这个块。

### E7003 — 部署超时

**解决**：增加 `max_wall_time` 参数或简化部署任务。

---

## 文件操作

### E4001 — 文件未找到

```python
# 先检查文件是否存在
exists = await sandbox.files.exists("/path/to/file")
if not exists:
    print("文件不存在")

# 列出目录内容
entries = await sandbox.files.list("/home/user")
```

### E4002 — 权限被拒绝

检查文件权限。沙箱默认用户为 `user`，可在命令中指定 `user` 参数。

---

## 快捷方式目标无效

快捷方式的目标是命令路径，不是带 `ebx` 的完整调用。下面的写法会被拒绝，且不会保存：

```bash
ebx config set shortcuts.aaaaa "ebx template init"
```

```text
Invalid shortcut target: 'ebx template init'
  Suggestion: Drop the leading "ebx". The target is the command path only, for example "template init".
              Try: ebx config set shortcuts.aaaaa "template init"
```

按提示里的命令重试即可。如果 `~/.ebx/config.toml` 里已经写了 `aaaaa = "ebx template init"`，下次启动 `ebx` 会警告 `Invalid shortcut ignored` 并跳过这一条，其他快捷方式仍然可用。不认识的路径（例如 `"not-a-command"`）同样会被拒绝，并按命令分组列出合法目标。

---

## 安装问题

### pip install 失败

```bash
# 确保使用正确的包名
pip install easy-sandbox

# 如果遇到依赖冲突
pip install easy-sandbox --force-reinstall
```

### ebx 命令未找到

确认 Python 的 bin 目录在 PATH 中：

```bash
python -m easy_sandbox --version
# 或
pip show easy-sandbox | grep Location
```

---

## 下一步

- [认证详解](authentication.md) — 认证配置
- [配置参考](../reference/configuration.md) — 所有配置项
- [错误码参考](../reference/error-codes.md) — 完整错误码列表
