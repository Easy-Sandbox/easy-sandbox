"""Skills 管理命令。

Skills 是 SKILL.md 文件，教 Agent 如何使用沙箱完成特定任务。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import click

from serverless_sandbox.cli.formatters import get_formatter
from serverless_sandbox.cli.main import handle_errors
from serverless_sandbox.cli.output import get_output


# ---------------------------------------------------------------------------
# Known skills catalogue (simplified, without real registry call)
# ---------------------------------------------------------------------------

KNOWN_SKILLS: list[dict[str, str]] = [
    {"name": "python-base", "category": "runtime", "description": "Python 3.11 基础环境"},
    {"name": "python-data-science", "category": "data-sci", "description": "pandas + numpy + matplotlib 数据科学"},
    {"name": "node-base", "category": "runtime", "description": "Node.js 20 LTS 环境"},
    {"name": "go-base", "category": "runtime", "description": "Go 1.22 开发环境"},
    {"name": "playwright", "category": "browser", "description": "Playwright 浏览器自动化"},
    {"name": "data-analysis", "category": "data-sci", "description": "pandas + matplotlib + seaborn 数据分析"},
    {"name": "ml-pytorch", "category": "ai-ml", "description": "PyTorch 深度学习环境"},
    {"name": "fastapi", "category": "web", "description": "FastAPI 高性能 API"},
    {"name": "nextjs", "category": "web", "description": "Next.js 全栈开发"},
    {"name": "postgres", "category": "database", "description": "PostgreSQL 数据库"},
]


# ---------------------------------------------------------------------------
# Install targets
# ---------------------------------------------------------------------------

_INSTALL_TARGETS = {
    "project": ".sbox/skills",
    "global": str(Path.home() / ".sbox" / "skills"),
    "cursor": str(Path.home() / ".cursor" / "rules"),
    "vscode": ".vscode",
    "claude": None,  # only prints guidance
}


# ---------------------------------------------------------------------------
# skill group
# ---------------------------------------------------------------------------

@click.group()
def skill() -> None:
    """Skills 管理。"""


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@skill.command("search")
@click.argument("query")
@click.pass_context
@handle_errors
def search(ctx: click.Context, query: str) -> None:
    """搜索可用 Skills。

    示例：\n
      sbox skill search python\n
      sbox skill search "data science"
    """
    fmt = get_formatter(ctx)
    query_lower = query.lower()

    results = [
        s for s in KNOWN_SKILLS
        if query_lower in s["name"].lower()
        or query_lower in s["description"].lower()
        or query_lower in s["category"].lower()
    ]

    if not results:
        fmt.print_success(f"No skills matching '{query}' found.")
        return

    headers = ["Name", "Category", "Description"]
    rows = [[s["name"], s["category"], s["description"]] for s in results]
    fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

@skill.command("install")
@click.argument("skill_ref")
@click.option(
    "--target",
    type=click.Choice(["project", "global", "cursor", "claude", "vscode"]),
    default="project",
    help="安装目标位置",
)
@click.pass_context
@handle_errors
def install(ctx: click.Context, skill_ref: str, target: str) -> None:
    """安装 Skill。

    示例：\n
      sbox skill install code-analysis\n
      sbox skill install owner/repo --target cursor
    """
    fmt = get_formatter(ctx)

    # Generate a minimal SKILL.md content
    skill_content = _generate_skill_content(skill_ref)

    if target == "claude":
        # Claude Desktop: just print guidance
        fmt.print_success(
            f"Skill '{skill_ref}' SKILL.md content generated.\n"
            "To use with Claude Desktop, add the MCP server config to:\n"
            "  ~/Library/Application Support/Claude/claude_desktop_config.json\n\n"
            "See: https://docs.anthropic.com/claude/docs/mcp"
        )
        return

    if target == "vscode":
        dest_dir = Path(".vscode")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"skill-{skill_ref}.md"
        dest_file.write_text(skill_content, encoding="utf-8")
        fmt.print_success(f"Skill '{skill_ref}' installed to {dest_file}")
        return

    if target == "cursor":
        dest_dir = Path(_INSTALL_TARGETS["cursor"])
    elif target == "global":
        dest_dir = Path(_INSTALL_TARGETS["global"])
    else:
        dest_dir = Path(_INSTALL_TARGETS["project"])

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{skill_ref}.md"
    dest_file.write_text(skill_content, encoding="utf-8")

    data = {
        "Skill": skill_ref,
        "Target": target,
        "Path": str(dest_file),
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success(f"Skill '{skill_ref}' installed successfully.")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@skill.command("list")
@click.option(
    "--target",
    type=click.Choice(["project", "global", "all"]),
    default="all",
    help="列出安装范围",
)
@click.pass_context
@handle_errors
def list_skills(ctx: click.Context, target: str) -> None:
    """列出已安装的 Skills。"""
    fmt = get_formatter(ctx)

    skills_found: list[dict[str, str]] = []

    targets_to_check: list[tuple[str, Path]] = []
    if target in ("project", "all"):
        targets_to_check.append(("project", Path(".sbox/skills")))
    if target in ("global", "all"):
        targets_to_check.append(("global", Path.home() / ".sbox" / "skills"))

    for scope, skill_dir in targets_to_check:
        if skill_dir.exists():
            for md_file in sorted(skill_dir.glob("*.md")):
                skills_found.append({
                    "name": md_file.stem,
                    "scope": scope,
                    "path": str(md_file),
                })

    if not skills_found:
        fmt.print_success("No skills installed.")
        return

    headers = ["Name", "Scope", "Path"]
    rows = [[s["name"], s["scope"], s["path"]] for s in skills_found]
    fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

@skill.command("create")
@click.argument("name")
@click.pass_context
@handle_errors
def create(ctx: click.Context, name: str) -> None:
    """创建新 Skill 骨架。"""
    fmt = get_formatter(ctx)

    skill_dir = Path(name)
    if skill_dir.exists():
        fmt.print_error(f"Directory '{name}' already exists.")
        sys.exit(1)

    skill_dir.mkdir(parents=True)
    (skill_dir / "scripts").mkdir()
    (skill_dir / "examples").mkdir()

    # SKILL.md
    skill_md = f"""# {name}

