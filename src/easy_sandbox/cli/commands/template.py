"""Template management CLI commands."""

from __future__ import annotations

import os
import shutil
import sys
import threading
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors
from easy_sandbox.cli.output import get_output, is_ci_env
from easy_sandbox.cli.region import region_option

if TYPE_CHECKING:
    from collections.abc import Callable


#: Shared help for the three ``--token`` options (task 206). The persistent
#: ``ebx config set github_token`` flow is recommended; the flag remains a
#: temporary override with an explicit leak warning.
_GITHUB_TOKEN_HELP = (
    "GitHub token for private repos / higher rate limits. Prefer "
    "'ebx config set github_token' (masked input, stored once in ~/.ebx/.env); "
    "--token is a temporary override that may leak into shell history and the "
    "process list (env: GITHUB_TOKEN)."
)


def _extract_platform_error(resp: Any) -> str:
    """Extract a human-readable error message from a Platform error response.

    Prefers JSON body common error fields, falls back to raw text or status code.
    """
    try:
        data = resp.json()
    except Exception:
        text = (resp.text or "").strip()
        return text or f"HTTP {resp.status_code}"
    if isinstance(data, dict):
        for key in (
            "error",
            "message",
            "Message",
            "ErrorMessage",
            "errorMessage",
            "detail",
        ):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return str(data)
    if isinstance(data, str) and data.strip():
        return data.strip()
    return f"HTTP {resp.status_code}"


def _translate_platform_error(
    exc: Any,
    *,
    context: str,
    template_id: str | None = None,
) -> Exception:
    """Map a Platform httpx.HTTPStatusError to a friendly SandboxError.

    - 404 with template_id → TemplateNotFoundError (suggest checking TEMPLATE_ID);
    - Other status codes → NetworkError with "check auth/platform status" suggestion.
    """
    from easy_sandbox.models.errors import NetworkError, TemplateNotFoundError

    resp = exc.response
    status = resp.status_code
    detail = _extract_platform_error(resp)
    if status == 404 and template_id is not None:
        return TemplateNotFoundError(
            f"Template '{template_id}' not found on the platform: {detail}",
            suggestion=(
                "Check the TEMPLATE_ID (run 'ebx template list' to see available templates)."
            ),
        )
    return NetworkError(
        f"{context} failed (HTTP {status}): {detail}",
        suggestion=(
            "Check your authentication (ebx auth / API key) and the platform status, then retry."
        ),
    )


def _find_template_yaml(template_path: Any) -> Any:
    """Return the template manifest path, or ``None`` if none is present.

    Prefers ``template.yaml`` and falls back to the legacy
    ``sandbox-template.yaml`` / ``sandbox.yaml`` names.
    """
    from pathlib import Path

    base = Path(template_path)
    for name in ("template.yaml", "sandbox-template.yaml", "sandbox.yaml"):
        candidate = base / name
        if candidate.exists():
            return candidate
    return None


