"""Platform API protocol — template management (REST).

Endpoints (relative to Platform API base URL):

**Legacy (deprecated by backend)**:
  POST /templates → 202, returns templateID + buildID (only creates metadata
  stub; actual build always fails with '400, invalid image format').

**Current v3/v2 API (aligned with E2B SDK 2.31.0)**:
  POST /v3/templates → creates metadata, returns templateID + buildID.
  POST /v2/templates/{tpl}/builds/{build} → triggers real build from an
  image reference (requires ACR EE registry headers).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from serverless_sandbox.models.errors import (
    SandboxError,
    TemplateBuildError,
    TemplateBuildTimeoutError,
)
from serverless_sandbox.transport.http import HttpClient
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("protocol.template")


class TemplateProtocol:
    """Typed wrapper for Platform API template operations.

    已实测验证：POST /templates 返回 HTTP 202, templateID + buildID。
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    async def create(
        self,
        dockerfile: str,
        *,
        alias: str | None = None,
        cpu_count: int | None = None,
        memory_mb: int | None = None,
        start_cmd: str | None = None,
        ready_cmd: str | None = None,
    ) -> dict[str, Any]:
        """Create a template.

        POST /templates → 202（已实测验证）

        Returns:
            dict with templateID and buildID.
        """
        payload: dict[str, Any] = {"dockerfile": dockerfile}
        if alias is not None:
            payload["alias"] = alias
        if cpu_count is not None:
            payload["cpuCount"] = cpu_count
        if memory_mb is not None:
            payload["memoryMB"] = memory_mb
        if start_cmd is not None:
            payload["startCmd"] = start_cmd
        if ready_cmd is not None:
            payload["readyCmd"] = ready_cmd

        try:
            response = await self._http.platform_request(
                "POST", "/templates", json=payload
            )
            data = response.json()
            logger.info(
                "Template creation started: templateID=%s, buildID=%s",
                data.get("templateID"),
                data.get("buildID"),
            )
            return data
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
            except Exception:
                body = {}
            message = body.get("message", str(exc))
            raise SandboxError(message, code=f"E7{status}") from exc

    async def list(self) -> list[dict[str, Any]]:
        """List templates.

        GET /templates → 200
        """
        response = await self._http.platform_request("GET", "/templates")
        data = response.json()
        # API may return list directly or wrapped in a data field
        if isinstance(data, list):
            return data
        return data.get("data", data.get("templates", []))

    async def get(self, template_id: str) -> dict[str, Any]:
        """Get template details.

        GET /templates/{id} → 200
        """
        response = await self._http.platform_request(
            "GET", f"/templates/{template_id}"
        )
        return response.json()

    async def delete(self, template_id: str) -> None:
        """Delete a template.

        DELETE /templates/{id} → 204
        """
        try:
            await self._http.platform_request(
                "DELETE", f"/templates/{template_id}"
            )
            logger.info("Template deleted: %s", template_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning(
                    "Template %s not found (already deleted?)", template_id
                )
                return
            raise

    async def get_build_status(
        self, template_id: str, build_id: str
    ) -> dict[str, Any]:
        """Query build status.

        GET /templates/{id}/builds/{buildId}/status → 200
        """
        response = await self._http.platform_request(
            "GET", f"/templates/{template_id}/builds/{build_id}/status"
        )
        content = response.content
        if content and content.strip():
            try:
                return response.json()
            except Exception:
                logger.warning(
                    "Build status response not valid JSON: %s",
                    content[:200],
                )
                return {"status": "building"}
        return {"status": "building"}

    # ------------------------------------------------------------------ #
    # v3/v2 API — current backend (aligned with E2B SDK 2.31.0)
    # ------------------------------------------------------------------ #

    async def create_v3(
        self,
        name: str,
        *,
        cpu_count: int | None = None,
        memory_mb: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create template metadata via the v3 API.

        POST /v3/templates → 200

        Returns:
            dict with templateID, buildID, aliases, names, tags, public.
        """
        payload: dict[str, Any] = {"name": name}
        if cpu_count is not None:
            payload["cpuCount"] = cpu_count
        if memory_mb is not None:
            payload["memoryMb"] = memory_mb
        if tags is not None:
            payload["tags"] = tags

        try:
            response = await self._http.platform_request(
                "POST", "/v3/templates", json=payload
            )
            data = response.json()
            logger.info(
                "Template v3 created: templateID=%s, buildID=%s",
                data.get("templateID"),
                data.get("buildID"),
            )
            return data
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
            except Exception:
                body = {}
            message = body.get("message", str(exc))
            raise SandboxError(message, code=f"E7{status}") from exc

    async def trigger_build_v2(
        self,
        template_id: str,
        build_id: str,
        *,
        from_image: str | None = None,
        from_image_registry: dict[str, str] | None = None,
        from_template: str | None = None,
        start_cmd: str | None = None,
        ready_cmd: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        force: bool = False,
        acr_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Trigger a template build via the v2 API.

        POST /v2/templates/{tpl}/builds/{build}

        Args:
            template_id: Template ID from create_v3.
            build_id: Build ID from create_v3.
            from_image: Source image reference (e.g. ACR EE image URL).
            from_image_registry: Registry auth info dict.
            from_template: Base template ID to build from.
            start_cmd: Start command for the sandbox.
            ready_cmd: Readiness check command.
            steps: Build step definitions.
            force: Force rebuild.
            acr_headers: ACR EE configuration headers
                (X-E2B-Template-Build-Mode, X-E2B-Template-Source-Registry-Type, etc.).

        Returns:
            Build trigger response dict.
        """
        payload: dict[str, Any] = {}
        if from_image is not None:
            payload["fromImage"] = from_image
        if from_image_registry is not None:
            payload["fromImageRegistry"] = from_image_registry
        if from_template is not None:
            payload["fromTemplate"] = from_template
        if start_cmd is not None:
            payload["startCmd"] = start_cmd
        if ready_cmd is not None:
            payload["readyCmd"] = ready_cmd
        if steps is not None:
            payload["steps"] = steps
        if force:
            payload["force"] = True

        path = f"/v2/templates/{template_id}/builds/{build_id}"
        try:
            response = await self._http.platform_request(
                "POST", path,
                json=payload,
                headers=acr_headers,
            )
            logger.info(
                "Template v2 build triggered: templateID=%s, buildID=%s, "
                "HTTP %s, content-length=%s",
                template_id, build_id,
                response.status_code,
                response.headers.get("content-length", "?"),
            )
            # v2 trigger may return empty body (202/204 with no content)
            content = response.content
            if content and content.strip():
                try:
                    data = response.json()
                except Exception as json_err:
                    logger.warning(
                        "v2 trigger response not valid JSON: %s (body=%s)",
                        json_err, content[:200],
                    )
                    data = {"status": "triggered", "raw": content.decode(errors="replace")[:200]}
            else:
                data = {"status": "triggered"}
            return data
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raw = exc.response.content
            try:
                body = exc.response.json()
            except Exception:
                body = {"raw": raw.decode(errors="replace")[:200] if raw else ""}
            message = body.get("message", str(exc))
            raise TemplateBuildError(
                f"Template build trigger failed (HTTP {status}): {message}",
            ) from exc

    async def get_build_logs(
        self, template_id: str, build_id: str
    ) -> list[dict]:
        """Fetch build log entries.

        GET /templates/{id}/builds/{buildId}/logs → 200
        Returns list of log entry dicts (timestamp, message, level, step).
        """
        try:
            response = await self._http.platform_request(
                "GET",
                f"/templates/{template_id}/builds/{build_id}/logs",
            )
            content = response.content
            if content and content.strip():
                try:
                    data = response.json()
                    if isinstance(data, list):
                        return data
                    return data.get("logEntries", data.get("logs", []))
                except Exception:
                    return []
            return []
        except Exception as exc:
            logger.debug("Failed to fetch build logs: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Shared: build polling
    # ------------------------------------------------------------------ #

    async def wait_for_build(
        self,
        template_id: str,
        build_id: str,
        *,
        timeout: int = 600,
        poll_interval: int = 5,
    ) -> dict[str, Any]:
        """Wait for a template build to complete.

        Polls build status until ready or error.

        Args:
            template_id: Template ID.
            build_id: Build ID.
            timeout: Maximum wait time in seconds.
            poll_interval: Seconds between polls.

        Returns:
            Final build status dict.

        Raises:
            TemplateBuildError: Build finished with error status.
            TemplateBuildTimeoutError: Build did not complete within timeout.
        """
        elapsed = 0
        while elapsed < timeout:
            status_data = await self.get_build_status(template_id, build_id)
            status = status_data.get("status", "building")

            if status == "ready":
                logger.info(
                    "Template build complete: templateID=%s, buildID=%s",
                    template_id,
                    build_id,
                )
                return status_data
            elif status == "error":
                error_msg = status_data.get("error", "Unknown build error")
                raise TemplateBuildError(
                    f"Template build failed: {error_msg}"
                )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TemplateBuildTimeoutError(
            f"Template build timed out after {timeout}s "
            f"(templateID={template_id}, buildID={build_id})"
        )
