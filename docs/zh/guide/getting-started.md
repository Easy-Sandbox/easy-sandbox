# 快速入门

本教程将带你完成从安装到销毁的完整沙箱生命周期。

---

## 前置条件

- Python 3.10 或更高版本
- 一个有效的 API Key（从 Easy Sandbox 平台获取）
- 网络可访问阿里云杭州区域（默认 `cn-hangzhou`）

## 1. 安装

```bash
# 安装 SDK（含 CLI 工具）
pip install easy-sandbox

# 安装含 CLI 额外依赖（推荐）
pip install "easy-sandbox[cli]"

# 验证安装
ebx --version
```

### 独立二进制（无需 Python）

如果不想安装 Python 环境，也可以使用预编译的独立二进制版本（支持 Linux、macOS 和 Windows）：

```bash
# 示例：在 macOS（Apple Silicon）上安装 v0.2.0
curl -fsSL -o /usr/local/bin/ebx \
  "https://github.com/Easy-Sandbox/easy-sandbox/releases/download/v0.2.0/ebx-0.2.0-darwin-arm64"
chmod +x /usr/local/bin/ebx
```

其他平台的安装命令、校验和验证以及与 pip 安装的对比，请参阅[二进制安装](binary-installation.md)。

## 2. 配置 API Key

有三种方式配置认证凭证。真正生效时按下面的优先级（从高到低）。完整的凭证表见 [配置参考 — 凭证解析](../reference/configuration.md#凭证解析)。

### 方式一：代码参数（只影响这一次调用）

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = await Sandbox.create(api_key="your-api-key-here")
```

### 方式二：环境变量（推荐用于 CI/CD）

```bash
export E2B_API_KEY="your-api-key-here"
```

### 方式三：`ebx config set`（推荐用于本地开发）

环境变量和项目 `.env` 都没写这个键时，才用这里保存的值。

```bash
ebx config set sandbox_api_key your-api-key
# 写入到 ~/.ebx/.env（权限 600）
```

验证配置状态：

```bash
ebx config get sandbox_api_key
```

## 3. 创建第一个 Sandbox

### 使用 SDK（异步）

```python
import asyncio
from easy_sandbox.api.sandbox import Sandbox

async def main():
    # 创建沙箱（默认模板: base，超时: 300 秒）
    sandbox = await Sandbox.create(template="base", timeout=300)
    print(f"Sandbox 已创建: {sandbox.id}")
    print(f"状态: {sandbox.status.value}")

asyncio.run(main())
```

### 使用 SDK（同步）

```python
from easy_sandbox.api.sandbox import Sandbox

sandbox = Sandbox.create_sync(template="base")
print(f"Sandbox ID: {sandbox.id}")
```

### 使用 CLI

```bash
ebx create --template base
```

## 4. 执行代码

### SDK

```python
result = await sandbox.run_code("print('Hello, Easy Sandbox!')")
print(result.text)     # "Hello, Easy Sandbox!"
print(result.stdout)   # "Hello, Easy Sandbox!\n"
print(result.exit_code)  # 0
```

### CLI

```bash
ebx exec <sandbox-id> "echo 'Hello from sandbox'"
```

## 5. 运行 Shell 命令

### SDK

```python
result = await sandbox.commands.run("ls -la /home/user")
print(result.stdout)
print(f"退出码: {result.exit_code}")
```

### CLI

```bash
ebx exec <sandbox-id> "pip install requests && python -c 'import requests; print(requests.__version__)'"
```

## 6. 文件操作

### 上传文件到沙箱

```python
# 写入文本文件
await sandbox.files.write("/home/user/hello.py", "print('hello world')")

# 上传本地文件
await sandbox.files.upload("./local_script.py", "/home/user/script.py")
```

### 从沙箱下载文件

```python
# 读取文本
content = await sandbox.files.read("/home/user/hello.py")
print(content)

# 下载到本地
await sandbox.files.download("/home/user/output.csv", "./output.csv")
```

### CLI 上传/下载

```bash
# 上传
ebx upload <sandbox-id> ./data.csv /home/user/data.csv

# 下载
ebx download <sandbox-id> /home/user/result.csv ./result.csv
```

## 7. 列出目录内容

```python
files = await sandbox.files.list("/home/user")
for f in files:
    print(f"{f.name} ({f.type.value}, {f.size} bytes)")
```

## 8. 销毁 Sandbox

### SDK

```python
await sandbox.kill()
```

### 使用 Context Manager（推荐）

```python
async with await Sandbox.create(template="base") as sandbox:
    result = await sandbox.run_code("print('auto cleanup')")
    print(result.text)
# 退出 with 块后自动销毁
```

### CLI

```bash
ebx kill <sandbox-id>

# 销毁所有运行中的沙箱
ebx kill --all --yes
```

## 9. 完整示例

```python
import asyncio
from easy_sandbox.api.sandbox import Sandbox

async def main():
    async with await Sandbox.create(template="base") as sandbox:
        # 安装依赖
        await sandbox.commands.run("pip install requests")

        # 执行代码
        result = await sandbox.run_code("""
import requests
resp = requests.get('https://httpbin.org/get')
print(resp.status_code)
""")
        print(f"状态码: {result.text}")

        # 写入和读取文件
        await sandbox.files.write("/home/user/note.txt", "Hello!")
        content = await sandbox.files.read("/home/user/note.txt")
        print(f"文件内容: {content}")

asyncio.run(main())
```

---

## 下一步

- [认证详解](authentication.md) — 多种认证方式与配置优先级
- [SDK 使用指南](sdk-usage.md) — 完整的 API 使用方法
- [CLI 教程](cli-tutorial.md) — 命令行完整生命周期操作
- [使用模板](using-templates.md) — 按模板创建沙箱
- [错误码参考](../reference/error-codes.md) — 错误排查
- [故障排查](troubleshooting.md) — 常见问题与解决方案
