"""claude-code 命名命令 — Anthropic Claude Code Agent。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

registry = CommandRegistry()


@registry.command("claude", description="Run Claude Code agent.")
def claude(prompt: str, model: str = "sonnet") -> str:
    """Run Claude Code agent."""
    import subprocess

    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "--model", model,
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
