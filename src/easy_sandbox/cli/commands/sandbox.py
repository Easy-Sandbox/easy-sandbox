"""Sandbox lifecycle CLI commands: create, list, info, kill, exec, connect, upload, download."""

from __future__ import annotations

import inspect
import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors
from easy_sandbox.cli.output import get_output
from easy_sandbox.cli.region import region_option

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from easy_sandbox.agent.coding_agent import CodingAgentBackend

# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

# Minimum HTTP timeout (seconds) for the sandbox-create call.  Cold starts
# routinely exceed the 30s transport default — even when the user has
# configured a custom http_timeout in ~/.ebx/config.toml, we enforce this
# floor so that a small configured value doesn't silently kill create.
_CREATE_REQUEST_TIMEOUT_FLOOR = 120.0

#: How many file/status lines a live progress block keeps. The display
#: itself shows only the last ``EBX_ACTIVITY_LINES`` (default 4).
_PROGRESS_NOTE_LIMIT = 10


def _rolling_note(
    update: Callable[[str], None] | None, *, limit: int = _PROGRESS_NOTE_LIMIT
) -> Callable[[str], None]:
    """Return a callback that keeps the last *limit* lines for ``update``.

    ``None`` (quiet, JSON, CI, non-TTY) drops every line. Callers must pass
    names and counters only — never file bytes, tokens, or tool input.
    """
    feed: list[str] = []

    def note(text: str) -> None:
        cleaned = text.strip()
        if update is None or not cleaned:
            return
        feed.append(cleaned)
        del feed[:-limit]
        update("\n".join(feed))

    return note


# ---------------------------------------------------------------------------
# AI template generation helpers for `ebx create "<description>"`
#
# The pipeline talks to a pluggable coding-agent backend (see
# :mod:`easy_sandbox.agent.coding_agent`); Qwen Code is the only shipped
# backend today, so every default message stays byte-identical to the
# Qwen Code wording.  Backend resolution, binary install/repair, and
# credential resolution are shared with the agent-driven deploy route and
# live in :mod:`easy_sandbox.cli.commands._coding_agent`.
# ---------------------------------------------------------------------------


@contextmanager
def _phase_status(out: Any, message: str) -> Iterator[Callable[[str], None] | None]:
    """Phase status for the clarification / generation flow.

    Interactive TTY: an animated spinner on **stderr** (never stdout)
    with the ``message... 12s`` header, and below it the agent's last four
    activity lines in grey (``EBX_ACTIVITY_LINES`` changes the count) that
    scroll line by line — its recent text and the tools it uses, never tool
    input or reasoning.  ``--verbose`` keeps the same block as a
    self-erasing one that log output is written around.  Every other mode (non-TTY, ``--json``): one
    machine-readable progress line on stderr; quiet and CI stay silent.
    stdout is never touched in any mode.

    Yields the ``update(summary)`` callable to hand to the agent as
    ``on_activity``, or ``None`` when no live line is drawn.
    """
    if not out.use_rich_spinner and not out.quiet:
        out.progress(message)
    with out.activity(message) as update:
        yield update


def _activity_kwargs(method: Any, update: Callable[[str], None] | None) -> dict[str, Any]:
    """``{"on_activity": update}`` when *method* accepts it, else ``{}``.

    Keeps third-party / test backends that predate ``on_activity`` working:
    the live line is a progressive enhancement, never a requirement.
    """
    if update is None:
        return {}
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return {}
    accepts = "on_activity" in parameters or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    )
    return {"on_activity": update} if accepts else {}


