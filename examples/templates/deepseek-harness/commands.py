"""deepseek-harness 命名命令 — DeepSeek Agent Runtime。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

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


enable_builtin("upload")
enable_builtin("download")

server = SandboxServer(registry=registry)
server.serve(port=9000)
