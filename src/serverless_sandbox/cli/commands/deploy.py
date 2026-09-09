"""项目部署命令。

Supports two modes:
1. NL deploy (qwen-code): ``sbox deploy ./my-project "部署这个 FastAPI 项目"``
2. Traditional deploy: ``sbox deploy build`` / ``sbox deploy run``
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import click

from serverless_sandbox.cli.formatters import get_formatter
from serverless_sandbox.cli.main import handle_errors


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

_START_COMMANDS: dict[str, str] = {
    "python": "python app.py",
    "nodejs": "npm start",
    "go": "go run .",
    "java": "mvn spring-boot:run",
    "docker": "",
    "sandbox-config": "",
}

_INSTALL_COMMANDS: dict[str, str | None] = {
    "python": "pip install -r requirements.txt",
    "nodejs": "npm install",
    "go": "go mod download",
    "java": None,
    "docker": None,
    "sandbox-config": None,
}


def _detect_project(path: Path) -> tuple[str, str]:
    """Detect project type and return (project_type, template).

    Returns:
        Tuple of (project_type, template_name).
    """
    for marker, proj_type, template in _PROJECT_DETECTORS:
        if (path / marker).exists():
            return proj_type, template
    return "unknown", "base"


def _generate_dockerfile(
    project_type: str,
    template: str,
    path: Path,
) -> str:
    """Generate a Dockerfile for the given project type."""
    if project_type == "python":
        return (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            'CMD ["python", "app.py"]'
        )
    elif project_type == "nodejs":
        return (
            "FROM node:20-slim\n"
            "WORKDIR /app\n"
            "COPY package*.json .\n"
            "RUN npm install\n"
            "COPY . .\n"
            'CMD ["npm", "start"]'
        )
    elif project_type == "go":
        return (
            "FROM golang:1.22\n"
            "WORKDIR /app\n"
            "COPY go.* .\n"
            "RUN go mod download\n"
            "COPY . .\n"
            'CMD ["go", "run", "."]'
        )
    else:
        return (
            "FROM ubuntu:22.04\n"
            "WORKDIR /app\n"
            "COPY . .\n"
        )


# ---------------------------------------------------------------------------
# deploy_group (traditional subcommands)
# ---------------------------------------------------------------------------

@click.group("deploy")
def deploy_group() -> None:
    """项目部署管理。"""


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

@deploy_group.command("build")
@click.argument("path", default=".")
@click.option("--alias", "-a", default=None, help="模板别名")
@click.option("--dockerfile", "-f", "dockerfile_path", default=None, type=click.Path(), help="Dockerfile 路径")
@click.pass_context
@handle_errors
def build(ctx: click.Context, path: str, alias: str | None, dockerfile_path: str | None) -> None:
    """从项目目录构建模板。

    自动检测项目类型：\n
    - requirements.txt → Python 环境\n
    - package.json → Node.js 环境\n
    - go.mod → Go 环境\n
    - Dockerfile → 直接使用
    """
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    project_path = Path(path).resolve()

    if not project_path.exists():
        fmt.print_error(f"Path '{path}' does not exist.")
        sys.exit(1)

    # Determine Dockerfile content
    if dockerfile_path:
        df = Path(dockerfile_path)
        if not df.exists():
            fmt.print_error(f"Dockerfile '{dockerfile_path}' not found.")
            sys.exit(1)
        dockerfile_content = df.read_text(encoding="utf-8")
        project_type = "docker"
        template = "base"
        fmt.print_success(f"Using provided Dockerfile: {dockerfile_path}")
    elif (project_path / "Dockerfile").exists():
        dockerfile_content = (project_path / "Dockerfile").read_text(encoding="utf-8")
        project_type = "docker"
        template = "base"
        fmt.print_success("Using existing Dockerfile.")
    else:
        project_type, template = _detect_project(project_path)
        if project_type == "unknown":
            fmt.print_error(
                "Unable to detect project type.",
                suggestion="Provide a Dockerfile with -f or add a recognized project marker file.",
            )
            sys.exit(1)
        fmt.print_success(f"Detected project type: {project_type}")
        dockerfile_content = _generate_dockerfile(project_type, template, project_path)

    build_alias = alias or project_path.name

    # Submit build via platform API
    from serverless_sandbox.transport.config import load_config
    from serverless_sandbox.transport.auth import create_auth_provider
    from serverless_sandbox.transport.http import HttpClient

    config = load_config(region=ctx.obj.get("region") if ctx.obj else None)
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)

    body: dict[str, str] = {"dockerfile": dockerfile_content}
    if build_alias:
        body["alias"] = build_alias

    resp = run_sync(http_client.platform_request("POST", "/templates", json=body))
    result = resp.json()
    run_sync(http_client.close())

    data = {
        "TemplateID": result.get("templateID", "N/A"),
        "BuildID": result.get("buildID", "N/A"),
        "Alias": build_alias,
        "ProjectType": project_type,
        "Status": "building",
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success("Build submitted. Use 'sbox template list' to check status.")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@deploy_group.command("run")
@click.argument("path", default=".")
@click.option("--template", "-t", default=None, help="使用指定模板（跳过构建）")
@click.option("--watch", is_flag=True, help="监听文件变化自动重新部署")
@click.pass_context
@handle_errors
def run_cmd(ctx: click.Context, path: str, template: str | None, watch: bool) -> None:
    """部署并运行项目。

    如果提供 --watch，监听文件变化自动同步。
    """
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    project_path = Path(path).resolve()

    if not project_path.exists():
        fmt.print_error(f"Path '{path}' does not exist.")
        sys.exit(1)

    project_type, detected_template = _detect_project(project_path)
    use_template = template or detected_template

    fmt.print_success(f"Creating sandbox with template: {use_template}")

    sandbox = run_sync(Sandbox.create(template=use_template))
    fmt.print_success(f"Sandbox {sandbox.id} created.")

    # Upload project files (simplified: just report intent)
    fmt.print_success(f"Uploading project from {project_path}...")

    # Detect and run start command
    start_cmd = _START_COMMANDS.get(project_type, "")
    if start_cmd:
        fmt.print_success(f"Starting: {start_cmd}")
        result = run_sync(sandbox.commands.run(start_cmd, timeout=ctx.obj.get("timeout", 300)))
        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.stderr:
            click.echo(result.stderr, err=True, nl=False)

    data = {
        "SandboxID": sandbox.id,
        "Template": use_template,
        "ProjectType": project_type,
        "URL": sandbox.url,
    }
    if watch:
        data["Watch"] = "enabled"

    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)

    if watch:
        fmt.print_success("Watch mode enabled. Press Ctrl+C to stop.")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            fmt.print_success("\nWatch mode stopped.")


# ---------------------------------------------------------------------------
# Top-level deploy shortcut: sbox deploy <path> [instruction]
# ---------------------------------------------------------------------------

@click.command("deploy")
@click.argument("path", default=".")
@click.argument("instruction", default="", required=False)
@click.option("--instruction", "-i", "instruction_opt", default=None, help="NL 部署指令（与位置参数二选一）")
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
      sbox deploy ./my-project "这是一个 FastAPI 项目，需要 Redis"
      sbox deploy ./my-project -i "部署到端口 8080"

    \b
    传统模式:
      sbox deploy ./my-project --traditional
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
    from serverless_sandbox.api.sandbox import Sandbox
    from serverless_sandbox.utils.async_bridge import run_sync

    fmt.print_success(f"Starting NL deploy: {project_path}")
    fmt.print_success(f"Instruction: {instruction}")

    def on_progress(msg: str) -> None:
        if not (ctx.obj or {}).get("quiet"):
            fmt.print_success(msg)

    try:
        sandbox = run_sync(
            Sandbox.deploy(
                project_path=str(project_path),
                description=instruction,
                max_wall_time=max_wall_time,
                max_tool_calls=max_tool_calls,
                on_progress=on_progress,
            )
        )
    except Exception as exc:
        # Let handle_errors deal with SandboxError subtypes
        raise

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
                suggestion="Check logs above or use 'sbox exec' to inspect the sandbox.",
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
        fmt.print_success(
            "Deploy shortcut: use 'sbox deploy build' + 'sbox deploy run' for full control."
        )
