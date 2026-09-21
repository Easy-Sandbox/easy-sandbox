"""claude-code — Anthropic Claude Code Agent 沙箱命令。"""
from __future__ import annotations

from easy_sandbox.server import (
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
table.enable_group(CapabilityGroup.TERMINAL)   # PTY — declared in template.yaml

# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

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


registry.freeze()

server = SandboxServer(registry=registry)
server.serve(port=9000)
