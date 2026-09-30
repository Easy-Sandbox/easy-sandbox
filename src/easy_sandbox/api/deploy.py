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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from easy_sandbox.models.errors import (
    DeployAgentError,
    DeployLLMKeyMissingError,
)
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from easy_sandbox.api.sandbox import Sandbox

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
    "EBX_LLM_API_KEY",
    "BAILIAN_CODING_PLAN_API_KEY",
    "DASHSCOPE_API_KEY",
    "OPENAI_API_KEY",
)

# Older name still honored in the process environment, after the variables
# above and before anything saved under ~/.ebx.
_LEGACY_LLM_KEY_ENV = "EBX_QWEN_CODE_API_KEY"

# System config directory. Tests replace this so resolution never reads
# the developer's real ~/.ebx.
_EBX_DIR = Path.home() / ".ebx"


def _first_env(names: tuple[str, ...]) -> str | None:
    """Return the first non-empty process environment variable in *names*."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _read_ebx_env_var(name: str) -> str | None:
    """Read *name* from the system config file ``~/.ebx/.env``."""
    path = _EBX_DIR / ".env"
    if not path.is_file():
        return None
    prefix = f"{name}="
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith(prefix):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def _read_ebx_transport(name: str) -> str | None:
    """Read one ``[transport]`` value from ``~/.ebx/config.toml``."""
    path = _EBX_DIR / "config.toml"
    if not path.is_file():
        return None
    try:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            import tomli as tomllib

        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return None
    transport = data.get("transport")
    source = transport if isinstance(transport, dict) else data
    if not isinstance(source, dict):
        return None
    value = source.get(name)
    if value in (None, ""):
        return None
    return str(value)


def resolve_llm_env(
    *,
    llm_api_key: str | None = None,
    openai_base_url: str | None = None,
    openai_model: str | None = None,
) -> dict[str, str]:
    """Build environment variables for the qwen-code agent inside the sandbox.

    Resolution order for the API key (first hit wins):

    1. Explicit *llm_api_key* parameter.
    2. Process environment: ``EBX_LLM_API_KEY``, then
       ``BAILIAN_CODING_PLAN_API_KEY``, ``DASHSCOPE_API_KEY``,
       ``OPENAI_API_KEY``, then a legacy ``EBX_QWEN_CODE_API_KEY``.
    3. The same names in the project ``.env``.
    4. System config: ``EBX_LLM_API_KEY`` in ``~/.ebx/.env``, then a legacy
       ``llm_api_key`` in ``~/.ebx/config.toml``, then
       ``EBX_QWEN_CODE_API_KEY`` in ``~/.ebx/.env``.

    Base URL and model use the same layers: explicit argument, then
    ``EBX_LLM_BASE_URL`` / ``OPENAI_BASE_URL`` (and the model equivalents),
    then the project ``.env``, then ``~/.ebx/config.toml``, then the
    DashScope default.

    Raises:
        DeployLLMKeyMissingError: If no LLM API key can be found.
    """
    from easy_sandbox.transport.config import project_dotenv_value

    api_key = (
        llm_api_key
        or _first_env(_LLM_KEY_ENV_VARS)
        or _first_env((_LEGACY_LLM_KEY_ENV,))
        or project_dotenv_value((*_LLM_KEY_ENV_VARS, _LEGACY_LLM_KEY_ENV))
    )
    if not api_key:
        api_key = (
            _read_ebx_env_var("EBX_LLM_API_KEY")
            or _read_ebx_transport("llm_api_key")
            or _read_ebx_env_var(_LEGACY_LLM_KEY_ENV)
        )

    if not api_key:
        raise DeployLLMKeyMissingError(
            "No LLM API key found for qwen-code agent.",
            suggestion=(
                "Export one of "
                + ", ".join(_LLM_KEY_ENV_VARS)
                + ", or store one with 'ebx config set llm_api_key <KEY>'."
            ),
        )

    env: dict[str, str] = {
        "DASHSCOPE_API_KEY": api_key,
    }

    # Set OpenAI-compatible endpoint for qwen-code. Environment wins over
    # the value saved in ~/.ebx/config.toml.
    base_url = (
        openai_base_url
        or _first_env(("EBX_LLM_BASE_URL", "OPENAI_BASE_URL"))
        or project_dotenv_value(("EBX_LLM_BASE_URL", "OPENAI_BASE_URL"))
        or _read_ebx_transport("llm_base_url")
        or _read_ebx_transport("qwen_code_base_url")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    model = (
        openai_model
        or _first_env(("EBX_LLM_MODEL", "OPENAI_MODEL"))
        or project_dotenv_value(("EBX_LLM_MODEL", "OPENAI_MODEL"))
        or _read_ebx_transport("llm_model")
        or _read_ebx_transport("qwen_code_model")
        or "qwen3-coder-plus"
    )

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
{{"status": "success|failed", "url": "http://localhost:<port>", "port": <port>,
"logs": "关键日志摘要"}}
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
        max_session_turns: int = 100,
        on_progress: Callable[[str], None] | None = None,
    ) -> DeployResult:
        """Deploy a local project using the qwen-code agent.

        Args:
            project_path: Local path to the project directory.
            instruction: Natural-language description / instruction.
            max_wall_time: Maximum wall-clock time (e.g. ``'10m'``, ``'600s'``).
            max_session_turns: Maximum number of qwen-code session turns
                (user/model/tool turns). Exceeding it makes qwen-code exit
                with code 53, reported as ``turn_limit_exceeded``.
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
            max_session_turns=max_session_turns,
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
        deploy_result = self._parse_result(result.stdout, result.stderr, result.exit_code)  # type: ignore[union-attr]
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
            if any(p in (".git", "__pycache__", "node_modules", ".venv", ".tox") for p in parts):
                continue
            # Skip .env files (may contain secrets)
            if rel.name == ".env":
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
        max_session_turns: int = 100,
    ) -> str:
        """Build the ``qwen`` CLI command string.

        The prompt travels as a positional argument (verified against
        qwen-code 0.15.11 and 0.23.0: the legacy ``-p`` flag is deprecated
        upstream and must not be used).  The turn budget travels as the
        official ``--max-session-turns`` flag (an integer capping
        user/model/tool turns in the run); qwen-code exits with code 53
        when it is exceeded.
        """
        safe_prompt = shlex.quote(prompt)
        return (
            f"qwen {safe_prompt} --yolo --output-format json "
            f"--max-session-turns {max_session_turns}"
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
