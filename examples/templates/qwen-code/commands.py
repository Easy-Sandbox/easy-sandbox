"""qwen-code — 通义千问编码 Agent 沙箱命令。"""
from __future__ import annotations

from serverless_sandbox.server import (
    CapabilityGroup,
    CommandRegistry,
    SandboxServer,
    default_table,
)

# ---------------------------------------------------------------------------
# Route table — enable capability groups
# ---------------------------------------------------------------------------

table = default_table()
table.enable_group(CapabilityGroup.FILE_OPS)   # upload/download + file operations
table.enable_group(CapabilityGroup.PROCESS)    # shell + process management

# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

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
            "--max-turns", str(max_turns),
        ],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


registry.freeze()

server = SandboxServer(registry=registry)
server.serve(port=9000)
