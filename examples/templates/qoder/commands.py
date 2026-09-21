"""qoder — Qoder AI 编程助手沙箱命令。"""
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


registry.freeze()

server = SandboxServer(registry=registry)
server.serve(port=9000)
