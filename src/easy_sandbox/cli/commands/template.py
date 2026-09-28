"""模板管理 CLI 命令。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors
from easy_sandbox.cli.output import get_output

if TYPE_CHECKING:
    from collections.abc import Callable


def _extract_platform_error(resp: Any) -> str:
    """从 Platform 错误响应中提取可读的错误消息。

    优先解析 JSON body 中的常见错误字段，回退到原始文本或状态码。
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
    """将 Platform 的 httpx.HTTPStatusError 映射为友好的 SandboxError。

    - 404 且带 template_id → TemplateNotFoundError（提示检查 TEMPLATE_ID）；
    - 其它状态码 → NetworkError，附“检查认证/平台状态”建议。
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
        }
    except OSError:
        # A missing or unreadable manifest is normal — no defaults.
        return {}
    except Exception as e:  # includes yaml.YAMLError and any parse failure
        click.echo(f"Warning: Failed to parse template.yaml: {e}", err=True)
        return {}


def _resolve_acr_namespace(cli_value: str | None) -> str:
    """Resolve ACR namespace from CLI > os.environ > .env file.

    ``.env`` is looked up in the current working directory first and then in
    ``~/.ebx/.env`` (mirroring the SDK config loader).  Raises
    click.UsageError if the namespace is not found in any source.
    """
    import os
    from pathlib import Path

    if cli_value:
        return cli_value
    env_val = os.environ.get("ACR_NAMESPACE")
    if env_val:
        return env_val
    # Try .env files: CWD first, then ~/.ebx/.env
    try:
        from dotenv import dotenv_values

        for dotenv_path in (Path.cwd() / ".env", Path.home() / ".ebx" / ".env"):
            if dotenv_path.exists():
                ns = dotenv_values(dotenv_path).get("ACR_NAMESPACE")
                if ns:
                    return ns
    except ImportError:
        pass
    raise click.UsageError(
        "Missing ACR namespace. Provide via:\n"
        "  1. --acr-namespace flag\n"
        "  2. export ACR_NAMESPACE=xxx\n"
        "  3. ACR_NAMESPACE=xxx in .env (CWD or ~/.ebx/.env)"
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
            f"Warning: invalid integer in template.yaml: {value!r}; "
            f"using default {default}",
            err=True,
        )
        return default


class _StepReporter:
    """Progress reporter for the long-running build/push/deploy steps.

    Each :meth:`phase` starts a Rich spinner for the new step (TTY mode) or
    prints a plain one-line message in degraded modes (quiet / JSON / CI /
    non-TTY).  The previous spinner is always stopped before the step
    message is echoed so output never gets garbled.  In verbose TTY mode
    plain messages are preferred over spinners so that streamed tool output
    stays readable.
    """

    def __init__(self, out: Any, *, verbose: bool = False) -> None:
        self._out = out
        self._verbose = verbose
        self._spinner_cm: Any = None

    def phase(self, message: str) -> None:
        """Report that a new long-running step has started."""
        self._stop()
        if self._verbose or not self._out.use_rich_spinner:
            self._out.progress(message)
            return
        self._spinner_cm = self._out.spinner(message)
        self._spinner_cm.__enter__()

    def done(self, message: str) -> None:
        """Stop any spinner and print a completion message."""
        self._stop()
        self._out.progress(message)

    def _stop(self) -> None:
        if self._spinner_cm is not None:
            self._spinner_cm.__exit__(None, None, None)
            self._spinner_cm = None


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
            "\u2139 已自动添加 --provenance=false"
            "（避免 FC 镜像优化失败；设置 DOCKER_BUILDKIT=0 可跳过）"
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
        on_output: When given (verbose mode), docker build output lines are
            streamed to this callback instead of being hidden behind the
            progress indicator.
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
) -> tuple[str, dict[str, Any]]:
    """Login to ACR, tag, and push a local image.

    Returns ``(acr_ref, creds)`` where *creds* is the credential dict from
    the ACR login (temp username/token, or AK/SK fallback).  Shared by the
    ``push`` and ``deploy`` commands.

    ``on_progress`` is called at the start of each phase; in spinner mode
    callers pass :meth:`_StepReporter.phase` so the slow ``docker push``
    phase shows an animated indicator.
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
    builder.push(acr_ref)
    return acr_ref, creds


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
    envd_inject: bool = True,
    generation: int = 1,
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
        ctx: Click context for output manager; falls back to defaults.
        verbose: Enable verbose docker build output streaming.

    Returns:
        Dict with keys TemplateID, BuildID, ACR Image, Status.
    """
    from easy_sandbox.api.docker_builder import ACRConfig, DockerBuilder
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.utils.async_bridge import run_sync

    config = load_config(
        region=(ctx.obj.get("region") if ctx and ctx.obj else None)
    )

    yaml_defaults = _read_yaml_defaults(template_dir)
    resolved_cpu: int = cpu if cpu is not None else _coerce_int(yaml_defaults.get("cpu"), 2)
    resolved_memory: int = (
        memory if memory is not None else _coerce_int(yaml_defaults.get("memory"), 2048)
    )
    resolved_acr_username = acr_username or config.access_key_id or ""
    resolved_acr_password = acr_password or config.access_key_secret or ""
    resolved_repo = (
        acr_repo or yaml_defaults.get("name") or Path(template_dir).resolve().name
    )

    if not resolved_acr_username or not resolved_acr_password:
        raise click.ClickException(
            "ACR credentials missing. Set --acr-username/--acr-password or "
            "ALICLOUD_ACCESS_KEY_ID/ALICLOUD_ACCESS_KEY_SECRET in .env"
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
    region = config.region or "cn-hangzhou"

    out = get_output(ctx)
    reporter = _StepReporter(out, verbose=verbose)

    # Provenance notice (Task #9)
    _provenance_notice(out)

    if use_official:
        local_tag = _build_image(
            template_dir,
            tag=tag,
            repo=resolved_repo,
            platform=platform,
            dockerfile=dockerfile,
            on_progress=reporter.phase,
            on_output=click.echo if verbose else None,
        )
        acr_ref, creds = _push_image(
            local_tag,
            acr=acr,
            tag=tag,
            region=region,
            on_progress=reporter.phase,
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
            generation=generation,
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
        )
        template_id = api_result.get("templateID", "")
        if not template_id:
            raise TemplateBuildError(
                "CreateTemplate returned no template ID.",
                suggestion="Check the official API response and retry.",
            )
        reporter.done(f"Waiting for template to become READY: {template_id}")
        with out.live_spinner(
            f"Waiting for template to become READY: {template_id}"
        ) as update_status:

            def on_poll(state: str, elapsed: float) -> None:
                update_status(
                    f"Waiting for template {template_id} ({state}, {elapsed:.0f}s)"
                )

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


@click.group()
def template() -> None:
    """模板管理。"""


@template.command("install")
@click.argument("template_ref")
@click.option(
    "--registry-url",
    default="https://github.com",
    help="Registry URL（默认 GitHub）",
)
@click.option(
    "--registry-type",
    type=click.Choice(["github", "local"]),
    default=None,
    help="Registry type (auto-detected if not specified)",
)
@click.option("--token", default=None, help="访问令牌（私有仓库需要）")
@click.option("--alias", "-a", default=None, help="模板别名")
@click.option(
    "--download-only",
    is_flag=True,
    default=False,
    help="Only download to local cache (skip build and deploy)",
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
    acr_namespace: str | None,
    cpu: int | None,
    memory: int | None,
    yes: bool,
) -> None:
    """Download a template and (by default) build + deploy it.

    By default, install downloads the template, then runs docker build,
    pushes to ACR, and creates a sandbox template via the official API.
    Use --download-only to skip the build/deploy step and only download
    to the local cache (~/.ebx/templates/).

    示例：\n
      ebx install owner/repo --acr-namespace my-ns  # Download + build + deploy\n
      ebx install owner/repo --download-only        # Download only\n
      ebx install owner/repo//subdir --download-only # Subdirectory of a repo\n
      ebx install ./my-template --acr-namespace ns  # Local dir + deploy\n
      ebx install owner/repo@v1.0 --yes             # Skip confirmation
    """
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
            suggestion="Verify the path exists, or use owner/repo format "
            "for GitHub templates.",
        )
        sys.exit(EXIT_NOT_FOUND)

    client = RegistryClient(registry_url=registry_url, token=token)
    ref = run_sync(client.resolve(template_ref, registry_type=registry_type))

    if ref.is_builtin:
        fmt.print_success(f"'{template_ref}' is a built-in template. No installation needed.")
        fmt.print_success(f"Use it directly: ebx create --template {template_ref}")
        return

    # Fetch the template sources.
    if ref.registry_type == "local":
        fmt.print_success(f"Using local template from {ref.local_path}...")
    else:
        fmt.print_success(f"Fetching template from {ref.owner}/{ref.repo}...")
    if ref.registry_type == "local":
        source_path = run_sync(client.fetch(ref))
    else:
        with out.spinner(f"Fetching template {template_ref}"):
            source_path = run_sync(client.fetch(ref))

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

    # Copy to local cache
    if ref.registry_type == "local":
        dest = TEMPLATE_CACHE_DIR / install_name
        if Path(source_path).resolve() != dest.resolve():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_path, dest, dirs_exist_ok=True)
        cached_path: Path = dest
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

    config = load_config(
        region=(ctx.obj.get("region") if ctx.obj else None),
    )
    if not (config.access_key_id and config.access_key_secret):
        missing.append(
            "Alibaba Cloud AK/SK credentials not found. "
            "Set ALICLOUD_ACCESS_KEY_ID / ALICLOUD_ACCESS_KEY_SECRET in .env or environment."
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
            fmt.print_success(
                f"Use: ebx create --template {deploy_data.get('TemplateID')}"
            )
        elif build_status in ("pushed", "submitted"):
            fmt.print_success(
                "Template downloaded and image pushed; registration submitted."
            )
        else:
            fmt.print_error(f"Build status: {build_status}")


@template.command("list")
@click.option(
    "--official-api",
    is_flag=True,
    default=False,
    help="Query templates via the official Alibaba Cloud FCSandbox API (AK/SK).",
)
@click.pass_context
@handle_errors
def list_templates(ctx: click.Context, official_api: bool) -> None:
    """List your custom templates on the platform.

    Shows templates you have built or cached locally via
    'ebx template build' or 'ebx template install'.  This does NOT
    query a central registry.  To discover community templates, visit
    GitHub and install with 'ebx template install <owner/repo>'.
    Pass ``--official-api`` to list templates registered via the
    official Alibaba Cloud FCSandbox CreateTemplate API.
    """
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)

    region = ctx.obj.get("region") if ctx.obj else None
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
            region=config.region or "cn-hangzhou",
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
@click.pass_context
@handle_errors
def info(ctx: click.Context, template_id: str, official_api: bool) -> None:
    """查看模板详情。

    Pass ``--official-api`` to use the official Alibaba Cloud FCSandbox
    ``GetTemplate`` API (requires AccessKey/AccessSecret in env).
    """
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)

    region = ctx.obj.get("region") if ctx.obj else None
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
            region=config.region or "cn-hangzhou",
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
@click.option("--generation", type=int, default=1, help="Sandbox generation (default 1)")
@click.option(
    "--envd-inject/--no-envd-inject", default=False, help="Enable envd injection in build"
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
    generation: int,
    envd_inject: bool,
    registry_type: str | None,
    acree_instance_id: str | None,
    registry_username: str | None,
    registry_password: str | None,
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
    """
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)
    config = load_config(region=ctx.obj.get("region") if ctx.obj else None)

    ak = config.access_key_id or ""
    sk = config.access_key_secret or ""
    if not ak or not sk:
        fmt.print_error(
            "Alibaba Cloud AK/SK credentials required for official CreateTemplate API.",
            suggestion="Set ALICLOUD_ACCESS_KEY_ID / ALICLOUD_ACCESS_KEY_SECRET "
            "(or AccessKey / AccessSecret) in .env or environment.",
        )
        sys.exit(1)

    from easy_sandbox.api.fc_template import create_official_template

    region = config.region or "cn-hangzhou"

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
        generation=generation,
        start_command=start_cmd,
        ready_command=ready_cmd,
        envd_inject=envd_inject,
        registry_type=registry_type,
        acr_instance_id=acree_instance_id,
        registry_username=registry_username,
        registry_password=registry_password,
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
) -> None:
    """Push a locally-built image to Alibaba Cloud ACR.

    IMAGE is a local image tag (e.g. ``python-hello:latest``) produced by
    a local ``docker build``.  The repository name and tag are derived from
    IMAGE.  Prints the full ACR image URL on success.

    \b
    Examples:
      ebx template push python-hello:latest --acr-namespace my-ns
      ebx template push my-tmpl:v1 --acr-namespace prod \\
        --acree-instance-id cri-xxx
    """
    from easy_sandbox.api.docker_builder import ACRConfig
    from easy_sandbox.models.errors import ACRLoginError
    from easy_sandbox.transport.config import load_config

    fmt = get_formatter(ctx)
    config = load_config(region=ctx.obj.get("region") if ctx.obj else None)

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
            suggestion="Set --acr-username/--acr-password or "
            "ALICLOUD_ACCESS_KEY_ID/ALICLOUD_ACCESS_KEY_SECRET in .env",
        )

    acr = ACRConfig(
        registry=acr_registry,
        namespace=resolved_namespace,
        repo=repo_name,
        username=resolved_username,
        password=resolved_password,
        acree_instance_id=acree_instance_id,
    )

    # Login/tag/push phases: show a spinner for the slow push (or plain
    # one-line messages in quiet/JSON/non-TTY sessions).
    out = get_output(ctx)
    reporter = _StepReporter(out, verbose=out.verbose)

    acr_ref, _creds = _push_image(
        image,
        acr=acr,
        tag=image_tag,
        region=config.region or "cn-hangzhou",
        on_progress=reporter.phase,
    )
    reporter.done(f"Image pushed to ACR: {acr_ref}")

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
@click.option("--alias", "-a", default=None, help="模板别名")
@click.option("--tag", "-t", default="latest", help="Docker image tag")
@click.option("--platform", default="linux/amd64", help="Target platform")
@click.option(
    "--cpu",
    type=int,
    default=None,
    help=(
        "CPU cores (default: from template.yaml resources.cpu, "
        "fallback 2)"
    ),
)
@click.option(
    "--memory",
    type=int,
    default=None,
    help=(
        "Memory in MB (default: from template.yaml resources.memory, "
        "fallback 2048)"
    ),
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
    default=True,
    help="Enable envd injection (default True for official API)",
)
@click.option("--generation", type=int, default=1, help="Sandbox generation (default 1)")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt")
@click.option(
    "-v", "--verbose", "verbose_flag", is_flag=True, help="Verbose output (DEBUG level)"
)
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
    generation: int,
    yes: bool,
    verbose_flag: bool,
) -> None:
    """Build Docker image locally, push to ACR, and create a sandbox template.

    Supports two modes:

    \b
    --official-api (default):
      local docker build → ACR push → official CreateTemplate API (envdInject).
      Requires AK/SK credentials and 'easy-sandbox[alicloud]' extra.

    \b
    --legacy-api:
      local docker build → ACR push → legacy v3/v2 platform API.
      Use --legacy-api to keep the old behaviour.

    Requires Docker daemon running and ACR credentials.

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
    """
    if verbose_flag:
        from easy_sandbox.cli.output import enable_verbose

        enable_verbose(ctx)

    fmt = get_formatter(ctx)
    out = get_output(ctx)

    # Resolve ACR namespace: CLI > env > .env file
    resolved_namespace = _resolve_acr_namespace(acr_namespace)
    yaml_defaults = _read_yaml_defaults(template_dir)
    resolved_repo = (
        acr_repo or yaml_defaults.get("name") or Path(template_dir).resolve().name
    )
    resolved_cpu: int = cpu if cpu is not None else _coerce_int(yaml_defaults.get("cpu"), 2)
    resolved_memory: int = (
        memory if memory is not None else _coerce_int(yaml_defaults.get("memory"), 2048)
    )
    template_name = alias or resolved_repo

    # Early credential check (before confirmation prompt)
    from easy_sandbox.transport.config import load_config

    config = load_config(
        region=(ctx.obj.get("region") if ctx.obj else None),
    )
    resolved_acr_username = acr_username or config.access_key_id or ""
    resolved_acr_password = acr_password or config.access_key_secret or ""
    if not resolved_acr_username or not resolved_acr_password:
        fmt.print_error(
            "ACR credentials missing.",
            suggestion="Set --acr-username/--acr-password or "
            "ALICLOUD_ACCESS_KEY_ID/ALICLOUD_ACCESS_KEY_SECRET in .env",
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
        generation=generation,
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
    help="Build, push, and create template in one step",
)
@click.pass_context
def deploy(ctx: click.Context, /, **kwargs: Any) -> None:
    """Build, push, and create template in one step."""
    ctx.invoke(build, **kwargs)


