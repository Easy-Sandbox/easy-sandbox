"""openclaw — OpenClaw AI Agent 网关沙箱命令。"""
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


registry.freeze()

server = SandboxServer(registry=registry)
server.serve(port=9000)
