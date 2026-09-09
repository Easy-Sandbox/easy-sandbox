"""python-hello 命名命令 — 端到端示例。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

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


enable_builtin("upload")
enable_builtin("download")

server = SandboxServer(registry=registry)
server.serve(port=9000)