@template.command("delete")
@click.argument("template_id")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt")
@click.pass_context
@handle_errors
def delete(ctx: click.Context, template_id: str, yes: bool) -> None:
    """Delete a custom template from the platform.

    Removes the template identified by TEMPLATE_ID from the remote
    platform.  This does NOT affect the local cache (~/.ebx/templates/).
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

    config = load_config(region=ctx.obj.get("region") if ctx.obj else None)
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
@click.pass_context
def search(ctx: click.Context, query: str, tag: str | None, status: str | None) -> None:
    """Search community templates by name, tag, or description.

    Searches the awesome-templates.yaml index for templates matching
    QUERY against name, description, tags, and author fields.

    \b
    Examples:
      ebx template search python
      ebx template search ai-agent
      ebx template search browser --status official
      ebx template search qwen --tag deploy
    """
    from pathlib import Path

    import yaml

    fmt = get_formatter(ctx)

    # Locate awesome-templates.yaml (project root or package root)
    candidates = [
        Path.cwd() / "awesome-templates.yaml",
        Path(__file__).resolve().parents[3] / "awesome-templates.yaml",
    ]
    index_path: Path | None = None
    for candidate in candidates:
        if candidate.exists():
            index_path = candidate
            break

    if index_path is None:
        fmt.print_error(
            "awesome-templates.yaml not found.",
            suggestion="Run this command from the project root or ensure "
            "awesome-templates.yaml is present.",
        )
        sys.exit(1)

    with open(index_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    templates_list: list[dict[str, Any]] = data.get("templates", [])
    if not templates_list:
        fmt.print_success("No templates found in the index.")
        return

    query_lower = query.lower()

    def matches(tmpl: dict[str, Any]) -> bool:
        """Check if a template matches the search query and filters."""
        # Status filter
        if status and tmpl.get("status", "") != status:
            return False
        # Tag filter
        if tag and tag.lower() not in [t.lower() for t in tmpl.get("tags", [])]:
            return False
        # Query match against name, description, tags, author
        name = tmpl.get("name", "").lower()
        desc = tmpl.get("description", "").lower()
        tags = [t.lower() for t in tmpl.get("tags", [])]
        author = tmpl.get("author", "").lower()
        return (
            query_lower in name
            or query_lower in desc
            or any(query_lower in t for t in tags)
            or query_lower in author
        )

    results = [t for t in templates_list if matches(t)]

    if not results:
        fmt.print_success(f"No templates matching '{query}'.")
        return

    if fmt.use_json:
        fmt.print_data(results)
        return

    headers = ["Name", "Description", "Tags", "Status"]
    rows = [
        [
            t.get("name", "N/A"),
            t.get("description", "N/A"),
            ", ".join(t.get("tags", [])),
            t.get("status", "N/A"),
        ]
        for t in results
    ]
    fmt.print_table(headers, rows)
    if not fmt.quiet:
        click.echo(f"\n{len(results)} template(s) found.")


# ---------------------------------------------------------------------------
# template init — scaffold a new template project
# ---------------------------------------------------------------------------


@template.command("init")
@click.argument("directory", default=".", type=click.Path())
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
    help='Template name (default: directory basename, or "my-template" for ".")',
)
@click.option(
    "--list", "list_cases", is_flag=True, default=False,
    help="List available scaffold cases",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite existing files")
@click.pass_context
@handle_errors
def init(
    ctx: click.Context,
    directory: str,
    case: str | None,
    from_ref: str | None,
    name: str | None,
    list_cases: bool,
    force: bool,
) -> None:
    """Scaffold a new sandbox template project.

    Creates a ready-to-build template directory with template.yaml,
    Dockerfile, and (depending on the case) a commands.py file.

    \b
    Examples:
      ebx template init --list                     # List built-in cases
      ebx template init -t python ./my-template    # Python scaffold
      ebx template init -t node                    # Node.js in current dir
      ebx template init --from owner/repo ./copy   # Copy from registry
    """
    from easy_sandbox.cli.scaffold import available_cases, render_scaffold

    fmt = get_formatter(ctx)
    out = get_output(ctx)

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

    # Resolve directory and template name
    target = Path(directory).resolve()
    if name is None:
        name = target.name if directory != "." else "my-template"

    # --from: fetch from registry and copy source files into DIR
    if from_ref:
        from easy_sandbox.utils.async_bridge import run_sync
        from easy_sandbox.utils.registry import RegistryClient

        client = RegistryClient()
        ref = run_sync(client.resolve(from_ref))
        if ref.is_builtin:
            raise click.UsageError(
                f"'{from_ref}' is a built-in template and cannot be used with --from. "
                "Use -t/--template for built-in cases."
            )
        with out.spinner(f"Fetching template from {from_ref}"):
            source_path = run_sync(client.fetch(ref))

        source = Path(source_path)
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
        if sys.stdin.isatty():
            click.echo("Available scaffold cases:")
            for i, (c, desc) in enumerate(cases, 1):
                click.echo(f"  {i}. {c:<12} {desc}")
            choice = click.prompt(
                "Select a case",
                type=click.IntRange(1, len(cases)),
                default=1,
            )
            case = cases[choice - 1][0]
        else:
            case_names = ", ".join(c for c, _ in cases)
            raise click.UsageError(
                f"No scaffold case specified. Available cases: {case_names}. "
                "Use -t/--template <case> or --from <ref>."
            )

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
) -> None:
    """Print a friendly summary after scaffold init."""
    if fmt.use_json:
        fmt.print_data({"name": name, "directory": str(target), "files": created})
        return
    out.info(f"\n✅ Template '{name}' created in {target}")
    out.info("Created files:")
    for f in sorted(created):
        out.info(f"  {f}")
    out.info("\nNext steps:")
    dir_arg = str(target) if str(target) != str(Path.cwd()) else "."
    out.info(f"  ebx template deploy {dir_arg} --acr-namespace <ns>")
    out.info(f"  ebx install {dir_arg} --acr-namespace <ns>")


# ---------------------------------------------------------------------------
# Top-level shortcuts: ebx install / ebx init
# ---------------------------------------------------------------------------


@click.command("install")
@click.argument("template_ref")
@click.option(
    "--registry-url",
    default="https://github.com",
    help="Registry URL（默认 GitHub）",
)
@click.option(
    "--registry-type",
    type=click.Choice(["github", "local"]),
    default=None,
    help="Registry type (auto-detected if not specified)",
)
@click.option("--token", default=None, help="访问令牌（私有仓库需要）")
@click.option("--alias", "-a", default=None, help="模板别名")
@click.option(
    "--download-only",
    is_flag=True,
    default=False,
    help="Only download to local cache (skip build and deploy)",
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
    acr_namespace: str | None,
    cpu: int | None,
    memory: int | None,
    yes: bool,
) -> None:
    """Install a template (shortcut for 'ebx template install').

    Downloads and (by default) builds + deploys a template.
    Use --download-only to skip the build/deploy step.
    """
    ctx.invoke(
        install,
        template_ref=template_ref,
        registry_url=registry_url,
        registry_type=registry_type,
        token=token,
        alias=alias,
        download_only=download_only,
        acr_namespace=acr_namespace,
        cpu=cpu,
        memory=memory,
        yes=yes,
    )


@click.command("init")
@click.argument("directory", default=".", type=click.Path())
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
    help="Fetch template source from a registry ref",
)
@click.option("--name", default=None, help="Template name")
@click.option(
    "--list", "list_cases", is_flag=True, default=False,
    help="List available scaffold cases",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite existing files")
@click.pass_context
@handle_errors
def init_shortcut(
    ctx: click.Context,
    directory: str,
    case: str | None,
    from_ref: str | None,
    name: str | None,
    list_cases: bool,
    force: bool,
) -> None:
    """Scaffold a new template (shortcut for 'ebx template init')."""
    ctx.invoke(
        init,
        directory=directory,
        case=case,
        from_ref=from_ref,
        name=name,
        list_cases=list_cases,
        force=force,
    )