def _read_yaml_defaults(template_dir: str) -> dict[str, Any]:
    """Read template.yaml and extract default values for cpu, memory, name.

    Returns a dict with keys 'name', 'cpu', 'memory' (values may be None).
    A missing manifest is normal and yields an empty dict silently; a
    malformed manifest or unexpected read error prints a warning on stderr
    so users learn why their declared cpu/memory were ignored.
    """
    yaml_path = _find_template_yaml(template_dir)
    if yaml_path is None:
        return {}
    try:
        import yaml

        with open(yaml_path, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
        resources = yaml_data.get("resources", {}) or {}
        return {
            "name": yaml_data.get("name"),
            "cpu": (
                resources.get("cpu")
                if resources.get("cpu") is not None
                else yaml_data.get("cpu_count")
            ),
            "memory": (
                resources.get("memory")
                if resources.get("memory") is not None
                else yaml_data.get("memory_mb")
            ),
            "generation": yaml_data.get("generation"),
        }
    except OSError:
        # A missing or unreadable manifest is normal — no defaults.
        return {}
    except Exception as e:  # includes yaml.YAMLError and any parse failure
        click.echo(f"Warning: Failed to parse template.yaml: {e}", err=True)
        return {}


def _resolve_index_name(
    name: str,
    *,
    token: str | None,
    fmt: Any,
    out: Any,
) -> str:
    """Resolve a bare template name through the remote template index (SSOT).

    The catalog lives in ``Easy-Sandbox/awesome-templates``; its index maps
    names to concrete ``owner/repo//subdir@ref`` references (with version
    pins where the entry declares ``ref``).  Returns the concrete registry
    ref.  When the cached index does not know the name and is not stale, a
    single forced refresh runs so freshly published templates resolve
    immediately.

    Raises:
        TemplateNotFoundError: the name is not in the index.
        NetworkError: the index is unreachable and no cache exists.
    """
    from easy_sandbox.models.errors import TemplateNotFoundError
    from easy_sandbox.utils.async_bridge import run_sync
    from easy_sandbox.utils.template_index import fetch_index

    index = run_sync(fetch_index(token=token))
    entry = index.find(name)
    if entry is None and not index.stale:
        # The cache may predate a freshly published template - refresh once.
        index = run_sync(fetch_index(token=token, force=True))
        entry = index.find(name)
    if index.notice:
        out.warning(index.notice)
    if entry is None:
        raise TemplateNotFoundError(
            f"Template '{name}' is not a built-in template and was not found in the "
            f"template index ({index.source_url}).",
            suggestion=(
                "Run 'ebx template search <query>' to browse the index, or install "
                "directly from a repository: 'ebx template install owner/repo//subdir[@ref]'."
            ),
        )
    fmt.print_success(f"Resolved '{name}' via the template index: {entry.install_ref}")
    return entry.install_ref


def _github_rate_limit_setup_available(out: Any) -> bool:
    """Whether the interactive GitHub-token onboarding can run here.

    JSON / CI sessions never prompt (machine output must stay clean and CI
    must never block); otherwise an interactive stdin is required.
    """
    if out.use_json or is_ci_env():
        return False
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _offer_github_token_setup(fmt: Any, out: Any) -> str | None:
    """Offer a one-shot interactive ``github_token`` setup after a rate limit.

    Shows the officially verified fine-grained PAT prefill URL, asks for
    confirmation, reads the token through the existing masked (asterisk)
    input (task 201), stores it in ``~/.ebx/.env`` and returns it so the
    caller can retry exactly once. Returns ``None`` when the user declines,
    cancels, or enters nothing - the original rate-limit error is re-raised
    by the caller. The token value is never echoed, printed, or logged.
    """
    from easy_sandbox.cli.commands.config_cmd import _prompt_secret, write_env_var
    from easy_sandbox.utils.github_token import (
        FINE_GRAINED_PAT_URL,
        GITHUB_TOKEN_ENV_VAR,
    )

    try:
        out.info(
            "GitHub rate limit reached and no token is configured "
            "(anonymous access is limited to 60 requests/hour)."
        )
        out.info(
            "Create a fine-grained token here - public repositories need no "
            "extra permissions; a 90-day expiry is recommended:\n"
            f"  {FINE_GRAINED_PAT_URL}"
        )
        if not click.confirm("Configure github_token now?", default=True):
            return None
        entered = _prompt_secret("Paste the GitHub token (input masked)")
    except click.Abort:
        return None
    token = entered.strip()
    if not token:
        out.warning("No token entered; nothing was saved.")
        return None
    write_env_var(GITHUB_TOKEN_ENV_VAR, token)
    fmt.print_success("Stored github_token in ~/.ebx/.env (input hidden); retrying once...")
    return token


def _with_github_rate_limit_retry(
    operation: Callable[[str | None], Any],
    *,
    token: str | None,
    fmt: Any,
    out: Any,
) -> Any:
    """Run *operation* (which takes the active token) with one-shot recovery.

    When the operation hits GitHub's anonymous rate limit while no token is
    configured, an interactive session is offered the masked
    ``github_token`` setup and the operation is retried exactly once with
    the freshly stored token. Declining, cancelling, or a retry that fails
    again raises the error unchanged - there is never a retry loop.
    """
    from easy_sandbox.models.errors import GitHubRateLimitError

    try:
        return operation(token)
    except GitHubRateLimitError:
        if token or not _github_rate_limit_setup_available(out):
            raise
        new_token = _offer_github_token_setup(fmt, out)
        if new_token is None:
            raise
        return operation(new_token)


def _resolve_acr_namespace(cli_value: str | None) -> str:
    """Resolve ACR namespace from CLI > os.environ > .env file.

    ``.env`` is looked up in the current working directory first and then in
    ``~/.ebx/.env`` (mirroring the SDK config loader).  Raises
    click.UsageError if the namespace is not found in any source.
    """
    import os
    from pathlib import Path

    if cli_value and cli_value.strip():
        return cli_value.strip()
    env_val = os.environ.get("ACR_NAMESPACE")
    if env_val and env_val.strip():
        return env_val.strip()
    # Try .env files: CWD first, then ~/.ebx/.env. A blank value does not count.
    try:
        from dotenv import dotenv_values

        for dotenv_path in (Path.cwd() / ".env", Path.home() / ".ebx" / ".env"):
            if dotenv_path.exists():
                ns = dotenv_values(dotenv_path).get("ACR_NAMESPACE")
                if ns and ns.strip():
                    return ns.strip()
    except ImportError:
        pass
    raise click.UsageError(
        "Missing ACR namespace. Provide via:\n"
        "  1. --acr-namespace flag\n"
        "  2. export ACR_NAMESPACE=<ns>\n"
        "  3. ACR_NAMESPACE=<ns> in ./.env\n"
        "  4. ebx config set acr_namespace <ns>   (or re-run 'ebx config init')"
    )


def _coerce_int(value: Any, default: int) -> int:
    """Safely coerce *value* to int, returning *default* on failure.

    Handles ``None``, ``bool``, numeric types, and string representations.
    Emits a warning on stderr for truly invalid values so users learn why
    their ``template.yaml`` value was ignored.
    """
    if value is None:
        return default
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return int(value)
        return int(str(value).strip())
    except (ValueError, TypeError):
        click.echo(
            f"Warning: invalid integer in template.yaml: {value!r}; using default {default}",
            err=True,
        )
        return default


#: How many build/push lines to remember. The display keeps the last
#: ``EBX_ACTIVITY_LINES`` of them (default 4).
_STEP_LOG_LINES = 10

#: Redraw the step header while a build or push is silent, so the elapsed
#: time keeps moving.
_STEP_TICK_SECONDS = 1.0


class _StepReporter:
    """Progress reporter for the long-running build/push/deploy steps.

    On an interactive terminal each :meth:`phase` is the same block as agent
    generation: a ``message... 12s`` header, and under it the last few log
    lines in grey (:meth:`log` appends docker build / push / poll output).
    The block is redrawn once a second even when the tool is silent, so the
    elapsed time does not freeze. ``--verbose`` prints every line in full
    instead. Quiet, JSON, CI, and non-TTY sessions get one progress line and
    no per-line log.
    """

    def __init__(self, out: Any, *, verbose: bool = False) -> None:
        self._out = out
        self._verbose = verbose
        self._spinner_cm: Any = None
        self._update: Callable[[str], None] | None = None
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._tick_stop: threading.Event | None = None
        self._tick: threading.Thread | None = None

    def phase(self, message: str) -> None:
        """Report that a new long-running step has started."""
        self._stop()
        self._lines = []
        if self._verbose or not self._out.use_activity_line:
            self._out.progress(message)
            return
        self._spinner_cm = self._out.activity(message)
        self._update = self._spinner_cm.__enter__()
        self._start_tick()

    def log(self, line: str) -> None:
        """Append one tool output line to the grey feed (or print it in verbose)."""
        if self._verbose:
            text = line.rstrip()
            if text:
                self._out.info(text)
            return
        text = " ".join(line.split())
        if not text:
            return
        with self._lock:
            self._lines.append(text)
            del self._lines[:-_STEP_LOG_LINES]
            snapshot = "\n".join(self._lines)
            update = self._update
        if update is not None:
            with suppress(Exception):
                update(snapshot)

    def done(self, message: str) -> None:
        """Stop any live block and print a completion message."""
        self._stop()
        self._out.progress(message)

    def close(self) -> None:
        """Stop the live block. Safe to call more than once."""
        self._stop()

    def _start_tick(self) -> None:
        stop = threading.Event()
        self._tick_stop = stop

        def run() -> None:
            while not stop.wait(_STEP_TICK_SECONDS):
                with self._lock:
                    snapshot = "\n".join(self._lines)
                    update = self._update
                if update is None:
                    continue
                with suppress(Exception):
                    update(snapshot)

        thread = threading.Thread(target=run, name="ebx-step-activity", daemon=True)
        self._tick = thread
        thread.start()

    def _stop(self) -> None:
        stop = self._tick_stop
        thread = self._tick
        self._tick_stop = None
        self._tick = None
        with self._lock:
            self._update = None
        if stop is not None:
            stop.set()
        if self._spinner_cm is not None:
            cm = self._spinner_cm
            self._spinner_cm = None
            with suppress(Exception):
                cm.__exit__(None, None, None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)


def _provenance_notice(out: Any) -> None:
    """Print a friendly notice when --provenance=false will be auto-injected.

    Only prints when BuildKit is enabled (DOCKER_BUILDKIT != "0") and the
    output manager is not in quiet/json mode.  The check duplicates the
    condition in docker_builder.py intentionally to keep the CLI layer
    responsible for user-facing messages.
    """
    if getattr(out, "json_mode", False) or getattr(out, "quiet", False):
        return
    if os.environ.get("DOCKER_BUILDKIT", "1") != "0":
        out.info(
            "\u2139 Auto-added --provenance=false"
            " (prevents FC image optimization failure; set DOCKER_BUILDKIT=0 to skip)"
        )


def _build_image(
    template_dir: str,
    *,
    tag: str,
    repo: str | None,
    platform: str,
    dockerfile: str | None,
    on_progress: Callable[[str], None],
    on_output: Callable[[str], None] | None = None,
) -> str:
    """Build a Docker image locally from a template directory.

    Reads the Dockerfile in *template_dir* (or *dockerfile*) and runs a
    local ``docker build``.  Returns the local image tag (``<name>:<tag>``).
    Shared by the ``build`` and ``deploy`` commands.

    Args:
        on_output: Called with each docker build line. The deploy reporter
            feeds these into the grey activity lines (or prints them in
            ``--verbose``).
    """
    from pathlib import Path

    from easy_sandbox.api.docker_builder import DockerBuilder
    from easy_sandbox.models.errors import DockerBuildError

    tdir = Path(template_dir).resolve()
    image_name = repo or tdir.name
    local_tag = f"{image_name}:{tag}"

    builder = DockerBuilder()
    on_progress("[1/3] Checking Docker daemon...")
    if not builder.check_docker():
        raise DockerBuildError(
            "Docker daemon is not running or not accessible.",
            suggestion="Start Docker Desktop or the Docker daemon.",
        )

    on_progress("[2/3] Injecting SDK wheel into build context...")
    injected_wheels = builder.inject_sdk_wheel(tdir)

    on_progress(f"[3/3] Building Docker image locally: {local_tag}")
    try:
        builder.build(
            context_dir=tdir,
            tag=local_tag,
            platform=platform,
            dockerfile=dockerfile,
            on_output=on_output,
        )
    finally:
        import contextlib

        for whl in injected_wheels:
            with contextlib.suppress(OSError):
                whl.unlink(missing_ok=True)
    return local_tag


def _push_image(
    local_image: str,
    *,
    acr: Any,
    tag: str,
    region: str,
    on_progress: Callable[[str], None],
    on_output: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Login to ACR, tag, and push a local image.

    Returns ``(acr_ref, creds)`` where *creds* is the credential dict from
    the ACR login (temp username/token, or AK/SK fallback).  Shared by the
    ``push`` and ``deploy`` commands.

    ``on_progress`` is called at the start of each phase. ``on_output``
    receives ``docker push`` lines so a live activity block can show them.
    """
    from easy_sandbox.api.docker_builder import DockerBuilder

    builder = DockerBuilder()
    acr_ref = acr.tagged_ref(tag)

    on_progress(f"Logging into ACR: {acr.registry}")
    creds = builder.login_acr_with_aksk(
        acr.registry,
        acr.username,
        acr.password,
        region=region,
        instance_id=acr.acree_instance_id or None,
    )
    on_progress(f"Tagging: {local_image} → {acr_ref}")
    builder.tag(local_image, acr_ref)
    on_progress(f"Pushing to ACR: {acr_ref}")
    builder.push(acr_ref, on_output=on_output)
    return acr_ref, creds


def _run_reported_deploy(
    reporter: _StepReporter,
    *,
    out: Any,
    config: Any,
    template_dir: str,
    acr: Any,
    template_name: str,
    region: str,
    tag: str,
    platform: str,
    resolved_cpu: int,
    resolved_memory: int,
    start_cmd: str | None,
    ready_cmd: str | None,
    timeout: int,
    dockerfile: str | None,
    disk_size: int | None,
    internet_access: bool | None,
    use_official: bool,
    team_id: str | None,
    envd_inject: bool,
    resolved_generation: int,
    target_image: str | None,
    platform_ak: str,
    platform_sk: str,
) -> dict[str, Any]:
    """Build, push, and register, streaming tool output through *reporter*."""
    from easy_sandbox.api.docker_builder import DockerBuilder
    from easy_sandbox.utils.async_bridge import run_sync

    if (start_cmd or ready_cmd) and resolved_generation != 2:
        # Diagnostic channel: rendered once on stderr, suppressed by
        # --quiet/--ci/--json instead of bypassing the output manager.
        out.warning("--start-cmd / --ready-cmd only take effect with --generation 2 (MicroVM).")

    # Provenance notice (Task #9)
    _provenance_notice(out)

    if use_official:
        local_tag = _build_image(
            template_dir,
            tag=tag,
            repo=acr.repo,
            platform=platform,
            dockerfile=dockerfile,
            on_progress=reporter.phase,
            on_output=reporter.log,
        )
        acr_ref, creds = _push_image(
            local_tag,
            acr=acr,
            tag=tag,
            region=region,
            on_progress=reporter.phase,
            on_output=reporter.log,
        )
        reporter.done(f"Image pushed to ACR: {acr_ref}")

        from easy_sandbox.api.fc_template import (
            create_official_template,
            wait_for_template_ready,
        )
        from easy_sandbox.models.errors import TemplateBuildError

        registry_type = "acree" if acr.acree_instance_id else "acr"
        reporter.phase(f"Creating template via official API: {template_name}")
        api_result = create_official_template(
            name=template_name,
            image=acr_ref,
            access_key_id=platform_ak,
            access_key_secret=platform_sk,
            region=region,
            team_id=team_id,
            cpu=resolved_cpu,
            memory_size=resolved_memory,
            disk_size=disk_size,
            internet_access=internet_access,
            generation=resolved_generation,
            start_command=start_cmd,
            ready_command=ready_cmd,
            envd_inject=envd_inject,
            registry_type=registry_type,
            acr_instance_id=acr.acree_instance_id or None,
            registry_username=creds.get("tempUserName"),
            registry_password=creds.get("authorizationToken"),
            registry_vpc_id=acr.vpc_id or None,
            registry_vswitch_id=acr.vswitch_ids or None,
            registry_security_group_id=acr.security_group_id or None,
            target_image=target_image,
        )
        template_id = api_result.get("templateID", "")
        if not template_id:
            raise TemplateBuildError(
                "CreateTemplate returned no template ID.",
                suggestion="Check the official API response and retry.",
            )
        reporter.phase(f"Waiting for template to become READY: {template_id}")

        def on_poll(state: str, elapsed: float) -> None:
            reporter.log(f"{state}  {elapsed:.0f}s")

        final_data = wait_for_template_ready(
            template_id,
            access_key_id=platform_ak,
            access_key_secret=platform_sk,
            region=region,
            team_id=team_id,
            timeout=timeout,
            on_poll=on_poll,
        )
        final_status = final_data.get("status") or {}
        build_status = (
            str(final_status.get("state", "unknown")).lower()
            if isinstance(final_status, dict)
            else str(final_status).lower()
        )
        build_id = ""
        build_logs: list[str] = []
    else:
        builder = DockerBuilder()
        result = run_sync(
            builder.build_and_register(
                template_dir=template_dir,
                acr=acr,
                name=template_name,
                tag=tag,
                platform=platform,
                dockerfile=dockerfile,
                cpu_count=resolved_cpu,
                memory_mb=resolved_memory,
                start_cmd=start_cmd,
                ready_cmd=ready_cmd,
                on_progress=reporter.phase,
                on_output=reporter.log,
                api_key=config.api_key,
                api_url=config.api_url,
                access_key_id=config.access_key_id,
                access_key_secret=config.access_key_secret,
                timeout=timeout,
            )
        )
        reporter.done(f"Template registration finished: {result.template_id or 'N/A'}")
        template_id = result.template_id
        build_id = result.build_id
        acr_ref = result.acr_ref
        build_status = result.build_status
        build_logs = result.logs

    return {
        "TemplateID": template_id or "N/A",
        "BuildID": build_id or "N/A",
        "ACR Image": acr_ref or "N/A",
        "Status": build_status,
        "_build_logs": build_logs if not use_official else [],
    }


def _do_deploy(
    template_dir: str,
    *,
    acr_namespace: str,
    acr_registry: str = "registry.cn-hangzhou.aliyuncs.com",
    acr_repo: str | None = None,
    acr_username: str | None = None,
    acr_password: str | None = None,
    acree_instance_id: str = "",
    vpc_id: str = "",
    vswitch_ids: str = "",
    security_group_id: str = "",
    alias: str | None = None,
    tag: str = "latest",
    platform: str = "linux/amd64",
    cpu: int | None = None,
    memory: int | None = None,
    start_cmd: str | None = None,
    ready_cmd: str | None = None,
    timeout: int = 600,
    dockerfile: str | None = None,
    disk_size: int | None = None,
    internet_access: bool | None = None,
    use_official: bool = True,
    team_id: str | None = None,
    envd_inject: bool = False,
    generation: int | None = None,
    target_image: str | None = None,
    region: str | None = None,
    ctx: click.Context | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Shared deploy logic: docker build -> ACR push -> CreateTemplate -> poll.

    Used by both ``template build``/``deploy`` and ``install`` (when not
    ``--download-only``).  Returns a summary dict with TemplateID, Status,
    etc.

    Args:
        template_dir: Path to a template directory containing a Dockerfile.
        acr_namespace: Resolved ACR namespace (required).
        region: Command-level region override (``--region``); ``None`` falls
            back to the configured region (``ebx config set region``).
        ctx: Click context for output manager; falls back to defaults.
        verbose: Enable verbose docker build output streaming.

    Returns:
        Dict with keys TemplateID, BuildID, ACR Image, Status.
    """
    from easy_sandbox.api.docker_builder import ACRConfig
    from easy_sandbox.transport.config import load_config

    config = load_config(region=region)

    yaml_defaults = _read_yaml_defaults(template_dir)
    resolved_cpu: int = cpu if cpu is not None else _coerce_int(yaml_defaults.get("cpu"), 2)
    resolved_memory: int = (
        memory if memory is not None else _coerce_int(yaml_defaults.get("memory"), 2048)
    )
    resolved_generation: int = (
        generation if generation is not None else _coerce_int(yaml_defaults.get("generation"), 1)
    )
    resolved_acr_username = acr_username or config.access_key_id or ""
    resolved_acr_password = acr_password or config.access_key_secret or ""
    resolved_repo = acr_repo or yaml_defaults.get("name") or Path(template_dir).resolve().name

    if not resolved_acr_username or not resolved_acr_password:
        raise click.ClickException(
            "ACR credentials missing. Run 'ebx config init', or "
            "'ebx config set access_key_id' / 'ebx config set access_key_secret', "
            "or pass --acr-username/--acr-password."
        )

    platform_ak = config.access_key_id or ""
    platform_sk = config.access_key_secret or ""

    acr = ACRConfig(
        registry=acr_registry,
        namespace=acr_namespace,
        repo=resolved_repo,
        username=resolved_acr_username,
        password=resolved_acr_password,
        acree_instance_id=acree_instance_id,
        vpc_id=vpc_id,
        vswitch_ids=vswitch_ids,
        security_group_id=security_group_id,
    )
    template_name = alias or resolved_repo
    region = config.region

    out = get_output(ctx)
    reporter = _StepReporter(out, verbose=verbose)
    try:
        return _run_reported_deploy(
            reporter,
            out=out,
            config=config,
            template_dir=template_dir,
            acr=acr,
            template_name=template_name,
            region=region,
            tag=tag,
            platform=platform,
            resolved_cpu=resolved_cpu,
            resolved_memory=resolved_memory,
            start_cmd=start_cmd,
            ready_cmd=ready_cmd,
            timeout=timeout,
            dockerfile=dockerfile,
            disk_size=disk_size,
            internet_access=internet_access,
            use_official=use_official,
            team_id=team_id,
            envd_inject=envd_inject,
            resolved_generation=resolved_generation,
            target_image=target_image,
            platform_ak=platform_ak,
            platform_sk=platform_sk,
        )
    finally:
        reporter.close()


#: Public alias so other commands (e.g. ``ebx create`` AI path) can reuse the
#: build -> push -> CreateTemplate -> poll pipeline.
do_deploy = _do_deploy

#: Public alias used by the ``ebx create`` AI path to resolve the ACR namespace.
resolve_acr_namespace = _resolve_acr_namespace


@click.group()
def template() -> None:
    """Discover, scaffold, build, and manage sandbox templates.

    \b
    Examples:
      ebx template search python
      ebx template init --template python --name my-template
      ebx template list

    \b
    Related commands:
      ebx create --template TEMPLATE  Launch a sandbox from a template
      ebx install TEMPLATE_REF        Install shortcut
      ebx config --help               Configure credentials and region
    """


@template.command("install")
@click.argument("template_ref")
@click.option(
    "--registry-url",
    default="https://github.com",
    help="Registry URL (default: GitHub)",
)
@click.option(
    "--registry-type",
    type=click.Choice(["github", "local"]),
    default=None,
    help="Registry type (auto-detected if not specified)",
)
@click.option(
    "--token",
    default=None,
    envvar="GITHUB_TOKEN",
    help=_GITHUB_TOKEN_HELP,
)
@click.option("--alias", "-a", default=None, help="Template alias")
@click.option(
    "--download-only",
    is_flag=True,
    default=False,
    help="Only download to local cache (skip build and deploy)",
)
@click.option(
    "--dir",
    "dest_dir",
    default=None,
    type=click.Path(),
    help="Download template source into this directory instead of the cache",
)
@click.option(
    "--acr-namespace",
    envvar="ACR_NAMESPACE",
    default=None,
    help="ACR namespace for deploy (env: ACR_NAMESPACE, or set in .env file)",
)
@click.option(
    "--cpu",
    type=int,
    default=None,
    help="CPU cores (default: from template.yaml or 2)",
)
@click.option(
    "--memory",
    type=int,
    default=None,
    help="Memory in MB (default: from template.yaml or 2048)",
)
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt")
@region_option
@click.pass_context
@handle_errors
def install(
    ctx: click.Context,
    template_ref: str,
    registry_url: str,
    registry_type: str | None,
    token: str | None,
    alias: str | None,
    download_only: bool,
    dest_dir: str | None,
    acr_namespace: str | None,
    cpu: int | None,
    memory: int | None,
    yes: bool,
    region: str | None,
) -> None:
    """Download a template and (by default) build + deploy it.

    By default, install downloads the template, then runs docker build,
    pushes to ACR, and creates a sandbox template via the official API —
    cloud-side operations that can incur Alibaba Cloud costs (ACR
    storage/traffic, template resources). Use --download-only to skip the
    build/deploy step and only download to the local cache
    (~/.ebx/templates/).

    Use --dir <path> to download into a specific directory instead of
    the cache.

    TEMPLATE_REF can be a bare template name from the official index
    (Easy-Sandbox/awesome-templates) or a registry reference. Bare names
    are resolved against the remote index; entries may pin a version, in
    which case that pinned ref is honoured.

    A GitHub token (private repos / higher rate limits) is taken from
    --token, then the GITHUB_TOKEN environment variable, then ./.env, then
    the stored github_token; prefer 'ebx config set github_token' - --token
    may leak into shell history and process listings.

    \b
    Examples:
      ebx template install python-hello --download-only   # install by index name
      ebx template install owner/repo --acr-namespace my-ns
      ebx template install owner/repo@v1.0 --download-only
      ebx template install owner/repo//subdir --dir ./local-copy
      ebx template install owner/repo --acr-namespace my-ns --region cn-shanghai

    \b
    Related commands:
      ebx template search QUERY  Find a template in the index
      ebx template list          List registered templates
      ebx create --template ID   Launch the installed template
    """
    from easy_sandbox.cli.commands.config_cmd import resolve_github_token
    from easy_sandbox.utils.async_bridge import run_sync
    from easy_sandbox.utils.registry import (
        TEMPLATE_CACHE_DIR,
        RegistryClient,
        load_template_from_yaml,
    )

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    # BUG-05: Early validation for local paths to avoid raw traceback.
    from easy_sandbox.cli.main import EXIT_NOT_FOUND

    local_path = Path(template_ref)
    _looks_local = (
        registry_type == "local"
        or template_ref.startswith(("./", "../", "/"))
        or local_path.exists()
    )
    if _looks_local and not local_path.exists():
        fmt.print_error(
            f"Path not found: {template_ref}",
            suggestion="Verify the path exists, or use owner/repo format for GitHub templates.",
        )
        sys.exit(EXIT_NOT_FOUND)

    active_token = resolve_github_token(token)

    def _acquire(active: str | None) -> tuple[Any, Path | None]:
        """Resolve TEMPLATE_REF and download its sources (task 206).

        Returns ``(ref, source_path)``; ``source_path`` is ``None`` when the
        ref is a built-in template that needs no installation.
        """
        nonlocal template_ref
        client = RegistryClient(registry_url=registry_url, token=active)
        ref = run_sync(client.resolve(template_ref, registry_type=registry_type))

        if ref.is_builtin:
            from easy_sandbox.utils.registry import BUILTIN_TEMPLATES

            if template_ref in BUILTIN_TEMPLATES:
                fmt.print_success(
                    f"'{template_ref}' is a built-in template. No installation needed."
                )
                fmt.print_success(f"Use it directly: ebx create --template {template_ref}")
                return ref, None
            # Bare name that is not built-in: resolve it through the remote
            # template index (single source of truth), then continue as usual.
            template_ref = _resolve_index_name(template_ref, token=active, fmt=fmt, out=out)
            ref = run_sync(client.resolve(template_ref, registry_type=registry_type))
            if ref.is_builtin:  # pragma: no cover - defensive: index refs are owner/repo
                raise click.ClickException(
                    f"Template index resolved '{template_ref}' to a built-in template."
                )

        # Fetch the template sources.
        if ref.registry_type == "local":
            fmt.print_success(f"Using local template from {ref.local_path}...")
            return ref, run_sync(client.fetch(ref))
        fmt.print_success(f"Fetching template from {ref.owner}/{ref.repo}...")
        with out.spinner(f"Fetching template {template_ref}"):
            return ref, run_sync(client.fetch(ref))

    ref, source_path = _with_github_rate_limit_retry(_acquire, token=active_token, fmt=fmt, out=out)
    if source_path is None:  # built-in template: nothing to install
        return

    # Locate template.yaml
    yaml_path = _find_template_yaml(source_path)
    if yaml_path is None:
        fmt.print_error(
            f"No template.yaml (or sandbox-template.yaml / sandbox.yaml) found in {source_path}",
            suggestion="Ensure the repository contains a template.yaml at the root.",
        )
        sys.exit(1)

    tmpl = load_template_from_yaml(yaml_path)
    install_name = alias or tmpl.name or Path(source_path).name

    # --dir: download into a user-specified directory
    if dest_dir is not None:
        dest_path = Path(dest_dir).resolve()
        if dest_path.exists() and any(dest_path.iterdir()):
            raise click.ClickException(
                f"Directory '{dest_path}' already exists and is not empty. "
                "Remove or empty it first, or choose a different --dir path."
            )
        dest_path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
        cached_path: Path = dest_path
    # Copy to local cache (default)
    elif ref.registry_type == "local":
        dest = TEMPLATE_CACHE_DIR / install_name
        if Path(source_path).resolve() != dest.resolve():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_path, dest, dirs_exist_ok=True)
        cached_path = dest
    else:
        cached_path = Path(source_path)

    cache_data = {
        "Alias": install_name or "N/A",
        "Source": str(source_path),
        "Cached": str(cached_path),
        "Status": "installed-locally",
    }

    if download_only:
        if fmt.use_json:
            fmt.print_data(cache_data)
        else:
            fmt.print_dict(cache_data)
            fmt.print_success(
                f"Template '{install_name}' installed to the local cache. "
                "Build and push the image with 'ebx template build'."
            )
        return

    # --- Build + deploy precheck ---
    missing: list[str] = []

    # Docker available?
    docker_path = shutil.which("docker")
    if not docker_path:
        missing.append("Docker not found in PATH. Install Docker or start Docker Desktop.")

    # ACR namespace resolvable?
    try:
        resolved_ns = _resolve_acr_namespace(acr_namespace)
    except click.UsageError as exc:
        missing.append(str(exc))
        resolved_ns = None

    # AK/SK credentials?
    from easy_sandbox.transport.config import load_config

    config = load_config(region=region)
    if not (config.access_key_id and config.access_key_secret):
        missing.append(
            "Alibaba Cloud AK/SK credentials not found. Run 'ebx config init', or:\n"
            "  ebx config set access_key_id <ALICLOUD_ACCESS_KEY_ID>\n"
            "  ebx config set access_key_secret <ALICLOUD_ACCESS_KEY_SECRET>\n"
            "  Or set ALICLOUD_ACCESS_KEY_ID / ALICLOUD_ACCESS_KEY_SECRET in the environment."
        )

    if missing:
        msg = (
            "Cannot build + deploy. Missing prerequisites:\n"
            + "\n".join(f"  • {m}" for m in missing)
            + "\n\nRun with --download-only to just download the template."
        )
        raise click.ClickException(msg)

    assert resolved_ns is not None  # ensured by precheck above

    # Confirmation
    if not yes:
        if not sys.stdin.isatty():
            raise click.UsageError(
                "Confirmation required for build + deploy. "
                "Use --yes/-y to skip in non-interactive mode."
            )
        click.confirm(
            f"Download complete. Build and deploy template '{install_name}'?",
            abort=True,
        )

    # Run deploy via shared helper
    out.info(f"Building and deploying template '{install_name}' from {cached_path}")
    deploy_data = _do_deploy(
        str(cached_path),
        acr_namespace=resolved_ns,
        cpu=cpu,
        memory=memory,
        alias=alias,
        region=region,
        ctx=ctx,
    )

    build_status = deploy_data.get("Status", "unknown")
    deploy_data.pop("_build_logs", None)
    if fmt.use_json:
        fmt.print_data({**cache_data, **deploy_data})
    else:
        fmt.print_dict(deploy_data)
        if build_status == "ready":
            fmt.print_success("Template installed, built, and ready!")
            fmt.print_success(f"Use: ebx create --template {deploy_data.get('TemplateID')}")
        elif build_status in ("pushed", "submitted"):
            fmt.print_success("Template downloaded and image pushed; registration submitted.")
        else:
            fmt.print_error(f"Build status: {build_status}")


@template.command("list")
@click.option(
    "--official-api",
    is_flag=True,
    default=False,
    help="Query templates via the official Alibaba Cloud FCSandbox API (AK/SK).",
)
@region_option
@click.pass_context
@handle_errors
def list_templates(ctx: click.Context, official_api: bool, region: str | None) -> None:
    """List custom templates registered for the current account.

    By default this queries the configured platform endpoint. Pass
    --official-api to use the Alibaba Cloud FCSandbox API with AK/SK.
    This command does not search the community template index.

    \b
    Examples:
      ebx template list
      ebx template list --official-api
      ebx template list --region cn-shanghai
      ebx --json template list

    \b
    Related commands:
      ebx template info TEMPLATE_ID
      ebx template search QUERY
      ebx template install TEMPLATE_REF
    """
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)

    config = load_config(region=region)

    if official_api:
        from easy_sandbox.api.fc_template import list_official_templates

        if not (config.access_key_id and config.access_key_secret):
            raise click.ClickException(
                "--official-api requires AccessKey/AccessSecret in the environment."
            )
        templates = list_official_templates(
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
            region=config.region,
        )
        if not templates:
            fmt.print_success("No official templates found for this team.")
            return
        headers = ["TemplateID", "Name", "Alias", "Status"]
        rows = [
            [
                str(t.get("templateID") or t.get("template_id") or "N/A"),
                str(t.get("name", "N/A")),
                str(t.get("alias", "") or ""),
                str(
                    (t.get("status") or {}).get("state", "N/A")
                    if isinstance(t.get("status"), dict)
                    else t.get("status", "N/A")
                ),
            ]
            for t in templates
        ]
        fmt.print_table(headers, rows)
        return

    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.utils.async_bridge import run_sync

    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)

    async def _list_and_close() -> Any:
        import httpx

        try:
            resp = await http_client.platform_request("GET", "/templates")
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise _translate_platform_error(exc, context="Listing templates") from exc
        finally:
            await http_client.close()

    templates = run_sync(_list_and_close())

    if not templates:
        fmt.print_success(
            "No custom templates found. Use 'ebx template install <repo>' to install from GitHub."
        )
        return

    if isinstance(templates, list):
        headers = ["TemplateID", "Alias", "Status"]
        rows = [
            [
                t.get("templateID", "N/A"),
                t.get("alias", "N/A"),
                t.get("status", "N/A"),
            ]
            for t in templates
        ]
        fmt.print_table(headers, rows)
    else:
        fmt.print_data(templates)


