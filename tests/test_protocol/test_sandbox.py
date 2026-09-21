"""Tests for protocol.sandbox module — Platform API sandbox lifecycle."""
from __future__ import annotations

import json

import httpx
import pytest

from easy_sandbox.models.errors import (
    SandboxCreationError,
    TemplateNotFoundError,
    QuotaExceededError,
)
from easy_sandbox.models.sandbox import SandboxConfig, SandboxInfo, SandboxStatus
from easy_sandbox.protocol.sandbox import SandboxProtocol
from easy_sandbox.transport.auth import ApiKeyAuth
from easy_sandbox.transport.config import TransportConfig
from easy_sandbox.transport.http import HttpClient

BASE = "https://sandbox-test.example.com"


@pytest.fixture
def transport_config():
    return TransportConfig(api_url=BASE, http2=False)


@pytest.fixture
def api_key_auth():
    return ApiKeyAuth("test-api-key")


@pytest.fixture
def http_client(transport_config, api_key_auth):
    return HttpClient(config=transport_config, auth=api_key_auth)


@pytest.fixture
def protocol(http_client):
    return SandboxProtocol(http_client)


# --- Sample API response payloads ---

_SANDBOX_RESPONSE = {
    "sandboxID": "sbx-abc123",
    "templateID": "python3",
    "status": "running",
    "timeout": 300,
    "region": "cn-hangzhou",
    "metadata": {},
    "envdUrl": "https://envd-sbx-abc123.example.com",
    "envdAccessToken": "tok-envd-xyz",
}


class TestCreate:
    """Test SandboxProtocol.create()."""

    async def test_create_minimal_config(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes",
            method="POST",
            json=_SANDBOX_RESPONSE,
        )
        config = SandboxConfig(template="python3")
        info = await protocol.create(config)

        assert isinstance(info, SandboxInfo)
        assert info.sandbox_id == "sbx-abc123"
        assert info.template == "python3"
        assert info.envd_access_token == "tok-envd-xyz"

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["templateID"] == "python3"
        assert body["timeout"] == 300
        assert "cpu" not in body
        assert "memory" not in body

    async def test_create_full_config(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes",
            method="POST",
            json=_SANDBOX_RESPONSE,
        )
        config = SandboxConfig(
            template="nodejs",
            timeout=600,
            env_vars={"NODE_ENV": "production"},
            auto_pause=True,
        )
        info = await protocol.create(config)
        assert info.sandbox_id == "sbx-abc123"

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["templateID"] == "nodejs"
        assert body["timeout"] == 600
        assert body["envVars"] == {"NODE_ENV": "production"}
        assert body["autoPause"] is True
        assert "cpu" not in body
        assert "memory" not in body
        assert "disk" not in body
        assert "region" not in body

    async def test_create_404_raises_template_not_found(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes",
            method="POST",
            status_code=404,
            json={"message": "Template 'nonexistent' not found"},
        )
        config = SandboxConfig(template="nonexistent")
        with pytest.raises(TemplateNotFoundError, match="not found"):
            await protocol.create(config)

    async def test_create_429_raises_quota_exceeded(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes",
            method="POST",
            status_code=429,
            json={"message": "Quota exceeded"},
        )
        config = SandboxConfig()
        with pytest.raises(QuotaExceededError, match="Quota exceeded"):
            await protocol.create(config)

    async def test_create_500_raises_creation_error(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes",
            method="POST",
            status_code=500,
            json={"message": "Internal server error"},
        )
        config = SandboxConfig()
        with pytest.raises(SandboxCreationError):
            await protocol.create(config)


class TestList:
    """Test SandboxProtocol.list()."""

    async def test_list_default_params(self, protocol, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            json=[_SANDBOX_RESPONSE],
        )
        result = await protocol.list()
        assert len(result) == 1
        assert result[0].sandbox_id == "sbx-abc123"

        request = httpx_mock.get_request()
        assert "limit=100" in str(request.url)
        assert "offset=0" in str(request.url)

    async def test_list_with_status_filter(self, protocol, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            json={"sandboxes": [_SANDBOX_RESPONSE]},
        )
        result = await protocol.list(status=SandboxStatus.RUNNING)
        assert len(result) == 1

        request = httpx_mock.get_request()
        assert "status=running" in str(request.url)

    async def test_list_with_data_wrapper(self, protocol, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            json={"data": [_SANDBOX_RESPONSE]},
        )
        result = await protocol.list()
        assert len(result) == 1

    async def test_list_empty(self, protocol, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            json=[],
        )
        result = await protocol.list()
        assert result == []


class TestGetInfo:
    """Test SandboxProtocol.get_info()."""

    async def test_get_info(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-abc123",
            method="GET",
            json=_SANDBOX_RESPONSE,
        )
        info = await protocol.get_info("sbx-abc123")
        assert isinstance(info, SandboxInfo)
        assert info.sandbox_id == "sbx-abc123"
        assert info.status == SandboxStatus.RUNNING


class TestKill:
    """Test SandboxProtocol.kill()."""

    async def test_kill_success(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-abc123",
            method="DELETE",
            status_code=200,
            json={},
        )
        await protocol.kill("sbx-abc123")  # Should not raise

    async def test_kill_404_does_not_raise(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-gone",
            method="DELETE",
            status_code=404,
            json={"message": "not found"},
        )
        await protocol.kill("sbx-gone")  # Should not raise


class TestSetTimeout:
    """Test SandboxProtocol.set_timeout()."""

    async def test_set_timeout(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-abc123/timeout",
            method="POST",
            json={},
        )
        await protocol.set_timeout("sbx-abc123", 600)

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body == {"timeout": 600}


class TestKeepAlive:
    """TestKeepAlive — removed: keep_alive has been removed from SandboxProtocol."""
    pass


class TestConnect:
    """Test SandboxProtocol.connect()."""

    async def test_connect(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-abc123",
            method="GET",
            json=_SANDBOX_RESPONSE,
        )
        info = await protocol.connect("sbx-abc123")
        assert isinstance(info, SandboxInfo)
        assert info.sandbox_id == "sbx-abc123"


class TestIsRunning:
    """Test SandboxProtocol.is_running()."""

    async def test_is_running_true(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-abc123",
            method="GET",
            json=_SANDBOX_RESPONSE,  # status is "running"
        )
        assert await protocol.is_running("sbx-abc123") is True

    async def test_is_running_false(self, protocol, httpx_mock):
        stopped_response = {**_SANDBOX_RESPONSE, "status": "stopped"}
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-abc123",
            method="GET",
            json=stopped_response,
        )
        assert await protocol.is_running("sbx-abc123") is False

    async def test_is_running_on_error(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-gone",
            method="GET",
            status_code=404,
            json={"message": "not found"},
        )
        assert await protocol.is_running("sbx-gone") is False


class TestPause:
    """Test SandboxProtocol.pause()."""

    async def test_pause(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/sandboxes/sbx-abc123/pause",
            method="POST",
            json={},
        )
        await protocol.pause("sbx-abc123")  # Should not raise

        request = httpx_mock.get_request()
        assert request.method == "POST"


# TestGetUploadUrl and TestGetDownloadUrl removed:
# These methods have been removed from SandboxProtocol.
# File upload/download is now handled via HTTP file API in FilesystemProtocol.
