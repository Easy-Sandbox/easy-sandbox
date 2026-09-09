"""qoder 命名命令 — Qoder AI 编程助手。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

registry = CommandRegistry()


@registry.command("qoder_run", description="Run a Python script in the Qoder environment.")
def qoder_run(script: str = "main.py") -> str:
    """Run a Python script in the Qoder environment."""
    import subprocess

    result = subprocess.run(
        ["python", script],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


enable_builtin("upload")
enable_builtin("download")

server = SandboxServer(registry=registry)
server.serve(port=9000)
