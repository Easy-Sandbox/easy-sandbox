# Troubleshooting (FAQ)

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

---

## Connection Timeout

### Symptoms

```text
[E5001] Failed to connect to sandbox service
  Suggestion: Check network connectivity and firewall rules.
```

### Troubleshooting

1. **Check network**: Confirm you can access `api.cn-hangzhou.e2b.fc.aliyuncs.com`
   ```bash
   curl -I https://api.cn-hangzhou.e2b.fc.aliyuncs.com
   ```

2. **Check timeout configuration**: Increase the HTTP timeout
   ```bash
   ebx config set http_timeout 60
   ```

3. **Check proxy**: If behind a proxy, ensure `https_proxy` is configured correctly

4. **Check region**: Confirm the region setting is correct
   ```bash
   ebx config get region
   ```

---

## Authentication Failure

### E1001 — Invalid or Missing API Key

```text
[E1001] API key cannot be empty
  Suggestion: Check your E2B_API_KEY environment variable or pass api_key parameter.
```

**Solution**:
```bash
# Check authentication status
ebx auth status

# Re-login
ebx auth login

# Or set the environment variable
export E2B_API_KEY="your-api-key"
```

### E1003 — Invalid AK/SK Credentials

```text
[E1003] AccessKey ID and Secret cannot be empty
```

**Solution**: Ensure both AK ID and AK Secret are set:
```bash
export ALICLOUD_ACCESS_KEY_ID="your-ak-id"
export ALICLOUD_ACCESS_KEY_SECRET="your-ak-secret"
```

### E1002 — Token Expired

```text
[E1002] The SDK should auto-refresh tokens. If this persists, check system clock synchronization.
```

**Solution**: Check that the system clock is accurate. The SDK auto-refreshes AK/SK temporary tokens (valid for 3600 seconds, refreshed 300 seconds before expiry).

---

## Template Not Found

### E2001 — TemplateNotFoundError

```text
[E2001] Template 'my-template' not found
  Suggestion: Run 'ebx template list' to see available templates.
```

**Solution**:

1. Check the template name for typos
2. Confirm the template is installed:
   ```bash
   ebx template install owner/repo
   ```
3. Test with the default template:
   ```bash
   ebx create --template base
   ```

---

## Capability Not Supported (E3004)

### Symptoms

```text
[E3004] Capability 'ports' is not supported by this sandbox template.
  Suggestion: Declare 'ports' in the template's capabilities list (template.yaml) or use a template that supports it.
```

### Explanation

Easy Sandbox uses a capability model to control sandbox features. Each capability must be explicitly declared in the template:

| Capability | Included by Default | Requires Explicit Declaration |
|------------|--------------------|-----------------------------|
| `shell` | ✅ | — |
| `files` | ✅ | — |
| `code` | ✅ | — |
| `terminal` | ❌ | Must be declared in template.yaml |
| `ports` | ❌ | Must be declared in template.yaml |

### Solution

If you need the `terminal` or `ports` capability, use a template that declares it, or create a custom template:

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

> **Server-side capability groups note**: The server has 8 capability groups. TERMINAL is enabled by default; only DEV_TOOLS and BROWSER are disabled by default (`_DEFAULT_DISABLED = {DEV_TOOLS, BROWSER}`). Client-side capabilities (the `capabilities` field) and server-side capability groups are controls at different levels.

---

## Quota Exceeded

### E2002 — QuotaExceededError

```text
[E2002] Sandbox quota has been exceeded
  Suggestion: Destroy idle sandboxes or request a quota increase.
```

**Solution**:

```bash
# View running sandboxes
ebx list --status running

# Destroy unneeded sandboxes
ebx kill sbx-xxxx

# Batch destroy
ebx kill --all --yes
```

---

## Command Execution Timeout

### E3001 — CommandTimeoutError

```text
[E3001] Command execution timed out
  Suggestion: Increase the timeout parameter or check if the command is hanging.
```

**Solution**:

```python
# Increase timeout in SDK
result = await sandbox.commands.run("long-command", timeout=300)

# Increase timeout in CLI
ebx exec sbx-xxxx "long-command" --timeout 300
```

---

## Deployment Issues

### E7001 — Missing LLM Key

```text
[E7001] No LLM API key found for the qwen-code agent.
  Suggestion: Set BAILIAN_CODING_PLAN_API_KEY, DASHSCOPE_API_KEY, or OPENAI_API_KEY environment variable.
```

**Solution**: Set any LLM API Key:

```bash
export DASHSCOPE_API_KEY="your-key"
# Or
ebx config set llm_api_key your-key
```

### E7003 — Deploy Timeout

**Solution**: Increase the `max_wall_time` parameter or simplify the deployment task.

---

## File Operations

### E4001 — File Not Found

```python
# Check if the file exists first
exists = await sandbox.files.exists("/path/to/file")
if not exists:
    print("File does not exist")

# List directory contents
entries = await sandbox.files.list("/home/user")
```

### E4002 — Permission Denied

Check file permissions. The default user in the sandbox is `user`; you can specify the `user` parameter in commands.

---

## Installation Issues

### pip install Fails

```bash
# Ensure the correct package name
pip install easy-sandbox

# If dependency conflicts occur
pip install easy-sandbox --force-reinstall
```

### ebx Command Not Found

Confirm that Python's bin directory is in your PATH:

```bash
python -m easy_sandbox --version
# Or
pip show easy-sandbox | grep Location
```

---

## Next Steps

- [Authentication](authentication.md) — Authentication configuration
- [Configuration Reference](../reference/configuration.md) — All configuration options
- [Error Codes Reference](../reference/error-codes.md) — Complete error code list
