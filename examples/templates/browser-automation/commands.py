"""browser-automation 命名命令 — Playwright 浏览器自动化。"""
from serverless_sandbox.server import CommandRegistry, SandboxServer, enable_builtin

registry = CommandRegistry()


@registry.command("browse", description="Browser automation — navigate to a URL and perform an action.")
def browse(url: str, action: str = "screenshot") -> str:
    """Browser automation — navigate to a URL and perform an action."""
    import subprocess

    script = (
        "from playwright.sync_api import sync_playwright; "
        "pw = sync_playwright().start(); "
        "browser = pw.chromium.launch(); "
        "page = browser.new_page(); "
        f"page.goto({url!r}); "
        f"print(page.title()); "
        "browser.close(); "
        "pw.stop()"
    )
    result = subprocess.run(
        ["python3", "-c", script],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout


enable_builtin("upload")
enable_builtin("download")

server = SandboxServer(registry=registry)
server.serve(port=9000)
