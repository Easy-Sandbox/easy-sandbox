# API 参考

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

本文档列出 Easy Sandbox Python SDK 的全部公开 API 签名、参数、返回值和异常。

---

## Sandbox 类

```python
from easy_sandbox.api.sandbox import Sandbox
```

### 类方法

#### `Sandbox.create()`

```python
@classmethod
async def create(
    cls,
    template: str = "base",
    *,
    timeout: int = 300,
    metadata: dict[str, str] | None = None,
    envs: dict[str, str] | None = None,
    cpu: int | None = None,
    memory: int | None = None,
    disk: int | None = None,
    gpu: str | None = None,
    description: str | None = None,
    secure: bool = True,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> Sandbox
```

创建新沙箱。当提供 `description` 且 `template` 保持默认值 `"base"` 时，SDK 通过 LLM 推断最佳模板和资源配置。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `template` | `str` | `"base"` | 沙箱模板名称 |
| `timeout` | `int` | `300` | 超时秒数（1~86400） |
| `metadata` | `dict` | `None` | 任意元数据键值对 |
| `envs` | `dict` | `None` | 注入的环境变量 |
| `cpu` | `int` | `None` | CPU 核数 |
| `memory` | `int` | `None` | 内存 MB |
| `disk` | `int` | `None` | 磁盘 MB |
| `gpu` | `str` | `None` | GPU 规格（如 `"A10"`） |
| `description` | `str` | `None` | 自然语言描述（触发推断） |
| `secure` | `bool` | `True` | 安全模式（端口访问需 token） |
| `api_key` | `str` | `None` | API Key 覆盖 |
| `api_url` | `str` | `None` | 平台 API URL 覆盖 |
| `domain` | `str` | `None` | 域名覆盖 |
| `access_key_id` | `str` | `None` | 阿里云 AK |
| `access_key_secret` | `str` | `None` | 阿里云 SK |

**返回**：`Sandbox` 实例

**同步版**：`Sandbox.create_sync(...)`

#### `Sandbox.connect()`

```python
@classmethod
async def connect(
    cls,
    sandbox_id: str,
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> Sandbox
```

连接到已有沙箱。

**返回**：`Sandbox` 实例

**同步版**：`Sandbox.connect_sync(...)`

#### `Sandbox.list()`

```python
@classmethod
async def list(
    cls,
    *,
    status: SandboxStatus | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: str | None = None,
    api_url: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> list[SandboxInfo]
```

列出沙箱（类方法，不需要实例）。

**返回**：`list[SandboxInfo]`

**同步版**：`Sandbox.list_sync(...)`

#### `Sandbox.kill_by_id()`

```python
@classmethod
async def kill_by_id(
    cls,
    sandbox_id: str,
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> None
```

按 ID 销毁沙箱（类方法，不需要先连接）。

**同步版**：`Sandbox.kill_by_id_sync(...)`

#### `Sandbox.deploy()`

```python
@classmethod
async def deploy(
    cls,
    project_path: str,
    description: str,
    *,
    max_wall_time: str = "10m",
    max_tool_calls: int = 100,
    llm_api_key: str | None = None,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
    timeout: int = 900,
    envs: dict[str, str] | None = None,
    cpu: int | None = None,
    memory: int | None = None,
    on_progress: Callable[[str], None] | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
    domain: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> Sandbox
```

使用 qwen-code agent 自动部署项目。创建 `qwen-code` 模板沙箱，上传项目并自动分析、安装依赖、构建和启动服务。

**返回**：`Sandbox` 实例（仍在运行），`_deploy_result` 属性包含部署结果。

**同步版**：`Sandbox.deploy_sync(...)`

### 实例方法

| 方法 | 签名 | 说明 | 同步版 |
|------|------|------|--------|
| `kill()` | `async def kill() -> None` | 销毁沙箱并释放资源 | `kill_sync()` |
| `set_timeout()` | `async def set_timeout(timeout: int) -> None` | 更新超时时间 | `set_timeout_sync()` |
| `is_running()` | `async def is_running() -> bool` | 检查运行状态（发起 API 调用） | `is_running_sync()` |
| `pause()` | `async def pause() -> None` | 暂停沙箱 | `pause_sync()` |
| `resume()` | `async def resume() -> None` | 恢复暂停的沙箱 | `resume_sync()` |
| `refresh_info()` | `async def refresh_info() -> SandboxInfo` | 刷新沙箱信息 | `refresh_info_sync()` |

#### `run_code()`

```python
async def run_code(
    self,
    code: str,
    *,
    language: str = "python",
    timeout: int = 30,
    envs: dict[str, str] | None = None,
    on_stdout: Callable[[str], None] | None = None,
    on_stderr: Callable[[str], None] | None = None,
    on_result: Callable[..., None] | None = None,
) -> CodeResult
```

通过 Code Interpreter 执行代码。需要 `code` 能力。

**返回**：`CodeResult`（含 `text`、`stdout`、`stderr`、`exit_code`、`execution_time`、`output_files`）

