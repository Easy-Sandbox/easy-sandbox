"""Official Alibaba Cloud FCSandbox CreateTemplate API adapter.

This module wraps the ``alibabacloud-fcsandbox20260509`` SDK to provide
a clean, SDK-independent interface for creating sandbox templates via
the official Alibaba Cloud API.

Layer: L3 (API) — may import L0 (models, utils) and L1 (transport).
"""
from __future__ import annotations

from typing import Any

from easy_sandbox.utils.logging import get_logger

logger = get_logger("api.fc_template")

# ---------------------------------------------------------------------------
# Friendly import guard
# ---------------------------------------------------------------------------

_SDK_INSTALL_HINT = (
    'Official Alibaba Cloud FCSandbox SDK is not installed.\n'
    'Install with: pip install "easy-sandbox[alicloud]"'
)


def _require_sdk() -> None:
    """Raise a clear error when the optional alicloud SDK is missing."""
    try:
        import alibabacloud_fcsandbox20260509  # noqa: F401
    except ImportError as exc:
        from easy_sandbox.models.errors import SandboxError

        raise SandboxError(
            _SDK_INSTALL_HINT,
            suggestion='pip install "easy-sandbox[alicloud]"',
        ) from exc


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_team_id(
    access_key_id: str,
    access_key_secret: str,
    region: str = "cn-hangzhou",
    *,
    endpoint: str | None = None,
) -> str:
    """Retrieve the first available team ID via ``ListTeams``.

    Args:
        access_key_id: Alibaba Cloud AccessKey ID.
        access_key_secret: Alibaba Cloud AccessKey Secret.
        region: Region ID (default ``cn-hangzhou``).
        endpoint: Override API endpoint.

    Returns:
        The ``teamID`` string.

    Raises:
        SandboxError: If SDK is missing or no teams found.
    """
    _require_sdk()

    from alibabacloud_fcsandbox20260509 import models as sdk_models
    from alibabacloud_fcsandbox20260509.client import Client
    from alibabacloud_tea_openapi.models import Config

    config = Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id=region,
        endpoint=endpoint or f"fcsandbox.{region}.aliyuncs.com",
    )
    client = Client(config)

    try:
        resp = client.list_teams(sdk_models.ListTeamsRequest())
    except Exception as exc:
        from easy_sandbox.models.errors import NetworkError

        raise NetworkError(
            f"ListTeams API call failed: {exc}",
            suggestion="Check AK/SK credentials and network connectivity.",
        ) from exc

    teams = resp.body.teams if resp.body and resp.body.teams else []
    if not teams:
        from easy_sandbox.models.errors import SandboxError

        raise SandboxError(
            "No teams found for the given credentials.",
            suggestion=(
                "Ensure the Alibaba Cloud account has FCSandbox teams, "
                "or pass --team-id explicitly."
            ),
        )

    team_id: str = teams[0].team_id or ""
    logger.info("Resolved team ID: %s (from %d team(s))", team_id, len(teams))
    return team_id


