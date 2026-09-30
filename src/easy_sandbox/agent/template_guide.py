"""Reference material handed to the coding agent when it generates a template.

A template that only ships a ``Dockerfile`` cannot be *used* once deployed:
callers reach a sandbox over HTTP(S), and something inside the container has
to answer.  In Easy Sandbox that something is the container-side
``easy_sandbox.server`` (``SandboxServer``), started from the template's
``commands.py``.  The guide below condenses the public server documentation
(``docs/en/design/server-api.md``) and the reference templates in
``awesome-templates`` into the prompt, so the agent writes the server entry
point instead of guessing the SDK.

Everything stated here is taken from the implementation under
``src/easy_sandbox/server/``; ``tests/test_agent/test_template_guide.py``
keeps the guide and the SDK from drifting apart.
"""

# ruff: noqa: E501  (prompt text: lines are kept whole so the agent reads them as written)
from __future__ import annotations

__all__ = [
    "REQUIRED_TEMPLATE_FILES",
    "build_template_guide",
    "SERVER_ENTRYPOINT",
    "SERVER_PORT",
    "TEMPLATE_GUIDE",
    "REFERENCE_COMMANDS_PY",
]

#: Files every generated template must contain.
REQUIRED_TEMPLATE_FILES: tuple[str, ...] = (
    "Dockerfile",
    "commands.py",
    "template.yaml",
)

#: Container entry point the Dockerfile must start.
SERVER_ENTRYPOINT = "commands.py"

#: Port the SandboxServer listens on (``SandboxServer.serve`` default).
SERVER_PORT = 9000

#: Minimal, complete ``commands.py`` shown to the agent as the shape to follow.
REFERENCE_COMMANDS_PY = '''\
"""<template-name> — sandbox command server."""
from __future__ import annotations

from easy_sandbox.server import (
    CapabilityGroup,
    CommandRegistry,
    SandboxServer,
    ServerResponse,
    default_table,
)

# 1. Route table: switch built-in capability groups on/off.
table = default_table()
table.enable_group(CapabilityGroup.FILE_OPS)   # upload / download / file ops
table.enable_group(CapabilityGroup.PROCESS)    # shell + background processes
table.enable_group(CapabilityGroup.SYSTEM)     # system info + port detection

# 2. Command registry: named commands, callable via POST /commands/<name>.
registry = CommandRegistry()


@registry.command("hello", description="Say hello.")
def hello(name: str = "World") -> str:
    return f"Hello, {name}!"


# 3. Custom HTTP route (optional): the business API of this template.
@table.route("GET", "/hello/{name}", group=CapabilityGroup.COMMANDS)
def hello_route(request: object) -> ServerResponse:
    name = getattr(request, "path_params", {}).get("name", "World")
    return ServerResponse.ok({"greeting": f"Hello, {name}!"})


# 4. Freeze and serve (blocks; this is the container's main process).
registry.freeze()
server = SandboxServer(registry=registry)
server.serve(port=9000)
'''

_FILES_CREATE = """\
### 2. 模板必须包含的文件
- `Dockerfile`
- `commands.py`：服务入口，见下文
- `template.yaml`
- `README.md`：模板是什么、需要哪些环境变量、调用示例（curl）
需求确实需要时，可再添加业务代码（如 `app.py`、`server.js`、`requirements.txt`），
放在当前目录，并在 Dockerfile 里 COPY 进镜像。
"""

_FILES_ADOPT = """\
### 2. 模板必须包含的文件（适配已有项目）
用户已经有一个可运行的项目。你只能在当前目录写下面三个文件，其余文件一律不要创建、修改或删除：
- `Dockerfile`
- `commands.py`：服务入口，见下文
- `template.yaml`
`.dockerignore` 由 ebx 自动生成，你不要创建或修改它。
不要创建 `README.md`，也不要新增业务代码或依赖清单：需要的依赖直接在 Dockerfile 里安装。
项目自己的代码按原样保留，用**明确的路径**逐项 COPY（例如 `COPY app/ ./app/`），
不要用 `COPY . .`。如果项目里已经有 Dockerfile，请在它的基础上修改（保留它的基础镜像与依赖安装步骤），
而不是重写。
"""