## 概述
在此描述 Skill 的功能。

## 能力
- 能力 1
- 能力 2

## 环境
- Python 3.11
- 工作目录：/app

## 使用方法

```python
# 示例代码
```

## MCP Tools
- `tool_name(param)` — 工具描述

## 注意事项
- 注意事项 1
"""
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # sandbox.yaml
    sandbox_yaml = f"""name: {name}
template: base
description: "{name} Skill"
"""
    (skill_dir / "sandbox.yaml").write_text(sandbox_yaml, encoding="utf-8")

    data = {
        "Skill": name,
        "Directory": str(skill_dir),
        "Files": "SKILL.md, sandbox.yaml, scripts/, examples/",
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success(f"Skill '{name}' scaffold created.")
        get_output(ctx).info(f"\n下一步：\n  cd {name}\n  编辑 SKILL.md 和 sandbox.yaml\n  sbox skill publish")


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

@skill.command("publish")
@click.argument("path", default=".")
@click.pass_context
@handle_errors
def publish(ctx: click.Context, path: str) -> None:
    """发布 Skill 到 Registry。"""
    fmt = get_formatter(ctx)

    skill_path = Path(path)
    skill_md = skill_path / "SKILL.md"

    if not skill_md.exists():
        fmt.print_error(
            f"No SKILL.md found in '{path}'.",
            suggestion="Ensure the directory contains a SKILL.md file.",
        )
        sys.exit(1)

    # Simplified: just prompt user to create a GitHub release
    fmt.print_success(
        f"Skill at '{path}' is ready to publish.\n\n"
        "To publish to the community registry:\n"
        "  1. Push your Skill directory to a GitHub repository\n"
        "  2. Create a GitHub Release with a semantic version tag (e.g. v1.0.0)\n"
        "  3. Others can install via: sbox skill install owner/repo"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_skill_content(skill_ref: str) -> str:
    """Generate minimal SKILL.md content for installation."""
    return f"""# {skill_ref}

## 概述
{skill_ref} Skill — 通过 sbox skill install 安装。

## 使用方法
请参阅 Skill 文档了解详细使用说明。
"""