@template.command("info")
@click.argument("template_id")
@click.option(
    "--official-api",
    is_flag=True,
    default=False,
    help="Query the template via the official Alibaba Cloud FCSandbox API (AK/SK).",
)
@region_option
@click.pass_context
@handle_errors
def info(ctx: click.Context, template_id: str, official_api: bool, region: str | None) -> None:
    """Show details for a template ID.

    Pass --official-api to use the Alibaba Cloud FCSandbox GetTemplate API;
    that mode requires configured AccessKey credentials.

    \b
    Examples:
      ebx template info tmpl-abc123
      ebx template info tmpl-abc123 --official-api
      ebx template info tmpl-abc123 --region cn-shanghai
      ebx --json template info tmpl-abc123

    \b
    Related commands:
      ebx template list
      ebx create --template TEMPLATE_ID
      ebx template delete TEMPLATE_ID
    """
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)

    config = load_config(region=region)

    if official_api:
        from easy_sandbox.api.fc_template import get_template

        if not (config.access_key_id and config.access_key_secret):
            raise click.ClickException(
                "--official-api requires AccessKey/AccessSecret in the environment."
            )
        data = get_template(
            template_id,
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
            region=config.region,
        )
        # BUG-09: Format as readable key-value pairs instead of raw dict.
        if isinstance(data, dict):
            fmt.print_dict({str(k): str(v) for k, v in data.items()})
        else:
            fmt.print_data(data)
        return

    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.utils.async_bridge import run_sync

    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)

    async def _info_and_close() -> Any:
        import httpx

        try:
            resp = await http_client.platform_request("GET", f"/templates/{template_id}")
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise _translate_platform_error(
                exc, context="Fetching template info", template_id=template_id
            ) from exc
        finally:
            await http_client.close()

    data = run_sync(_info_and_close())

    # BUG-09: Format as readable key-value pairs instead of raw dict.
    if isinstance(data, dict):
        fmt.print_dict({str(k): str(v) for k, v in data.items()})
    else:
        fmt.print_data(data)


