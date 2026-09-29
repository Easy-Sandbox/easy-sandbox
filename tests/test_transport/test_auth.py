"""Tests for transport.auth module."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from easy_sandbox.models.errors import (
    InvalidAPIKeyError,
    InvalidCredentialsError,
    TokenExchangeError,
    TokenExpiredError,
)
from easy_sandbox.transport.auth import (
    ENVD_AUTH_HEADER,
    ENVD_SANDBOX_ID_HEADER,
    ENVD_SANDBOX_PORT_HEADER,
    PLATFORM_AUTH_HEADER,
    AkSkAuth,
    ApiKeyAuth,
    EnvdTokenManager,
    _exchange_aksk_for_api_key,
    build_envd_headers,
    create_auth_provider,
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

    async def test_refresh_without_exchange_func_raises_credentials_error(self):
        auth = AkSkAuth("ak-id", "sk-secret")
        with pytest.raises(InvalidCredentialsError, match="exchange function not configured"):
            await auth.refresh()


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

    def test_ak_sk_has_exchange_func_injected(self):
        """When AK/SK is used, exchange function should be auto-injected."""
        auth = create_auth_provider(access_key_id="ak", access_key_secret="sk")
        assert isinstance(auth, AkSkAuth)
        assert auth._exchange_func is not None

    def test_ak_sk_with_custom_region(self):
        """Exchange function should bind the provided region."""
        auth = create_auth_provider(
            access_key_id="ak", access_key_secret="sk", region="cn-shanghai"
        )
        assert isinstance(auth, AkSkAuth)
        assert auth._exchange_func is not None

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


class TestExchangeAkskForApiKey:
    """Tests for the _exchange_aksk_for_api_key function."""

    async def test_successful_exchange(self):
        """Test successful token exchange returns API key."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ApiKey": "ek-test-key-123"}
        mock_response.text = '{"ApiKey": "ek-test-key-123"}'

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _exchange_aksk_for_api_key("ak-id", "sk-secret")
            assert result == "ek-test-key-123"

    async def test_exchange_with_nested_data_field(self):
        """Test exchange parsing Data.ApiKey response format."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Data": {"ApiKey": "ek-nested-key"},
            "RequestId": "req-123",
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _exchange_aksk_for_api_key("ak-id", "sk-secret")
            assert result == "ek-nested-key"

    async def test_exchange_http_error_raises(self):
        """Test that HTTP errors raise TokenExchangeError."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden: invalid credentials"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(TokenExchangeError, match="HTTP 403"),
        ):
            await _exchange_aksk_for_api_key("ak-id", "sk-secret")

    async def test_exchange_connect_error_raises(self):
        """Test that connection errors raise TokenExchangeError."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(TokenExchangeError, match="Failed to connect"),
        ):
            await _exchange_aksk_for_api_key("ak-id", "sk-secret")

    async def test_exchange_timeout_raises(self):
        """Test that timeout raises TokenExchangeError."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ReadTimeout("Read timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(TokenExchangeError, match="timed out"),
        ):
            await _exchange_aksk_for_api_key("ak-id", "sk-secret")

    async def test_exchange_missing_api_key_in_response(self):
        """Test that missing API key in response raises TokenExchangeError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"RequestId": "req-123", "Status": "ok"}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(TokenExchangeError, match="did not contain an API key"),
        ):
            await _exchange_aksk_for_api_key("ak-id", "sk-secret")

    async def test_exchange_invalid_json_raises(self):
        """Test that invalid JSON response raises TokenExchangeError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "not json at all"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(TokenExchangeError, match="Invalid JSON"),
        ):
            await _exchange_aksk_for_api_key("ak-id", "sk-secret")

    async def test_exchange_uses_correct_region(self):
        """Test that the exchange function uses the specified region."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ApiKey": "ek-key"}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await _exchange_aksk_for_api_key("ak-id", "sk-secret", region="cn-shanghai")
            # Verify the endpoint includes the region
            call_args = mock_client.get.call_args
            assert "cn-shanghai" in call_args[0][0]


class TestAkSkAuthIntegration:
    """Integration tests for AK/SK auth with injected exchange function."""

    async def test_end_to_end_exchange_and_cache(self):
        """Test full flow: create provider -> first call exchanges -> second uses cache."""
        mock_exchange = AsyncMock(return_value="ek-fresh-token")

        auth = AkSkAuth("ak-id", "sk-secret")
        auth.set_exchange_func(mock_exchange)

        # First call triggers exchange
        headers1 = await auth.get_headers()
        assert headers1 == {PLATFORM_AUTH_HEADER: "Bearer ek-fresh-token"}
        assert mock_exchange.call_count == 1

        # Second call uses cache
        headers2 = await auth.get_headers()
        assert headers2 == {PLATFORM_AUTH_HEADER: "Bearer ek-fresh-token"}
        assert mock_exchange.call_count == 1  # not called again

    async def test_token_refresh_on_near_expiry(self):
        """Test that token is refreshed when near expiry."""
        call_count = 0

        async def mock_exchange(ak: str, sk: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"ek-token-{call_count}"

        auth = AkSkAuth("ak-id", "sk-secret")
        auth.set_exchange_func(mock_exchange)

        # First call
        await auth.get_headers()
        assert call_count == 1

        # Simulate near-expiry (within REFRESH_BEFORE_EXPIRY buffer)
        auth._token_expires_at = time.time() + 100  # within 300s buffer

        # Should trigger re-exchange
        headers = await auth.get_headers()
        assert call_count == 2
        assert headers == {PLATFORM_AUTH_HEADER: "Bearer ek-token-2"}

    async def test_force_refresh(self):
        """Test force refresh clears cache and re-exchanges."""
        mock_exchange = AsyncMock(side_effect=["token-1", "token-2"])

        auth = AkSkAuth("ak-id", "sk-secret")
        auth.set_exchange_func(mock_exchange)

        await auth.get_headers()
        assert auth._cached_token == "token-1"

        await auth.refresh()
        assert auth._cached_token == "token-2"
        assert mock_exchange.call_count == 2

    async def test_exchange_error_propagates(self):
        """Test that exchange errors propagate correctly."""

        async def failing_exchange(ak: str, sk: str) -> str:
            raise TokenExchangeError("Exchange endpoint returned 500")

        auth = AkSkAuth("ak-id", "sk-secret")
        auth.set_exchange_func(failing_exchange)

        with pytest.raises(TokenExchangeError, match="500"):
            await auth.get_headers()

    async def test_create_auth_provider_injects_working_exchange(self):
        """Test that create_auth_provider creates AkSkAuth with working exchange."""
        auth = create_auth_provider(access_key_id="test-ak", access_key_secret="test-sk")
        assert isinstance(auth, AkSkAuth)

        # The exchange func should be callable (it will fail at HTTP level
        # in tests, but it should be set)
        assert auth._exchange_func is not None

        # Verify the injected function is async and callable
        import asyncio

        assert asyncio.iscoroutinefunction(auth._exchange_func)
