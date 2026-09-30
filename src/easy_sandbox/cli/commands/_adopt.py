"""``ebx template init --adopt`` orchestration.

The agent work and the safety checks live in
:mod:`easy_sandbox.agent.adopt`.  This module only talks to the user:
consent, the preview, and translating rejections into Click errors.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlparse

import click

from easy_sandbox.agent.adopt import (
    ADOPT_SESSION_TURNS,
    AdoptPlan,
    AdoptRejectedError,
    StagedProject,
    assert_adoptable,
    build_adopt_prompt,
    default_template_name,
    plan_from_staging,
    preflight,
    promote,
    stage_project,
    validate_template_name,
)
from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.output import get_output, is_ci_env

_PREVIEW_LINES = 200


def run_adopt(
    ctx: click.Context,
    directory: str | None,
    *,
    hint: str | None,
    name: str | None,
    dry_run: bool,
    force: bool,
    yes: bool,
    verbose: bool,
) -> None:
    """Adapt *directory* (default ``.``) into a template.  Nothing is deployed."""
    from easy_sandbox.cli.commands.sandbox import _activity_kwargs, _phase_status
    from easy_sandbox.cli.commands.template import _print_init_summary

    if verbose:
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)

    fmt = get_formatter(ctx)
    out = get_output(ctx)
    interactive = _is_interactive(fmt)
    needs_confirm = interactive and not yes

    try:
        project = assert_adoptable(Path(directory or ".").expanduser())
        template_name = validate_template_name(name) if name else default_template_name(project)
        state = preflight(project, force=force, needs_confirm=needs_confirm)
    except AdoptRejectedError as exc:
        _reraise(exc)

    if not dry_run and not yes and not interactive:
        raise click.UsageError(
            "Confirmation required before project files are sent to the model. "
            "Use --yes/-y to approve, or --dry-run to list the files without sending them."
        )

    try:
        staged = stage_project(project)
    except AdoptRejectedError as exc:
        _reraise(exc)
    cleanup = False
    try:
        if dry_run:
            _emit_dry_run(ctx, out, project, template_name, staged)
            cleanup = True
            return

        from easy_sandbox.cli.commands._coding_agent import (
            ensure_coding_agent_binary,
            resolve_coding_agent_backend,
            resolve_coding_agent_credentials,
        )

        backend = resolve_coding_agent_backend()
        binary = ensure_coding_agent_binary(ctx, yes=yes, backend=backend)
        credentials = resolve_coding_agent_credentials(ctx, yes=yes, backend=backend)
        host = _model_host(credentials)
        _announce(out, project, template_name, staged, host)
        if needs_confirm and not click.confirm(
            f"Send {len(staged.copied)} files to {host}?", default=True, err=True
        ):
            out.info("Nothing was sent.")
            cleanup = True
            raise click.Abort()

        existing = tuple(n for n, digest in state.hashes.items() if digest is not None)
        prompt = build_adopt_prompt(
            staged, hint=hint, template_name=template_name, existing=existing
        )
        with _phase_status(out, "Adapting project") as update:
            raw = backend.run_in_workspace(
                prompt,
                workdir=staged.staging_dir,
                binary=binary,
                env=credentials.as_env(),
                max_session_turns=ADOPT_SESSION_TURNS,
                **_activity_kwargs(backend.run_in_workspace, update),
            )
        plan = plan_from_staging(project, staged, template_name=template_name, raw_output=raw)
        for warning in plan.warnings:
            out.warning(warning)
        _preview(out, project, plan)
        if needs_confirm and not click.confirm("Write these files?", default=True, err=True):
            out.info(f"Nothing was written. Staging kept at {staged.staging_dir}")
            raise click.Abort()

        try:
            result = promote(project, plan, state)
        except AdoptRejectedError as exc:
            _reraise(exc)
        cleanup = True
        dir_arg = "." if project == Path.cwd().resolve() else str(project)
        _print_init_summary(
            fmt,
            out,
            project,
            list(result.written),
            template_name,
            replaced=list(plan.replaces),
            backed_up=list(result.backed_up),
            not_applied=list(plan.not_applied),
            next_steps=[f"ebx deploy {dir_arg} --acr-namespace <ns>"],
        )
    finally:
        if cleanup:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)


def _is_interactive(fmt: Any) -> bool:
    """True only on a terminal that is not JSON and not CI."""
    return sys.stdin.isatty() and not fmt.use_json and not is_ci_env()


def _reraise(exc: AdoptRejectedError) -> NoReturn:
    if exc.usage:
        raise click.UsageError(str(exc)) from exc
    raise click.ClickException(str(exc)) from exc


def _model_host(credentials: Any) -> str:
    base = str(getattr(credentials, "base_url", "") or "")
    if not base:
        return "the model provider"
    host = urlparse(base).netloc
    return host or base


def _announce(out: Any, project: Path, name: str, staged: StagedProject, host: str) -> None:
    kilobytes = max(staged.total_bytes, 1) / 1024
    out.info(
        f"Adopting {project} as template '{name}': "
        f"{len(staged.copied)} files ({kilobytes:.0f} KB) would be sent to {host}."
    )
    if staged.excluded:
        counts = ", ".join(
            f"{len(paths)} {reason}" for reason, paths in sorted(staged.excluded.items())
        )
        out.info(f"Excluded: {counts}.")


def _emit_dry_run(
    ctx: click.Context,
    out: Any,
    project: Path,
    name: str,
    staged: StagedProject,
) -> None:
    fmt = get_formatter(ctx)
    _announce(out, project, name, staged, "the model provider (nothing is sent)")
    if fmt.use_json:
        fmt.print_data(
            {
                "name": name,
                "directory": str(project),
                "dry_run": True,
                "would_send": list(staged.copied),
                "excluded": {key: list(values) for key, values in staged.excluded.items()},
                "bytes": staged.total_bytes,
            }
        )
        return
    out.info("Would send:")
    for path in staged.copied:
        out.info(f"  {path}")
    for reason, paths in sorted(staged.excluded.items()):
        out.info(f"Excluded ({reason}):")
        for path in paths:
            out.info(f"  {path}")
    out.info("Dry run: no files were sent or written.")


def _preview(out: Any, project: Path, plan: AdoptPlan) -> None:
    import difflib

    for rel, content in plan.files.items():
        current = project / rel
        old = current.read_text(encoding="utf-8", errors="replace") if current.is_file() else ""
        if current.is_file():
            diff = "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=rel,
                    tofile=rel,
                )
            )
            out.info(f"~ {rel}")
            _bounded(out, diff or "(no changes)\n")
        else:
            out.info(f"+ {rel}")
            _bounded(out, content)


def _bounded(out: Any, text: str) -> None:
    lines = text.splitlines()
    for line in lines[:_PREVIEW_LINES]:
        out.info(f"  {line}")
    if len(lines) > _PREVIEW_LINES:
        out.info(f"  … {len(lines) - _PREVIEW_LINES} more lines")
