"""模板管理 CLI 命令。"""
from __future__ import annotations

import sys
from typing import Any

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors
from easy_sandbox.cli.output import get_output


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
                "Check the TEMPLATE_ID (run 'ebx template list' to see "
                "available templates)."
            ),
        )
    return NetworkError(
        f"{context} failed (HTTP {status}): {detail}",
        suggestion=(
            "Check your authentication (ebx auth / API key) and the platform "
            "status, then retry."
        ),
    )


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
@click.pass_context
@handle_errors
def install(
    ctx: click.Context,
    template_ref: str,
    registry_url: str,
    registry_type: str | None,
    token: str | None,
    alias: str | None,
) -> None:
    """Install a template from GitHub or a local directory.

    There is no central template registry.  Templates are sourced from
    GitHub repos (fetched by tag/branch/sha via the GitHub tarball API,
    no Release required) or local directories.

    示例：\n
      ebx template install owner/repo              # GitHub repo (default branch)\n
      ebx template install owner/repo//subdir      # Subdirectory of a repo\n
      ebx template install owner/repo//subdir@v1.0 # Subdirectory + tag/branch/sha\n
      ebx template install owner/repo@main         # Specific branch\n
      ebx template install owner/repo@v1.0         # Specific tag\n
      ebx template install owner/repo --token xxx  # Private repo\n
      ebx template install ./my-template           # Local directory\n
      ebx template install /path/to/tmpl --registry-type local
    """
    from easy_sandbox.utils.async_bridge import run_sync
    from easy_sandbox.utils.registry import RegistryClient, load_template_from_yaml

    fmt = get_formatter(ctx)

    client = RegistryClient(registry_url=registry_url, token=token)
    ref = run_sync(client.resolve(template_ref, registry_type=registry_type))

    if ref.is_builtin:
        fmt.print_success(
            f"'{template_ref}' is a built-in template. No installation needed."
        )
        fmt.print_success(
            f"Use it directly: ebx create --template {template_ref}"
        )
        return

    # 拉取模板（本地或 GitHub）
    if ref.registry_type == "local":
        fmt.print_success(f"Using local template from {ref.local_path}...")
    else:
        fmt.print_success(f"Fetching template from {ref.owner}/{ref.repo}...")
    template_path = run_sync(client.fetch(ref))

    # 加载 template.yaml（或 sandbox-template.yaml / sandbox.yaml 向后兼容）
    yaml_path = template_path / "template.yaml"
    if not yaml_path.exists():
        alt = template_path / "sandbox-template.yaml"
        if alt.exists():
            yaml_path = alt
        else:
            alt2 = template_path / "sandbox.yaml"
            if alt2.exists():
                yaml_path = alt2
            else:
                fmt.print_error(
                    f"No template.yaml (or sandbox-template.yaml / sandbox.yaml) found in {template_path}",
                    suggestion=(
                        "Ensure the repository contains a template.yaml"
                        " at the root."
                    ),
                )
                sys.exit(1)

    tmpl = load_template_from_yaml(yaml_path)
    dockerfile = tmpl.to_dockerfile()

    # 调用 Platform API 构建模板
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.http import HttpClient

    config = load_config(region=ctx.obj.get("region") if ctx.obj else None)
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)

    build_alias = alias or tmpl.name
    body = {"dockerfile": dockerfile}
    if build_alias:
        body["alias"] = build_alias

    async def _submit_and_close():
        import httpx

        from easy_sandbox.models.errors import TemplateBuildError

        try:
            resp = await http_client.platform_request("POST", "/templates", json=body)
            return resp.json()
        except httpx.HTTPStatusError as exc:
            detail = _extract_platform_error(exc.response)
            raise TemplateBuildError(
                f"Build submission rejected by platform: {detail}",
                suggestion=(
                    "Review the template's Dockerfile/config and try again. "
                    "Run 'ebx template list' to check existing builds."
                ),
            ) from exc
        finally:
            await http_client.close()

    result = run_sync(_submit_and_close())

    data = {
        "TemplateID": result.get("templateID", "N/A"),
        "BuildID": result.get("buildID", "N/A"),
        "Alias": build_alias or "N/A",
        "Status": "building",
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success("Template build submitted. Use 'ebx template list' to check status.")


@template.command("list")
@click.pass_context
@handle_errors
def list_templates(ctx: click.Context) -> None:
    """List your custom templates on the platform.

    Shows templates you have built or installed on the platform via
    'ebx template build' or 'ebx template install'.  This does NOT
    query a central registry.  To discover community templates, visit
    GitHub and install with 'ebx template install <owner/repo>'.
    """
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.auth import create_auth_provider
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

    async def _list_and_close():
        import httpx

        try:
            resp = await http_client.platform_request("GET", "/templates")
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise _translate_platform_error(
                exc, context="Listing templates"
            ) from exc
        finally:
            await http_client.close()

    templates = run_sync(_list_and_close())

    if not templates:
        fmt.print_success(
            "No custom templates found. "
            "Use 'ebx template install <repo>' to install from GitHub."
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
@click.pass_context
@handle_errors
def info(ctx: click.Context, template_id: str) -> None:
    """查看模板详情。"""
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.auth import create_auth_provider
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

    async def _info_and_close():
        import httpx

        try:
            resp = await http_client.platform_request(
                "GET", f"/templates/{template_id}"
            )
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise _translate_platform_error(
                exc, context="Fetching template info", template_id=template_id
            ) from exc
        finally:
            await http_client.close()

    data = run_sync(_info_and_close())

    fmt.print_data(data)


@template.command("create")
@click.argument("image")
@click.option("--name", "-n", required=True, help="Template name")
@click.option("--team-id", envvar=["TEAM_ID", "E2B_TEAM_ID"], default=None,
              help="Team ID (or env TEAM_ID / E2B_TEAM_ID; auto-resolved if omitted)")
@click.option("--cpu", type=float, default=2, help="CPU cores (default 2)")
@click.option("--memory", type=int, default=2048, help="Memory in MB (default 2048)")
@click.option("--disk-size", type=int, default=None, help="Disk size in MB")
@click.option("--internet-access/--no-internet-access", default=None,
              help="Internet access (default: platform decides)")
@click.option("--start-cmd", default=None, help="Container start command")
@click.option("--ready-cmd", default=None, help="Container readiness check command")
@click.option("--generation", type=int, default=1,
              help="Sandbox generation (default 1)")
@click.option("--envd-inject/--no-envd-inject", default=False,
              help="Enable envd injection in build")
@click.option("--registry-type", type=click.Choice(["acr", "acree"]),
              default=None, help="Registry type (auto-detected from --acree-instance-id)")
@click.option("--acree-instance-id", envvar="ACREE_INSTANCE_ID", default=None,
              help="ACR EE instance ID (cri-...)")
@click.option("--registry-username", default=None,
              help="Registry login username (for pulling image)")
@click.option("--registry-password", default=None,
              help="Registry login password (for pulling image)")
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
            fmt.print_success(
                f"Template created! Use: ebx create --template {template_id}"
            )


@template.command("build")
@click.option("--dockerfile", "-f", required=True, type=click.Path(exists=True))
@click.option("--alias", "-a", default=None, help="模板别名")
@click.pass_context
@handle_errors
def build(ctx: click.Context, dockerfile: str, alias: str | None) -> None:
    """从 Dockerfile 构建模板（旧 API，已知后端不再支持实际构建）。"""
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.http import HttpClient
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)

    with open(dockerfile) as f:
        dockerfile_content = f.read()

    config = load_config(region=ctx.obj.get("region") if ctx.obj else None)
    auth = create_auth_provider(
        api_key=config.api_key,
        access_key_id=config.access_key_id,
        access_key_secret=config.access_key_secret,
    )
    http_client = HttpClient(config, auth)

    body: dict[str, str] = {"dockerfile": dockerfile_content}
    if alias:
        body["alias"] = alias

    async def _build_and_close():
        import httpx

        from easy_sandbox.models.errors import TemplateBuildError

        try:
            resp = await http_client.platform_request("POST", "/templates", json=body)
            return resp.json()
        except httpx.HTTPStatusError as exc:
            detail = _extract_platform_error(exc.response)
            raise TemplateBuildError(
                f"Build submission rejected by platform: {detail}",
                suggestion=(
                    "The legacy build API no longer performs real builds. "
                    "Use 'ebx template install <owner/repo>' or "
                    "'ebx template build-local' instead."
                ),
            ) from exc
        finally:
            await http_client.close()

    result = run_sync(_build_and_close())

    data = {
        "TemplateID": result.get("templateID", "N/A"),
        "BuildID": result.get("buildID", "N/A"),
        "Alias": alias or "N/A",
        "Status": "building",
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        fmt.print_success("Template build submitted.")


@template.command("build-local")
@click.argument("template_dir", type=click.Path(exists=True))
@click.option("--acr-registry", envvar="ACR_REGISTRY",
              default="registry.cn-hangzhou.aliyuncs.com",
              help="ACR registry host")
@click.option("--acr-namespace", envvar="ACR_NAMESPACE", required=True,
              help="ACR namespace")
@click.option("--acr-repo", envvar="ACR_REPO", default=None,
              help="ACR repository name (defaults to template dir name)")
@click.option("--acr-username", envvar="ACR_USERNAME", default=None,
              help="ACR login username (defaults to AccessKey from .env)")
@click.option("--acr-password", envvar="ACR_PASSWORD", default=None,
              help="ACR login password (defaults to AccessSecret from .env)")
@click.option("--acree-instance-id", envvar="ACREE_INSTANCE_ID", default="",
              help="ACR EE instance ID (cri-...)")
@click.option("--vpc-id", envvar="ACR_VPC_ID", default="",
              help="VPC ID for ACR EE")
@click.option("--vswitch-ids", envvar="ACR_VSWITCH_IDS", default="",
              help="Comma-separated VSwitch IDs")
@click.option("--security-group-id", envvar="ACR_SECURITY_GROUP_ID", default="",
              help="Security group ID")
@click.option("--alias", "-a", default=None, help="模板别名")
@click.option("--tag", "-t", default="latest", help="Docker image tag")
@click.option("--platform", default="linux/amd64", help="Target platform")
@click.option("--cpu", type=int, default=2, help="CPU cores for template")
@click.option("--memory", type=int, default=2048, help="Memory in MB")
@click.option("--start-cmd", default=None, help="Container start command")
@click.option("--ready-cmd", default=None, help="Container readiness check command")
@click.option("--timeout", type=int, default=600, help="Build timeout in seconds")
@click.option("--dockerfile", "-f", default=None, type=click.Path(exists=True),
              help="Custom Dockerfile path")
@click.option("--disk-size", type=int, default=None,
              help="Disk size in MB (official API only)")
@click.option("--internet-access/--no-internet-access", default=None,
              help="Internet access (default: platform decides; official API only)")
@click.option("--official-api/--legacy-api", "use_official", default=True,
              help="Use official CreateTemplate API (default) or legacy v3/v2")
@click.option("--team-id", envvar=["TEAM_ID", "E2B_TEAM_ID"], default=None,
              help="Team ID for official API (or env TEAM_ID / E2B_TEAM_ID)")
@click.option("--envd-inject/--no-envd-inject", default=True,
              help="Enable envd injection (default True for official API)")
@click.option("--generation", type=int, default=1,
              help="Sandbox generation (default 1)")
@click.pass_context
@handle_errors
def build_local(
    ctx: click.Context,
    template_dir: str,
    acr_registry: str,
    acr_namespace: str,
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
    cpu: int,
    memory: int,
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
      ebx template build-local ./examples/templates/python-hello \\
        --acr-namespace my-ns --acr-repo python-hello
      ebx template build-local ./my-template \\
        --acr-namespace prod --acree-instance-id cri-xxx
      ebx template build-local ./my-template \\
        --acr-namespace prod --disk-size 10240 --internet-access
      ebx template build-local ./my-template \\
        --acr-namespace prod --legacy-api
    """
    from pathlib import Path
    from easy_sandbox.api.docker_builder import ACRConfig, DockerBuilder
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.utils.async_bridge import run_sync

    fmt = get_formatter(ctx)
    config = load_config(region=ctx.obj.get("region") if ctx.obj else None)

    # Resolve ACR credentials: CLI explicit values take priority,
    # fall back to platform AK/SK from config/.env.
    resolved_acr_username = acr_username or config.access_key_id or ""
    resolved_acr_password = acr_password or config.access_key_secret or ""
    resolved_repo = acr_repo or Path(template_dir).resolve().name

    if not resolved_acr_username or not resolved_acr_password:
        fmt.print_error(
            "ACR credentials missing.",
            suggestion="Set --acr-username/--acr-password or "
            "ALICLOUD_ACCESS_KEY_ID/ALICLOUD_ACCESS_KEY_SECRET in .env",
        )
        sys.exit(1)

    # Platform API credentials always come from load_config().
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

    builder = DockerBuilder()
    template_name = alias or resolved_repo

    def on_progress(msg: str) -> None:
        fmt.print_success(msg)

    region = config.region or "cn-hangzhou"

    if use_official:
        # Official CreateTemplate API path
        if disk_size is not None or internet_access is not None:
            # These options are only supported by the official API
            pass  # will be forwarded below
        result = run_sync(
            builder.build_and_register_official(
                template_dir=template_dir,
                acr=acr,
                name=template_name,
                tag=tag,
                platform=platform,
                dockerfile=dockerfile,
                cpu_count=cpu,
                memory_mb=memory,
                disk_size=disk_size,
                internet_access=internet_access,
                start_cmd=start_cmd,
                ready_cmd=ready_cmd,
                envd_inject=envd_inject,
                generation=generation,
                team_id=team_id,
                region=region,
                on_progress=on_progress,
                acr_access_key_id=resolved_acr_username,
                acr_access_key_secret=resolved_acr_password,
                api_access_key_id=platform_ak,
                api_access_key_secret=platform_sk,
                timeout=timeout,
            )
        )
    else:
        # Legacy v3/v2 API path
        if disk_size is not None or internet_access is not None:
            fmt.print_error(
                "--disk-size and --internet-access are only supported with "
                "the official API (default). They are ignored with --legacy-api.",
            )
        result = run_sync(
            builder.build_and_register(
                template_dir=template_dir,
                acr=acr,
                name=template_name,
                tag=tag,
                platform=platform,
                dockerfile=dockerfile,
                cpu_count=cpu,
                memory_mb=memory,
                start_cmd=start_cmd,
                ready_cmd=ready_cmd,
                on_progress=on_progress,
                api_key=config.api_key,
                api_url=config.api_url,
                access_key_id=config.access_key_id,
                access_key_secret=config.access_key_secret,
                timeout=timeout,
            )
        )

    data = {
        "TemplateID": result.template_id or "N/A",
        "BuildID": result.build_id or "N/A",
        "ACR Image": result.acr_ref or "N/A",
        "Status": result.build_status,
    }
    if fmt.use_json:
        fmt.print_data(data)
    else:
        fmt.print_dict(data)
        if result.build_status == "ready":
            fmt.print_success("Template built and ready!")
            fmt.print_success(
                f"Use: ebx create --template {result.template_id}"
            )
        elif result.build_status == "pushed":
            fmt.print_success("Image pushed to ACR, but template build pending.")
        else:
            fmt.print_error(f"Build status: {result.build_status}")
            if result.logs:
                out = get_output(ctx)
                for log in result.logs:
                    out.info(f"  {log}")


@template.command("delete")
@click.argument("template_id")
@click.confirmation_option(prompt="确认删除模板？")
@click.pass_context
@handle_errors
def delete(ctx: click.Context, template_id: str) -> None:
    """Delete a custom template from the platform.

    Removes the template identified by TEMPLATE_ID from the remote
    platform.  This does NOT affect the local cache — use
    'ebx template cache --clear' to clean local copies.
    """
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.auth import create_auth_provider
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

    async def _delete_and_close():
        import httpx

        try:
            await http_client.platform_request(
                "DELETE", f"/templates/{template_id}"
            )
        except httpx.HTTPStatusError as exc:
            raise _translate_platform_error(
                exc, context="Deleting template", template_id=template_id
            ) from exc
        finally:
            await http_client.close()

    run_sync(_delete_and_close())

    fmt.print_success(f"Template {template_id} deleted.")


@template.command("cache")
@click.option("--clear", is_flag=True, help="Clear local template cache (~/.ebx/templates/)")
@click.pass_context
def cache(ctx: click.Context, clear: bool) -> None:
    """Manage the local template cache (~/.ebx/templates/).

    Without flags, lists cached templates.  With --clear, removes all
    locally cached copies.  This only affects local files — to delete
    a template from the platform, use 'ebx template delete'.
    """
    from easy_sandbox.utils.registry import RegistryClient, TEMPLATE_CACHE_DIR

    out = get_output(ctx)
    client = RegistryClient()
    if clear:
        count = client.clear_cache()
        out.success(f"Cleared {count} cached item(s).")
    else:
        if TEMPLATE_CACHE_DIR.exists():
            items = list(TEMPLATE_CACHE_DIR.rglob("template.yaml"))
            items.extend(
                p for p in TEMPLATE_CACHE_DIR.rglob("sandbox-template.yaml")
                if not (p.parent / "template.yaml").exists()
            )
            items.extend(
                p for p in TEMPLATE_CACHE_DIR.rglob("sandbox.yaml")
                if not (p.parent / "template.yaml").exists()
                and not (p.parent / "sandbox-template.yaml").exists()
            )
            if items:
                out.info(f"Cached templates ({len(items)}):")
                for item in items:
                    out.info(f"  {item.parent.relative_to(TEMPLATE_CACHE_DIR)}")
            else:
                out.info("No templates cached.")
        else:
            out.info("No templates cached.")


@template.command("search")
@click.argument("query")
@click.option(
    "--tag", "-t", default=None,
    help="Filter by exact tag name",
)
@click.option(
    "--status", "-s",
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
# Top-level shortcut: ebx install <ref>
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
@click.pass_context
@handle_errors
def install_shortcut(
    ctx: click.Context,
    template_ref: str,
    registry_url: str,
    registry_type: str | None,
    token: str | None,
    alias: str | None,
) -> None:
    """Install a template (shortcut for 'ebx template install').

    Templates are fetched from GitHub repos — there is no central registry.
    Use TEMPLATE_REF in the form owner/repo, owner/repo//subdir, or a
    local directory path.
    """
    ctx.invoke(
        install,
        template_ref=template_ref,
        registry_url=registry_url,
        registry_type=registry_type,
        token=token,
        alias=alias,
    )
