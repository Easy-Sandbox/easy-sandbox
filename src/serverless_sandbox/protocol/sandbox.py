"""Platform API protocol — sandbox lifecycle management (REST).

All methods use standard HTTP REST with Authorization: Bearer authentication.
Endpoints are relative to the Platform API base URL.

路径无 /api/v1 前缀（已实测验证）。
"""
from __future__ import annotations

from typing import Any

import httpx

from serverless_sandbox.models.errors import (
    QuotaExceededError,
    SandboxCreationError,
    TemplateNotFoundError,
)
from serverless_sandbox.models.sandbox import SandboxConfig, SandboxInfo, SandboxStatus
from serverless_sandbox.transport.http import HttpClient
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("protocol.sandbox")


class SandboxProtocol:
    """Typed wrapper for Platform API sandbox operations."""

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    async def create(self, config: SandboxConfig) -> SandboxInfo:
        """Create a new sandbox.

        POST /sandboxes → 201（已实测验证）

        请求体使用 camelCase: templateID, timeout, autoPause, metadata, envVars
        响应体使用 camelCase: sandboxID, templateID, envdAccessToken, envdVersion, clientID
        """
        payload = config.to_create_payload()

        try:
            # 已实测验证：路径无 /api/v1 前缀
            response = await self._http.platform_request("POST", "/sandboxes", json=payload)
            data = response.json()
            return SandboxInfo.model_validate(data)
        except httpx.HTTPStatusError as exc:
            self._handle_create_error(exc)
            raise  # unreachable but satisfies type checker

    async def list(
        self,
        *,
        status: SandboxStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SandboxInfo]:
        """List sandboxes (v1).

        GET /sandboxes → 200（已实测验证）
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status.value

        # 已实测验证：路径无 /api/v1 前缀
        response = await self._http.platform_request("GET", "/sandboxes", params=params)
        data = response.json()
        # API may return list directly or wrapped in a data field
        items = data if isinstance(data, list) else data.get("data", data.get("sandboxes", []))
        return [SandboxInfo.model_validate(item) for item in items]

    async def list_v2(
        self,
        *,
        status: SandboxStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SandboxInfo]:
        """List sandboxes (v2).

        GET /v2/sandboxes → 200（已实测验证）
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status.value

        response = await self._http.platform_request("GET", "/v2/sandboxes", params=params)
        data = response.json()
        items = data if isinstance(data, list) else data.get("data", data.get("sandboxes", []))
        return [SandboxInfo.model_validate(item) for item in items]

    async def get_info(self, sandbox_id: str) -> SandboxInfo:
        """Get sandbox information.

        GET /sandboxes/{sandboxId} → 200（已实测验证）
        """
        # 已实测验证
        response = await self._http.platform_request("GET", f"/sandboxes/{sandbox_id}")
        data = response.json()
        return SandboxInfo.model_validate(data)

    async def kill(self, sandbox_id: str) -> None:
        """Kill/destroy a sandbox.

        DELETE /sandboxes/{sandbox_id} → 204（已实测验证）
        """
        try:
            # 已实测验证
            await self._http.platform_request("DELETE", f"/sandboxes/{sandbox_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("Sandbox %s not found (already killed?)", sandbox_id)
                return
            raise

    async def set_timeout(self, sandbox_id: str, timeout: int) -> None:
        """Update sandbox timeout.

        POST /sandboxes/{sandbox_id}/timeout → 204（已实测验证）
        """
        # 已实测验证：POST（非 PUT）
        await self._http.platform_request(
            "POST",
            f"/sandboxes/{sandbox_id}/timeout",
            json={"timeout": timeout},
        )

    async def connect(self, sandbox_id: str) -> SandboxInfo:
        """Connect to an existing sandbox (fetch current info).

        GET /sandboxes/{sandbox_id} → 200（已实测验证）
        """
        # 已实测验证
        response = await self._http.platform_request("GET", f"/sandboxes/{sandbox_id}")
        data = response.json()
        return SandboxInfo.model_validate(data)

    async def is_running(self, sandbox_id: str) -> bool:
        """Check if a sandbox is currently running.

        Calls get_info and checks status.
        """
        try:
            info = await self.get_info(sandbox_id)
            return info.status == SandboxStatus.RUNNING
        except Exception:
            return False

    async def pause(self, sandbox_id: str) -> None:
        """Pause a running sandbox.

        POST /sandboxes/{sandbox_id}/pause
        # 注意：REST 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        # 注意：REST 路径基于 E2B SDK 逆向推断，未经官方文档确认
        await self._http.platform_request(
            "POST",
            f"/sandboxes/{sandbox_id}/pause",
        )

    async def resume(self, sandbox_id: str) -> None:
        """Resume a paused sandbox.

        POST /sandboxes/{sandbox_id}/resume
        # 注意：REST 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        # 注意：REST 路径基于 E2B SDK 逆向推断，未经官方文档确认
        await self._http.platform_request(
            "POST",
            f"/sandboxes/{sandbox_id}/resume",
        )

    def _handle_create_error(self, exc: httpx.HTTPStatusError) -> None:
        """Convert HTTP errors to typed exceptions for create."""
        status = exc.response.status_code
        try:
            body = exc.response.json()
        except Exception:
            body = {}

        message = body.get("message", str(exc))

        if status == 404:
            raise TemplateNotFoundError(message) from exc
        elif status == 429:
            raise QuotaExceededError(message) from exc
        elif status >= 400:
            raise SandboxCreationError(message) from exc