@template.command("create")
@click.argument("image")
@click.option("--name", "-n", required=True, help="Template name")
@click.option(
    "--team-id",
    envvar=["TEAM_ID", "E2B_TEAM_ID"],
    default=None,
    help="Team ID (or env TEAM_ID / E2B_TEAM_ID; auto-resolved if omitted)",
)
@click.option("--cpu", type=float, default=2, help="CPU cores (default 2)")
@click.option("--memory", type=int, default=2048, help="Memory in MB (default 2048)")
@click.option("--disk-size", type=int, default=None, help="Disk size in MB")
@click.option(
    "--internet-access/--no-internet-access",
    default=None,
    help="Internet access (default: platform decides)",
)
@click.option("--start-cmd", default=None, help="Container start command")
@click.option("--ready-cmd", default=None, help="Container readiness check command")
@click.option(
    "--generation",
    type=int,
    default=None,
    help="Sandbox generation (default: template.yaml 'generation', otherwise 1). "
    "1=first-gen (rund), 2=second-gen MicroVM.",
)
@click.option(
    "--envd-inject/--no-envd-inject", default=False, help="Enable envd injection in build"
)
@click.option(
    "--target-image",
    default=None,
    help="Destination image ref for envd copy (auto-derived with random suffix if omitted)",
)
@click.option(
    "--registry-type",
    type=click.Choice(["acr", "acree"]),
    default=None,
    help="Registry type (auto-detected from --acree-instance-id)",
)
@click.option(
    "--acree-instance-id",
    envvar="ACREE_INSTANCE_ID",
    default=None,
    help="ACR EE instance ID (cri-...)",
)
@click.option(
    "--registry-username", default=None, help="Registry login username (for pulling image)"
)
@click.option(
    "--registry-password", default=None, help="Registry login password (for pulling image)"
)
@region_option
@click.pass_context
@handle_errors
def create_template(
    ctx: click.Context,
    image: str,
    name: str,
    team_id: str | None,
    cpu: float,
    memory: int,
    disk_size: int | None,
    internet_access: bool | None,
    start_cmd: str | None,
    ready_cmd: str | None,
    generation: int | None,
    envd_inject: bool,
    target_image: str | None,
    registry_type: str | None,
    acree_instance_id: str | None,
    registry_username: str | None,
    registry_password: str | None,
    region: str | None,
) -> None:
    """Create a sandbox template from an existing container image.

    Uses the official Alibaba Cloud FCSandbox CreateTemplate API.
    Requires AK/SK credentials and 'easy-sandbox[alicloud]' extra.

    \b
    Examples:
      ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \\
        --name my-template
      ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \\
        --name my-template --team-id team-xxx --cpu 4 --memory 4096
      ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \\
        --name my-template --envd-inject --generation 1
      ebx template create registry.cn-hangzhou.aliyuncs.com/ns/repo:tag \\
        --name my-template --region cn-shanghai

    \b
    Related commands:
      ebx template push IMAGE       Push a local image to ACR first
      ebx template info TEMPLATE_ID Inspect the created template
      ebx create --template ID      Launch a sandbox from the template
    """
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)
    config = load_config(region=region)

    ak = config.access_key_id or ""
    sk = config.access_key_secret or ""
    if not ak or not sk:
        fmt.print_error(
            "Alibaba Cloud AK/SK credentials required for official CreateTemplate API.",
            suggestion="Run 'ebx config init', or "
            "'ebx config set access_key_id' / 'ebx config set access_key_secret'. "
            "ALICLOUD_ACCESS_KEY_ID / ALICLOUD_ACCESS_KEY_SECRET "
            "(or AccessKey / AccessSecret) in the environment also work.",
        )
        sys.exit(1)

    from easy_sandbox.api.fc_template import create_official_template

    region = config.region
    resolved_generation: int = generation if generation is not None else 1

    # Warn if start/ready commands used without generation 2
    if (start_cmd or ready_cmd) and resolved_generation != 2:
        click.echo(
            "Warning: --start-cmd / --ready-cmd only take effect with --generation 2 (MicroVM).",
            err=True,
        )

    with get_output(ctx).spinner(f"Creating template {name}"):
        result = create_official_template(
            name=name,
            image=image,
            access_key_id=ak,
            access_key_secret=sk,
            region=region,
            team_id=team_id,
            cpu=cpu,
            memory_size=memory,
            disk_size=disk_size,
            internet_access=internet_access,
            generation=resolved_generation,
            start_command=start_cmd,
            ready_command=ready_cmd,
            envd_inject=envd_inject,
            registry_type=registry_type,
            acr_instance_id=acree_instance_id,
            registry_username=registry_username,
            registry_password=registry_password,
            target_image=target_image,
        )

    data = {
        "TemplateID": result.get("templateID", "N/A"),
        "RequestID": result.get("requestId", "N/A"),
        "StatusCode": result.get("statusCode", "N/A"),
        "Message": result.get("message") or "N/A",
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        template_id = result.get("templateID")
        if template_id:
            fmt.print_success(f"Template created! Use: ebx create --template {template_id}")


@template.command("push")
@click.argument("image")
@click.option(
    "--acr-registry",
    envvar="ACR_REGISTRY",
    default="registry.cn-hangzhou.aliyuncs.com",
    help="ACR registry host",
)
@click.option(
    "--acr-namespace",
    envvar="ACR_NAMESPACE",
    required=False,
    default=None,
    help="ACR namespace (env: ACR_NAMESPACE, or set in .env file)",
)
@click.option(
    "--acr-username",
    envvar="ACR_USERNAME",
    default=None,
    help="ACR login username (defaults to AccessKey from .env)",
)
@click.option(
    "--acr-password",
    envvar="ACR_PASSWORD",
    default=None,
    help="ACR login password (defaults to AccessSecret from .env)",
)
@click.option(
    "--acree-instance-id",
    envvar="ACREE_INSTANCE_ID",
    default="",
    help="ACR EE instance ID (cri-...)",
)
@region_option
@click.pass_context
@handle_errors
def push(
    ctx: click.Context,
    image: str,
    acr_registry: str,
    acr_namespace: str | None,
    acr_username: str | None,
    acr_password: str | None,
    acree_instance_id: str,
    region: str | None,
) -> None:
    """Push a locally-built image to Alibaba Cloud ACR.

    IMAGE is a local image tag (e.g. ``python-hello:latest``) produced by
    a local ``docker build``.  The repository name and tag are derived from
    IMAGE.  Prints the full ACR image URL on success.

    \b
    Examples:
      ebx template push python-hello:latest --acr-namespace my-ns
      ebx template push python-hello:latest --acr-namespace my-ns --region cn-shanghai
      ebx template push my-tmpl:v1 --acr-namespace prod \\
        --acree-instance-id cri-xxx

    \b
    Related commands:
      ebx template build TEMPLATE_DIR  Build, push, and register a template
      ebx template create IMAGE        Register an existing image
      ebx config set access_key_id KEY
    """
    from easy_sandbox.api.docker_builder import ACRConfig
    from easy_sandbox.models.errors import ACRLoginError
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)
    config = load_config(region=region)

    # Parse the local image reference into repo name + tag.
    if ":" in image:
        repo_part, image_tag = image.rsplit(":", 1)
    else:
        repo_part, image_tag = image, "latest"
    repo_name = repo_part.rsplit("/", 1)[-1]

    # Resolve ACR namespace: CLI > env > .env file (CWD, then ~/.ebx/.env)
    resolved_namespace = _resolve_acr_namespace(acr_namespace)

    resolved_username = acr_username or config.access_key_id or ""
    resolved_password = acr_password or config.access_key_secret or ""
    if not resolved_username or not resolved_password:
        raise ACRLoginError(
            "ACR credentials missing.",
            suggestion="Run 'ebx config init', or "
            "'ebx config set access_key_id' / 'ebx config set access_key_secret', "
            "or pass --acr-username/--acr-password.",
        )

    acr = ACRConfig(
        registry=acr_registry,
        namespace=resolved_namespace,
        repo=repo_name,
        username=resolved_username,
        password=resolved_password,
        acree_instance_id=acree_instance_id,
    )

    # Login/tag/push: header plus the last few push lines in grey (or the
    # full log with --verbose; one progress line when there is no TTY).
    out = get_output(ctx)
    reporter = _StepReporter(out, verbose=out.verbose)
    try:
        acr_ref, _creds = _push_image(
            image,
            acr=acr,
            tag=image_tag,
            region=config.region,
            on_progress=reporter.phase,
            on_output=reporter.log,
        )
        reporter.done(f"Image pushed to ACR: {acr_ref}")
    finally:
        reporter.close()

    data = {"ACR Image": acr_ref, "Status": "pushed"}
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success(f"Image pushed to ACR: {acr_ref}")