def _clarify_requirements(
    ctx: click.Context,
    description: str,
    *,
    yes: bool,
    workdir: Path,
    binary: Any,
    env: dict[str, str],
    backend: CodingAgentBackend,
) -> Any:
    """Complete *description* through the research-first clarification loop.

    The research, the evaluation, and the questions all come from the
    coding agent itself, on ONE native session: round 1 runs a plain
    research round (``backend.research`` — the agent settles publicly
    verifiable facts with its own tools before anything is asked)
    followed by the structured assessment (``backend.assess`` with
    ``--json-schema``); every following round resumes the same session
    (``--resume``) with one user answer, so the model keeps the
    description, the research summary, and every Q/A pair in its own
    memory.

    Easy Sandbox keeps only its own surface:

    * the single question per round, numbered ``Question 1``,
      ``Question 2``, … with **no total shown** — the internal round cap
      is a safety bound, mentioned only when reached;
    * the 80% threshold gate (our verdict, not the model's);
    * delegation answers ("你自己决定" / "you decide") — the follow-up
      prompt instructs the agent to settle the delegated choice itself;
    * anti-repetition — asked questions are embedded in every follow-up
      prompt, and an exactly-repeated question breaks the loop;
    * non-interactive fail-fast with the missing details + example;
    * research stays fail-open — a failed round only warns (with the
      outcome's stable ``reason`` hint when the backend provides one)
      and the assessment continues;
    * degradation to direct generation when the assessment is
      unavailable.

    All phase status (assessing / re-assessing / generating) renders on
    **stderr only** (spinner on TTY, machine-readable progress lines
    otherwise); stdout stays clean and the model's research output is
    never echoed.

    Returns a :class:`~easy_sandbox.agent.clarify.ClarifyOutcome`; a
    non-empty ``session_id`` means generation should resume that session.
    """
    from easy_sandbox.agent import clarify
    from easy_sandbox.models.errors import DescriptionClarificationError

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    if yes:
        return clarify.ClarifyOutcome(skipped=True)

    interactive = sys.stdin.isatty() and not fmt.use_json
    session_id = clarify.new_session_id()
    asked: list[str] = []

    def failure_hint(assessment: Any) -> str:
        parts = [f"Missing details: {assessment.missing_summary()}."]
        if assessment.example:
            parts.append(f'Example description: "{assessment.example}".')
        parts.append(
            "Add them to DESCRIPTION, pass --yes/-y to generate from the current "
            "description anyway, or use 'ebx create --template <name>'."
        )
        return " ".join(parts)

    def warn_incomplete(assessment: Any) -> None:
        out.warning(
            f"Description is about {assessment.completeness:.0%} complete; "
            f"missing: {assessment.missing_summary()}. Generating anyway."
        )
        if assessment.example:
            out.info(f'Example description: "{assessment.example}"')

    research_hints = {
        clarify.RESEARCH_REASON_TIMEOUT: (
            "The research round timed out; retry, or continue — the assessment "
            "still applies safe defaults."
        ),
        clarify.RESEARCH_REASON_AGENT_UNAVAILABLE: (
            "The agent could not be started; check that the agent CLI runs, then retry."
        ),
        clarify.RESEARCH_REASON_COMMAND_FAILED: (
            "The agent command failed; re-run with --verbose to inspect the agent's output."
        ),
        clarify.RESEARCH_REASON_TURN_LIMIT: (
            "The research used up its step budget; continuing — the assessment "
            "still applies safe defaults."
        ),
    }

    def research_failure_warning(research: Any) -> str:
        """Warning for a failed research round, with a reason-specific hint.

        The outcome is bool-compatible (legacy backends return a plain
        ``bool``), so the stable ``reason`` attribute is read defensively;
        the sanitised ``detail`` is deliberately not rendered — the
        warning stays terse.
        """
        message = (
            f"{backend.display_name} could not research the public facts "
            "behind the description; continuing with the assessment "
            "(safe defaults apply where facts are missing)."
        )
        reason = getattr(research, "reason", "")
        hint = research_hints.get(reason) if isinstance(reason, str) else None
        return f"{message} {hint}" if hint else message

    # ---- Round 1: research the public facts, then assess (one session) ----
    with _phase_status(out, "Researching public facts") as update:
        research = backend.research(
            clarify.research_prompt(description),
            workdir=workdir,
            binary=binary,
            env=env,
            session_id=session_id,
            **_activity_kwargs(backend.research, update),
        )
    researched = bool(research)
    if not researched:
        out.warning(research_failure_warning(research))
        # The failed round may already have created ``session_id`` in the
        # agent (it rejects re-pinning an existing id with "Session Id ... is
        # already in use"), so the assessment starts a fresh session.
        session_id = clarify.new_session_id()
    with _phase_status(out, "Assessing description") as update:
        assessment = backend.assess(
            clarify.assessment_prompt(description),
            workdir=workdir,
            binary=binary,
            env=env,
            resume=session_id if researched else None,
            session_id=None if researched else session_id,
            **_activity_kwargs(backend.assess, update),
        )
    if assessment is None:
        out.warning(
            f"Could not assess the description completeness with "
            f"{backend.display_name} (assessment unavailable); continuing "
            "straight to generation."
        )
        return clarify.ClarifyOutcome(degraded=True)

    if assessment.complete:
        return clarify.ClarifyOutcome(session_id=session_id, assessment=assessment)

    if not interactive:
        # Non-TTY / JSON / CI: never block — fail fast with the missing
        # details and a ready-to-use example.
        raise DescriptionClarificationError(
            f"The description is about {assessment.completeness:.0%} complete "
            f"(minimum {clarify.CLARITY_THRESHOLD:.0%}) and this session cannot "
            "ask clarifying questions.",
            suggestion=failure_hint(assessment),
        )

    # ---- Interactive: one question per round, same native session ----
    out.info(
        f"Description is about {assessment.completeness:.0%} complete. "
        "I'll ask for the missing details one question at a time — "
        "press Enter to cancel."
    )
    rounds = 0
    repeated = False
    for round_number in range(1, clarify.MAX_CLARIFY_ROUNDS + 1):
        question = assessment.question
        if question is None:  # the model has nothing left to ask
            break
        if question in asked:  # defensive net behind the prompt rule
            repeated = True
            break
        asked.append(question)
        try:
            answer = click.prompt(
                f"Question {round_number}: {question}",
                default="",
                show_default=False,
            )
        except (click.Abort, EOFError):
            raise DescriptionClarificationError(
                "Clarification was interrupted (EOF) before the description was complete.",
                suggestion=failure_hint(assessment),
            ) from None
        if not answer.strip():
            raise DescriptionClarificationError(
                "Clarification was cancelled; no template was generated.",
                suggestion=failure_hint(assessment),
            )
        rounds = round_number
        with _phase_status(out, "Re-assessing description") as update:
            assessment = backend.assess(
                clarify.answer_prompt(answer, asked=asked),
                workdir=workdir,
                binary=binary,
                env=env,
                resume=session_id,
                **_activity_kwargs(backend.assess, update),
            )
        if assessment is None:
            out.warning(
                "The clarification assessment became unavailable; continuing "
                "straight to generation."
            )
            return clarify.ClarifyOutcome(session_id=session_id, degraded=True, rounds=rounds)
        if assessment.complete:
            out.info(f"Description is now about {assessment.completeness:.0%}; generating.")
            break

    if not assessment.complete:
        if repeated:
            out.warning(
                "The agent repeated an already-answered question; generating "
                "with the information collected."
            )
        elif rounds >= clarify.MAX_CLARIFY_ROUNDS:
            out.info(
                f"Reached the {clarify.MAX_CLARIFY_ROUNDS}-question safety "
                "limit; generating with the information collected."
            )
        warn_incomplete(assessment)
    return clarify.ClarifyOutcome(session_id=session_id, assessment=assessment, rounds=rounds)


def _resolve_output_dir(
    ctx: click.Context,
    output_dir: str | None,
    *,
    yes: bool,
    ask: bool,
) -> Path | None:
    """Resolve where the generated template workspace is created (``--dir``).

    The returned path is the **parent** directory: a fresh
    ``<slug>-<timestamp>-<token>`` subdirectory is created inside it, so a
    previous generation (or the user's own files) is never overwritten and
    the SDK wheel that the image build copies in stays inside that subdir.

    * ``--dir`` given → used as is;
    * not given, *ask* is true, and the session is an interactive
      terminal (not ``--yes`` / ``--json``) → one prompt whose default is
      the standard location, so Enter accepts it;
    * otherwise → ``None`` (the standard ``~/.ebx/generated``).

    Nothing is created here: the path is only validated (it must be, or be
    creatable under, a writable directory).

    Raises:
        click.UsageError: The path is a file, cannot be created, or is not
            writable.
    """
    from pathlib import Path

    from easy_sandbox.agent.codegen import default_generated_dir

    default_dir = default_generated_dir()
    chosen = output_dir
    if chosen is None:
        fmt = get_formatter(ctx)
        if not ask or yes or fmt.use_json or not sys.stdin.isatty():
            return None
        home = str(Path.home())
        shown = str(default_dir)
        if shown.startswith(home):
            shown = "~" + shown[len(home) :]
        chosen = click.prompt(
            "Save the generated template under which directory?",
            default=shown,
            err=True,
        )
    chosen = chosen.strip() or str(default_dir)
    target = Path(chosen).expanduser().resolve()
    if target == default_dir.resolve() and output_dir is None:
        return None
    if target.exists() and not target.is_dir():
        raise click.UsageError(f"--dir {chosen!r} exists and is not a directory.")
    # Validate only. The directory is created by the generation step itself
    # (``prepare_workdir``), so an answer typed at the wrong prompt — or a
    # run cancelled before generation — never leaves stray directories behind.
    existing = target
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir():
        raise click.UsageError(f"Cannot create --dir {chosen!r}: {existing} is not a directory.")
    if not os.access(existing, os.W_OK):
        where = "is" if existing == target else f"cannot be created: {existing} is"
        raise click.UsageError(f"--dir {chosen!r} {where} not writable.")
    return target


