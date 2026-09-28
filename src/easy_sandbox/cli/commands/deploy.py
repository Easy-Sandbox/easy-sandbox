"""项目部署命令。

Supports two modes:
1. NL deploy (qwen-code): ``ebx deploy ./my-project "部署这个 FastAPI 项目"``
2. Traditional deploy: ``ebx deploy ./my-project --traditional``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors

# ---------------------------------------------------------------------------
# Project type detection (retained for traditional deploy)
# ---------------------------------------------------------------------------

_PROJECT_DETECTORS: list[tuple[str, str, str]] = [
    # (marker file, project type, default template)
    ("sandbox.yaml", "sandbox-config", "base"),
    ("Dockerfile", "docker", "base"),
    ("requirements.txt", "python", "python-base"),
    ("pyproject.toml", "python", "python-base"),
    ("package.json", "nodejs", "node-web"),
    ("go.mod", "go", "go-dev"),
    ("pom.xml", "java", "java-dev"),
    ("build.gradle", "java", "java-dev"),
]


def _detect_project(path: Path) -> tuple[str, str]:
    """Detect project type and return (project_type, template).

    Returns:
        Tuple of (project_type, template_name).
    """
    for marker, proj_type, template in _PROJECT_DETECTORS:
        if (path / marker).exists():
            return proj_type, template
    return "unknown", "base"


# ---------------------------------------------------------------------------
# Top-level deploy shortcut: ebx deploy <path> [instruction]
# ---------------------------------------------------------------------------


@click.command("deploy")
@click.argument("path", default=".")
@click.argument("instruction", default="", required=False)
@click.option(
    "--instruction", "-i", "instruction_opt", default=None, help="NL 部署指令（与位置参数二选一）"
)
@click.option("--max-wall-time", default="10m", help="qwen-code 最大执行时间 (如 '10m', '600s')")
@click.option("--max-tool-calls", default=100, type=int, help="qwen-code 最大工具调用次数")
@click.option("--alias", "-a", default=None, help="模板别名（传统模式）")
@click.option("--watch", is_flag=True, help="监听文件变化自动重新部署（传统模式）")
@click.option("--traditional", is_flag=True, help="使用传统 build+run 模式而非 AI 部署")
@click.pass_context
@handle_errors
def deploy_shortcut(
    ctx: click.Context,
    path: str,
    instruction: str,
    instruction_opt: str | None,
    max_wall_time: str,
    max_tool_calls: int,
    alias: str | None,
    watch: bool,
    traditional: bool,
) -> None:
    """部署项目到 sandbox。

    \b
    NL 模式（默认）:
      ebx deploy ./my-project "这是一个 FastAPI 项目，需要 Redis"
      ebx deploy ./my-project -i "部署到端口 8080"

    \b
    传统模式:
      ebx deploy ./my-project --traditional
    """
    fmt = get_formatter(ctx)
    project_path = Path(path).resolve()

    if not project_path.exists():
        fmt.print_error(f"Path '{path}' does not exist.")
        sys.exit(1)

    # Resolve instruction: positional arg > --instruction flag
    effective_instruction = instruction_opt or instruction

    # If no instruction and not traditional mode, detect project and generate
    # a default instruction
    if not effective_instruction and not traditional:
        project_type, _ = _detect_project(project_path)
        if project_type != "unknown":
            effective_instruction = f"自动检测并部署这个 {project_type} 项目"
        else:
            effective_instruction = "分析项目结构，安装依赖，构建并启动服务"

    # Traditional mode (no AI agent)
    if traditional:
        _run_traditional_deploy(ctx, fmt, project_path, alias, watch)
        return

    # NL deploy mode via qwen-code
    _run_nl_deploy(ctx, fmt, project_path, effective_instruction, max_wall_time, max_tool_calls)


def _run_nl_deploy(
    ctx: click.Context,
    fmt: Any,
    project_path: Path,
    instruction: str,
    max_wall_time: str,
    max_tool_calls: int,
) -> None:
    """Execute NL-driven deployment via qwen-code agent."""
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    fmt.print_success(f"Starting NL deploy: {project_path}")
    fmt.print_success(f"Instruction: {instruction}")

    def on_progress(msg: str) -> None:
        if not (ctx.obj or {}).get("quiet"):
            fmt.print_success(msg)

    sandbox = run_sync(
        Sandbox.deploy(
            project_path=str(project_path),
            description=instruction,
            max_wall_time=max_wall_time,
            max_tool_calls=max_tool_calls,
            on_progress=on_progress,
        )
    )

    deploy_result = getattr(sandbox, "_deploy_result", None)
    data: dict[str, Any] = {
        "SandboxID": sandbox.id,
        "Status": deploy_result.status if deploy_result else "unknown",
        "URL": deploy_result.url if deploy_result else "",
        "Port": deploy_result.port if deploy_result else 0,
    }
    if deploy_result and deploy_result.logs:
        data["Logs"] = deploy_result.logs

    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        if deploy_result and deploy_result.success:
            fmt.print_success("Deployment completed successfully!")
        elif deploy_result:
            fmt.print_error(
                f"Deployment finished with status: {deploy_result.status}",
                suggestion="Check logs above or use 'ebx exec' to inspect the sandbox.",
            )


def _run_traditional_deploy(
    ctx: click.Context,
    fmt: Any,
    project_path: Path,
    alias: str | None,
    watch: bool,
) -> None:
    """Execute traditional build+run deployment (no AI agent)."""
    project_type, template = _detect_project(project_path)

    fmt.print_success(f"Detected project type: {project_type or 'unknown'}")
    fmt.print_success(f"Template: {template}")

    data = {
        "Path": str(project_path),
        "ProjectType": project_type,
        "Template": template,
        "Alias": alias or project_path.name,
        "Watch": "enabled" if watch else "disabled",
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success("Deploy completed. Use 'ebx template deploy' for custom image builds.")
