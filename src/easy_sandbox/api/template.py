"""Template management — high-level API.

Usage:
    from easy_sandbox.api.template import TemplateManager
    from easy_sandbox.transport.config import load_config
    from easy_sandbox.transport.auth import create_auth_provider
    from easy_sandbox.transport.http import HttpClient

    config = load_config(api_key="...")
    auth = create_auth_provider(api_key=config.api_key)
    http = HttpClient(config, auth)

    manager = TemplateManager(http)
    info = await manager.build("FROM python:3.11\\nRUN pip install flask")
"""
from __future__ import annotations

from typing import Any

from easy_sandbox.models.template import TemplateInfo, BuildStatus
from easy_sandbox.protocol.template import TemplateProtocol
from easy_sandbox.transport.http import HttpClient
from easy_sandbox.utils.logging import get_logger

logger = get_logger("api.template")


class TemplateManager:
    """Template management high-level API.

    Wraps TemplateProtocol with a friendlier interface that returns
    typed TemplateInfo objects.
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client
        self._protocol = TemplateProtocol(http_client)

    async def build(
        self,
        dockerfile: str,
        *,
        alias: str | None = None,
        timeout: int = 600,
        poll_interval: int = 5,
        cpu_count: int | None = None,
        memory_mb: int | None = None,
        start_cmd: str | None = None,
        ready_cmd: str | None = None,
    ) -> TemplateInfo:
        """Build a template (synchronously wait for completion).

        Args:
            dockerfile: Dockerfile content.
            alias: Template alias name.
            timeout: Maximum build wait time in seconds.
            poll_interval: Seconds between status polls.
            cpu_count: Default CPU count for sandboxes from this template.
            memory_mb: Default memory in MB.
            start_cmd: Start command.
            ready_cmd: Readiness check command.

        Returns:
            TemplateInfo with build_status=ready.
        """
        template_id, build_id = await self.build_in_background(
            dockerfile,
            alias=alias,
            cpu_count=cpu_count,
            memory_mb=memory_mb,
            start_cmd=start_cmd,
            ready_cmd=ready_cmd,
        )

        # Wait for build to complete
        await self._protocol.wait_for_build(
            template_id,
            build_id,
            timeout=timeout,
            poll_interval=poll_interval,
        )

        # Fetch final template info
        data = await self._protocol.get(template_id)
        info = TemplateInfo.model_validate(data)
        # Override build_status since we confirmed the build completed
        info.build_status = BuildStatus.READY
        logger.info("Template built successfully: %s", template_id)
        return info

    async def build_in_background(
        self,
        dockerfile: str,
        *,
        alias: str | None = None,
        cpu_count: int | None = None,
        memory_mb: int | None = None,
        start_cmd: str | None = None,
        ready_cmd: str | None = None,
    ) -> tuple[str, str]:
        """Build a template in the background.

        Returns:
            Tuple of (template_id, build_id).
        """
        data = await self._protocol.create(
            dockerfile,
            alias=alias,
            cpu_count=cpu_count,
            memory_mb=memory_mb,
            start_cmd=start_cmd,
            ready_cmd=ready_cmd,
        )
        template_id = data["templateID"]
        build_id = data["buildID"]
        logger.info(
            "Template build started: templateID=%s, buildID=%s",
            template_id,
            build_id,
        )
        return template_id, build_id

    async def list(self) -> list[TemplateInfo]:
        """List all templates.

        Returns:
            List of TemplateInfo objects.
        """
        items = await self._protocol.list()
        return [TemplateInfo.model_validate(item) for item in items]

    async def get(self, template_id: str) -> TemplateInfo:
        """Get template details.

        Args:
            template_id: Template ID.

        Returns:
            TemplateInfo object.
        """
        data = await self._protocol.get(template_id)
        return TemplateInfo.model_validate(data)

    async def delete(self, template_id: str) -> None:
        """Delete a template.

        Args:
            template_id: Template ID to delete.
        """
        await self._protocol.delete(template_id)
        logger.info("Template deleted: %s", template_id)

    async def get_build_status(
        self, template_id: str, build_id: str
    ) -> dict[str, Any]:
        """Get build status for a template build.

        Args:
            template_id: Template ID.
            build_id: Build ID.

        Returns:
            Build status dict.
        """
        return await self._protocol.get_build_status(template_id, build_id)

    # ------------------------------------------------------------------ #
    # v3/v2 API — current backend
    # ------------------------------------------------------------------ #

    async def build_from_image(
        self,
        from_image: str,
        *,
        name: str,
        cpu_count: int = 2,
        memory_mb: int = 2048,
        start_cmd: str | None = None,
        ready_cmd: str | None = None,
        tags: list[str] | None = None,
        acr_headers: dict[str, str] | None = None,
        timeout: int = 600,
        poll_interval: int = 5,
    ) -> TemplateInfo:
        """Build a template from a pre-built image via v3/v2 APIs.

        This is the modern build path aligned with E2B SDK 2.31.0:
        1. ``POST /v3/templates`` — create metadata
        2. ``POST /v2/templates/{tpl}/builds/{build}`` — trigger build
        3. Poll build status until ready.

        Args:
            from_image: Full image reference (e.g. ACR EE image URL).
            name: Template name / alias.
            cpu_count: Default CPU count.
            memory_mb: Default memory in MB.
            start_cmd: Start command for sandboxes.
            ready_cmd: Readiness check command.
            tags: Template tags.
            acr_headers: ACR EE configuration headers.
            timeout: Build wait timeout in seconds.
            poll_interval: Status poll interval in seconds.

        Returns:
            TemplateInfo with build_status=ready.
        """
        # Step 1: Create metadata
        v3_data = await self._protocol.create_v3(
            name, cpu_count=cpu_count, memory_mb=memory_mb, tags=tags,
        )
        template_id = v3_data["templateID"]
        build_id = v3_data["buildID"]
        logger.info(
            "Template v3 metadata created: templateID=%s, buildID=%s",
            template_id, build_id,
        )

        # Step 2: Trigger build
        await self._protocol.trigger_build_v2(
            template_id, build_id,
            from_image=from_image,
            start_cmd=start_cmd,
            ready_cmd=ready_cmd,
            acr_headers=acr_headers,
        )

        # Step 3: Wait for build
        await self._protocol.wait_for_build(
            template_id, build_id,
            timeout=timeout, poll_interval=poll_interval,
        )

        # Fetch final info
        data = await self._protocol.get(template_id)
        info = TemplateInfo.model_validate(data)
        info.build_status = BuildStatus.READY
        logger.info("Template built from image: %s", template_id)
        return info