def _generate_template_workspace(
    ctx: click.Context,
    description: str,
    *,
    yes: bool,
    output_dir: str | None = None,
    ask_output_dir: bool = False,
) -> Any:
    """Clarify *description* and generate the template files.

    The agent writes ``Dockerfile``, the ``commands.py`` HTTP server entry
    point, and ``template.yaml`` (plus README / business code).

    The description first goes through the single-question clarification
    loop (:func:`_clarify_requirements`), which runs on the backend's
    native session (Qwen Code by default); generation then resumes that
    very session so the model keeps the clarification context in its own
    memory.

    Returns the codegen result. Nothing is built, pushed, or deployed.
    """
    from easy_sandbox.cli.commands._coding_agent import (
        ensure_coding_agent_binary,
        resolve_coding_agent_backend,
        resolve_coding_agent_credentials,
    )

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    backend = resolve_coding_agent_backend()
    binary = ensure_coding_agent_binary(ctx, yes=yes, backend=backend)
    creds = resolve_coding_agent_credentials(ctx, yes=yes, backend=backend)
    # Decided before any agent call: sessions are keyed by the working
    # directory, so it must exist (and never change) from research onwards.
    base_dir = _resolve_output_dir(ctx, output_dir, yes=yes, ask=ask_output_dir)
    if base_dir is None:
        workdir, template_name = backend.prepare_workdir(description)
    else:
        workdir, template_name = backend.prepare_workdir(description, base_dir=base_dir)
    outcome = _clarify_requirements(
        ctx,
        description,
        yes=yes,
        workdir=workdir,
        binary=binary,
        env=creds.as_env(),
        backend=backend,
    )

    gen: Any
    with _phase_status(out, "Generating template") as update:
        gen = backend.generate(
            description,
            workdir=workdir,
            template_name=template_name,
            resume_session=outcome.session_id or None,
            binary=binary,
            env=creds.as_env(),
            on_progress=None if out.use_rich_spinner else out.progress,
            **_activity_kwargs(backend.generate, update),
        )
    if not fmt.use_json:
        out.info("")
        out.info(f"\u2713 AI generated template: {gen.template_name}")
        out.info(f"    Dockerfile:    {gen.dockerfile}")
        commands_py = getattr(gen, "commands_py", None)
        if commands_py is not None:
            out.info(f"    commands.py:   {commands_py}")
        out.info(f"    template.yaml: {gen.template_yaml}")
    return gen


def _materialize_local_template(
    gen: Any,
    *,
    name: str | None,
    force: bool,
    directory: Path | None = None,
) -> tuple[Any, list[str]]:
    """Copy the generated template into ``./<name>/`` and return ``(dir, files)``.

    ``--name`` overrides both the directory and the ``name`` field in
    ``template.yaml``. *directory*, when given, is the project directory
    itself (the init prompt). Existing files in the target are left alone
    unless *force* is set.
    """
    import shutil
    from pathlib import Path

    folder = name or gen.template_name
    target = directory if directory is not None else (Path.cwd() / folder).resolve()
    # Every deliverable the agent produced (Dockerfile, commands.py server,
    # template.yaml, README.md, business code, ...); older results only
    # carry the two deployment files.
    filenames = list(getattr(gen, "files", ()) or ("Dockerfile", "template.yaml"))
    if target == Path(gen.workdir).resolve():
        return target, [fn for fn in filenames if (target / fn).is_file()]

    target.mkdir(parents=True, exist_ok=True)
    if not force:
        conflicts = [fn for fn in filenames if (target / fn).exists()]
        if conflicts:
            raise click.ClickException(
                f"Files already exist in {target}: {', '.join(conflicts)}. "
                "Use --force to overwrite."
            )
    for filename in filenames:
        destination = target / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gen.workdir / filename, destination)
    if name and name != gen.template_name:
        _rename_generated_template(target / "template.yaml", name)
    return target, filenames


