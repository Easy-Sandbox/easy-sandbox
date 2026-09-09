"""Authentication providers for Platform API and Sandbox envd API.

Two authentication modes:
1. API Key: E2B_API_KEY -> Authorization: Bearer {api_key} header (Platform API, 已实测验证)
2. AK/SK: Exchange for temporary API key (TTL=3600s, auto-refresh 5min before expiry)

After sandbox creation, envd API uses envdAccessToken from create response,
sent via multiple headers (X-Access-Token, E2b-Sandbox-Id, etc. 已实测验证).
"""
from __future__ import annotations

import base64
import time
from typing import Any, Protocol

from serverless_sandbox.models.errors import (
    InvalidAPIKeyError,
    InvalidCredentialsError,
    TokenExpiredError,
)
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("transport.auth")

# Header names（已实测验证）
PLATFORM_AUTH_HEADER = "Authorization"  # 已实测验证：Bearer token 认证
ENVD_AUTH_HEADER = "X-Access-Token"
ENVD_SANDBOX_ID_HEADER = "E2b-Sandbox-Id"
ENVD_SANDBOX_PORT_HEADER = "E2b-Sandbox-Port"
_ENVD_BASIC_AUTH = base64.b64encode(b"user:").decode("ascii")  # 已实测验证


class AuthProvider(Protocol):
    """Protocol for authentication providers."""

    async def get_headers(self) -> dict[str, str]:
        """Return authentication headers for Platform API requests."""
        ...

    async def refresh(self) -> None:
        """Force refresh credentials if applicable."""
        ...


