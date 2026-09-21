"""Tests for protocol.template module — Platform API template management."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from easy_sandbox.models.errors import SandboxError
from easy_sandbox.protocol.template import (
    TemplateProtocol,
    TemplateBuildError,
    TemplateBuildTimeoutError,
)
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
    return TemplateProtocol(http_client)


# --- Sample API response payloads ---

_CREATE_RESPONSE = {
    "templateID": "tpl-abc123",
    "buildID": "bld-xyz789",
}

_TEMPLATE_RESPONSE = {
    "templateID": "tpl-abc123",
    "buildID": "bld-xyz789",
    "aliases": "my-template",
    "public": False,
    "cpuCount": 2,
    "memoryMB": 4096,
}

_BUILD_STATUS_READY = {
    "buildID": "bld-xyz789",
    "templateID": "tpl-abc123",
    "status": "ready",
}

_BUILD_STATUS_BUILDING = {
    "buildID": "bld-xyz789",
    "templateID": "tpl-abc123",
    "status": "building",
}

_BUILD_STATUS_ERROR = {
    "buildID": "bld-xyz789",
    "templateID": "tpl-abc123",
    "status": "error",
    "error": "Dockerfile syntax error",
}


class TestCreate:
    """Test TemplateProtocol.create()."""

    async def test_create_minimal(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates",
            method="POST",
            json=_CREATE_RESPONSE,
        )
        result = await protocol.create("FROM python:3.11\nRUN pip install flask")

        assert result["templateID"] == "tpl-abc123"
        assert result["buildID"] == "bld-xyz789"

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["dockerfile"] == "FROM python:3.11\nRUN pip install flask"

    async def test_create_with_options(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates",
            method="POST",
            json=_CREATE_RESPONSE,
        )
        result = await protocol.create(
            "FROM python:3.11",
            alias="my-tpl",
            cpu_count=2,
            memory_mb=4096,
            start_cmd="python app.py",
            ready_cmd="curl localhost:8080/health",
        )
        assert result["templateID"] == "tpl-abc123"

        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body["alias"] == "my-tpl"
        assert body["cpuCount"] == 2
        assert body["memoryMB"] == 4096
        assert body["startCmd"] == "python app.py"
        assert body["readyCmd"] == "curl localhost:8080/health"

    async def test_create_http_error(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates",
            method="POST",
            status_code=400,
            json={"message": "Invalid Dockerfile"},
        )
        with pytest.raises(SandboxError, match="Invalid Dockerfile"):
            await protocol.create("INVALID")


class TestList:
    """Test TemplateProtocol.list()."""

    async def test_list_as_array(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates",
            method="GET",
            json=[_TEMPLATE_RESPONSE],
        )
        result = await protocol.list()
        assert len(result) == 1
        assert result[0]["templateID"] == "tpl-abc123"

    async def test_list_with_data_wrapper(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates",
            method="GET",
            json={"data": [_TEMPLATE_RESPONSE]},
        )
        result = await protocol.list()
        assert len(result) == 1

    async def test_list_empty(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates",
            method="GET",
            json=[],
        )
        result = await protocol.list()
        assert result == []


class TestGet:
    """Test TemplateProtocol.get()."""

    async def test_get_template(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates/tpl-abc123",
            method="GET",
            json=_TEMPLATE_RESPONSE,
        )
        result = await protocol.get("tpl-abc123")
        assert result["templateID"] == "tpl-abc123"
        assert result["cpuCount"] == 2


class TestDelete:
    """Test TemplateProtocol.delete()."""

    async def test_delete_success(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates/tpl-abc123",
            method="DELETE",
            status_code=200,
            json={},
        )
        await protocol.delete("tpl-abc123")  # Should not raise

    async def test_delete_404_does_not_raise(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates/tpl-gone",
            method="DELETE",
            status_code=404,
            json={"message": "not found"},
        )
        await protocol.delete("tpl-gone")  # Should not raise


class TestGetBuildStatus:
    """Test TemplateProtocol.get_build_status()."""

    async def test_get_build_status(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates/tpl-abc123/builds/bld-xyz789/status",
            method="GET",
            json=_BUILD_STATUS_READY,
        )
        result = await protocol.get_build_status("tpl-abc123", "bld-xyz789")
        assert result["status"] == "ready"


class TestWaitForBuild:
    """Test TemplateProtocol.wait_for_build()."""

    async def test_wait_immediately_ready(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates/tpl-abc123/builds/bld-xyz789/status",
            method="GET",
            json=_BUILD_STATUS_READY,
        )
        result = await protocol.wait_for_build(
            "tpl-abc123", "bld-xyz789", timeout=10, poll_interval=1
        )
        assert result["status"] == "ready"

    async def test_wait_build_error(self, protocol, httpx_mock):
        httpx_mock.add_response(
            url=f"{BASE}/templates/tpl-abc123/builds/bld-xyz789/status",
            method="GET",
            json=_BUILD_STATUS_ERROR,
        )
        with pytest.raises(TemplateBuildError, match="Dockerfile syntax error"):
            await protocol.wait_for_build(
                "tpl-abc123", "bld-xyz789", timeout=10, poll_interval=1
            )

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_wait_timeout(self, protocol, httpx_mock):
        # Add multiple "building" responses for the polling loop
        for _ in range(5):
            httpx_mock.add_response(
                url=f"{BASE}/templates/tpl-abc123/builds/bld-xyz789/status",
                method="GET",
                json=_BUILD_STATUS_BUILDING,
            )
        with pytest.raises(TemplateBuildTimeoutError, match="timed out"):
            await protocol.wait_for_build(
                "tpl-abc123", "bld-xyz789", timeout=2, poll_interval=1
            )