@template.command("build")
@click.argument("template_dir", type=click.Path(exists=True), envvar="EBX_TEMPLATE_DIR")
@click.option(
    "--acr-registry",
    envvar="ACR_REGISTRY",
    default="registry.cn-hangzhou.aliyuncs.com",
    help="ACR registry host",
)
@click.option(
    "--acr-namespace",
    envvar="ACR_NAMESPACE",
    required=False,
    default=None,
    help="ACR namespace (env: ACR_NAMESPACE, or set in .env file)",
)
@click.option(
    "--acr-repo",
    envvar="ACR_REPO",
    default=None,
    help="ACR repository name (defaults to template.yaml name or dir name)",
)
@click.option(
    "--acr-username",
    envvar="ACR_USERNAME",
    default=None,
    help="ACR login username (defaults to AccessKey from .env)",
)
@click.option(
    "--acr-password",
    envvar="ACR_PASSWORD",
    default=None,
    help="ACR login password (defaults to AccessSecret from .env)",
)
@click.option(
    "--acree-instance-id",
    envvar="ACREE_INSTANCE_ID",
    default="",
    help="ACR EE instance ID (cri-...)",
)
@click.option("--vpc-id", envvar="ACR_VPC_ID", default="", help="VPC ID for ACR EE")
@click.option(
    "--vswitch-ids", envvar="ACR_VSWITCH_IDS", default="", help="Comma-separated VSwitch IDs"
)
@click.option(
    "--security-group-id", envvar="ACR_SECURITY_GROUP_ID", default="", help="Security group ID"
)
@click.option("--alias", "-a", default=None, help="Template alias")
@click.option("--tag", "-t", default="latest", help="Docker image tag")
@click.option("--platform", default="linux/amd64", help="Target platform")
@click.option(
    "--cpu",
    type=int,
    default=None,
    help=("CPU cores (default: from template.yaml resources.cpu, fallback 2)"),
)
@click.option(
    "--memory",
    type=int,
    default=None,
    help=("Memory in MB (default: from template.yaml resources.memory, fallback 2048)"),
)
@click.option("--start-cmd", default=None, help="Container start command")
@click.option("--ready-cmd", default=None, help="Container readiness check command")
@click.option("--timeout", type=int, default=600, help="Build timeout in seconds")
@click.option(
    "--dockerfile", "-f", default=None, type=click.Path(exists=True), help="Custom Dockerfile path"
)
@click.option("--disk-size", type=int, default=None, help="Disk size in MB (official API only)")
@click.option(
    "--internet-access/--no-internet-access",
    default=None,
    help="Internet access (default: platform decides; official API only)",
)
@click.option(
    "--official-api/--legacy-api",
    "use_official",
    default=True,
    help="Use official CreateTemplate API (default) or legacy v3/v2",
)
@click.option(
    "--team-id",
    envvar=["TEAM_ID", "E2B_TEAM_ID"],
    default=None,
    help="Team ID for official API (or env TEAM_ID / E2B_TEAM_ID)",
)
@click.option(
    "--envd-inject/--no-envd-inject",
    default=False,
    help="Enable envd injection (default False)",
)
@click.option(
    "--generation",
    type=int,
    default=None,
    help="Sandbox generation (default: template.yaml 'generation', otherwise 1). "
    "1=first-gen (rund), 2=second-gen MicroVM.",
)
@click.option(
    "--target-image",
    default=None,
    help="Destination image ref for envd copy (auto-derived with random suffix if omitted)",
)
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt")
@click.option("-v", "--verbose", "verbose_flag", is_flag=True, help="Verbose output (DEBUG level)")
@region_option
@click.pass_context
@handle_errors
def build(
    ctx: click.Context,
    template_dir: str,
    acr_registry: str,
    acr_namespace: str | None,
    acr_repo: str | None,
    acr_username: str | None,
    acr_password: str | None,
    acree_instance_id: str,
    vpc_id: str,
    vswitch_ids: str,
    security_group_id: str,
    alias: str | None,
    tag: str,
    platform: str,
    cpu: int | None,
    memory: int | None,
    start_cmd: str | None,
    ready_cmd: str | None,
    timeout: int,
    dockerfile: str | None,
    disk_size: int | None,
    internet_access: bool | None,
    use_official: bool,
    team_id: str | None,
    envd_inject: bool,
    generation: int | None,
    target_image: str | None,
    yes: bool,
    verbose_flag: bool,
    region: str | None,
) -> None:
    """Build Docker image locally, push to ACR, and create a sandbox template.

    Full pipeline with cloud side effects: the local docker build is
    local-only, but the ACR push and the remote template registration
    can incur Alibaba Cloud costs (ACR storage/traffic, template
    resources).

    Supports two modes:

    \b
    --official-api (default):
      local docker build → ACR push → official CreateTemplate API (envdInject).
      Requires AK/SK credentials and 'easy-sandbox[alicloud]' extra.

    \b
    --legacy-api:
      local docker build → ACR push → legacy v3/v2 platform API.
      Use --legacy-api to keep the old behaviour.

    Requires Docker daemon running and ACR credentials. In automation/CI,
    pass --acr-namespace and TEMPLATE_DIR explicitly instead of relying
    on ACR_NAMESPACE / EBX_TEMPLATE_DIR environment variables or .env
    files, so the build cannot drift with the surrounding environment.

    \b
    Examples:
      ebx template build ./examples/templates/python-hello \\
        --acr-namespace my-ns --acr-repo python-hello
      ebx template build ./my-template \\
        --acr-namespace prod --acree-instance-id cri-xxx
      ebx template build ./my-template \\
        --acr-namespace prod --disk-size 10240 --internet-access
      ebx template build ./my-template \\
        --acr-namespace prod --legacy-api
      ebx template build ./my-template --acr-namespace prod --region cn-shanghai

    \b
    Related commands:
      ebx template init DIRECTORY    Scaffold template source files
      ebx template push IMAGE        Push an existing local image only
      ebx create --template ID       Launch the completed template
    """
    if verbose_flag:
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    # Resolve ACR namespace: CLI > env > .env file
    resolved_namespace = _resolve_acr_namespace(acr_namespace)
    yaml_defaults = _read_yaml_defaults(template_dir)
    resolved_repo = acr_repo or yaml_defaults.get("name") or Path(template_dir).resolve().name
    resolved_cpu: int = cpu if cpu is not None else _coerce_int(yaml_defaults.get("cpu"), 2)
    resolved_memory: int = (
        memory if memory is not None else _coerce_int(yaml_defaults.get("memory"), 2048)
    )
    resolved_generation: int = (
        generation if generation is not None else _coerce_int(yaml_defaults.get("generation"), 1)
    )
    template_name = alias or resolved_repo

    # Early credential check (before confirmation prompt)
    from easy_sandbox.transport.config import load_config

    config = load_config(region=region)
    resolved_acr_username = acr_username or config.access_key_id or ""
    resolved_acr_password = acr_password or config.access_key_secret or ""
    if not resolved_acr_username or not resolved_acr_password:
        fmt.print_error(
            "ACR credentials missing.",
            suggestion="Run 'ebx config init', or "
            "'ebx config set access_key_id' / 'ebx config set access_key_secret', "
            "or pass --acr-username/--acr-password.",
        )
        sys.exit(1)

    # Show the resolved configuration so users can see the effective values.
    click.echo(f"Template: {template_name}")
    click.echo(f"ACR: {resolved_namespace}/{resolved_repo}:{tag}")
    click.echo(f"Resources: cpu={resolved_cpu}, memory={resolved_memory}MB")

    # Confirmation before destructive cloud operations.
    if not yes:
        if not sys.stdin.isatty():
            raise click.UsageError(
                "Confirmation required for deploying to cloud. "
                "Use --yes/-y to skip in non-interactive mode."
            )
        click.confirm(
            f"\nPush image to {resolved_namespace}/{resolved_repo}:{tag} "
            f"and register template '{template_name}'?",
            abort=True,
        )

    data = _do_deploy(
        template_dir,
        acr_namespace=resolved_namespace,
        acr_registry=acr_registry,
        acr_repo=acr_repo,
        acr_username=acr_username,
        acr_password=acr_password,
        acree_instance_id=acree_instance_id,
        vpc_id=vpc_id,
        vswitch_ids=vswitch_ids,
        security_group_id=security_group_id,
        alias=alias,
        tag=tag,
        platform=platform,
        cpu=cpu,
        memory=memory,
        start_cmd=start_cmd,
        ready_cmd=ready_cmd,
        timeout=timeout,
        dockerfile=dockerfile,
        disk_size=disk_size,
        internet_access=internet_access,
        use_official=use_official,
        team_id=team_id,
        envd_inject=envd_inject,
        generation=resolved_generation,
        target_image=target_image,
        region=region,
        ctx=ctx,
        verbose=out.verbose,
    )

    build_status = data.get("Status", "unknown")
    build_logs: list[str] = data.pop("_build_logs", [])
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        if build_status == "ready":
            fmt.print_success("Template built and ready!")
            fmt.print_success(f"Use: ebx create --template {data.get('TemplateID')}")
        elif build_status in ("pushed", "submitted"):
            fmt.print_success("Image pushed to ACR; template registration submitted.")
        else:
            fmt.print_error(f"Build status: {build_status}")
            if build_logs:
                for log in build_logs:
                    out.info(f"  {log}")


