"""codex 命名命令 — OpenAI Codex CLI Agent。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

registry = CommandRegistry()


@registry.command("codex", description="Run Codex agent.")
def codex(prompt: str, model: str = "codex-mini") -> str:
    """Run Codex agent."""
    import subprocess

    result = subprocess.run(
        [
            "codex", "-p", prompt,
            "--model", model,
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
