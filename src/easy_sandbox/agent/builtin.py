"""内置 Agent 语法糖。"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from easy_sandbox.api.sandbox import Sandbox

logger = get_logger("agent.builtin")


# ---------------------------------------------------------------------------
# BUILTIN_AGENTS registry — maps keywords to agent templates
# ---------------------------------------------------------------------------

BUILTIN_AGENTS: dict[str, dict[str, Any]] = {
    "qwen-code-deploy": {
        "template": "qwen-code",
        "display_name": "Qwen Code Deploy Agent",
        "description": "使用 qwen-code 在 sandbox 内自主部署项目",
        "keywords": [
            "deploy", "部署", "发布", "上线",
            "qwen-code", "qwen deploy", "NL deploy",
            "自动部署", "智能部署",
        ],
        "capabilities": ["shell", "files", "code", "ports"],
        "resources": {"cpu": 2, "memory": 4096},
    },
    "codex": {
        "template": "codex",
        "display_name": "Codex Agent",
        "description": "OpenAI Codex CLI Agent",
        "keywords": ["codex", "openai codex"],
        "capabilities": ["shell", "files", "code"],
        "resources": {"cpu": 2, "memory": 4096},
    },
    "claude-code": {
        "template": "claude-code",
        "display_name": "Claude Code Agent",
        "description": "Anthropic Claude Code Agent",
        "keywords": ["claude", "claude code", "anthropic"],
        "capabilities": ["shell", "files", "code"],
        "resources": {"cpu": 2, "memory": 4096},
    },
}


def match_builtin_agent(query: str) -> dict[str, Any] | None:
    """Match a natural-language query to a built-in agent.

    Args:
        query: User query / intent string.

    Returns:
        Agent config dict if matched, else ``None``.
    """
    query_lower = query.lower()
    best_match: dict[str, Any] | None = None
    best_score = 0

    for _name, agent in BUILTIN_AGENTS.items():
        score = 0
        for kw in agent["keywords"]:
            if kw.lower() in query_lower:
                score += len(kw)
        if score > best_score:
            best_score = score
            best_match = agent

    return best_match if best_score > 0 else None


class AgentModule:
    """Agent 便捷方法。本质是 commands.run() + code.run() 的语法糖。

    Usage::

        sandbox = await Sandbox.create(template="code-interpreter-v1")
        agent = AgentModule(sandbox)
        output = await agent.code("print('hello')")
        result = await agent.shell("ls -la")
    """

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    async def code(
        self,
        instruction: str,
        code: str | None = None,
        language: str = "python",
    ) -> str:
        """执行代码相关操作。

        如果提供了 code，直接执行。
        如果只有 instruction，暂时作为命令描述传递。

        Args:
            instruction: 代码或指令描述。
            code: 要执行的源代码（可选）。
            language: 编程语言（默认 python）。

        Returns:
            执行结果的文本输出。
        """
        source = code if code else instruction
        result = await self._sandbox.code.run(source, language=language)
        # CodeResult 有 text 属性
        return getattr(result, "text", str(result))

    async def shell(self, command: str, timeout: int = 60) -> str:
        """执行 shell 命令。

        Args:
            command: Shell 命令字符串。
            timeout: 超时秒数。

        Returns:
            命令的 stdout 输出。
        """
        result = await self._sandbox.commands.run(command, timeout=timeout)
        return result.stdout

    async def browse(self, url: str) -> str:
        """浏览网页（使用 curl 获取）。

        Args:
            url: 要访问的 URL。

        Returns:
            网页内容。
        """
        result = await self._sandbox.commands.run(f"curl -sL {url}")
        return result.stdout

    async def analyze(self, code: str) -> str:
        """分析代码（运行 pylint 等工具）。

        Args:
            code: 要分析的代码。

        Returns:
            分析结果。
        """
        # 将代码写入临时文件再分析
        write_cmd = f"cat > /tmp/_analyze.py << 'ANALYZE_EOF'\n{code}\nANALYZE_EOF"
        await self._sandbox.commands.run(write_cmd)

        result = await self._sandbox.commands.run(
            "python -m py_compile /tmp/_analyze.py 2>&1 || true"
        )
        return result.stdout or "No issues found."

    async def install(self, *packages: str) -> str:
        """安装 Python 包。

        Args:
            packages: 要安装的包名。

        Returns:
            安装命令输出。
        """
        pkgs = " ".join(packages)
        result = await self._sandbox.commands.run(
            f"pip install --quiet {pkgs}", timeout=120,
        )
        return result.stdout

    async def upload(self, content: str | bytes, path: str) -> None:
        """上传文件内容到沙箱。

        Args:
            content: 文件内容（文本或二进制）。
            path: 目标路径。
        """
        if isinstance(content, str):
            content = content.encode("utf-8")
        await self._sandbox.files.write(path, content)

    async def download(self, path: str) -> bytes:
        """下载沙箱中的文件。

        Args:
            path: 文件路径。

        Returns:
            文件内容。
        """
        return await self._sandbox.files.read(path)
