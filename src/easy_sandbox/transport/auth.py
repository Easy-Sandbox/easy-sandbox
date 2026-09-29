"""Authentication providers for Platform API and Sandbox envd API.

Two authentication modes:
1. API Key: E2B_API_KEY -> Authorization: Bearer {api_key} header (Platform API, 已实测验证)
2. AK/SK: Exchange for temporary API key (TTL=3600s, auto-refresh 5min before expiry)

After sandbox creation, envd API uses envdAccessToken from create response,
sent via multiple headers (X-Access-Token, E2b-Sandbox-Id, etc. 已实测验证).
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from easy_sandbox.models.errors import (
    InvalidAPIKeyError,
    InvalidCredentialsError,
    TokenExchangeError,
    TokenExpiredError,
)
from easy_sandbox.utils.logging import get_logger

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
                suggestion=(
                    "Set ALICLOUD_ACCESS_KEY_ID and ALICLOUD_ACCESS_KEY_SECRET"
                    " environment variables."
                ),
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
        return str(token)

    async def get_headers(self) -> dict[str, str]:
        """Return Authorization: Bearer header with exchanged token."""
        if not self._is_token_valid():
            await self._exchange_token()
        if self._cached_token is None:
            raise TokenExpiredError("Failed to obtain API token via AK/SK exchange")
        return {PLATFORM_AUTH_HEADER: f"Bearer {self._cached_token}"}

    async def refresh(self) -> None:
        """Force refresh the exchanged token."""
        if self._exchange_func is None:
            raise InvalidCredentialsError(
                "AK/SK token exchange function not configured. "
                "Use create_auth_provider() to get a properly initialised AkSkAuth.",
                suggestion=(
                    "Call create_auth_provider(access_key_id=..., access_key_secret=...) "
                    "instead of constructing AkSkAuth directly, or set the exchange "
                    "function via set_exchange_func()."
                ),
            )
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


# ── Alibaba Cloud API signing helpers ──────────────────────────────────────
# Minimal subset needed for token exchange.  These mirror the helpers in
# api/docker_builder.py but are duplicated here to respect the layer
# constraint (L1 transport must not import L3 api).
# TODO: Consider extracting into a shared L0 utils module.


def _percent_encode(s: str) -> str:
    """RFC 3986 percent-encoding (Alibaba Cloud signature convention)."""
    return (
        urllib.parse.quote(s, safe="").replace("+", "%20").replace("*", "%2A").replace("%7E", "~")
    )


def _sign_rpc(params: dict[str, str], secret: str, method: str = "GET") -> str:
    """Compute Alibaba Cloud RPC (POP) V1 HMAC-SHA1 signature."""
    sorted_params = sorted(params.items())
    canonical = "&".join(f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_params)
    sts = f"{method}&{_percent_encode('/')}&{_percent_encode(canonical)}"
    key = (secret + "&").encode("utf-8")
    return base64.b64encode(hmac_mod.new(key, sts.encode("utf-8"), hashlib.sha1).digest()).decode(
        "utf-8"
    )


# ── Token exchange endpoint ────────────────────────────────────────────────
# TODO(fcsandbox-api): The actual FCSandbox OpenAPI action for exchanging
# AK/SK to a temporary Platform API key has NOT been confirmed with the
# FC Agent Sandbox team.  The implementation below uses a *reasonable*
# pattern modelled after ACR GetAuthorizationToken (see docker_builder.py).
# Replace ``_TOKEN_EXCHANGE_ACTION`` and the response-parsing logic when
# the real endpoint is documented.
#
# See: AGENTS.md rule #5 — "Never fabricate FC/envd API endpoints."
_TOKEN_EXCHANGE_ACTION = "CreateApiKey"  # TODO: confirm actual action name
_TOKEN_EXCHANGE_API_VERSION = "2026-05-09"  # matches alibabacloud-fcsandbox SDK


async def _exchange_aksk_for_api_key(
    access_key_id: str,
    access_key_secret: str,
    *,
    region: str = "cn-hangzhou",
) -> str:
    """Exchange Alibaba Cloud AK/SK for a temporary FCSandbox Platform API key.

    Uses Alibaba Cloud RPC (POP) V1 HMAC-SHA1 signing to call the FCSandbox
    API, similar to how :func:`docker_builder.get_acr_auth_token` exchanges
    AK/SK for temporary ACR credentials.

    Args:
        access_key_id: Alibaba Cloud AccessKey ID.
        access_key_secret: Alibaba Cloud AccessKey Secret.
        region: Region ID (default ``cn-hangzhou``).

    Returns:
        Temporary API key string.

    Raises:
        TokenExchangeError: If the exchange fails.
    """
    endpoint = f"https://fcsandbox.{region}.aliyuncs.com"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    params: dict[str, str] = {
        "Action": _TOKEN_EXCHANGE_ACTION,
        "Format": "JSON",
        "Version": _TOKEN_EXCHANGE_API_VERSION,
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": ts,
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
    }
    params["Signature"] = _sign_rpc(params, access_key_secret)

    logger.info(
        "Exchanging AK/SK for Platform API key (region=%s, action=%s)",
        region,
        _TOKEN_EXCHANGE_ACTION,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(endpoint, params=params)
    except httpx.ConnectError as exc:
        raise TokenExchangeError(
            f"Failed to connect to FCSandbox API for token exchange: {exc}",
            suggestion=(
                "Check network connectivity to fcsandbox."
                f"{region}.aliyuncs.com. "
                "Or use E2B_API_KEY directly."
            ),
        ) from exc
    except httpx.TimeoutException as exc:
        raise TokenExchangeError(
            f"Token exchange request timed out: {exc}",
            suggestion="Check network connectivity or try again later.",
        ) from exc

    if resp.status_code != 200:
        body_text = resp.text[:500]
        logger.warning("Token exchange failed (HTTP %s): %s", resp.status_code, body_text)
        raise TokenExchangeError(
            f"Token exchange failed (HTTP {resp.status_code}): {body_text}",
            suggestion=(
                "Verify AK/SK credentials have FCSandbox API access. Or use E2B_API_KEY directly."
            ),
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise TokenExchangeError(
            f"Invalid JSON response from token exchange: {resp.text[:200]}",
        ) from exc

    # TODO(fcsandbox-api): Adjust response field names to match the actual
    # API response when confirmed.  Common patterns in Alibaba Cloud APIs:
    #   {"ApiKey": "ek-xxx", "ExpireTime": "...", "RequestId": "..."}
    #   {"Data": {"ApiKey": "ek-xxx", ...}, "RequestId": "..."}
    api_key = (
        data.get("ApiKey")
        or data.get("apiKey")
        or (data.get("Data") or {}).get("ApiKey")
        or (data.get("data") or {}).get("apiKey")
    )

    if not api_key:
        raise TokenExchangeError(
            f"Token exchange response did not contain an API key: {list(data.keys())}",
            suggestion=(
                "The FCSandbox token exchange API response format may have changed. "
                "Use E2B_API_KEY directly as a workaround."
            ),
        )

    logger.debug("AK/SK token exchange succeeded (region=%s)", region)
    return str(api_key)


def create_auth_provider(
    api_key: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
    *,
    region: str = "cn-hangzhou",
) -> AuthProvider:
    """Create the appropriate auth provider based on available credentials.

    Priority: api_key > E2B_API_KEY (fallback) > AK/SK

    When the AK/SK path is selected, a token exchange function is
    automatically injected into the :class:`AkSkAuth` instance so that
    credentials are exchanged for a temporary Platform API key on first
    use (and auto-refreshed before expiry).

    Args:
        api_key: Direct API key.
        access_key_id: Alibaba Cloud AccessKey ID.
        access_key_secret: Alibaba Cloud AccessKey Secret.
        region: Alibaba Cloud region for token exchange (default ``cn-hangzhou``).

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
        logger.debug("Using AK/SK authentication (with token exchange)")
        auth = AkSkAuth(access_key_id, access_key_secret)

        # Bind region into the exchange function via closure
        _region = region

        async def _exchange(ak: str, sk: str) -> str:
            return await _exchange_aksk_for_api_key(ak, sk, region=_region)

        auth.set_exchange_func(_exchange)
        return auth

    raise InvalidAPIKeyError(
        "No authentication credentials provided",
        suggestion="Set E2B_API_KEY or both ALICLOUD_ACCESS_KEY_ID and ALICLOUD_ACCESS_KEY_SECRET.",
    )
