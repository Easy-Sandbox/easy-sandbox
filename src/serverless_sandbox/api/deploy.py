"""Deploy module — NL-driven project deployment via qwen-code agent.

Usage:
    sandbox = await Sandbox.create(template="qwen-code", envs={...})
    deployer = DeployModule(sandbox)
    result = await deployer.deploy_project("./my-project", "部署这个 FastAPI 项目")

The module uploads the project to ``/workspace`` inside the sandbox, then
invokes ``qwen`` in headless mode to autonomously analyse, install
dependencies, build, and start the service.
"""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING

from serverless_sandbox.models.errors import (
    DeployError,
    DeployLLMKeyMissingError,
    DeployAgentError,
)
from serverless_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from serverless_sandbox.api.sandbox import Sandbox

logger = get_logger("api.deploy")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DeployResult:
    """Result of a qwen-code driven deployment."""

    status: str = "unknown"
    """One of: success, failed, timeout, interrupted."""

    url: str = ""
    """Service URL if deployment exposed a port."""

    port: int = 0
    """Port the service is listening on."""

    logs: str = ""
    """Summarised deployment logs."""

    raw_output: str = ""
    """Full raw stdout from the qwen-code agent."""

    exit_code: int = -1
    """qwen-code process exit code."""

    sandbox_id: str = ""
    """ID of the sandbox where the project was deployed."""

    @property
    def success(self) -> bool:
        return self.status == "success"


# ---------------------------------------------------------------------------
# Exit-code mapping (from qwen-code CLI)
# ---------------------------------------------------------------------------

_QWEN_EXIT_MAP: dict[int, str] = {
    0: "success",
    53: "turn_limit_exceeded",
    55: "budget_exceeded",
    130: "interrupted",
}


def _exit_code_to_status(code: int) -> str:
    """Map a qwen-code exit code to a human-readable status."""
    return _QWEN_EXIT_MAP.get(code, "failed")


# ---------------------------------------------------------------------------
# LLM credential resolution
# ---------------------------------------------------------------------------

_LLM_KEY_ENV_VARS = (
    "BAILIAN_CODING_PLAN_API_KEY",
    "DASHSCOPE_API_KEY",
    "OPENAI_API_KEY",
)