class ApiKeyAuth:
    """API Key authentication for Platform API.

    Uses E2B_API_KEY environment variable or explicit api_key parameter.
    Sends X-API-KEY header on Platform API requests.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise InvalidAPIKeyError("API key cannot be empty")
        self._api_key = api_key.strip()

    async def get_headers(self) -> dict[str, str]:
        """Return Authorization: Bearer header (已实测验证)."""
        return {PLATFORM_AUTH_HEADER: f"Bearer {self._api_key}"}

    async def refresh(self) -> None:
        """No-op for API key auth."""
        pass


class AkSkAuth:
    """AK/SK authentication — exchanges AccessKey for temporary API key.

    Uses ALICLOUD_ACCESS_KEY_ID and ALICLOUD_ACCESS_KEY_SECRET.
    Exchanges for a temporary token with TTL=3600s.
    Auto-refreshes 5 minutes (300s) before expiry.
    Token is cached in memory only (never persisted to disk).
    """

    TOKEN_TTL = 3600  # 1 hour  # 假设值，官方文档未给出 token 交换参数，需实测验证
    REFRESH_BEFORE_EXPIRY = 300  # 5 minutes  # 假设值，官方文档未给出 token 交换参数，需实测验证

    def __init__(self, access_key_id: str, access_key_secret: str) -> None:
        if not access_key_id or not access_key_secret:
            raise InvalidCredentialsError(
                "AccessKey ID and Secret cannot be empty",
                suggestion="Set ALICLOUD_ACCESS_KEY_ID and ALICLOUD_ACCESS_KEY_SECRET environment variables.",
            )
        self._ak = access_key_id.strip()
        self._sk = access_key_secret.strip()
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0
        self._exchange_func: Any = None  # Set by transport layer

    def _is_token_valid(self) -> bool:
        """Check if cached token is still valid (with refresh buffer)."""
        if self._cached_token is None:
            return False
        return time.time() < (self._token_expires_at - self.REFRESH_BEFORE_EXPIRY)

    async def _exchange_token(self) -> str:
        """Exchange AK/SK for a temporary API key.

        This calls the Alibaba Cloud STS-like endpoint to get a temporary token.
        The actual HTTP call is delegated to the exchange function set by the transport layer.
        """
        if self._exchange_func is None:
            raise InvalidCredentialsError(
                "Token exchange function not configured. "
                "AK/SK auth requires the transport layer to be initialized first.",
            )
        token = await self._exchange_func(self._ak, self._sk)
        self._cached_token = token
        self._token_expires_at = time.time() + self.TOKEN_TTL
        logger.debug("AK/SK token exchanged, expires at %.0f", self._token_expires_at)
        return token

    async def get_headers(self) -> dict[str, str]:
        """Return Authorization: Bearer header with exchanged token."""
        if not self._is_token_valid():
            await self._exchange_token()
        if self._cached_token is None:
            raise TokenExpiredError("Failed to obtain API token via AK/SK exchange")
        return {PLATFORM_AUTH_HEADER: f"Bearer {self._cached_token}"}

    async def refresh(self) -> None:
        """Force refresh the exchanged token."""
        self._cached_token = None
        self._token_expires_at = 0.0
        await self._exchange_token()

    def set_exchange_func(self, func: Any) -> None:
        """Set the token exchange function (called by transport layer)."""
        self._exchange_func = func


class EnvdTokenManager:
    """Manages envdAccessToken for sandbox envd API requests.

    Each sandbox has its own envdAccessToken returned during creation.
    envd 认证需要四个 header（已实测验证）：
    - X-Access-Token: {envd_access_token}
    - E2b-Sandbox-Id: {sandbox_id}
    - E2b-Sandbox-Port: 49983
    - Authorization: Basic {base64("user:")}
    """

    def __init__(
        self,
        token: str | None = None,
        sandbox_id: str | None = None,
    ) -> None:
        self._token = token
        self._sandbox_id = sandbox_id

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def sandbox_id(self) -> str | None:
        return self._sandbox_id

    def set_token(self, token: str, sandbox_id: str | None = None) -> None:
        """Set the envd access token (from sandbox create response)."""
        self._token = token
        if sandbox_id is not None:
            self._sandbox_id = sandbox_id
        logger.debug("envdAccessToken set for sandbox %s", self._sandbox_id)

    def get_headers(self) -> dict[str, str]:
        """Return all envd auth headers (已实测验证).

        Returns dict with X-Access-Token, E2b-Sandbox-Id, E2b-Sandbox-Port,
        and Authorization (Basic) headers.
        """
        if self._token is None:
            raise TokenExpiredError(
                "envdAccessToken not available. Sandbox may not be created or connected.",
                suggestion="Create or connect to a sandbox first.",
            )
        headers = {
            ENVD_AUTH_HEADER: self._token,
            "Authorization": f"Basic {_ENVD_BASIC_AUTH}",
        }
        if self._sandbox_id is not None:
            headers[ENVD_SANDBOX_ID_HEADER] = self._sandbox_id
        headers[ENVD_SANDBOX_PORT_HEADER] = "49983"
        return headers

    def clear(self) -> None:
        """Clear the cached token."""
        self._token = None
        self._sandbox_id = None


def build_envd_headers(sandbox_id: str, envd_access_token: str) -> dict[str, str]:
    """Build envd authentication headers from sandbox_id and envd_access_token (已实测验证).

    Args:
        sandbox_id: Sandbox ID (e.g., "sbx-xxxx").
        envd_access_token: The envdAccessToken from sandbox create response.

    Returns:
        Dict with all required envd auth headers.
    """
    return {
        ENVD_AUTH_HEADER: envd_access_token,
        ENVD_SANDBOX_ID_HEADER: sandbox_id,
        ENVD_SANDBOX_PORT_HEADER: "49983",
        "Authorization": f"Basic {_ENVD_BASIC_AUTH}",
    }


def create_auth_provider(
    api_key: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> AuthProvider:
    """Create the appropriate auth provider based on available credentials.

    Priority: api_key > E2B_API_KEY (fallback) > AK/SK

    Args:
        api_key: Direct API key.
        access_key_id: Alibaba Cloud AccessKey ID.
        access_key_secret: Alibaba Cloud AccessKey Secret.

    Returns:
        An AuthProvider instance.

    Raises:
        InvalidAPIKeyError: If no credentials provided.
    """
    if api_key:
        logger.debug("Using API Key authentication")
        return ApiKeyAuth(api_key)

    # E2B-compatible: check E2B_API_KEY
    import os
    e2b_key = os.environ.get("E2B_API_KEY")
    if e2b_key:
        logger.debug("Using API Key authentication (via E2B_API_KEY)")
        return ApiKeyAuth(e2b_key)

    if access_key_id and access_key_secret:
        logger.debug("Using AK/SK authentication")
        return AkSkAuth(access_key_id, access_key_secret)

    raise InvalidAPIKeyError(
        "No authentication credentials provided",
        suggestion="Set E2B_API_KEY or both ALICLOUD_ACCESS_KEY_ID and ALICLOUD_ACCESS_KEY_SECRET.",
    )