def _rename_generated_template(template_yaml: Any, name: str) -> None:
    """Set the ``name`` field of a generated ``template.yaml``."""
    import yaml

    data = yaml.safe_load(template_yaml.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    data["name"] = name
    template_yaml.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


#: Shown as the default when the generated folder name is not known yet.
_AUTO_PROJECT_DIR = "./<name>"


def _validate_project_directory(chosen: str, *, force: bool) -> Path:
    """Check *chosen* can become the template project. Do not create it.

    Raises:
        click.UsageError: The path is a file, or cannot be created under a
            writable directory.
        click.ClickException: The directory already holds template files and
            *force* is not set.
    """
    from pathlib import Path

    target = Path(chosen).expanduser().resolve()
    if target.exists() and not target.is_dir():
        raise click.UsageError(f"{chosen!r} exists and is not a directory.")
    existing = target
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir() or not os.access(existing, os.W_OK):
        raise click.UsageError(f"Cannot create {chosen!r}: {existing} is not a writable directory.")
    if target.exists() and not force:
        conflicts = [
            filename
            for filename in ("Dockerfile", "commands.py", "template.yaml")
            if (target / filename).exists()
        ]
        if conflicts:
            raise click.ClickException(
                f"Files already exist in {target}: {', '.join(conflicts)}. "
                "Use --force to overwrite."
            )
    return target


def _prompt_project_directory(
    ctx: click.Context,
    *,
    yes: bool,
    name: str | None,
    force: bool,
) -> Path | None:
    """Ask where ``ebx init "DESCRIPTION"`` should write the project.

    Returns the chosen directory, or ``None`` to keep ``./<name>/`` (or
    ``./<--name>/``). ``--yes``, ``--json``, and a non-interactive terminal
    skip the prompt. Enter accepts the default. Nothing is created here.
    """
    fmt = get_formatter(ctx)
    if yes or fmt.use_json or not sys.stdin.isatty():
        return None
    default = f"./{name}" if name else _AUTO_PROJECT_DIR
    chosen = click.prompt(
        "Directory for the template project",
        default=default,
        err=True,
    )
    chosen = chosen.strip()
    if not chosen or chosen in {default, _AUTO_PROJECT_DIR}:
        return None
    return _validate_project_directory(chosen, force=force)


def _generate_local_template(
    ctx: click.Context,
    description: str,
    *,
    yes: bool,
    name: str | None = None,
    force: bool = False,
    ask_directory: bool = False,
) -> None:
    """Generate a local template project and stop.

    Shared by ``ebx template init "DESCRIPTION"`` and by the create-path
    switch that opts out of build, push, deploy, and sandbox creation.
    *ask_directory* prompts for the project directory before generation
    (init). The create switch keeps ``./<name>/``.
    """
    from easy_sandbox.cli.commands.template import _print_init_summary

    project_dir = (
        _prompt_project_directory(ctx, yes=yes, name=name, force=force) if ask_directory else None
    )
    gen = _generate_template_workspace(ctx, description, yes=yes)
    target, created = _materialize_local_template(
        gen, name=name, force=force, directory=project_dir
    )
    _print_init_summary(
        get_formatter(ctx),
        get_output(ctx),
        target,
        created,
        name or gen.template_name,
    )


def _wants_template_only(
    ctx: click.Context,
    description: str,
    *,
    yes: bool,
) -> bool:
    """Ask whether natural-language create should stop after the local template.

    ``--yes`` and ``--json`` keep the full create pipeline and do not ask.
    A non-interactive terminal gets a one-line reminder and continues; the
    later build confirmation still applies. An interactive terminal must
    opt in — the default is to continue creating the sandbox.
    """
    fmt = get_formatter(ctx)
    if yes or fmt.use_json:
        return False

    hint = (
        "Natural-language create generates a template, then builds and pushes "
        "the image, deploys it, and creates a sandbox. "
        f'Template only: ebx template init "{description}"'
    )
    if not sys.stdin.isatty():
        get_output(ctx).info(hint)
        return False

    click.echo(
        "Natural-language create will:\n"
        "  1. generate a template (Dockerfile, commands.py server, template.yaml)\n"
        "  2. build and push the image\n"
        "  3. deploy the template\n"
        "  4. create a sandbox\n",
        err=True,
    )
    return click.confirm(
        "Switch to template init and only create the local template?",
        default=False,
        err=True,
    )


def _generate_and_deploy_template(
    ctx: click.Context,
    description: str,
    *,
    yes: bool,
    acr_namespace: str | None,
    verbose: bool,
    output_dir: str | None = None,
) -> str:
    """Generate a template with the coding agent, build+deploy it, return its ref.

    *output_dir* is ``--dir``: the parent directory for the generated
    workspace (an interactive terminal is asked when it is omitted).

    Returns the template ID (or name) to pass to ``Sandbox.create``.
    """
    from easy_sandbox.cli.commands.template import do_deploy, resolve_acr_namespace

    gen = _generate_template_workspace(
        ctx, description, yes=yes, output_dir=output_dir, ask_output_dir=True
    )

    if not yes:
        if not sys.stdin.isatty():
            raise click.UsageError(
                "Confirmation required to build and deploy the AI-generated template. "
                "Use --yes/-y to skip in non-interactive mode."
            )
        click.confirm(f"Build and deploy template '{gen.template_name}' now?", abort=True)

    namespace = resolve_acr_namespace(acr_namespace)
    data = do_deploy(str(gen.workdir), acr_namespace=namespace, ctx=ctx, verbose=verbose)
    template_ref = str(data.get("TemplateID") or "").strip()
    if not template_ref or template_ref == "N/A":
        template_ref = gen.template_name
    return template_ref


@click.command()
@click.argument("description", required=False, default=None)
@click.option(
    "--template",
    "-T",
    default=None,
    help="Template ID or alias to launch (e.g. 'base', 'python-hello'). "
    "Defaults to 'base' when omitted. Cannot be combined with DESCRIPTION.",
)
@click.option(
    "--upload",
    "-u",
    type=click.Path(exists=True),
    default=None,
    help="Local file or directory to upload after creation",
)
@click.option(
    "--timeout",
    "-t",
    "cmd_timeout",
    type=int,
    default=None,
    help="Sandbox lifetime in seconds (positive integer; default: global --timeout)",
)
@click.option(
    "--request-timeout",
    type=float,
    default=None,
    help="HTTP request timeout in seconds for the create call "
    "(floor: 120s for cold starts, or your configured http_timeout if larger). "
    "Increase for very slow sandbox creation.",
)
@click.option(
    "--env",
    "-e",
    multiple=True,
    help="Environment variable for the sandbox, format KEY=VALUE (repeatable)",
)
@click.option(
    "--metadata", "-m", multiple=True, help="Metadata key-value pair, format KEY=VALUE (repeatable)"
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip interactive prompts (the template-only switch, Qwen Code install, "
    "credentials, description clarification, build/deploy confirmation) and run "
    "the full create pipeline. Required for AI generation in non-interactive shells.",
)
@click.option(
    "--acr-namespace",
    envvar="ACR_NAMESPACE",
    default=None,
    help="ACR namespace for building the AI-generated template "
    "(env: ACR_NAMESPACE, or set in .env file)",
)
@click.option(
    "--dir",
    "output_dir",
    default=None,
    metavar="DIRECTORY",
    help="Parent directory for the AI-generated template files (Dockerfile, "
    "commands.py, template.yaml); a new <name>-<timestamp>-<id> subfolder is created inside it. "
    "Default: ~/.ebx/generated (an interactive terminal is asked when omitted).",
)
@click.option("-v", "--verbose", "verbose_flag", is_flag=True, help="Verbose output (DEBUG level)")
@click.pass_context
@handle_errors
def create(
    ctx: click.Context,
    description: str | None,
    template: str | None,
    upload: str | None,
    cmd_timeout: int | None,
    request_timeout: float | None,
    env: tuple[str, ...],
    metadata: tuple[str, ...],
    yes: bool,
    acr_namespace: str | None,
    output_dir: str | None,
    verbose_flag: bool,
) -> None:
    """Create a new sandbox.

    Exactly one route is taken, and it must be explicit:

    \b
      ebx create --template base  →  launch the 'base' template
      ebx create --template NAME  →  launch NAME directly (no AI)
      ebx create "DESCRIPTION"    →  Qwen Code generates a template, builds
                                    and deploys it, then launches a sandbox;
                                    the agent researches public facts first
                                    and asks only for details it cannot infer.
                                    An interactive terminal is first asked
                                    whether to switch to template init
                                    (local files only)

    DESCRIPTION and --template are mutually exclusive: passing both is
    rejected instead of silently ignoring one of them.

    \b
    Examples:
      ebx create --template base              # explicit 'base' template
      ebx create --template python-hello      # named template (no AI)
      ebx create -e API_KEY=xxx -e DEBUG=1    # inject env vars
      ebx create --upload ./app --timeout 600 # upload dir, 10-min lifetime
      ebx create "a python data science env"  # AI-generate, build, deploy, create
      ebx create -y "a node.js api server"    # non-interactive full pipeline
      ebx template init "a python data science env"  # template files only

    \b
    Notes:
      AI generation needs the Qwen Code CLI and a DashScope/ModelStudio key
      ('ebx config init'). The agent researches publicly verifiable facts
      itself (tool stack, official install method, common dependencies) and
      only asks for private preferences or business decisions it cannot
      infer — one question at a time in interactive sessions. Non-interactive
      shells must pass --yes to generate without asking. Interactive
      sessions are asked up front whether to switch to template init,
      which writes Dockerfile, commands.py, and template.yaml and stops
      before build, push, deploy, and sandbox create. --yes skips that
      question and runs the full pipeline.

    \b
    Related commands:
      ebx list                 List existing sandboxes
      ebx info SANDBOX_ID      Inspect a created sandbox
      ebx template init DIR    Scaffold a new template project (local)
      ebx template init "DESC" AI-scaffold a template only (no build)
      ebx template search KEY  Find reusable templates
      ebx config init          Configure platform and Qwen Code credentials
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    if verbose_flag:
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)

    # Routing guard: one of the three routes must be explicit.  An
    # implicit 'base' fallback made ``ebx create`` with no arguments easy
    # to trigger by accident (e.g. a dropped argument), so require an
    # explicit choice and show all three paths instead.  Emitted directly
    # on stderr with exit code 2 (usage-error contract) instead of raising
    # ``click.UsageError``, which ``handle_errors`` would re-wrap to exit 1.
    if not description and not template:
        click.echo(
            "Error: No DESCRIPTION or --template given. Choose one of:\n\n"
            "  ebx create --template base       launch the explicit base template\n"
            "  ebx create --template <NAME>     launch an existing template (no AI)\n"
            '  ebx create "<DESCRIPTION>"      AI-generate, build, deploy, create',
            err=True,
        )
        sys.exit(2)

    # Routing guard: DESCRIPTION and --template are mutually exclusive.
    # Accepting both while silently dropping one of them would be surprising,
    # so reject the combination before any AI generation or network call.
    if description and template:
        raise click.UsageError(
            "DESCRIPTION and --template cannot be combined. Drop --template to "
            "generate a template from the description, or drop DESCRIPTION to "
            "launch an existing template directly."
        )

    if output_dir and not description:
        raise click.UsageError(
            "--dir only applies to AI template generation; pass a DESCRIPTION, "
            "or drop --dir when launching an existing template."
        )

    fmt = get_formatter(ctx)

    # ---- AI template generation when description given and --template omitted --
    effective_template = template or "base"
    if description and not template:
        if _wants_template_only(ctx, description, yes=yes):
            if output_dir:
                get_output(ctx).warning(
                    "--dir is ignored for template-only generation; the files are "
                    "written to ./<name>/."
                )
            _generate_local_template(ctx, description, yes=yes)
            return
        effective_template = _generate_and_deploy_template(
            ctx,
            description,
            yes=yes,
            acr_namespace=acr_namespace,
            verbose=verbose_flag,
            output_dir=output_dir,
        )
        if not fmt.use_json:
            out = get_output(ctx)
            if not out.use_rich_spinner:
                # The spinner below already announces creation in TTY mode;
                # only print the plain progress line in degraded modes.
                out.progress("Creating...")

    # Parse env vars from "KEY=VALUE" format
    envs: dict[str, str] = {}
    for item in env:
        if "=" in item:
            k, v = item.split("=", 1)
            envs[k] = v
        else:
            fmt.print_error(f"Invalid environment variable format: {item!r} (expected KEY=VALUE)")
            sys.exit(2)

    # Parse metadata from "KEY=VALUE" format
    meta: dict[str, str] = {}
    for item in metadata:
        if "=" in item:
            k, v = item.split("=", 1)
            meta[k] = v
        else:
            fmt.print_error(f"Invalid metadata format: {item!r} (expected KEY=VALUE)")
            sys.exit(2)

    # Build create kwargs
    create_kwargs: dict[str, Any] = {"template": effective_template}
    if cmd_timeout is not None:
        create_kwargs["timeout"] = cmd_timeout
    else:
        create_kwargs["timeout"] = ctx.obj.get("timeout", 300)
    if envs:
        create_kwargs["envs"] = envs
    if meta:
        create_kwargs["metadata"] = meta

    # HTTP timeout for the create call: sandbox creation (cold start) is
    # known to be slow, so we always enforce a floor of 120s.  If the user
    # configured a *larger* http_timeout (e.g. 300s) that is respected;
    # if they configured a *smaller* value (e.g. 30s) or left the default,
    # we bump to the floor.  --request-timeout always wins when provided.
    if request_timeout is not None:
        create_kwargs["request_timeout"] = request_timeout
    else:
        from easy_sandbox.transport.config import load_config as _load_cfg

        configured = _load_cfg().http_timeout
        create_kwargs["request_timeout"] = max(configured, _CREATE_REQUEST_TIMEOUT_FLOOR)

    out = get_output(ctx)

    def _run_create(note: Callable[[str], None] | None) -> Any:
        async def _create_and_upload() -> Any:
            sbx = await Sandbox.create(**create_kwargs)
            if upload:
                from pathlib import Path

                local = Path(upload)
                remote_base = "/home/user"
                if local.is_file():
                    dest = f"{remote_base}/{local.name}"
                    await sbx.files.write(dest, local.read_bytes())
                    if note is not None:
                        note(local.name)
                    if not fmt.use_json:
                        out.info(f"↑ Uploaded {upload} → {dest}")
                elif local.is_dir():
                    count = 0
                    for file in local.rglob("*"):
                        if file.is_file():
                            rel = file.relative_to(local)
                            dest = f"{remote_base}/{rel}"
                            await sbx.files.write(dest, file.read_bytes())
                            count += 1
                            if note is not None:
                                note(str(rel))
                    if not fmt.use_json:
                        out.info(f"↑ Uploaded {count} file(s) → {remote_base}/")
            return sbx

        return run_sync(_create_and_upload())

    if upload:
        with out.activity("Creating sandbox", tick=True) as update:
            sandbox = _run_create(_rolling_note(update))
    else:
        with out.spinner("Creating sandbox"):
            sandbox = _run_create(None)

    data = {
        "ID": sandbox.id,
        "Status": sandbox.status.value,
        "Template": sandbox.info.template,
        "URL": sandbox.url,
    }
    if sandbox.info.envd_version:
        data["EnvdVersion"] = sandbox.info.envd_version
    # Result channel (task 167): the machine-consumable document goes to
    # stdout; the success notice is skipped in --json mode so that stdout
    # stays a single parseable JSON document.
    out.data(data)
    if not out.json_mode:
        out.success(f"Sandbox {sandbox.id} created successfully.")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@click.command("list")
@click.option(
    "--status",
    "-s",
    type=click.Choice(["running", "stopped", "creating", "paused", "error"]),
    default=None,
    help="Filter by status",
)
@click.option(
    "--limit", "-l", type=int, default=20, help="Maximum results (positive integer; default: 20)"
)
@region_option
@click.pass_context
@handle_errors
def list_cmd(ctx: click.Context, status: str | None, limit: int, region: str | None) -> None:
    """List sandboxes, optionally filtered by lifecycle status.

    \b
    Examples:
      ebx list
      ebx list --status running
      ebx list --status error --limit 50
      ebx list --region cn-shanghai

    \b
    Related commands:
      ebx info SANDBOX_ID  Show one sandbox in detail
      ebx create           Create a new sandbox
      ebx kill SANDBOX_ID  Destroy a sandbox
    """
    from easy_sandbox.models.sandbox import SandboxStatus
    from easy_sandbox.protocol.sandbox import SandboxProtocol
    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    config = load_config(region=region)
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)
    proto = SandboxProtocol(http_client)

    sb_status = SandboxStatus(status) if status else None
    sandboxes = run_sync(proto.list(status=sb_status, limit=limit))

    if not sandboxes:
        fmt.print_success("No sandboxes found.")
        return

    headers = ["ID", "Template", "Status", "Region"]
    rows = [[sb.sandbox_id, sb.template, sb.status.value, sb.region] for sb in sandboxes]
    fmt.print_table(headers, rows)


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


@click.command()
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def info(ctx: click.Context, sandbox_id: str) -> None:
    """Show status, template, region, timeout, and URL for a sandbox.

    \b
    Examples:
      ebx info abc123
      ebx --json info abc123

    \b
    Related commands:
      ebx list                  Find sandbox IDs
      ebx sandbox capabilities  Show declared capability groups
      ebx exec SANDBOX_ID CMD   Run a command in the sandbox
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    sandbox = run_sync(Sandbox.connect(sandbox_id))
    sb_info = sandbox.info

    data: dict[str, Any] = {
        "ID": sb_info.sandbox_id,
        "Template": sb_info.template,
        "Status": sb_info.status.value,
        "Region": sb_info.region,
        "Timeout": f"{sb_info.timeout}s",
        "URL": sb_info.envd_url or "N/A",
    }
    if sb_info.envd_version:
        data["EnvdVersion"] = sb_info.envd_version
    if sb_info.started_at:
        data["Started"] = str(sb_info.started_at)
    if sb_info.metadata:
        data["Metadata"] = str(sb_info.metadata)

    fmt.print_dict(data)


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------


@click.command()
@click.argument("sandbox_id", required=False)
@click.option("--all", "kill_all", is_flag=True, help="Kill all running sandboxes")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@region_option
@click.pass_context
@handle_errors
def kill(
    ctx: click.Context, sandbox_id: str | None, kill_all: bool, yes: bool, region: str | None
) -> None:
    """Permanently destroy one sandbox or all running sandboxes.

    Confirmation is required unless --yes is supplied. Use --yes for scripts
    and other non-interactive environments.

    \b
    Examples:
      ebx kill abc123
      ebx kill abc123 --yes
      ebx kill --all --yes
      ebx kill --all --yes --region cn-shanghai

    \b
    Related commands:
      ebx list              Find running sandbox IDs
      ebx info SANDBOX_ID   Verify a sandbox before deletion
      ebx create            Create a replacement sandbox
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.models.sandbox import SandboxStatus
    from easy_sandbox.protocol.sandbox import SandboxProtocol
    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    if not kill_all and not sandbox_id:
        fmt.print_error(
            "Either provide a sandbox ID or use --all.",
            suggestion="Usage: ebx kill <sandbox-id> or ebx kill --all",
        )
        sys.exit(2)

    if kill_all:
        config = load_config(region=region)
        auth = create_auth_provider(
            api_key=config.api_key,
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
        )
        http_client = HttpClient(config, auth)
        proto = SandboxProtocol(http_client)
        sandboxes = run_sync(proto.list(status=SandboxStatus.RUNNING))

        if not sandboxes:
            fmt.print_success("No running sandboxes to kill.")
            return

        if not yes:
            if not sys.stdin.isatty():
                raise click.UsageError(
                    "Confirmation required for killing all sandboxes. "
                    "Use --yes/-y to skip in non-interactive mode."
                )
            click.confirm(f"Kill all {len(sandboxes)} running sandbox(es)?", abort=True)

        async def _connect_and_kill(sid: str) -> None:
            sbx = await Sandbox.connect(sid)
            await sbx.kill()

        out = get_output(ctx)
        killed = 0
        total = len(sandboxes)
        with out.activity(f"Killing {total} sandbox(es)", tick=True) as update:
            note = _rolling_note(update)
            for index, sb in enumerate(sandboxes, start=1):
                note(f"{index}/{total} {sb.sandbox_id}")
                try:
                    run_sync(_connect_and_kill(sb.sandbox_id))
                    killed += 1
                except Exception as exc:
                    fmt.print_error(f"Failed to kill {sb.sandbox_id}: {exc}")

        fmt.print_success(f"Killed {killed}/{total} sandbox(es).")
    else:
        if not yes:
            click.confirm(f"Kill sandbox {sandbox_id}?", abort=True)

        async def _connect_and_kill(sid: str) -> None:
            sbx = await Sandbox.connect(sid)
            await sbx.kill()

        with get_output(ctx).spinner(f"Killing sandbox {sandbox_id}"):
            run_sync(_connect_and_kill(sandbox_id))  # type: ignore[arg-type]

        fmt.print_success(f"Sandbox {sandbox_id} killed.")


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------


@click.command("exec")
@click.argument("sandbox_id")
@click.argument("command")
@click.option(
    "--timeout",
    "-t",
    "cmd_timeout",
    type=int,
    default=60,
    help="Command timeout in seconds (positive integer; default: 60)",
)
@click.option("--cwd", default="", help="Working directory (empty = container default)")
@click.option("-v", "--verbose", "verbose_flag", is_flag=True, help="Verbose output (DEBUG level)")
@click.pass_context
@handle_errors
def exec_cmd(
    ctx: click.Context,
    sandbox_id: str,
    command: str,
    cmd_timeout: int,
    cwd: str,
    verbose_flag: bool,
) -> None:
    """Execute one command in a sandbox and return its exit code.

    Quote commands containing spaces or shell operators. Use --cwd to select
    the remote working directory and --timeout for long-running commands.

    \b
    Examples:
      ebx exec abc123 "python --version"
      ebx exec abc123 "pytest -q" --cwd /app --timeout 300
      ebx --json exec abc123 "echo ready"

    \b
    Related commands:
      ebx connect SANDBOX_ID  Open the command REPL
      ebx sandbox shell-stream SANDBOX_ID -c CMD
      ebx run SANDBOX_ID NAME  Run a registered custom command
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    if verbose_flag:
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)

    fmt = get_formatter(ctx)

    async def _connect_and_exec() -> Any:
        sandbox = await Sandbox.connect(sandbox_id)
        return await sandbox.commands.run(command, timeout=cmd_timeout, cwd=cwd)

    result = run_sync(_connect_and_exec())

    if fmt.use_json:
        fmt.print_data(
            {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
            }
        )
    else:
        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.stderr:
            click.echo(result.stderr, err=True, nl=False)

    sys.exit(result.exit_code)


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


@click.command()
@click.argument("sandbox_id")
@click.pass_context
@handle_errors
def connect(ctx: click.Context, sandbox_id: str) -> None:
    """Open an interactive command REPL for a sandbox.

    This is a line-based REPL, not a PTY or a full SSH session: every entered
    line runs in a new process with a 30-second timeout, and no shell state
    survives between lines - ``cd``, environment variables and aliases are
    gone after each command (use ``cd /path && <cmd>`` on one line, or
    ``ebx exec --cwd``, instead).

    On interactive terminals basic line editing and command history are
    enabled (Up/Down history, Ctrl+R search, Ctrl+A/E and friends).  Type
    ``exit``/``quit`` or press Ctrl+D to leave; Ctrl+C also disconnects.
    Failed commands are reported as one friendly message - never as raw
    HTTP errors.

    \b
    Examples:
      ebx connect abc123
      ebx sandbox connect abc123

    \b
    Related commands:
      ebx exec SANDBOX_ID CMD  Run one command with a custom timeout
      ebx info SANDBOX_ID      Inspect connection details
      ebx sandbox shell-stream SANDBOX_ID -c CMD
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.cli.repl import (
        REPL_TIMEOUT,
        describe_command_failure,
        enable_line_editing,
        program_name,
    )
    from easy_sandbox.utils.async_bridge import run_sync

    async def _connect() -> None:
        sandbox = await Sandbox.connect(sandbox_id)
        out = get_output(ctx)
        out.success(f"Connected to sandbox {sandbox_id}")
        out.info("Type 'exit' or Ctrl+D to disconnect")
        out.info(
            "Note: each line runs in an independent process - cd, environment "
            "variables and shell state do not persist"
        )
        enable_line_editing()

        # Executables observed in this session, used only as a reliable
        # source for "did you mean" hints (never a guess about the image).
        known_commands: set[str] = set()

        while True:
            try:
                cmd = input(f"ebx:{sandbox_id[:8]}> ")
            except (EOFError, KeyboardInterrupt):
                out.info("\nDisconnected.")
                break

            cmd = cmd.strip()
            if not cmd:
                continue
            if cmd in ("exit", "quit"):
                out.info("Disconnected.")
                break

            try:
                # Hardcoded 30s timeout for interactive commands to prevent
                # indefinite hangs; long-running tasks should use 'ebx exec'
                # with an explicit --timeout instead.
                result = await sandbox.commands.run(cmd, timeout=REPL_TIMEOUT)
                if result.stdout:  # type: ignore[union-attr]
                    click.echo(result.stdout, nl=False)  # type: ignore[union-attr]
                if result.stderr:  # type: ignore[union-attr]
                    click.echo(result.stderr, nl=False, err=True)  # type: ignore[union-attr]
                # 126/127 mean "not executable / not found" - a shell wrapper
                # may report the failure while the program does not exist.
                if result.exit_code not in (126, 127):  # type: ignore[union-attr]
                    name = program_name(cmd)
                    if name:
                        known_commands.add(name)
            except Exception as exc:
                # One friendly message per failure: a raw exception string
                # could leak the sandbox URL / an MDN link, and logging it as
                # a warning on top would repeat the same information.
                failure = describe_command_failure(
                    exc,
                    command=cmd,
                    timeout=REPL_TIMEOUT,
                    known_commands=known_commands,
                )
                out.error(failure.message, code=failure.code, suggestion=failure.suggestion)

    run_sync(_connect())


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------


@click.command()
@click.argument("sandbox_id")
@click.argument("local_path", type=click.Path(exists=True))
@click.argument("remote_path")
@click.pass_context
@handle_errors
def upload(ctx: click.Context, sandbox_id: str, local_path: str, remote_path: str) -> None:
    """Upload a local file or directory to the sandbox.

    Examples:\n
        ebx upload abc123 ./script.py /app/script.py\n
        ebx upload abc123 ./data/ /app/data/

    \b
    Related commands:
      ebx download SANDBOX_ID REMOTE_PATH LOCAL_PATH
      ebx sandbox files list SANDBOX_ID --path /app
      ebx exec SANDBOX_ID CMD
    """
    from pathlib import Path

    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    def _run_upload(note: Callable[[str], None]) -> str:
        async def _connect_and_upload() -> str:
            sandbox = await Sandbox.connect(sandbox_id)
            local = Path(local_path)

            if local.is_file():
                await sandbox.files.write(remote_path, local.read_bytes())
                note(Path(remote_path).name)
                return f"Uploaded {local_path} -> {remote_path}"
            if local.is_dir():
                count = 0
                for file in local.rglob("*"):
                    if file.is_file():
                        rel = file.relative_to(local)
                        dest = f"{remote_path.rstrip('/')}/{rel}"
                        await sandbox.files.write(dest, file.read_bytes())
                        count += 1
                        note(str(rel))
                return f"Uploaded {count} files from {local_path} -> {remote_path}"
            return ""

        return run_sync(_connect_and_upload())

    # Directory uploads can sit for a long time. On a terminal the header
    # keeps the elapsed time moving and the grey lines name each file
    # (never the bytes). Quiet / JSON / CI / non-TTY stay silent here; the
    # success line below is the only result.
    with out.activity(f"Uploading {local_path}", tick=True) as update:
        message = _run_upload(_rolling_note(update))
    if message:
        fmt.print_success(message)


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


@click.command()
@click.argument("sandbox_id")
@click.argument("remote_path")
@click.argument("local_path", type=click.Path())
@click.pass_context
@handle_errors
def download(ctx: click.Context, sandbox_id: str, remote_path: str, local_path: str) -> None:
    """Download a file from the sandbox to local.

    Examples:\n
        ebx download abc123 /app/result.csv ./result.csv\n
        ebx download abc123 /app/output.log .

    \b
    Related commands:
      ebx upload SANDBOX_ID LOCAL_PATH REMOTE_PATH
      ebx sandbox files stat SANDBOX_ID --path REMOTE_PATH
      ebx sandbox files list SANDBOX_ID --path REMOTE_DIR
    """
    from pathlib import Path

    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    async def _connect_and_download() -> bytes:
        sandbox = await Sandbox.connect(sandbox_id)
        return await sandbox.files.read_bytes(remote_path)

    with out.spinner(f"Downloading {remote_path}"):
        content = run_sync(_connect_and_download())

    local = Path(local_path)
    if local.is_dir():
        filename = remote_path.rsplit("/", 1)[-1]
        local = local / filename

    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(content)
    fmt.print_success(f"Downloaded {remote_path} -> {local}")


# ---------------------------------------------------------------------------
# run (custom command)
# ---------------------------------------------------------------------------


@click.command(
    "run",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.argument("sandbox_id")
@click.argument("command_name")
@click.option(
    "--arg",
    "-a",
    "args",
    multiple=True,
    help="Command argument as key=value (repeatable, legacy style)",
)
@click.pass_context
@handle_errors
def run_cmd(
    ctx: click.Context,
    sandbox_id: str,
    command_name: str,
    args: tuple[str, ...],
) -> None:
    """Run a named custom command or registered command.

    Supports two argument styles:

    \b
    Legacy:  ebx run <id> <cmd> --arg key=value
    New:     ebx run <id> <cmd> --key value

    When the command comes from @sandbox.register, typed options
    (--x, --y, ...) are derived automatically from the function signature.

    Examples:\n
        ebx run abc123 dev\n
        ebx run abc123 test --arg file=tests/\n
        ebx run abc123 demo --x 1 --y hello

    \b
    Related commands:
      ebx exec SANDBOX_ID CMD  Run an arbitrary shell command
      ebx info SANDBOX_ID      Inspect the target sandbox
      ebx template info ID     Inspect a template definition
    """
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    # -- Parse arguments --------------------------------------------------
    kwargs: dict[str, str] = {}

    # Legacy --arg key=value
    for item in args:
        if "=" in item:
            k, v = item.split("=", 1)
            kwargs[k] = v
        else:
            fmt.print_error(
                f"Invalid argument format: {item!r} (expected key=value)",
            )
            sys.exit(2)

    # New-style --key value from extra args
    kwargs.update(_parse_extra_args(ctx.args, fmt))

    # -- Connect and dispatch ----------------------------------------------
    async def _connect_and_run() -> None:
        from easy_sandbox.models.errors import CommandNotFoundError

        sandbox = await Sandbox.connect(sandbox_id)

        # server_port is a reserved kwarg controlling mechanism-B routing;
        # it is never forwarded as a command argument.
        port = 9000
        if "server_port" in kwargs:
            try:
                port = int(kwargs.pop("server_port"))
            except ValueError:
                fmt.print_error("server_port must be an integer")
                sys.exit(2)

        # sandbox.custom() resolves template commands (A) then falls back to
        # the in-sandbox SandboxServer registry (B), returning a unified
        # CommandResult.  This preserves the historic `ebx run` A→B routing.
        try:
            result = await sandbox.custom(command_name, server_port=port, **kwargs)
        except CommandNotFoundError as exc:
            fmt.print_error(str(exc))
            sys.exit(2)
        except ValueError as exc:
            fmt.print_error(str(exc))
            sys.exit(2)

        if result.source == "server":
            # Mechanism B: print the function's JSON return value.
            if fmt.use_json:
                fmt.print_data({"result": result.value})
            else:
                click.echo(result.value)
            sys.exit(0 if result.success else 1)

        # Mechanism A: print process stdout/stderr like the old template path.
        _print_process_result(fmt, result)
        sys.exit(result.exit_code)

    run_sync(_connect_and_run())


# ---------------------------------------------------------------------------
# run_cmd helpers
# ---------------------------------------------------------------------------


def _parse_extra_args(
    extra: list[str],
    fmt: Any,
) -> dict[str, str]:
    """Parse Click extra-args (``--key value`` pairs) into a dict."""
    kwargs: dict[str, str] = {}
    i = 0
    while i < len(extra):
        arg = extra[i]
        if arg.startswith("--"):
            key = arg[2:]
            if not key:
                fmt.print_error("Empty option name: '--'")
                sys.exit(2)
            # Next token is the value unless it's another option
            if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
                kwargs[key] = extra[i + 1]
                i += 2
            else:
                # Treat as boolean flag
                kwargs[key] = "true"
                i += 1
        else:
            fmt.print_error(f"Unexpected positional argument: {arg!r}")
            sys.exit(2)
    return kwargs


def _print_process_result(fmt: Any, result: Any) -> None:
    """Print a :class:`ProcessResult` using *fmt*."""
    if fmt.use_json:
        fmt.print_data(
            {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
            }
        )
    else:
        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.stderr:
            click.echo(result.stderr, err=True, nl=False)


def _discover_registered_commands() -> None:
    """Best-effort: scan ``*.py`` in *cwd* for ``@sandbox.register``.

    Files containing the literal ``sandbox.register`` are imported so that
    registrations are triggered on the module-level ``sandbox`` singleton.
    Failures are silently ignored.

    **Opt-in behaviour**  (security hardening):

    Discovery is gated behind an explicit opt-in to prevent accidental
    code-execution when the CLI is invoked from an untrusted directory.
    At least one of the following conditions must hold:

    * The ``EBX_DISCOVER_COMMANDS`` environment variable is set to a truthy
      value (``1``, ``true``, ``yes``).
    * A ``.ebx`` marker file or directory exists in the current working
      directory, indicating a trusted Easy-Sandbox project root.

    When neither condition is satisfied the function returns immediately
    without scanning.

    SECURITY NOTE
    -------------
    Matched Python files are *executed* during ``importlib`` loading.
    Only enable discovery in project directories whose ``.py`` files you
    trust.  The scan is limited to top-level files in ``cwd`` (no
    recursive descent) and only files whose names are valid Python
    identifiers are considered.
    """
    import importlib.util
    import logging
    import re
    from pathlib import Path

    _log = logging.getLogger(__name__)

    # ---- Opt-in gate -------------------------------------------------------
    _truthy = frozenset({"1", "true", "yes"})
    env_flag = os.environ.get("EBX_DISCOVER_COMMANDS", "").strip().lower()
    cwd = Path.cwd()
    marker_exists = (cwd / ".ebx").exists()

    if env_flag not in _truthy and not marker_exists:
        _log.debug(
            "Skipping command discovery: set EBX_DISCOVER_COMMANDS=1 "
            "or create a .ebx marker in the project root to enable."
        )
        return

    # ---- Safe filename filter -----------------------------------------------
    safe_stem = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    for py_file in sorted(cwd.glob("*.py")):
        if not safe_stem.match(py_file.stem):
            _log.debug("Skipping %s: stem is not a valid Python identifier", py_file.name)
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            if "sandbox.register" not in text:
                continue
            module_name = f"_ebx_discover_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
        except Exception:
            _log.debug("Failed to import %s during command discovery", py_file.name, exc_info=True)
            continue


# ---------------------------------------------------------------------------
# sandbox group (ebx sandbox list/info/kill/...)
# ---------------------------------------------------------------------------


@click.group()
@click.pass_context
def sandbox(ctx: click.Context) -> None:
    """Manage sandbox lifecycle, files, processes, and system details.

    Lifecycle commands are also available as shorter top-level aliases.

    \b
    Examples:
      ebx sandbox create --template base
      ebx sandbox list --status running
      ebx sandbox system info abc123

    \b
    Related commands:
      ebx sandbox files --help    Inspect and modify remote files
      ebx sandbox process --help  Inspect and control processes
      ebx sandbox system --help   Inspect runtime system details
    """
    ctx.ensure_object(dict)


sandbox.add_command(create)
sandbox.add_command(list_cmd, "list")
sandbox.add_command(info)
sandbox.add_command(kill)
sandbox.add_command(exec_cmd, "exec")
sandbox.add_command(connect)
sandbox.add_command(upload)
sandbox.add_command(download)
sandbox.add_command(run_cmd, "run")

# Sub-groups for extended server capabilities
from easy_sandbox.cli.commands.sandbox_files import files  # noqa: E402
from easy_sandbox.cli.commands.sandbox_process import process  # noqa: E402
from easy_sandbox.cli.commands.sandbox_system import (  # noqa: E402
    capabilities,
    shell_stream,
    system,
)

sandbox.add_command(files, "files")
sandbox.add_command(process, "process")
sandbox.add_command(system, "system")
sandbox.add_command(capabilities, "capabilities")
sandbox.add_command(shell_stream, "shell-stream")