@template.command(
    "deploy",
    params=list(build.params),
    help=(
        "Build, push, and create template in one step (alias of 'template build').\n\n"
        "Builds a Docker image locally, pushes it to ACR, and creates a sandbox "
        "template. The ACR push and the remote template registration are "
        "cloud-side operations that can incur Alibaba Cloud costs (ACR "
        "storage/traffic, template resources).\n\n"
        "Requires: Docker daemon running, ACR credentials, and an ACR namespace "
        "(--acr-namespace, 'ebx config set acr_namespace', or ACR_NAMESPACE in "
        "the environment / .env). AK/SK credentials come from 'ebx config init' "
        "(access_key_id / access_key_secret) when --acr-username/--acr-password "
        "are omitted.\n\n"
        "\b\n"
        "Examples:\n"
        "  ebx template deploy ./examples/templates/python-hello \\\n"
        "    --acr-namespace my-ns --acr-repo python-hello\n"
        "  ebx template deploy ./my-template --acr-namespace prod --yes\n\n"
        "\b\n"
        "Related commands:\n"
        "  ebx template init DIRECTORY  Scaffold a template project\n"
        "  ebx template list            Verify the registered template\n"
        "  ebx create --template ID     Launch a sandbox from the template"
    ),
)
@click.pass_context
def deploy(ctx: click.Context, /, **kwargs: Any) -> None:
    """Build, push, and create template in one step."""
    ctx.invoke(build, **kwargs)


