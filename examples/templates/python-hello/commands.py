"""python-hello — 教学标杆模板，展示 Server API 全部新特性。

演示内容:
- CapabilityGroup 能力组开关（替代旧版 enable_builtin）
- RouteTable.route() 装饰器注册自定义 HTTP 路由
- hidden=True 隐藏命令（不在 GET /commands 中列出）
- registry.freeze() 冻结命令注册表
"""
from __future__ import annotations

from serverless_sandbox.server import (
    CapabilityGroup,
    CommandRegistry,
    SandboxServer,
    ServerResponse,
    default_table,
)

# ---------------------------------------------------------------------------
# Route table — enable capability groups
# ---------------------------------------------------------------------------

table = default_table()
table.enable_group(CapabilityGroup.FILE_OPS)   # upload/download + file operations
table.enable_group(CapabilityGroup.PROCESS)    # shell + process management
table.enable_group(CapabilityGroup.SYSTEM)     # system info + port detection

# ---------------------------------------------------------------------------
# Command registry — custom commands
# ---------------------------------------------------------------------------

registry = CommandRegistry()


@registry.command("hello", description="Say hello.")
def hello(name: str = "World") -> str:
    """Say hello."""
    return f"Hello, {name}!"


@registry.command("run_script", description="Execute Python code and return stdout.")
def run_script(code: str) -> str:
    """Execute Python code and return stdout."""
    import subprocess

    result = subprocess.run(
        ["python3", "-c", code], capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


@registry.command(hidden=True)
def _debug_info() -> dict:
    """Internal debug command — not listed in /commands."""
    import platform

    return {"python": platform.python_version(), "system": platform.system()}


# ---------------------------------------------------------------------------
# Custom HTTP route via RouteTable.route() decorator
# ---------------------------------------------------------------------------


@table.route("GET", "/hello/{name}", group=CapabilityGroup.COMMANDS)
def hello_route(request: object) -> ServerResponse:
    """Custom route: GET /hello/{name} returns a greeting as JSON."""
    name = getattr(request, "path_params", {}).get("name", "World")
    return ServerResponse.ok({"greeting": f"Hello, {name}!"})


# ---------------------------------------------------------------------------
# Freeze & serve
# ---------------------------------------------------------------------------

registry.freeze()

server = SandboxServer(registry=registry)
server.serve(port=9000)
