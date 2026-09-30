"""Top-level ``ebx deploy`` — publish a template project.

``ebx deploy [PATH]`` is the fixed, deterministic *publish* step of the
template lifecycle: docker build → ACR push → CreateTemplate → poll.  It is
exactly ``ebx template deploy`` with ``PATH`` defaulting to ``.`` and shares
**every** option of it (``--acr-namespace``, ``--alias``, ``--yes``,
``-v/--verbose``, ...).

It takes no description and needs no LLM: everything about *what* the
template is (name, resources, ports, capabilities, commands) is authored
earlier — by hand, from ``ebx template init``, or by
``ebx template init "DESCRIPTION"`` (AI) — and lives in ``template.yaml``,
which ``deploy`` only reads.

The in-sandbox agent deployment (``Sandbox.deploy``, which starts a
``qwen-code`` cloud sandbox) remains available as an SDK API only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from easy_sandbox.cli.commands.template import build, resolve_acr_namespace
from easy_sandbox.cli.main import handle_errors
from easy_sandbox.cli.output import get_output

#: Every option of ``template build`` (without its TEMPLATE_DIR argument),
#: reused verbatim so ``deploy`` and ``template deploy`` cannot drift.
_BUILD_OPTIONS: list[click.Parameter] = [p for p in build.params if isinstance(p, click.Option)]


@click.command(
    "deploy",
    params=[
        click.Argument(["path"], default=".", required=False),
        click.Option(["--traditional"], is_flag=True, hidden=True),
        *_BUILD_OPTIONS,
    ],
)
@click.pass_context
@handle_errors
def deploy_shortcut(ctx: click.Context, /, **kwargs: Any) -> None:
    """Publish a template project: build, push to ACR, register the template.

    Runs the fixed pipeline: docker build, push the image to ACR, register
    the template, and wait until it is ready. No LLM is involved.
    PATH is the template directory (default: .). It must contain a
    Dockerfile; template.yaml supplies the template name and resources.

    To author the files first, use 'ebx template init': --adopt for an existing
    project, a natural-language description to let the AI write the files, or
    -t for a scaffold.

    Accepts every option of 'ebx template deploy' (--acr-namespace,
    --alias, --yes, -v/--verbose, ...).

    \b
    Examples:
      ebx deploy --acr-namespace my-ns           # publish ./ as a template
      ebx deploy ./my-template --yes             # non-interactive
      ebx deploy ./my-template -v                # with debug logs

    \b
    Typical flow:
      ebx template init --adopt .                      # 1a. author from a project
      ebx template init "a python data science env"   # 1b. author from a description
      ebx deploy ./<name> --acr-namespace my-ns       # 2. publish
      ebx create --template <TEMPLATE_ID>             # 3. launch a sandbox

    \b
    Related commands:
      ebx template init          Author Dockerfile / template.yaml (AI optional)
      ebx template deploy DIR    The same pipeline with a required DIRECTORY
      ebx create "DESCRIPTION"   Author + publish + launch in one go
    """
    path: str = kwargs.pop("path")
    traditional: bool = kwargs.pop("traditional")

    if kwargs.get("verbose_flag"):
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)
    out = get_output(ctx)

    project_path = Path(path).expanduser().resolve()
    if not project_path.is_dir():
        raise click.UsageError(f"Path '{path}' is not an existing directory.")

    if traditional:
        out.warning(
            "--traditional is deprecated and ignored: 'ebx deploy' always runs the "
            "build/push/register pipeline."
        )

    # Fail fast, before any docker or cloud call.
    resolve_acr_namespace(kwargs.get("acr_namespace"))

    if not (project_path / "Dockerfile").is_file() and not kwargs.get("dockerfile"):
        raise click.UsageError(
            f"No Dockerfile found in {project_path}. Pass --dockerfile, or author the "
            "template first: 'ebx template init --adopt .' (adapt this project), "
            "'ebx template init \"DESCRIPTION\"' (AI) or "
            "'ebx template init -t python' (scaffold)."
        )

    ctx.invoke(build, template_dir=str(project_path), **kwargs)