def build_template_guide(mode: str = "create") -> str:
    """Return the template specification handed to the coding agent.

    *mode* is ``"create"`` (a template is written from a description: it
    ships a ``README.md`` and may add business code) or ``"adopt"`` (an
    existing project is adapted: only the four reserved files are written and
    the project's own code is never touched).
    """
    if mode not in ("create", "adopt"):
        raise ValueError(f"Unknown template guide mode {mode!r}; expected 'create' or 'adopt'.")
    files_section = (_FILES_ADOPT if mode == "adopt" else _FILES_CREATE).rstrip("\n") + "\n"
    return f"""\
## Easy Sandbox 模板规范（必须遵守）

### 1. 沙箱怎么被使用
沙箱部署后，调用方只能通过 HTTP(S) 访问它：`https://<端口>-<sandbox_id>.<domain>`
（SDK 里是 `sandbox.network.get_url(port)`）。所以镜像里**必须有一个常驻的 HTTP 服务**，
仅有 Dockerfile 的模板部署后无法被使用。Easy Sandbox 的标准做法是：`commands.py`
用 `easy_sandbox.server`（纯标准库、零第三方依赖的 HTTP 服务）在 **{SERVER_PORT}** 端口对外服务，
容器主进程就是 `python3 commands.py`。

{files_section}
### 3. Dockerfile 规则
- 以 FROM 开头，选官方基础镜像；镜像里必须有 python3 和 pip（基础镜像不是 Python 时
  用 apt-get 安装 `python3 python3-pip`，pip 需加 `--break-system-packages`）。
- 安装 easy-sandbox SDK，固定使用下面这段（`ebx` 部署时会把 SDK wheel 注入构建上下文，
  没有 wheel 时回退到 PyPI）：
```
COPY *.whl /tmp/
RUN if ls /tmp/*.whl 1>/dev/null 2>&1; then \\
        pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl; \\
    else \\
        pip install --no-cache-dir easy-sandbox; \\
    fi
```
- `WORKDIR /app`，`COPY commands.py .`（以及业务代码），`EXPOSE {SERVER_PORT}`（业务端口一并 EXPOSE），
  最后 `CMD ["python3", "commands.py"]`。
- 不要在镜像里写入任何密钥；需要的密钥在 template.yaml 的 `env` 里只列名字（空值或非敏感默认值）。

### 4. commands.py 规则（`easy_sandbox.server` API）
```python
from easy_sandbox.server import (
    CapabilityGroup, CommandRegistry, SandboxServer, ServerResponse, SSEResponse, default_table,
)
```
- `table = default_table()`：路由表（全局单例）。`table.enable_group(CapabilityGroup.X)` 开启能力组。
  能力组：CORE（常开）、COMMANDS（默认开）、FILE_OPS（文件上传/下载/列表/搜索/打包）、
  PROCESS（`/shell`、`/shell/stream`、后台进程）、TERMINAL（PTY，WebSocket 在 9001）、
  SYSTEM（系统信息、`/env`、`/ports`）、DEV_TOOLS（`/code/run`、git，**默认关闭**）、
  BROWSER（Playwright 浏览器自动化，**默认关闭**，需镜像里装好 playwright 与浏览器）。
  只开启需求用得到的组，攻击面越小越好。
- `registry = CommandRegistry()`；`@registry.command("名字", description="…")` 注册命令，
  通过 `POST /commands/<名字>` 调用，body 是 JSON 参数，返回 `{{"result": <返回值>}}`。
  参数类型从函数签名推断（int→integer，float→float，bool→boolean，其余 string；无默认值即必填）。
  返回值必须可 JSON 序列化；出错直接 `raise`（服务返回 500）。`hidden=True` 的命令可调用但不在
  `GET /commands` 里列出。
- 自定义 HTTP 路由：`@table.route("GET"|"POST"|"DELETE", "/path/{{param}}", group=CapabilityGroup.COMMANDS)`，
  处理函数接收 `request`（属性：`method`、`path`、`query`（值是列表）、`headers`、`body`（已解析的 JSON
  dict 或 None）、`path_params`），返回 `ServerResponse.ok({{...}})` 或
  `ServerResponse.error(status, message)`。只实现了 GET / POST / DELETE。
  `auth_required=False` 表示免鉴权；`streaming=True` 时返回 `SSEResponse(event_iterator=…)`，
  迭代器逐个产出 `"event: <名>\\ndata: <json>\\n\\n"` 字符串。
- 内置接口总是存在（无需自己实现）：`GET /health`、`GET /capabilities`、`GET /commands`、
  `POST /commands/<名字>`，以及已开启能力组对应的文件、shell、系统接口。
- 鉴权：设置了环境变量 `EBX_SERVER_TOKEN` 时，请求必须带 `X-Access-Token`（`/health` 与
  `/capabilities` 免鉴权）。不要在代码里写死 token。
- 需求是一个 Web/API 服务（例如 Express、FastAPI、Flask）时：业务服务由 `commands.py`
  在 `serve()` 之前用 `subprocess.Popen([...])` 作为子进程拉起并监听自己的端口（该端口写进
  template.yaml 的 `ports` 与 Dockerfile 的 EXPOSE），或者干脆做成 `@registry.command`/`@table.route`。
  不要让业务服务替代 SandboxServer——{SERVER_PORT} 端口必须始终由 SandboxServer 提供。
- 文件末尾固定：`registry.freeze()`，然后 `SandboxServer(registry=registry).serve(port={SERVER_PORT})`。
  `serve()` 会阻塞，所以它必须是 `commands.py` 的最后一条语句。
- 只使用上面列出的 API，不要臆造 SDK 里不存在的类、函数或接口。

### 5. template.yaml 规则
必填：`name`（使用给定的模板名）、`version: "1.0.0"`、`description`（一句话中文，不超过 50 字）、
`capabilities`、`ports`、`resources`。
- `capabilities` 取自 `shell | files | code | terminal | ports`，要与 commands.py 开启的能力组一致：
  `files`↔FILE_OPS，`shell`↔PROCESS，`code`↔DEV_TOOLS，`terminal`↔TERMINAL，
  `ports`↔SYSTEM（端口检测）与对外端口。`terminal` 和 `ports` 必须显式声明才会生效。
  参考示例开启了 FILE_OPS/PROCESS/SYSTEM，对应 `shell, files, ports`。
- `ports`：至少包含 {SERVER_PORT}，业务端口一并列出。
- `resources.cpu`：1-8 的整数；`resources.memory`：512-16384 的整数（MB）。
- `env`：环境变量的名字与非敏感默认值（如 `LANG: C.UTF-8`）；密钥类只列名字，值留空。
- `custom_commands`（可选，供 `ebx run <sandbox_id> <命令>` 使用）：
  `<名字>: {{cmd: "python3 {{file}}", description, cwd: "/app", timeout: 60, args: [{{name, default, required, description, type}}]}}`，
  `cmd` 里的 `{{占位符}}` 由 `args` 填充，`type` 取 string | integer | float | boolean。
- `tags`、`author` 可省略。

### 6. 完整参考：commands.py 的最小形态
```python
{REFERENCE_COMMANDS_PY}```
"""


#: Guide used by ``ebx create "<description>"`` (README + optional business code).
TEMPLATE_GUIDE = build_template_guide("create")