@template.command("delete")
@click.argument("template_id")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt")
@region_option
@click.pass_context
@handle_errors
def delete(ctx: click.Context, template_id: str, yes: bool, region: str | None) -> None:
    """Delete a custom template from the remote platform.

    This irreversible operation does not remove the local template cache.
    Confirmation is required unless --yes is supplied.

    \b
    Examples:
      ebx template delete tmpl-abc123
      ebx template delete tmpl-abc123 --yes --region cn-shanghai

    \b
    Related commands:
      ebx template info TEMPLATE_ID  Verify the target before deletion
      ebx template list              Confirm the template was removed
      ebx template install REF       Reinstall a template
    """
    if not yes:
        if not sys.stdin.isatty():
            raise click.UsageError(
                "Confirmation required for deleting template. "
                "Use --yes/-y to skip in non-interactive mode."
            )
        click.confirm(
            f"Delete template '{template_id}'? This action cannot be undone.",
            abort=True,
        )
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

    async def _delete_and_close() -> None:
        import httpx

        try:
            await http_client.platform_request("DELETE", f"/templates/{template_id}")
        except httpx.HTTPStatusError as exc:
            raise _translate_platform_error(
                exc, context="Deleting template", template_id=template_id
            ) from exc
        finally:
            await http_client.close()

    run_sync(_delete_and_close())

    fmt.print_success(f"Template {template_id} deleted.")


@template.command("search")
@click.argument("query")
@click.option(
    "--tag",
    "-t",
    default=None,
    help="Filter by exact tag name",
)
@click.option(
    "--status",
    "-s",
    type=click.Choice(["official", "community", "experimental"]),
    default=None,
    help="Filter by template status",
)
@click.option(
    "--index-url",
    default=None,
    envvar="EBX_TEMPLATE_INDEX_URL",
    help="Template index location: HTTP(S) URL or local file path "
    "(env: EBX_TEMPLATE_INDEX_URL; default: the canonical remote index)",
)
@click.option(
    "--token",
    default=None,
    envvar="GITHUB_TOKEN",
    help=_GITHUB_TOKEN_HELP,
)
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help="Force a re-fetch of the index, ignoring the local cache",
)
@click.pass_context
@handle_errors
def search(
    ctx: click.Context,
    query: str,
    tag: str | None,
    status: str | None,
    index_url: str | None,
    token: str | None,
    refresh: bool,
) -> None:
    """Search the template catalog by name, tag, or description.

    Queries the template index published in the Easy-Sandbox/awesome-templates
    repository - the single source of truth for official and community
    templates. The fetched index is cached under ~/.ebx/index/ and reused for
    up to an hour; on network failures the cached copy is served with a
    warning.

    For private mirrors / higher rate limits a token is taken from --token,
    then the GITHUB_TOKEN environment variable, then ./.env, then the stored
    github_token (in that order); prefer 'ebx config set github_token'.

    \b
    Examples:
      ebx template search python
      ebx template search ai-agent
      ebx template search browser --status official
      ebx template search qwen --tag deploy
      ebx template search python --refresh    # bypass the local cache

    \b
    Related commands:
      ebx template install <name>             Install a template by index name
      ebx template install owner/repo//subdir[@ref]
      ebx template list
    """
    from easy_sandbox.cli.commands.config_cmd import resolve_github_token
    from easy_sandbox.utils.async_bridge import run_sync
    from easy_sandbox.utils.template_index import fetch_index

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    def _fetch(active: str | None) -> Any:
        """Fetch the index with *active* as the token (retried once)."""
        with out.spinner("Fetching the template index"):
            return run_sync(fetch_index(index_url, token=active, force=refresh))

    index = _with_github_rate_limit_retry(
        _fetch, token=resolve_github_token(token), fmt=fmt, out=out
    )

    if index.notice:
        out.warning(index.notice)

    results = index.filter(query, tag=tag, status=status)

    if not results:
        fmt.print_success(f"No templates matching '{query}'.")
        return

    if fmt.use_json:
        fmt.print_data(
            [
                {
                    "name": entry.name,
                    "description": entry.description,
                    "repo": entry.repo,
                    "path": entry.path,
                    "ref": entry.ref,
                    "tags": list(entry.tags),
                    "author": entry.author,
                    "capabilities": list(entry.capabilities),
                    "status": entry.status,
                }
                for entry in results
            ]
        )
        return

    headers = ["Name", "Description", "Tags", "Status"]
    rows = [
        [entry.name, entry.description or "N/A", ", ".join(entry.tags), entry.status or "N/A"]
        for entry in results
    ]
    fmt.print_table(headers, rows)
    if not fmt.quiet:
        click.echo(f"\n{len(results)} template(s) found.")
        click.echo(f"Install one with: ebx template install <name> (index: {index.source_url})")


# ---------------------------------------------------------------------------
# template init — scaffold a new template project
# ---------------------------------------------------------------------------


def _scaffold_picker_available(fmt: Any) -> bool:
    """Whether the interactive scaffold-case picker can run here.

    JSON / CI sessions never prompt (machine output must stay clean and CI
    must never block); otherwise an interactive stdin is required.
    """
    if fmt.use_json or is_ci_env():
        return False
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _try_arrow_case_picker(cases: list[tuple[str, str]]) -> str | None:
    """Cross-platform arrow-key picker backed by ``questionary`` (lazy import).

    Returns the chosen case name, or ``None`` when ``questionary`` is not
    installed / cannot start, so the caller can fall back to the numbered
    prompt. Cancelling the picker (Ctrl-C) aborts the command instead of
    silently re-prompting.
    """
    try:
        import questionary

        choices = [questionary.Choice(title=f"{c:<12} {desc}", value=c) for c, desc in cases]
        answer = questionary.select("Select a case", choices=choices, default=cases[0][0]).ask()
    except ImportError:
        # Optional dependency (declared in the ``cli`` extra); degrade quietly.
        return None
    except KeyboardInterrupt:
        raise click.Abort() from None
    except Exception:
        # No usable terminal (or a picker failure): fall back to numbered input.
        return None
    if answer is None:
        # ``ask()`` returns None when the user cancels with Ctrl-C.
        raise click.Abort()
    return str(answer)


def _is_nl_description(value: str) -> bool:
    """Return whether *value* is a sentence rather than a directory path.

    A path token (``my-app``, ``./my app``, ``.``) stays a directory so
    existing ``ebx template init [DIRECTORY]`` invocations are unchanged.
    Whitespace or CJK text is a natural-language description. Prefix a
    directory that contains spaces with ``./``.
    """
    if value in {".", ".."} or value.startswith(".") or "/" in value or "\\" in value:
        return False
    if any(ch.isspace() for ch in value):
        return True
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _select_scaffold_case(cases: list[tuple[str, str]]) -> str:
    """Pick a scaffold case interactively.

    Prefers the cross-platform arrow-key picker; falls back to the previous
    numbered ``click.prompt`` whenever the picker is unavailable.
    """
    picked = _try_arrow_case_picker(cases)
    if picked is not None:
        return picked
    click.echo("Available scaffold cases:")
    for i, (c, desc) in enumerate(cases, 1):
        click.echo(f"  {i}. {c:<12} {desc}")
    choice = click.prompt("Select a case", type=click.IntRange(1, len(cases)), default=1)
    return cases[int(choice) - 1][0]


