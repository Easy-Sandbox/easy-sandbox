"""deepseek-harness — DeepSeek Agent Runtime 沙箱命令。"""
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

# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

registry = CommandRegistry()


@registry.command("deepseek", description="Run DeepSeek agent with a prompt.")
def deepseek(prompt: str, model: str = "deepseek-coder") -> str:
    """Run DeepSeek agent with a prompt."""
    import subprocess

    result = subprocess.run(
        ["python", "-c", (
            "import json, openai; "
            f"c = openai.OpenAI(); "
            f"r = c.chat.completions.create("
            f"model={model!r}, "
            f"messages=[{{'role':'user','content':{prompt!r}}}]); "
            f"print(json.dumps({{'content': r.choices[0].message.content}}))"
        )],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


registry.freeze()

server = SandboxServer(registry=registry)
server.serve(port=9000)
