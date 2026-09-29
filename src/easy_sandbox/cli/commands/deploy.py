"""Project deployment commands.

Supports two modes:
1. NL deploy (qwen-code): ``ebx deploy ./my-project "deploy this FastAPI project"``
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
    "--instruction",
    "-i",
    "instruction_opt",
    default=None,
    help="NL deploy instruction (alternative to positional arg)",
)
@click.option("--max-wall-time", default="10m", help="qwen-code max wall time (e.g. '10m', '600s')")
@click.option(
    "--max-session-turns",
    default=100,
    type=int,
    help="qwen-code session turn limit (positive integer; default: 100)",
)
@click.option("--alias", "-a", default=None, help="Template alias (traditional mode)")
@click.option(
    "--watch",
    is_flag=True,
    help="Watch for file changes and auto-redeploy (traditional mode)",
)
@click.option(
    "--traditional",
    is_flag=True,
    help="Use traditional build+run mode instead of AI deploy",
)
@click.pass_context
@handle_errors
def deploy_shortcut(
    ctx: click.Context,
    path: str,
    instruction: str,
    instruction_opt: str | None,
    max_wall_time: str,
    max_session_turns: int,
    alias: str | None,
    watch: bool,
    traditional: bool,
) -> None:
    """Deploy a local project to a sandbox.

    AI mode (default) analyzes the project and follows an optional natural-
    language instruction. Use --traditional for marker-based project detection
    without the AI agent.

    \b
    Examples:
      ebx deploy ./my-project "deploy this FastAPI app on port 8080"
      ebx deploy ./my-project --max-wall-time 15m --max-session-turns 150
      ebx deploy ./my-project --traditional --alias my-app

    \b
    Related commands:
      ebx create             Create an empty sandbox
      ebx exec --help        Run a command in a sandbox
      ebx template deploy    Build and register a reusable template
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
            effective_instruction = f"Auto-detect and deploy this {project_type} project"
        else:
            effective_instruction = (
                "Analyze project structure, install dependencies, build and start the service"
            )

    # Traditional mode (no AI agent)
    if traditional:
        _run_traditional_deploy(ctx, fmt, project_path, alias, watch)
        return

    # NL deploy mode via qwen-code
    _run_nl_deploy(ctx, fmt, project_path, effective_instruction, max_wall_time, max_session_turns)


def _run_nl_deploy(
    ctx: click.Context,
    fmt: Any,
    project_path: Path,
    instruction: str,
    max_wall_time: str,
    max_session_turns: int,
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
            max_session_turns=max_session_turns,
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
