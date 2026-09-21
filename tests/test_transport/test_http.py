"""Tests for transport.http module."""
from __future__ import annotations

import json

import httpx
import pytest

from easy_sandbox.models.errors import ConnectionError_
from easy_sandbox.transport.auth import ApiKeyAuth, EnvdTokenManager, PLATFORM_AUTH_HEADER
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
        response = await http_client.platform_request(
            "POST",
            "/v1/sandboxes",
            json={"template": "python3"},
        )
        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body == {"template": "python3"}

    async def test_sends_query_params(self, http_client, httpx_mock):
        httpx_mock.add_response(json={"sandboxes": []})
        await http_client.platform_request(
            "GET", "/v1/sandboxes", params={"limit": "10"}
        )
        request = httpx_mock.get_request()
        assert "limit=10" in str(request.url)

    async def test_custom_headers_merged(self, http_client, httpx_mock):
        httpx_mock.add_response(json={})
        await http_client.platform_request(
            "GET", "/v1/sandboxes", headers={"X-Custom": "value"}
        )
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
