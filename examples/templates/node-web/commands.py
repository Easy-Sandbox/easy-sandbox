"""node-web 命名命令 — Node.js Web 服务。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

registry = CommandRegistry()


@registry.command("serve", description="Start Node.js app.")
def serve(entry: str = "index.js") -> str:
    """Start Node.js app."""
    import subprocess

    result = subprocess.run(
        ["node", entry],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


enable_builtin("upload")
enable_builtin("download")

server = SandboxServer(registry=registry)
server.serve(port=9000)
