# 常见问题（FAQ）

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

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
# 检查认证状态
ebx auth status

# 重新登录
ebx auth login

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

```text
[E7001] No LLM API key found for the qwen-code agent.
  Suggestion: Set BAILIAN_CODING_PLAN_API_KEY, DASHSCOPE_API_KEY, or OPENAI_API_KEY environment variable.
```

**解决**：设置任一 LLM API Key：

```bash
export DASHSCOPE_API_KEY="your-key"
# 或
ebx config set llm_api_key your-key
```

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
