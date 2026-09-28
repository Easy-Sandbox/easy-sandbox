"""Tests for transport.http module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from easy_sandbox.transport.auth import PLATFORM_AUTH_HEADER, ApiKeyAuth, EnvdTokenManager
from easy_sandbox.transport.codec import CONNECT_CONTENT_TYPE
from easy_sandbox.transport.config import TransportConfig
from easy_sandbox.transport.http import HttpClient


@pytest.fixture
def transport_config():
    return TransportConfig(
        api_url="https://sandbox-test.example.com",
        http2=False,  # Disable HTTP/2 for test mocking
    )


@pytest.fixture
def api_key_auth():
    return ApiKeyAuth("test-api-key")


@pytest.fixture
def envd_token():
    return EnvdTokenManager("test-envd-token")


@pytest.fixture
def http_client(transport_config, api_key_auth):
    return HttpClient(config=transport_config, auth=api_key_auth)


class TestPlatformRequest:
    """Test Platform API requests."""

    async def test_sends_auth_headers(self, http_client, httpx_mock):
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/v1/sandboxes",
            json={"sandboxes": []},
        )
        response = await http_client.platform_request("GET", "/v1/sandboxes")
        assert response.status_code == 200

        request = httpx_mock.get_request()
        assert request.headers[PLATFORM_AUTH_HEADER.lower()] == "Bearer test-api-key"

    async def test_sends_json_body(self, http_client, httpx_mock):
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/v1/sandboxes",
            json={"id": "sbx-123"},
        )
        await http_client.platform_request(
            "POST",
            "/v1/sandboxes",
            json={"template": "python3"},
        )
        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body == {"template": "python3"}

    async def test_sends_query_params(self, http_client, httpx_mock):
        httpx_mock.add_response(json={"sandboxes": []})
        await http_client.platform_request("GET", "/v1/sandboxes", params={"limit": "10"})
        request = httpx_mock.get_request()
        assert "limit=10" in str(request.url)

    async def test_custom_headers_merged(self, http_client, httpx_mock):
        httpx_mock.add_response(json={})
        await http_client.platform_request("GET", "/v1/sandboxes", headers={"X-Custom": "value"})
        request = httpx_mock.get_request()
        assert request.headers["x-custom"] == "value"

    async def test_http_status_error_propagated(self, http_client, httpx_mock):
        httpx_mock.add_response(status_code=404, json={"error": "not found"})
        with pytest.raises(httpx.HTTPStatusError):
            await http_client.platform_request("GET", "/v1/sandboxes/missing")


class TestEnvdRequest:
    """Test envd API requests."""

    async def test_sends_connect_content_type(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/Start",
            json={"pid": 123},
        )
        result = await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/Start",
            payload={"command": "ls"},
            envd_token=envd_token,
        )
        request = httpx_mock.get_request()
        assert request.headers["content-type"] == CONNECT_CONTENT_TYPE
        assert result == {"pid": 123}

    async def test_sends_envd_auth_header(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/Start",
            json={"pid": 123},
        )
        await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/Start",
            envd_token=envd_token,
        )
        request = httpx_mock.get_request()
        assert request.headers["x-access-token"] == "test-envd-token"

    async def test_decode_response(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/filesystem.Filesystem/ReadFile",
            json={"content": "hello world"},
        )
        result = await http_client.envd_request(
            "https://envd.example.com",
            "/filesystem.Filesystem/ReadFile",
            payload={"path": "/tmp/test.txt"},
            envd_token=envd_token,
        )
        assert result == {"content": "hello world"}

    async def test_empty_payload(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/List",
            json={"processes": []},
        )
        result = await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/List",
            envd_token=envd_token,
        )
        assert result == {"processes": []}

    async def test_request_timeout_override(self, http_client, envd_token, httpx_mock):
        """request_timeout overrides the client-level default for a single call."""
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/List",
            json={"ok": True},
        )
        await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/List",
            envd_token=envd_token,
            request_timeout=120.0,
        )
        request = httpx_mock.get_request()
        # The request was sent successfully; the timeout was applied
        # at the httpx level (not directly visible in the request object,
        # but we verify it via monkeypatch below).
        assert request is not None

    async def test_request_timeout_none_uses_default(self, http_client, envd_token, httpx_mock):
        """When request_timeout is None, the default http_timeout is used."""
        httpx_mock.add_response(
            url="https://envd.example.com/test",
            json={"ok": True},
        )
        await http_client.envd_request(
            "https://envd.example.com",
            "/test",
            envd_token=envd_token,
            request_timeout=None,
        )
        # Should not raise — default timeout from config is used.
        assert httpx_mock.get_request() is not None


class TestClose:
    """Test client cleanup."""

    async def test_close_platform_client(self, http_client, httpx_mock):
        httpx_mock.add_response(json={})
        await http_client.platform_request("GET", "/v1/health")
        await http_client.close()
        assert http_client._platform_client is None

    async def test_close_envd_clients(self, http_client, httpx_mock):
        envd_token = EnvdTokenManager("tok")
        httpx_mock.add_response(
            url="https://envd1.example.com/test",
            json={"ok": True},
        )
        await http_client.envd_request(
            "https://envd1.example.com",
            "/test",
            envd_token=envd_token,
        )
        await http_client.close()
        assert len(http_client._envd_clients) == 0

    async def test_close_idempotent(self, http_client):
        await http_client.close()
        await http_client.close()  # Should not raise

    async def test_context_manager(self, transport_config, api_key_auth, httpx_mock):
        httpx_mock.add_response(json={})
        async with HttpClient(config=transport_config, auth=api_key_auth) as client:
            await client.platform_request("GET", "/v1/health")
        assert client._platform_client is None


class TestRequestTimeoutPropagation:
    """Verify that request_timeout is forwarded to httpx correctly."""

    async def test_envd_request_passes_timeout_to_httpx_post(
        self, transport_config, api_key_auth, envd_token, httpx_mock
    ):
        """envd_request(request_timeout=120) should pass timeout=Timeout(120) to client.post()."""
        httpx_mock.add_response(
            url="https://envd.example.com/test",
            json={"ok": True},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        envd_client = client._create_envd_client("https://envd.example.com")

        captured_kwargs: dict = {}
        original_post = envd_client.post

        async def patched_post(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_post(*args, **kwargs)

        envd_client.post = patched_post  # type: ignore[method-assign]

        await client.envd_request(
            "https://envd.example.com",
            "/test",
            envd_token=envd_token,
            request_timeout=120.0,
        )

        assert "timeout" in captured_kwargs
        assert captured_kwargs["timeout"].read == 120.0
        await client.close()

    async def test_envd_request_no_timeout_kwarg_when_none(
        self, transport_config, api_key_auth, envd_token, httpx_mock
    ):
        """envd_request(request_timeout=None) should NOT pass timeout kwarg."""
        httpx_mock.add_response(
            url="https://envd.example.com/test",
            json={"ok": True},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        envd_client = client._create_envd_client("https://envd.example.com")

        captured_kwargs: dict = {}
        original_post = envd_client.post

        async def patched_post(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_post(*args, **kwargs)

        envd_client.post = patched_post  # type: ignore[method-assign]

        await client.envd_request(
            "https://envd.example.com",
            "/test",
            envd_token=envd_token,
        )

        # No per-request timeout override — client-level default applies
        assert "timeout" not in captured_kwargs
        await client.close()

    async def test_platform_request_passes_timeout_to_httpx_request(
        self, transport_config, api_key_auth, httpx_mock
    ):
        """platform_request(request_timeout=120) forwards timeout=Timeout(120) to request()."""
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/sandboxes",
            json={"sandboxID": "sbx-1"},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        platform_client = await client._get_platform_client()

        captured_kwargs: dict = {}
        original_request = platform_client.request

        async def patched_request(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_request(*args, **kwargs)

        platform_client.request = patched_request  # type: ignore[method-assign]

        await client.platform_request(
            "POST", "/sandboxes", json={"templateID": "base"}, request_timeout=120.0
        )

        assert "timeout" in captured_kwargs
        assert isinstance(captured_kwargs["timeout"], httpx.Timeout)
        assert captured_kwargs["timeout"].read == 120.0
        await client.close()

    async def test_platform_request_no_timeout_kwarg_when_none(
        self, transport_config, api_key_auth, httpx_mock
    ):
        """platform_request(request_timeout=None) must NOT pass a timeout kwarg."""
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/sandboxes",
            json={"sandboxes": []},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        platform_client = await client._get_platform_client()

        captured_kwargs: dict = {}
        original_request = platform_client.request

        async def patched_request(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_request(*args, **kwargs)

        platform_client.request = patched_request  # type: ignore[method-assign]

        await client.platform_request("GET", "/sandboxes")

        # Client-level default applies — no per-request override sent.
        assert "timeout" not in captured_kwargs
        await client.close()

    async def test_envd_stream_uses_override_timeout(self, envd_token):
        """envd_stream(request_timeout=180) should create httpx client with Timeout(180)."""
        captured_timeouts: list[float] = []
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b""  # empty streaming response

        original_init = httpx.AsyncClient.__init__

        def patched_init(self_client, **kwargs):
            if "timeout" in kwargs:
                t = kwargs["timeout"]
                captured_timeouts.append(t.read if isinstance(t, httpx.Timeout) else t)
            original_init(self_client, **kwargs)

        fake_post = AsyncMock(return_value=fake_response)

        config = TransportConfig(
            api_url="https://test.example.com",
            http2=False,
            http_timeout=30.0,
        )
        auth = MagicMock()
        client = HttpClient(config=config, auth=auth)

        with (
            patch.object(httpx.AsyncClient, "__init__", patched_init),
            patch.object(httpx.AsyncClient, "post", fake_post),
            patch.object(
                httpx.AsyncClient, "__aenter__",
                AsyncMock(return_value=MagicMock(post=fake_post)),
            ),
            patch.object(httpx.AsyncClient, "__aexit__", AsyncMock(return_value=False)),
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
                request_timeout=180.0,
            ):
                pass

        assert 180.0 in captured_timeouts
        await client.close()

    async def test_envd_stream_default_timeout(self, envd_token):
        """envd_stream without request_timeout uses config.http_timeout."""
        captured_timeouts: list[float] = []
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b""

        original_init = httpx.AsyncClient.__init__

        def patched_init(self_client, **kwargs):
            if "timeout" in kwargs:
                t = kwargs["timeout"]
                captured_timeouts.append(t.read if isinstance(t, httpx.Timeout) else t)
            original_init(self_client, **kwargs)

        fake_post = AsyncMock(return_value=fake_response)

        config = TransportConfig(
            api_url="https://test.example.com",
            http2=False,
            http_timeout=42.0,  # custom default
        )
        auth = MagicMock()
        client = HttpClient(config=config, auth=auth)

        with (
            patch.object(httpx.AsyncClient, "__init__", patched_init),
            patch.object(httpx.AsyncClient, "post", fake_post),
            patch.object(
                httpx.AsyncClient, "__aenter__",
                AsyncMock(return_value=MagicMock(post=fake_post)),
            ),
            patch.object(httpx.AsyncClient, "__aexit__", AsyncMock(return_value=False)),
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass

        # Should use config default, not an override
        assert 42.0 in captured_timeouts
        await client.close()
