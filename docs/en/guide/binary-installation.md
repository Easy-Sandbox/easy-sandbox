# Binary Installation

`ebx` is also distributed as a **precompiled standalone binary** — a single
executable that bundles the Python runtime, the Easy Sandbox SDK, and all
core CLI dependencies. **No Python installation is required.**

Binaries are published for every release on
[GitHub Releases](https://github.com/Easy-Sandbox/easy-sandbox/releases):

| Platform | File |
|----------|------|
| Linux (x64) | `ebx-{version}-linux-x64` |
| macOS (Apple Silicon) | `ebx-{version}-darwin-arm64` |
| macOS (Intel) | `ebx-{version}-darwin-x64` |
| Windows (x64) | `ebx-{version}-windows-x64.exe` |

---

## Quick Install

### macOS / Linux (curl)

```bash
# Set the version you want to install
VERSION=0.1.0

# Detect the platform
OS=$(uname -s | tr '[:upper:]' '[:lower:]')   # darwin or linux
ARCH=$(uname -m); case "$ARCH" in
  x86_64) ARCH=x64 ;;
  arm64|aarch64) ARCH=arm64 ;;
esac

# Download, make executable, and place it on your PATH
curl -fsSL -o /usr/local/bin/ebx \
  "https://github.com/Easy-Sandbox/easy-sandbox/releases/download/v${VERSION}/ebx-${VERSION}-${OS}-${ARCH}"
chmod +x /usr/local/bin/ebx
```

> Requires write permission for `/usr/local/bin` (prefix with `sudo` if
> needed), or choose any other directory on your `PATH`.

### Windows (PowerShell)

```powershell
$VERSION = "0.1.0"
$asset = "ebx-$VERSION-windows-x64.exe"

# Download the release asset
Invoke-WebRequest `
  -Uri "https://github.com/Easy-Sandbox/easy-sandbox/releases/download/v$VERSION/$asset" `
  -OutFile $asset

# Move it to a directory on your PATH (create it first if needed)
$installDir = "$env:LOCALAPPDATA\Programs\ebx"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Move-Item $asset "$installDir\ebx.exe"
```

> If `$installDir` is not on your `PATH` yet, add it via
> *Settings → System → About → Advanced system settings → Environment
> Variables*, then reopen the terminal.

## Manual Download

1. Open the [GitHub Releases](https://github.com/Easy-Sandbox/easy-sandbox/releases) page.
2. Pick the release you want (usually the latest).
3. Download the asset matching your platform from the table above.
4. Make it executable (macOS/Linux only) and place it on your `PATH`:

```bash
chmod +x ./ebx-0.1.0-darwin-arm64
mkdir -p ~/.local/bin && mv ./ebx-0.1.0-darwin-arm64 ~/.local/bin/ebx
```

## Verify the SHA256 Checksum

Every release asset ships with a `*.sha256` checksum file. After
downloading, verify the binary's integrity:

```bash
# macOS
shasum -a 256 -c ebx-0.1.0-darwin-arm64.sha256

# Linux
sha256sum -c ebx-0.1.0-linux-x64.sha256
```

Windows (`certutil`):

```powershell
# Compare the printed digest against the content of the .sha256 file
certutil -hashfile ebx-0.1.0-windows-x64.exe SHA256

# Or with PowerShell:
Get-FileHash ebx-0.1.0-windows-x64.exe -Algorithm SHA256
```

## Verify the Installation

```bash
ebx --version
# ebx, version 0.1.0
```

> **macOS Gatekeeper note:** the binaries are not code-signed, so the first
> launch may be blocked by Gatekeeper. If that happens, remove the
> quarantine attribute before running:
>
> ```bash
> xattr -d com.apple.quarantine /usr/local/bin/ebx
> ```
>
> Alternatively, right-click the binary in Finder and choose **Open** once.

## Binary vs. pip install

| | Standalone binary | `pip install "easy-sandbox[cli]"` |
|---|---|---|
| Python required | No | Yes (3.9+) |
| Install method | Download one file | pip / any Python package manager |
| Startup time | Slightly slower (one-file self-extraction) | Faster |
| Update | Re-download from Releases | `pip install -U easy-sandbox` |
| Python SDK (`import easy_sandbox`) | Not included | Included |
| Optional extensions (`alicloud`, `mcp`, ...) | Not included | Installable via extras |

## Notes & Limitations

- The binary bundles the full CLI **plus** the standard SDK runtime, but
  **does not include the optional Alibaba Cloud SDK extension** (`alicloud`)
  or other optional extras (`mcp`, `session`, `fast`). If you need those,
  install via pip instead:

  ```bash
  pip install "easy-sandbox[all]"
  ```

- The binary only provides the `ebx` CLI. To use the Python SDK
  (`from easy_sandbox.api.sandbox import Sandbox`), install the package
  with pip.

---

## Next Steps

- [Getting Started](getting-started.md) — Install, configure, first sandbox
- [CLI Tutorial](cli-tutorial.md) — Full CLI lifecycle operations
- [Authentication](authentication.md) — API Key / AK-SK configuration
- [Troubleshooting](troubleshooting.md) — Common issues and solutions