def get_template(
    template_id: str,
    *,
    access_key_id: str,
    access_key_secret: str,
    region: str = "cn-hangzhou",
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Query template status via ``GetTemplate``.

    Returns:
        Dict with template details from the API response.
    """
    _require_sdk()

    from alibabacloud_fcsandbox20260509 import models as sdk_models
    from alibabacloud_fcsandbox20260509.client import Client
    from alibabacloud_tea_openapi.models import Config

    config = Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id=region,
        endpoint=endpoint or f"fcsandbox.{region}.aliyuncs.com",
    )
    client = Client(config)

    try:
        resp = client.get_template(template_id, sdk_models.GetTemplateRequest())
    except Exception as exc:
        from easy_sandbox.models.errors import NetworkError

        raise NetworkError(
            f"GetTemplate API call failed: {exc}",
            suggestion="Check template ID, AK/SK, and network connectivity.",
        ) from exc

    body = resp.body
    result: dict[str, Any] = {}
    if body:
        # Extract all available fields from the response body
        body_map = body.to_map() if hasattr(body, "to_map") else {}
        result.update(body_map)
    result["statusCode"] = resp.status_code
    return result


# ---------------------------------------------------------------------------
# Helpers: find + update existing template (409 fallback)
# ---------------------------------------------------------------------------


def _find_template_by_name(
    client: Any,
    team_id: str,
    name: str,
) -> str | None:
    """Search for a template by name in the given team.

    Returns the templateID if found, else ``None``.
    Handles pagination to ensure all templates are checked.
    """
    from alibabacloud_fcsandbox20260509 import models as sdk_models

    next_token: str | None = None
    while True:
        try:
            req = sdk_models.ListTemplatesRequest(
                team_id=team_id, max_results=100, next_token=next_token,
            )
            resp = client.list_templates(req)
        except Exception:
            return None

        templates = resp.body.templates if resp.body and resp.body.templates else []
        for tpl in templates:
            if tpl.name == name:
                return tpl.template_id  # type: ignore[return-value]

        next_token = resp.body.next_token if resp.body else None
        if not next_token:
            break

    return None


def _update_existing_template(
    *,
    client: Any,
    name: str,
    team_id: str,
    image: str,
    cpu: float,
    memory_size: int,
    disk_size: int | None,
    internet_access: bool | None,
    generation: int,
    start_command: str | None,
    ready_command: str | None,
    envd_inject: bool,
    effective_registry_type: str | None,
    acr_instance_id: str | None,
    registry_username: str | None,
    registry_password: str | None,
    registry_vpc_id: str | None,
    registry_vswitch_id: str | None,
    registry_security_group_id: str | None,
) -> dict[str, Any]:
    """Update an existing template by name (fallback for 409)."""
    from alibabacloud_fcsandbox20260509 import models as sdk_models

    template_id = _find_template_by_name(client, team_id, name)
    if not template_id:
        from easy_sandbox.models.errors import TemplateBuildError

        raise TemplateBuildError(
            f"Template '{name}' already exists but could not be found for update.",
            suggestion="Delete the old template or use a different name.",
        )

    # Build registry config for copy action
    copy_registry_config = None
    if registry_username or registry_password:
        copy_auth = sdk_models.PublicUpdateTemplateRegistryAuthConfig(
            user_name=registry_username or "",
            password=registry_password or "",
        )
        copy_network = None
        if registry_vpc_id or registry_vswitch_id or registry_security_group_id:
            copy_network = sdk_models.PublicUpdateTemplateRegistryNetworkConfig(
                vpc_id=registry_vpc_id,
                v_switch_id=registry_vswitch_id,
                security_group_id=registry_security_group_id,
            )
        copy_registry_config = sdk_models.PublicUpdateTemplateRegistryConfig(
            auth_config=copy_auth,
            network_config=copy_network,
        )

    # Build sandbox config
    # Note: generation and osType cannot be modified via UpdateTemplate;
    # only image, start_command, ready_command, registry_* are allowed.
    sandbox_config = sdk_models.PublicUpdateTemplateSandboxConfig(
        image=image,
        registry_type=effective_registry_type,
        acr_instance_id=acr_instance_id,
        start_command=start_command,
        ready_command=ready_command,
        registry_config=copy_registry_config,
    )

    # Build runtime config
    runtime_config = sdk_models.PublicUpdateTemplateRuntimeConfig(
        cpu=cpu,
        memory_size=memory_size,
        disk_size=disk_size,
        internet_access=internet_access,
        sandbox_config=sandbox_config,
    )

    # Build build config
    build_config = None
    if envd_inject:
        copy_action = sdk_models.PublicUpdateTemplateCopyAction(
            enabled=True,
            image=image,
            registry_type=effective_registry_type,
            acr_instance_id=acr_instance_id,
            registry_config=copy_registry_config,
        )
        build_config = sdk_models.PublicUpdateTemplateBuildConfig(
            envd_inject=sdk_models.PublicUpdateTemplateEnvdInjectAction(enabled=True),
            copy=copy_action,
        )

    update_input = sdk_models.PublicUpdateTemplateInput(
        runtime_config=runtime_config,
        build_config=build_config,
    )
    request = sdk_models.UpdateTemplateRequest(
        body=update_input,
        team_id=team_id,
    )

    logger.info(
        "Calling UpdateTemplate: id=%s, name=%s, image=%s",
        template_id, name, image,
    )

    try:
        resp = client.update_template(template_id, request)
    except Exception as exc:
        from easy_sandbox.models.errors import TemplateBuildError

        raise TemplateBuildError(
            f"UpdateTemplate API call failed: {exc}",
            suggestion="Check template status, AK/SK credentials, and image URL.",
        ) from exc

    body = resp.body
    result: dict[str, Any] = {
        "templateID": template_id,
        "requestId": body.request_id if body else None,
        "code": None,
        "message": "updated (was already existing)",
        "statusCode": resp.status_code,
    }

    logger.info(
        "UpdateTemplate succeeded: templateID=%s, statusCode=%s",
        template_id, resp.status_code,
    )

    return result


# ---------------------------------------------------------------------------
# Core: create_official_template
# ---------------------------------------------------------------------------


def create_official_template(
    *,
    name: str,
    image: str,
    access_key_id: str,
    access_key_secret: str,
    region: str = "cn-hangzhou",
    team_id: str | None = None,
    endpoint: str | None = None,
    cpu: float = 2,
    memory_size: int = 2048,
    disk_size: int | None = None,
    internet_access: bool | None = None,
    generation: int = 1,
    start_command: str | None = None,
    ready_command: str | None = None,
    envd_inject: bool = False,
    registry_type: str | None = None,
    acr_instance_id: str | None = None,
    registry_username: str | None = None,
    registry_password: str | None = None,
    registry_vpc_id: str | None = None,
    registry_vswitch_id: str | None = None,
    registry_security_group_id: str | None = None,
) -> dict[str, Any]:
    """Create a sandbox template via the official Alibaba Cloud CreateTemplate API.

    Internally lazy-imports the ``alibabacloud-fcsandbox20260509`` SDK.
    Raises a friendly error if the SDK is not installed.

    Args:
        name: Template name.
        image: Container image URL (e.g. ``registry.cn-hangzhou.aliyuncs.com/ns/repo:tag``).
        access_key_id: Alibaba Cloud AccessKey ID.
        access_key_secret: Alibaba Cloud AccessKey Secret.
        region: Region ID (default ``cn-hangzhou``).
        team_id: Team ID. If ``None``, auto-resolved via ``ListTeams``.
        endpoint: Override API endpoint (default ``fcsandbox.<region>.aliyuncs.com``).
        cpu: CPU cores (default 2).
        memory_size: Memory in MB (default 2048).
        disk_size: Disk size in MB (optional).
        internet_access: Whether sandbox has internet access (optional).
        generation: Sandbox generation (default 1, required by API).
        start_command: Container start command (optional).
        ready_command: Container ready check command (optional).
        envd_inject: Enable envd injection for the build (default ``False``).
        registry_type: Registry type (``"acr"`` or ``"acree"``). Auto-detected
            from ``acr_instance_id`` if not set.
        acr_instance_id: ACR EE instance ID (optional).
        registry_username: Registry login username for pulling image.
        registry_password: Registry login password for pulling image.
        registry_vpc_id: VPC ID for registry network access.
        registry_vswitch_id: VSwitch ID for registry network access.
        registry_security_group_id: Security group ID for registry network access.

    Returns:
        Dict with keys: ``templateID``, ``requestId``, ``code``, ``message``,
        ``statusCode``.

    Raises:
        SandboxError: If the SDK is missing.
        NetworkError: If the API call fails.
    """
    _require_sdk()

    from alibabacloud_fcsandbox20260509 import models as sdk_models
    from alibabacloud_fcsandbox20260509.client import Client
    from alibabacloud_tea_openapi.models import Config

    # Auto-resolve team_id if not provided
    if not team_id:
        logger.info("No team_id provided, auto-resolving via ListTeams...")
        team_id = get_team_id(
            access_key_id, access_key_secret, region, endpoint=endpoint,
        )

    # Auto-detect registry_type
    effective_registry_type = registry_type
    if not effective_registry_type:
        effective_registry_type = "acree" if acr_instance_id else None

    # Build registry config if credentials provided
    registry_config = None
    if registry_username or registry_password:
        auth_config = sdk_models.CreateTemplateRegistryAuthConfig(
            user_name=registry_username or "",
            password=registry_password or "",
        )
        network_config = None
        if registry_vpc_id or registry_vswitch_id or registry_security_group_id:
            network_config = sdk_models.CreateTemplateRegistryNetworkConfig(
                vpc_id=registry_vpc_id,
                v_switch_id=registry_vswitch_id,
                security_group_id=registry_security_group_id,
            )
        registry_config = sdk_models.CreateTemplateRegistryConfig(
            auth_config=auth_config,
            network_config=network_config,
        )

    # Build sandbox config
    sandbox_config = sdk_models.CreateTemplateSandboxConfig(
        image=image,
        generation=generation,
        registry_type=effective_registry_type,
        acr_instance_id=acr_instance_id,
        start_command=start_command,
        ready_command=ready_command,
        registry_config=registry_config,
    )

    # Build runtime config
    runtime_config = sdk_models.CreateTemplateRuntimeConfig(
        cpu=cpu,
        memory_size=memory_size,
        disk_size=disk_size,
        internet_access=internet_access,
        sandbox_config=sandbox_config,
    )

    # Build build config (envd inject)
    # When envdInject is enabled, the API requires copy.enabled=True as well.
    build_config = None
    if envd_inject:
        # Build copy action — copies the user image into an internal registry
        # so that envd can inject into it.
        copy_auth = None
        if registry_username or registry_password:
            copy_auth = sdk_models.CreateTemplateRegistryAuthConfig(
                user_name=registry_username or "",
                password=registry_password or "",
            )
        copy_network = None
        if registry_vpc_id or registry_vswitch_id or registry_security_group_id:
            copy_network = sdk_models.CreateTemplateRegistryNetworkConfig(
                vpc_id=registry_vpc_id,
                v_switch_id=registry_vswitch_id,
                security_group_id=registry_security_group_id,
            )
        copy_registry_config = None
        if copy_auth or copy_network:
            copy_registry_config = sdk_models.CreateTemplateRegistryConfig(
                auth_config=copy_auth,
                network_config=copy_network,
            )
        copy_action = sdk_models.CreateTemplateCopyAction(
            enabled=True,
            image=image,
            registry_type=effective_registry_type,
            acr_instance_id=acr_instance_id,
            registry_config=copy_registry_config,
        )
        build_config = sdk_models.CreateTemplateBuildConfig(
            envd_inject=sdk_models.CreateTemplateEnvdInjectAction(enabled=True),
            copy=copy_action,
        )

    # Assemble the request
    create_input = sdk_models.CreateTemplateInput(
        name=name,
        team_id=team_id,
        runtime_config=runtime_config,
        build_config=build_config,
    )
    request = sdk_models.CreateTemplateRequest(body=create_input)

    # Create SDK client
    resolved_endpoint = endpoint or f"fcsandbox.{region}.aliyuncs.com"
    config = Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id=region,
        endpoint=resolved_endpoint,
    )
    client = Client(config)

    logger.info(
        "Calling CreateTemplate: name=%s, image=%s, team=%s, region=%s, "
        "envdInject=%s, generation=%d",
        name, image, team_id, region, envd_inject, generation,
    )

    try:
        resp = client.create_template(request)
    except Exception as exc:
        exc_str = str(exc)
        # Handle 409 TemplateAlreadyExists by falling back to UpdateTemplate
        if "TemplateAlreadyExists" in exc_str or "409" in exc_str:
            logger.info(
                "Template '%s' already exists, attempting UpdateTemplate...", name,
            )
            return _update_existing_template(
                client=client,
                name=name,
                team_id=team_id or "",
                image=image,
                cpu=cpu,
                memory_size=memory_size,
                disk_size=disk_size,
                internet_access=internet_access,
                generation=generation,
                start_command=start_command,
                ready_command=ready_command,
                envd_inject=envd_inject,
                effective_registry_type=effective_registry_type,
                acr_instance_id=acr_instance_id,
                registry_username=registry_username,
                registry_password=registry_password,
                registry_vpc_id=registry_vpc_id,
                registry_vswitch_id=registry_vswitch_id,
                registry_security_group_id=registry_security_group_id,
            )

        from easy_sandbox.models.errors import TemplateBuildError

        raise TemplateBuildError(
            f"CreateTemplate API call failed: {exc}",
            suggestion=(
                "Check AK/SK credentials, image URL, and network. "
                "Ensure the image is accessible from the FC sandbox platform."
            ),
        ) from exc

    body = resp.body
    result: dict[str, Any] = {
        "templateID": body.template_id if body else None,
        "requestId": body.request_id if body else None,
        "code": body.code if body else None,
        "message": body.message if body else None,
        "statusCode": resp.status_code,
    }

    logger.info(
        "CreateTemplate succeeded: templateID=%s, statusCode=%s",
        result.get("templateID"), result.get("statusCode"),
    )

    return result


# ---------------------------------------------------------------------------
# Request body builder (for testing / inspection)
# ---------------------------------------------------------------------------


def build_create_template_request_map(
    *,
    name: str,
    image: str,
    team_id: str,
    cpu: float = 2,
    memory_size: int = 2048,
    disk_size: int | None = None,
    internet_access: bool | None = None,
    generation: int = 1,
    start_command: str | None = None,
    ready_command: str | None = None,
    envd_inject: bool = False,
    registry_type: str | None = None,
    acr_instance_id: str | None = None,
    registry_username: str | None = None,
    registry_password: str | None = None,
) -> dict[str, Any]:
    """Build the CreateTemplateRequest as a dict (for testing / debugging).

    This constructs the same request body that ``create_official_template``
    would send, but returns the ``to_map()`` dict without making an API call.

    Requires the alicloud SDK to be installed.
    """
    _require_sdk()

    from alibabacloud_fcsandbox20260509 import models as sdk_models

    effective_registry_type = registry_type
    if not effective_registry_type:
        effective_registry_type = "acree" if acr_instance_id else None

    registry_config = None
    if registry_username or registry_password:
        registry_config = sdk_models.CreateTemplateRegistryConfig(
            auth_config=sdk_models.CreateTemplateRegistryAuthConfig(
                user_name=registry_username or "",
                password=registry_password or "",
            ),
        )

    sandbox_config = sdk_models.CreateTemplateSandboxConfig(
        image=image,
        generation=generation,
        registry_type=effective_registry_type,
        acr_instance_id=acr_instance_id,
        start_command=start_command,
        ready_command=ready_command,
        registry_config=registry_config,
    )

    runtime_config = sdk_models.CreateTemplateRuntimeConfig(
        cpu=cpu,
        memory_size=memory_size,
        disk_size=disk_size,
        internet_access=internet_access,
        sandbox_config=sandbox_config,
    )

    build_config = None
    if envd_inject:
        copy_rc = None
        if registry_username or registry_password:
            copy_rc = sdk_models.CreateTemplateRegistryConfig(
                auth_config=sdk_models.CreateTemplateRegistryAuthConfig(
                    user_name=registry_username or "",
                    password=registry_password or "",
                ),
            )
        copy_action = sdk_models.CreateTemplateCopyAction(
            enabled=True,
            image=image,
            registry_type=registry_type if registry_type else (
                "acree" if acr_instance_id else None
            ),
            acr_instance_id=acr_instance_id,
            registry_config=copy_rc,
        )
        build_config = sdk_models.CreateTemplateBuildConfig(
            envd_inject=sdk_models.CreateTemplateEnvdInjectAction(enabled=True),
            copy=copy_action,
        )

    create_input = sdk_models.CreateTemplateInput(
        name=name,
        team_id=team_id,
        runtime_config=runtime_config,
        build_config=build_config,
    )
    request = sdk_models.CreateTemplateRequest(body=create_input)
    return request.to_map()