**异常**：`CapabilityNotSupportedError`（E3004）— 若 `code` 能力未启用

**同步版**：`run_code_sync()`

#### `get_terminal()`

```python
async def get_terminal(
    self,
    *,
    cols: int = 80,
    rows: int = 24,
    shell: str = "/bin/bash",
) -> TerminalSession
```

打开交互式 PTY 终端会话。需要 `terminal` 能力。

**返回**：`TerminalSession`（WebSocket 连接）

**异常**：`CapabilityNotSupportedError`（E3004）— 若 `terminal` 能力未启用

**同步版**：`get_terminal_sync()`

#### `list_commands()`

```python
def list_commands(self) -> list[dict[str, Any]]
```

返回模板定义的自定义命令目录。需要 `shell` 能力。

**返回**：列表，每项包含 `name`、`description`、`args`

#### `run()`

```python
async def run(self, name: str, **kwargs: str) -> ProcessResult
```

执行命名的自定义命令。查找模板的 `custom_commands` 定义，填充 `{placeholder}` 令牌，运行 shell 命令。

**异常**：`ValueError` — 命令不存在、缺少必需参数、未声明参数

#### `run_command()`

```python
async def run_command(
    self,
    name: str,
    *,
    server_port: int = 9000,
    **kwargs: Any,
) -> Any
```

调用沙箱内 HTTP server 上的命名命令（`POST {port_url}/commands/{name}`）。需要 `ports` 能力。

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 沙箱 ID |
| `status` | `SandboxStatus` | 当前状态（缓存值，调用 `refresh_info()` 更新） |
| `url` | `str` | envd URL |
| `info` | `SandboxInfo` | 完整沙箱信息 |
| `capabilities` | `frozenset[str]` | 有效能力集 |

### 子模块

| 属性 | 类型 | 说明 |
|------|------|------|
| `commands` | `CommandsModule` | Shell 命令执行 |
| `files` | `FilesModule` | 文件系统操作 |
| `network` | `NetworkModule` | 端口 URL 计算 |
| `code` | `CodeContextModule` | Code Interpreter 操作 |

### Context Manager

```python
async with await Sandbox.create() as sandbox:
    ...  # 退出时自动 kill()
```

---

## CommandsModule

```python
sandbox.commands  # CommandsModule 实例
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `run()` | `async def run(cmd, *, timeout=60, env=None, cwd="", user="", background=False) -> ProcessResult \| StreamReader` | 执行命令并等待。`background=True` 时返回 `StreamReader` |
| `stream()` | `async def stream(cmd, *, timeout=60, env=None, cwd="", user="") -> AsyncIterator[ProcessChunk]` | 流式输出命令结果 |
| `start()` | `async def start(cmd, *, timeout=60, env=None, cwd="", user="") -> StreamReader[ProcessChunk]` | 后台启动命令，返回 StreamReader |
| `list()` | `async def list() -> list[ProcessInfo]` | 列出运行中的进程 |
| `kill()` | `async def kill(pid: int) -> None` | 终止进程 |
| `send_input()` | `async def send_input(pid: int, data: str) -> None` | 向进程 stdin 发送数据 |
| `send_stdin()` | `async def send_stdin(pid: int, data: str) -> None` | （已弃用）同 `send_input()` |
| `send_signal()` | `async def send_signal(pid: int, signal: int = 15) -> None` | 向进程发送信号 |

所有方法均需 `shell` 能力。每个异步方法都有 `_sync` 后缀的同步版本（如 `run_sync()`）。

---

## FilesModule

```python
sandbox.files  # FilesModule 实例
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `read()` | `async def read(path, *, encoding="utf-8") -> str` | 读取文本文件 |
| `read_bytes()` | `async def read_bytes(path) -> bytes` | 读取二进制文件 |
| `write()` | `async def write(path, content: str \| bytes) -> None` | 写入文件 |
| `list()` | `async def list(path="/") -> list[FileInfo]` | 列出目录 |
| `remove()` | `async def remove(path) -> None` | 删除文件/目录 |
| `exists()` | `async def exists(path) -> bool` | 检查路径是否存在 |
| `make_dir()` | `async def make_dir(path) -> None` | 创建目录（含父目录） |
| `upload()` | `async def upload(local_path, remote_path) -> None` | 上传本地文件到沙箱 |
| `download()` | `async def download(remote_path, local_path) -> None` | 下载沙箱文件到本地 |
| `watch()` | `async def watch(path) -> StreamReader[WatchEvent]` | 监听目录变更 |
| `move()` | `async def move(source, destination) -> None` | 移动/重命名 |
| `rename()` | `async def rename(old_path, new_path) -> None` | （已弃用）同 `move()` |
| `get_info()` | `async def get_info(path) -> FileInfo` | 获取文件信息 |
| `upload_url()` | `async def upload_url(path) -> str` | 获取上传 URL（兼容用） |
| `download_url()` | `async def download_url(path) -> str` | 获取下载 URL（兼容用） |

