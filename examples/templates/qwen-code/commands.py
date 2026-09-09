"""qwen-code 命名命令 — 通义千问编码 Agent。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

registry = CommandRegistry()


@registry.command("qwen", description="Run Qwen Code agent.")
def qwen(prompt: str, max_turns: int = 50) -> str:
    """Run Qwen Code agent."""
    import subprocess

    result = subprocess.run(
        [
            "qwen", "-p", prompt,
            "--yolo",
            "--output-format", "json",
        ],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


enable_builtin("upload")
enable_builtin("download")

server = SandboxServer(registry=registry)
server.serve(port=9000)
