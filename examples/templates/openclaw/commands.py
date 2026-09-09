"""openclaw 命名命令 — OpenClaw AI Agent 网关。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

registry = CommandRegistry()


@registry.command("gateway", description="Start or manage the OpenClaw gateway server.")
def gateway(action: str = "start") -> str:
    """Start or manage the OpenClaw gateway server."""
    import subprocess

    result = subprocess.run(
        ["openclaw", action],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


enable_builtin("upload")
enable_builtin("download")

server = SandboxServer(registry=registry)
server.serve(port=9000)