所有方法均需 `files` 能力。每个异步方法都有 `_sync` 后缀的同步版本。

---

## NetworkModule

```python
sandbox.network  # NetworkModule 实例
```

所有方法均为本地计算，不涉及网络请求。均需 `ports` 能力。

| 方法 | 签名 | 说明 |
|------|------|------|
| `get_host()` | `def get_host(port: int) -> str` | 返回 `{port}-{sandbox_id}.{domain}` |
| `get_url()` | `def get_url(port: int) -> str` | 返回 `https://{port}-{sandbox_id}.{domain}` |
| `get_access_headers()` | `def get_access_headers() -> dict[str, str]` | 返回端口访问所需 HTTP 头 |

---

## CodeContextModule

```python
sandbox.code  # CodeContextModule 实例
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `run()` | `async def run(code, *, language="python", timeout=30, context_id=None, envs=None, on_stdout=None, on_stderr=None, on_result=None) -> CodeResult` | 执行代码 |
| `create_context()` | `async def create_context(*, language="python") -> dict` | 创建执行上下文 |
| `list_contexts()` | `async def list_contexts() -> list[dict]` | 列出所有上下文 |
| `restart_context()` | `async def restart_context(context_id) -> dict` | 重启上下文 |
| `remove_context()` | `async def remove_context(context_id) -> None` | 删除上下文 |

所有方法均需 `code` 能力。每个异步方法都有 `_sync` 后缀的同步版本。

---

## Image 类

```python
from easy_sandbox.api.image import Image
```

链式镜像构建器（Modal 风格）。

### 工厂方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `from_template()` | `@classmethod def from_template(template: str) -> Image` | 基于已有模板创建 |
| `from_image()` | `@classmethod def from_image(image: str) -> Image` | 基于 Docker 镜像创建 |

### 链式方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `pip_install()` | `def pip_install(*packages: str) -> Image` | 安装 pip 包 |
| `apt_install()` | `def apt_install(*packages: str) -> Image` | 安装系统包 |
| `copy_local()` | `def copy_local(src: str, dst: str) -> Image` | 复制本地文件 |
| `env()` | `def env(**kwargs: str) -> Image` | 设置环境变量 |
| `run_command()` | `def run_command(cmd: str) -> Image` | 构建时执行命令 |
| `workdir()` | `def workdir(path: str) -> Image` | 设置工作目录 |
| `expose()` | `def expose(*ports: int) -> Image` | 暴露端口 |
| `entrypoint()` | `def entrypoint(cmd: str) -> Image` | 设置入口命令 |

### 输出方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `to_dockerfile()` | `def to_dockerfile() -> str` | 生成 Dockerfile 文本 |
| `build()` | `async def build(*, alias=None, api_key=None, ..., timeout=600) -> TemplateInfo` | 构建为平台模板 |

---

## 数据模型

### SandboxStatus

```python
from easy_sandbox.models.sandbox import SandboxStatus

class SandboxStatus(str, Enum):
    CREATING = "creating"
    RUNNING  = "running"
    PAUSED   = "paused"
    STOPPING = "stopping"
    STOPPED  = "stopped"
    ERROR    = "error"
```

### SandboxInfo

| 字段 | 类型 | 说明 |
|------|------|------|
| `sandbox_id` | `str` | 沙箱 ID |
| `template` | `str` | 模板名称 |
| `status` | `SandboxStatus` | 当前状态 |
| `envd_url` | `str \| None` | envd 数据平面 URL |
| `envd_access_token` | `str \| None` | envd 认证令牌 |
| `metadata` | `dict` | 用户元数据 |
| `started_at` | `datetime \| None` | 创建时间 |

### CodeResult

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str` | stdout（去除尾部空白） |
| `stdout` | `str` | 原始 stdout |
| `stderr` | `str` | 原始 stderr |
| `exit_code` | `int` | 退出码 |
| `execution_time` | `float` | 执行耗时（秒） |
| `output_files` | `list` | 输出文件列表 |

### ProcessResult

| 字段 | 类型 | 说明 |
|------|------|------|
| `stdout` | `str` | 标准输出 |
| `stderr` | `str` | 标准错误 |
| `exit_code` | `int` | 退出码 |
| `execution_time` | `float` | 执行耗时（秒） |
| `success` | `bool` | `exit_code == 0`（属性） |

### ProcessChunk

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `ProcessChunkType` | `stdout` / `stderr` / `exit` |
| `data` | `str` | 数据内容 |
| `exit_code` | `int \| None` | 退出码（仅 `exit` 类型） |

### FileInfo

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 文件名 |
| `path` | `str` | 绝对路径 |
| `type` | `FileType` | `file` / `directory` |
| `size` | `int` | 文件大小（字节） |

---

## 异常层级

所有异常继承自 `SandboxError`，携带 `code`、`message`、`suggestion`、`docs_url` 属性。

详细错误码列表参见 [错误码参考](./error-codes.md)。