@template.command("init")
@click.argument("directory", default=None, required=False, type=click.Path())
@click.option(
    "--template",
    "-t",
    "case",
    default=None,
    help="Built-in scaffold case (python, node, minimal)",
)
@click.option(
    "--from",
    "from_ref",
    default=None,
    help="Fetch template source from a registry ref (owner/repo, local path)",
)
@click.option(
    "--name",
    default=None,
    help="Template name (default: case name, or fetched template name)",
)
@click.option(
    "--list",
    "list_cases",
    is_flag=True,
    default=False,
    help="List available scaffold cases",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite existing files")
@click.option(
    "--adopt",
    is_flag=True,
    default=False,
    help="Adapt an existing source project: the coding agent adds the template files "
    "(Dockerfile, commands.py, template.yaml). DIRECTORY is the project (default: .).",
)
@click.option(
    "--hint",
    default=None,
    help="With --adopt: what the code cannot tell the agent (ports, services).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="With --adopt: list what would be sent to the model. Nothing is sent or written.",
)
@click.option("-v", "--verbose", "verbose_flag", is_flag=True, help="Verbose output (DEBUG level)")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompts: the template directory, description "
    "clarification, and (with --adopt) the send and write prompts. Required for "
    "non-interactive AI generation. "
    "Does not build or deploy. Replacing an existing Dockerfile still needs --force "
    "when there is no interactive preview.",
)
@click.pass_context
@handle_errors
def init(
    ctx: click.Context,
    directory: str | None,
    case: str | None,
    from_ref: str | None,
    name: str | None,
    list_cases: bool,
    force: bool,
    adopt: bool,
    hint: str | None,
    dry_run: bool,
    verbose_flag: bool,
    yes: bool,
) -> None:
    """Scaffold a new sandbox template project.

    Creates a ready-to-build template directory with template.yaml,
    Dockerfile, and (depending on the case) a commands.py file.
    Nothing is built, pushed, deployed, or turned into a sandbox.

    When DIRECTORY is omitted a new ./<name> subdirectory is created
    (derived from --name, the scaffold case, or the fetched template).

    A DIRECTORY that contains whitespace or CJK text is a natural-language
    description: Qwen Code generates Dockerfile, commands.py (the HTTP
    server) and template.yaml into ./<name>/ and stops. An interactive
    terminal is asked for that directory first (Enter keeps ./<name>/).
    A path token (my-app, ./my app) stays a directory.

    --adopt adapts a project that already has source code and no template
    files. The agent sees a copy, and only Dockerfile, commands.py,
    template.yaml and a generated .dockerignore are written back, after you
    confirm. Nothing is built or deployed.

    \b
    Examples:
      ebx template init --list                     # List built-in cases
      ebx template init -t python                  # Creates ./python/
      ebx template init -t python --name myapp     # Creates ./myapp/
      ebx template init -t python ./my-template    # Explicit directory
      ebx template init --from owner/repo          # Creates ./<template-name>/
      ebx template init "a python data science env"  # AI files only, no build
      ebx template init -y "a node.js api server"    # non-interactive AI files
      ebx template init --adopt . --hint "port 8080" # adapt this project
      ebx template init --adopt ./app --dry-run      # show what would be sent

    \b
    Related commands:
      ebx template deploy DIRECTORY
      ebx template install TEMPLATE_REF
      ebx create --template TEMPLATE
      ebx create "DESCRIPTION"   # generate, build, deploy, and create
    """
    from easy_sandbox.cli.scaffold import available_cases, render_scaffold

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    if adopt or hint is not None or dry_run:
        if not adopt:
            raise click.UsageError("--hint and --dry-run require --adopt.")
        if case or from_ref or list_cases:
            raise click.UsageError(
                "--adopt cannot be combined with --template/-t, --from or --list."
            )
        from easy_sandbox.cli.commands._adopt import run_adopt

        run_adopt(
            ctx,
            directory,
            hint=hint,
            name=name,
            dry_run=dry_run,
            force=force,
            yes=yes,
            verbose=verbose_flag,
        )
        return

    # --list: print available cases and exit
    if list_cases:
        cases = available_cases()
        if fmt.use_json:
            fmt.print_data([{"case": c, "description": d} for c, d in cases])
        else:
            for c, desc in cases:
                click.echo(f"  {c:<12} {desc}")
        return

    # --template and --from are mutually exclusive
    if case and from_ref:
        raise click.UsageError(
            "--template/-t and --from are mutually exclusive. Use one or the other."
        )

    # A sentence is a description, not a directory name. Generate the
    # template files and stop — no build, push, deploy, or sandbox.
    if directory is not None and _is_nl_description(directory):
        if case or from_ref:
            raise click.UsageError(
                "A natural-language description cannot be combined with "
                "--template/-t or --from. Drop those flags to generate a "
                "template from the description, or drop the description to "
                "scaffold or fetch a template."
            )
        from easy_sandbox.cli.commands.sandbox import _generate_local_template

        _generate_local_template(
            ctx, directory, yes=yes, name=name, force=force, ask_directory=True
        )
        return

    # Whether the user explicitly provided a DIRECTORY argument
    dir_provided = directory is not None

    # --from: fetch from registry and copy source files into DIR
    if from_ref:
        from easy_sandbox.cli.commands.config_cmd import resolve_github_token
        from easy_sandbox.utils.async_bridge import run_sync
        from easy_sandbox.utils.registry import RegistryClient, load_template_from_yaml

        def _fetch_from(active: str | None) -> tuple[Any, Path]:
            """Resolve --from and download it (retried once after setup)."""
            client = RegistryClient(token=active)
            ref = run_sync(client.resolve(from_ref))
            if ref.is_builtin:
                raise click.UsageError(
                    f"'{from_ref}' is a built-in template and cannot be used with --from. "
                    "Use -t/--template for built-in cases."
                )
            with out.spinner(f"Fetching template from {from_ref}"):
                return ref, run_sync(client.fetch(ref))

        ref, source_path = _with_github_rate_limit_retry(
            _fetch_from, token=resolve_github_token(), fmt=fmt, out=out
        )

        source = Path(source_path)

        # A local directory with no manifest is a source project, not a template.
        # Copying it would also copy .env and .git.  Remote refs stay tolerant.
        if getattr(ref, "registry_type", "") == "local" and _find_template_yaml(source) is None:
            raise click.ClickException(
                f"'{from_ref}' has no template.yaml, so it is not a template. "
                f"To adapt a source project, run: ebx template init --adopt {from_ref}"
            )

        # Derive name: --name > template.yaml name > ref basename
        if name is None:
            yaml_path = _find_template_yaml(source)
            if yaml_path:
                tmpl = load_template_from_yaml(yaml_path)
                name = tmpl.name or ""
            if not name:
                # Fallback: repo basename or last path component
                name = (
                    ref.path.rstrip("/").rsplit("/", 1)[-1]
                    if ref.path
                    else (ref.repo or Path(from_ref).name)
                )
        assert name  # ensured above

        # Resolve target directory
        target = Path(directory).resolve() if dir_provided else Path.cwd() / name  # type: ignore[arg-type]

        target.mkdir(parents=True, exist_ok=True)
        # Check for conflicts
        if not force:
            conflicts = [f.name for f in source.iterdir() if (target / f.name).exists()]
            if conflicts:
                raise click.ClickException(
                    f"Files already exist in {target}: {', '.join(conflicts[:5])}. "
                    "Use --force to overwrite."
                )
        shutil.copytree(source, target, dirs_exist_ok=True)
        out.info(f"Template files copied from {from_ref} to {target}")
        created = [f.name for f in target.iterdir() if f.is_file()]
        _print_init_summary(fmt, out, target, created, name)
        return

    # Interactive selection when no --template/--from given
    if case is None:
        cases = available_cases()
        if _scaffold_picker_available(fmt):
            case = _select_scaffold_case(cases)
        else:
            case_names = ", ".join(c for c, _ in cases)
            raise click.UsageError(
                f"No scaffold case specified. Available cases: {case_names}. "
                "Use -t/--template <case> or --from <ref>."
            )

    # Derive name: --name > case name > "my-template"
    if name is None:
        name = case or "my-template"

    # Resolve target directory
    target = Path(directory).resolve() if dir_provided else Path.cwd() / name  # type: ignore[arg-type]

    # Render scaffold files
    try:
        files = render_scaffold(case, name)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    # Check for conflicts
    target.mkdir(parents=True, exist_ok=True)
    if not force:
        conflicts = [fn for fn in files if (target / fn).exists()]
        if conflicts:
            raise click.ClickException(
                f"Files already exist in {target}: {', '.join(conflicts)}. "
                "Use --force to overwrite."
            )

    # Write files
    for filename, content in files.items():
        filepath = target / filename
        filepath.write_text(content, encoding="utf-8")

    _print_init_summary(fmt, out, target, list(files.keys()), name)


def _print_init_summary(
    fmt: Any,
    out: Any,
    target: Path,
    created: list[str],
    name: str,
    *,
    replaced: list[str] | None = None,
    backed_up: list[str] | None = None,
    not_applied: list[str] | None = None,
    dry_run: bool = False,
    next_steps: list[str] | None = None,
) -> None:
    """Print a friendly summary after scaffold init."""
    if fmt.use_json:
        payload: dict[str, Any] = {"name": name, "directory": str(target), "files": created}
        if replaced is not None:
            payload["replaced"] = replaced
        if backed_up is not None:
            payload["backed_up"] = backed_up
        if not_applied is not None:
            payload["not_applied"] = not_applied
        if dry_run:
            payload["dry_run"] = True
        fmt.print_data(payload)
        return
    title = "previewed" if dry_run else "created"
    out.info(f"\n✅ Template '{name}' {title} in {target}")
    out.info("Created files:")
    for filename in sorted(created):
        out.info(f"  {filename}")
    if replaced:
        out.info("Replaced files:")
        for filename in replaced:
            out.info(f"  {filename}")
    if backed_up:
        out.info("Backups:")
        for filename in backed_up:
            out.info(f"  {filename}")
    if not_applied:
        out.info("Agent changes not applied:")
        for filename in not_applied:
            out.info(f"  {filename}")
    out.info("\nNext steps:")
    if next_steps is not None:
        for step in next_steps:
            out.info(f"  {step}")
        return
    dir_arg = str(target) if str(target) != str(Path.cwd()) else "."
    out.info(f"  ebx template deploy {dir_arg} --acr-namespace <ns>")
    out.info(f"  ebx install {dir_arg} --acr-namespace <ns>")


# ---------------------------------------------------------------------------
# Top-level shortcut: ebx install
# ---------------------------------------------------------------------------


@click.command("install")
@click.argument("template_ref")
@click.option(
    "--registry-url",
    default="https://github.com",
    help="Registry URL (default: GitHub)",
)
@click.option(
    "--registry-type",
    type=click.Choice(["github", "local"]),
    default=None,
    help="Registry type (auto-detected if not specified)",
)
@click.option(
    "--token",
    default=None,
    envvar="GITHUB_TOKEN",
    help=_GITHUB_TOKEN_HELP,
)
@click.option("--alias", "-a", default=None, help="Template alias")
@click.option(
    "--download-only",
    is_flag=True,
    default=False,
    help="Only download to local cache (skip build and deploy)",
)
@click.option(
    "--dir",
    "dest_dir",
    default=None,
    type=click.Path(),
    help="Download template source into this directory instead of the cache",
)
@click.option(
    "--acr-namespace",
    envvar="ACR_NAMESPACE",
    default=None,
    help="ACR namespace for deploy",
)
@click.option("--cpu", type=int, default=None, help="CPU cores")
@click.option("--memory", type=int, default=None, help="Memory in MB")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt")
@region_option
@click.pass_context
@handle_errors
def install_shortcut(
    ctx: click.Context,
    template_ref: str,
    registry_url: str,
    registry_type: str | None,
    token: str | None,
    alias: str | None,
    download_only: bool,
    dest_dir: str | None,
    acr_namespace: str | None,
    cpu: int | None,
    memory: int | None,
    yes: bool,
    region: str | None,
) -> None:
    """Install a template from TEMPLATE_REF (shortcut for 'ebx template install').

    Downloads and (by default) builds + deploys a template: local docker
    build, ACR push, and CreateTemplate registration — cloud-side steps
    that can incur Alibaba Cloud costs. Use --download-only to only fetch
    it into the local cache (~/.ebx/templates/) without building.

    \b
    TEMPLATE_REF formats:
      <name>                Template name from the official index
      owner/repo            GitHub repo (default registry)
      owner/repo@v1.0       Pinned to a tag/branch/commit
      owner/repo//subdir    A subdirectory within a repo
      ./path/to/template    Local directory

    \b
    Examples:
      ebx install python-hello --download-only       # install by index name
      ebx install owner/repo --acr-namespace my-ns  # download + build + deploy
      ebx install owner/repo --acr-namespace my-ns --region cn-shanghai
      ebx install owner/repo --download-only         # download only
      ebx install ./my-template --acr-namespace ns   # local dir + deploy

    \b
    Related commands:
      ebx template search QUERY
      ebx template list
      ebx create --template TEMPLATE
    """
    ctx.invoke(
        install,
        template_ref=template_ref,
        registry_url=registry_url,
        registry_type=registry_type,
        token=token,
        alias=alias,
        download_only=download_only,
        dest_dir=dest_dir,
        acr_namespace=acr_namespace,
        cpu=cpu,
        memory=memory,
        yes=yes,
        region=region,
    )
