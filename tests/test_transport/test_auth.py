"""Tests for transport.auth module."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from easy_sandbox.models.errors import (
    InvalidAPIKeyError,
    InvalidCredentialsError,
    TokenExpiredError,
)
from easy_sandbox.transport.auth import (
    ApiKeyAuth,
    AkSkAuth,
    EnvdTokenManager,
    create_auth_provider,
    build_envd_headers,
    PLATFORM_AUTH_HEADER,
    ENVD_AUTH_HEADER,
    ENVD_SANDBOX_ID_HEADER,
    ENVD_SANDBOX_PORT_HEADER,
)


class TestApiKeyAuth:
    """Test API Key authentication."""

    async def test_get_headers(self):
        auth = ApiKeyAuth("my-api-key")
        headers = await auth.get_headers()
        assert headers == {PLATFORM_AUTH_HEADER: "Bearer my-api-key"}

    async def test_get_headers_strips_whitespace(self):
        auth = ApiKeyAuth("  my-api-key  ")
        headers = await auth.get_headers()
        assert headers == {PLATFORM_AUTH_HEADER: "Bearer my-api-key"}

    def test_empty_key_raises(self):
        with pytest.raises(InvalidAPIKeyError):
            ApiKeyAuth("")

    def test_whitespace_only_key_raises(self):
        with pytest.raises(InvalidAPIKeyError):
            ApiKeyAuth("   ")

    async def test_refresh_is_noop(self):
        auth = ApiKeyAuth("key")
        await auth.refresh()  # Should not raise


class TestAkSkAuth:
    """Test AK/SK authentication."""

    def test_empty_ak_raises(self):
        with pytest.raises(InvalidCredentialsError):
            AkSkAuth("", "secret")

    def test_empty_sk_raises(self):
        with pytest.raises(InvalidCredentialsError):
            AkSkAuth("ak-id", "")

    def test_is_token_valid_no_token(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        assert not auth._is_token_valid()

    def test_is_token_valid_fresh_token(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        auth._cached_token = "some-token"
        auth._token_expires_at = time.time() + 3600
        assert auth._is_token_valid()

    def test_is_token_valid_near_expiry(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        auth._cached_token = "some-token"
        # Set expiry within 5 min (300s) refresh buffer
        auth._token_expires_at = time.time() + 200
        assert not auth._is_token_valid()

    def test_is_token_valid_expired(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        auth._cached_token = "some-token"
        auth._token_expires_at = time.time() - 100
        assert not auth._is_token_valid()

    async def test_get_headers_calls_exchange_when_invalid(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        mock_exchange = AsyncMock(return_value="exchanged-token")
        auth.set_exchange_func(mock_exchange)

        headers = await auth.get_headers()
        assert headers == {PLATFORM_AUTH_HEADER: "Bearer exchanged-token"}
        mock_exchange.assert_called_once_with("ak-id", "sk-secret")

    async def test_get_headers_uses_cached_token(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        auth._cached_token = "cached-token"
        auth._token_expires_at = time.time() + 3600

        mock_exchange = AsyncMock(return_value="new-token")
        auth.set_exchange_func(mock_exchange)

        headers = await auth.get_headers()
        assert headers == {PLATFORM_AUTH_HEADER: "Bearer cached-token"}
        mock_exchange.assert_not_called()

    async def test_refresh_clears_and_exchanges(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        auth._cached_token = "old-token"
        auth._token_expires_at = time.time() + 3600

        mock_exchange = AsyncMock(return_value="new-token")
        auth.set_exchange_func(mock_exchange)

        await auth.refresh()
        assert auth._cached_token == "new-token"
        mock_exchange.assert_called_once()

    async def test_exchange_without_func_raises(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        with pytest.raises(InvalidCredentialsError, match="exchange function not configured"):
            await auth.get_headers()

    def test_set_exchange_func(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        func = AsyncMock()
        auth.set_exchange_func(func)
        assert auth._exchange_func is func


class TestEnvdTokenManager:
    """Test envd access token manager."""

    def test_initial_token_none(self):
        mgr = EnvdTokenManager()
        assert mgr.token is None

    def test_initial_token_set(self):
        mgr = EnvdTokenManager("my-token")
        assert mgr.token == "my-token"

    def test_set_token(self):
        mgr = EnvdTokenManager()
        mgr.set_token("new-token")
        assert mgr.token == "new-token"

    def test_get_headers(self):
        mgr = EnvdTokenManager("my-token", sandbox_id="sbx-123")
        headers = mgr.get_headers()
        assert ENVD_AUTH_HEADER in headers
        assert headers[ENVD_AUTH_HEADER] == "my-token"
        assert ENVD_SANDBOX_ID_HEADER in headers
        assert headers[ENVD_SANDBOX_ID_HEADER] == "sbx-123"
        assert ENVD_SANDBOX_PORT_HEADER in headers
        assert headers[ENVD_SANDBOX_PORT_HEADER] == "49983"
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

    def test_get_headers_without_sandbox_id(self):
        mgr = EnvdTokenManager("my-token")
        headers = mgr.get_headers()
        assert ENVD_AUTH_HEADER in headers
        assert ENVD_SANDBOX_ID_HEADER not in headers
        assert ENVD_SANDBOX_PORT_HEADER in headers
        assert "Authorization" in headers

    def test_get_headers_no_token_raises(self):
        mgr = EnvdTokenManager()
        with pytest.raises(TokenExpiredError):
            mgr.get_headers()

    def test_clear(self):
        mgr = EnvdTokenManager("my-token")
        mgr.clear()
        assert mgr.token is None


class TestCreateAuthProvider:
    """Test create_auth_provider factory."""

    def test_api_key_priority(self):
        auth = create_auth_provider(api_key="my-key", access_key_id="ak", access_key_secret="sk")
        assert isinstance(auth, ApiKeyAuth)

    def test_ak_sk_fallback(self):
        auth = create_auth_provider(access_key_id="ak", access_key_secret="sk")
        assert isinstance(auth, AkSkAuth)

    def test_no_credentials_raises(self):
        with pytest.raises(InvalidAPIKeyError, match="No authentication credentials"):
            create_auth_provider()

    def test_partial_ak_sk_raises(self):
        with pytest.raises(InvalidAPIKeyError, match="No authentication credentials"):
            create_auth_provider(access_key_id="ak")

    def test_api_key_used(self):
        auth = create_auth_provider(api_key="key-123")
        assert isinstance(auth, ApiKeyAuth)


class TestBuildEnvdHeaders:
    """Test build_envd_headers convenience function."""

    def test_returns_all_four_headers(self):
        headers = build_envd_headers("sbx-abc", "tok-xyz")
        assert headers[ENVD_AUTH_HEADER] == "tok-xyz"
        assert headers[ENVD_SANDBOX_ID_HEADER] == "sbx-abc"
        assert headers[ENVD_SANDBOX_PORT_HEADER] == "49983"
        assert headers["Authorization"].startswith("Basic ")
        assert len(headers) == 4
