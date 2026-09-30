# 二进制安装

`ebx` 同时以**预编译独立二进制**的形式发布 —— 单个可执行文件内嵌了
Python 运行时、Easy Sandbox SDK 以及全部核心 CLI 依赖。**无需安装
Python 环境。**

二进制文件随每个版本发布在
[GitHub Releases](https://github.com/Easy-Sandbox/easy-sandbox/releases)：

| 平台 | 文件 |
|------|------|
| Linux (x64) | `ebx-{version}-linux-x64` |
| macOS (Apple Silicon) | `ebx-{version}-darwin-arm64` |
| macOS (Intel) | `ebx-{version}-darwin-x64` |
| Windows (x64) | `ebx-{version}-windows-x64.exe` |

---

## 快速安装

### macOS / Linux（curl）

```bash
# 设置要安装的版本
VERSION=0.1.0

# 自动检测平台
OS=$(uname -s | tr '[:upper:]' '[:lower:]')   # darwin 或 linux
ARCH=$(uname -m); case "$ARCH" in
  x86_64) ARCH=x64 ;;
  arm64|aarch64) ARCH=arm64 ;;
esac

# 下载、添加可执行权限并放到 PATH 中
curl -fsSL -o /usr/local/bin/ebx \
  "https://github.com/Easy-Sandbox/easy-sandbox/releases/download/v${VERSION}/ebx-${VERSION}-${OS}-${ARCH}"
chmod +x /usr/local/bin/ebx
```

> 需要对 `/usr/local/bin` 的写权限（必要时加 `sudo`），也可以选择
> `PATH` 中的任意其他目录。

### Windows（PowerShell）

```powershell
$VERSION = "0.1.0"
$asset = "ebx-$VERSION-windows-x64.exe"

# 下载 Release 资产
Invoke-WebRequest `
  -Uri "https://github.com/Easy-Sandbox/easy-sandbox/releases/download/v$VERSION/$asset" `
  -OutFile $asset

# 移动到 PATH 中的目录（不存在则先创建）
$installDir = "$env:LOCALAPPDATA\Programs\ebx"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Move-Item $asset "$installDir\ebx.exe"
```

> 如果 `$installDir` 尚不在 `PATH` 中，请通过
> *设置 → 系统 → 关于 → 高级系统设置 → 环境变量* 添加，
> 然后重新打开终端。

## 手动下载

1. 打开 [GitHub Releases](https://github.com/Easy-Sandbox/easy-sandbox/releases) 页面。
2. 选择目标版本（通常是最新的）。
3. 按上表选择匹配当前平台的资产下载。
4. 添加可执行权限（仅 macOS/Linux）并放到 `PATH` 中：

```bash
chmod +x ./ebx-0.1.0-darwin-arm64
mkdir -p ~/.local/bin && mv ./ebx-0.1.0-darwin-arm64 ~/.local/bin/ebx
```

## 校验 SHA256

每个 Release 资产都附带 `*.sha256` 校验文件。下载后请校验二进制文件的完整性：

```bash
# macOS
shasum -a 256 -c ebx-0.1.0-darwin-arm64.sha256

# Linux
sha256sum -c ebx-0.1.0-linux-x64.sha256
```

Windows（`certutil`）：

```powershell
# 将打印出的摘要与 .sha256 文件中的内容进行比对
certutil -hashfile ebx-0.1.0-windows-x64.exe SHA256

# 或使用 PowerShell：
Get-FileHash ebx-0.1.0-windows-x64.exe -Algorithm SHA256
```

## 验证安装

```bash
ebx --version
# ebx, version 0.1.0
```

> **macOS Gatekeeper 提示：** 二进制文件未做代码签名，首次运行可能被
> Gatekeeper 拦截。如遇到该情况，先移除隔离属性再运行：
>
> ```bash
> xattr -d com.apple.quarantine /usr/local/bin/ebx
> ```
>
> 也可以在 Finder 中右键点击二进制文件，选择**打开**一次即可放行。

## 二进制与 pip install 对比

| | 独立二进制 | `pip install "easy-sandbox[cli]"` |
|---|---|---|
| 是否需要 Python | 否 | 需要（3.10+） |
| 安装方式 | 下载单个文件 | pip 或任意 Python 包管理器 |
| 启动速度 | 稍慢（单文件需自解压） | 更快 |
| 更新方式 | 从 Releases 重新下载 | `pip install -U easy-sandbox` |
| Python SDK（`import easy_sandbox`） | 不包含 | 包含 |
| 可选扩展（`alicloud`、`mcp` 等） | 不包含 | 可通过 extras 安装 |

## 说明与限制

- 二进制文件捆绑了完整的 CLI **以及**标准 SDK 运行时，但**不包含可选的
  阿里云 SDK 扩展**（`alicloud`）及其他可选 extras（`mcp`、`session`、
  `fast`）。如需这些功能，请改用 pip 安装：

  ```bash
  pip install "easy-sandbox[all]"
  ```

- 二进制仅提供 `ebx` CLI。如需使用 Python SDK
  （`from easy_sandbox.api.sandbox import Sandbox`），请通过 pip 安装本包。

---

## 后续步骤

- [快速开始](getting-started.md) — 安装、配置与第一个沙箱
- [CLI 教程](cli-tutorial.md) — 完整的 CLI 生命周期操作
- [身份认证](authentication.md) — API Key / AK-SK 配置
- [故障排查](troubleshooting.md) — 常见问题与解决方案