def resolve_llm_env(
    *,
    llm_api_key: str | None = None,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
) -> dict[str, str]:
    """Build environment variables for the qwen-code agent inside the sandbox.

    Resolution order:
    1. Explicit *llm_api_key* parameter.
    2. ``BAILIAN_CODING_PLAN_API_KEY`` env var.
    3. ``DASHSCOPE_API_KEY`` env var.
    4. ``OPENAI_API_KEY`` env var.

    Raises:
        DeployLLMKeyMissingError: If no LLM API key can be found.
    """
    api_key = llm_api_key
    if not api_key:
        for var in _LLM_KEY_ENV_VARS:
            api_key = os.environ.get(var)
            if api_key:
                break

    if not api_key:
        raise DeployLLMKeyMissingError(
            "No LLM API key found for qwen-code agent.",
            suggestion=(
                "Set one of the following environment variables: "
                + ", ".join(_LLM_KEY_ENV_VARS)
            ),
        )

    env: dict[str, str] = {
        "DASHSCOPE_API_KEY": api_key,
    }

    # Set OpenAI-compatible endpoint for qwen-code
    base_url = openai_base_url or os.environ.get(
        "OPENAI_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model = openai_model or os.environ.get("OPENAI_MODEL", "qwen3-coder-plus")

    env["OPENAI_BASE_URL"] = base_url
    env["OPENAI_MODEL"] = model

    return env


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_DEPLOY_PROMPT_TEMPLATE = """\
你是一个部署助手。请完成以下任务：

项目位于 /workspace 目录。

用户指令: {instruction}

执行步骤:
1. 扫描 /workspace 目录，确定项目类型和使用的框架
2. 安装所有必要的依赖 (pip install / npm install / go mod download 等)
3. 如果需要构建，执行构建命令
4. 启动服务并验证端口可达
5. 完成后输出部署结果（JSON 格式）

最终请输出一行 JSON（不要 markdown 代码块），格式:
{{"status": "success|failed", "url": "http://localhost:<port>", "port": <port>, "logs": "关键日志摘要"}}
"""


def _build_prompt(instruction: str) -> str:
    """Build the qwen-code agent prompt."""
    return _DEPLOY_PROMPT_TEMPLATE.format(instruction=instruction)


# ---------------------------------------------------------------------------
# Wall-time parsing
# ---------------------------------------------------------------------------

def _parse_wall_time(wall_time: str) -> int:
    """Parse a wall-time string like ``'10m'`` or ``'300s'`` into seconds."""
    wall_time = wall_time.strip().lower()
    if wall_time.endswith("m"):
        return int(wall_time[:-1]) * 60
    if wall_time.endswith("s"):
        return int(wall_time[:-1])
    if wall_time.endswith("h"):
        return int(wall_time[:-1]) * 3600
    return int(wall_time)


# ---------------------------------------------------------------------------
# DeployModule
# ---------------------------------------------------------------------------

class DeployModule:
    """Orchestrates NL-driven deployment inside a sandbox via qwen-code.

    The caller is responsible for creating the sandbox with the ``qwen-code``
    template and injecting LLM credentials.  This module handles:

    1. Uploading the local project tree to ``/workspace``.
    2. Constructing the qwen-code prompt.
    3. Running ``qwen`` in headless mode.
    4. Parsing the JSON result from qwen-code's output.
    """

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    # ---- public ----

    async def deploy_project(
        self,
        project_path: str,
        instruction: str,
        *,
        max_wall_time: str = "10m",
        max_tool_calls: int = 100,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> DeployResult:
        """Deploy a local project using the qwen-code agent.

        Args:
            project_path: Local path to the project directory.
            instruction: Natural-language description / instruction.
            max_wall_time: Maximum wall-clock time (e.g. ``'10m'``, ``'600s'``).
            max_tool_calls: Maximum number of tool calls for qwen-code.
            on_progress: Optional callback invoked with progress messages.

        Returns:
            A :class:`DeployResult` with deployment outcome.

        Raises:
            DeployAgentError: If the qwen-code agent fails unexpectedly.
        """
        timeout_seconds = _parse_wall_time(max_wall_time)

        # Step 1: Upload project files
        if on_progress:
            on_progress("Uploading project files...")
        await self._upload_project(project_path)

        # Step 2: Build and run qwen command
        if on_progress:
            on_progress("Starting qwen-code agent...")
        prompt = _build_prompt(instruction)
        cmd = self._build_qwen_command(
            prompt=prompt,
            max_tool_calls=max_tool_calls,
        )

        logger.info("Running qwen-code: %s", cmd)
        result = await self._sandbox.commands.run(
            cmd,
            timeout=timeout_seconds,
            cwd="/workspace",
        )

        # Step 3: Parse output
        if on_progress:
            on_progress("Parsing deployment result...")
        deploy_result = self._parse_result(result.stdout, result.stderr, result.exit_code)
        deploy_result.sandbox_id = self._sandbox.id

        if on_progress:
            on_progress(f"Deploy finished: {deploy_result.status}")

        return deploy_result

    # ---- internals ----

    async def _upload_project(self, project_path: str) -> None:
        """Upload all files from *project_path* to ``/workspace`` in the sandbox."""
        local_root = Path(project_path).resolve()
        if not local_root.exists():
            raise DeployAgentError(
                f"Project path does not exist: {local_root}",
                suggestion="Provide a valid local directory path.",
            )
        if not local_root.is_dir():
            raise DeployAgentError(
                f"Project path is not a directory: {local_root}",
                suggestion="Provide a directory, not a file.",
            )

        # Walk the directory tree and upload each file
        for file_path in local_root.rglob("*"):
            if not file_path.is_file():
                continue
            # Skip common non-essential directories
            rel = file_path.relative_to(local_root)
            parts = rel.parts
            if any(
                p in (".git", "__pycache__", "node_modules", ".venv", ".env", ".tox")
                for p in parts
            ):
                continue

            remote_path = f"/workspace/{rel.as_posix()}"
            try:
                content = file_path.read_bytes()
                await self._sandbox.files.write(remote_path, content)
            except Exception as exc:
                logger.warning("Failed to upload %s: %s", rel, exc)

    @staticmethod
    def _build_qwen_command(
        *,
        prompt: str,
        max_tool_calls: int = 100,
    ) -> str:
        """Build the ``qwen`` CLI command string."""
        safe_prompt = shlex.quote(prompt)
        return (
            f"qwen -p {safe_prompt} "
            f"--yolo "
            f"--output-format json "
            f"--max-turns {max_tool_calls}"
        )

    @staticmethod
    def _parse_result(
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> DeployResult:
        """Parse qwen-code output into a :class:`DeployResult`."""
        status = _exit_code_to_status(exit_code)
        result = DeployResult(
            status=status,
            raw_output=stdout,
            exit_code=exit_code,
            logs=stderr if stderr else "",
        )

        # Try to extract structured JSON from the last line(s) of stdout
        if stdout.strip():
            json_data = _extract_json_from_output(stdout)
            if json_data:
                result.status = json_data.get("status", status)
                result.url = json_data.get("url", "")
                result.port = int(json_data.get("port", 0))
                if json_data.get("logs"):
                    result.logs = json_data["logs"]

        return result


def _extract_json_from_output(output: str) -> dict[str, Any] | None:
    """Try to find and parse a JSON object from qwen-code output.

    Scans lines from the end backwards, trying to parse each as JSON.
    """
    lines = output.strip().splitlines()
    # Try lines from the end (most likely location of the result JSON)
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict) and "status" in data:
                return data
        except json.JSONDecodeError:
            continue
    return None
