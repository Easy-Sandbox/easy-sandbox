"""Tests for api.template module — TemplateManager high-level API."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from easy_sandbox.api.template import TemplateManager
from easy_sandbox.models.template import TemplateInfo, BuildStatus
from easy_sandbox.protocol.template import TemplateProtocol, TemplateBuildError
from easy_sandbox.transport.http import HttpClient


# --- Sample data ---

_CREATE_RESPONSE = {
    "templateID": "tpl-abc123",
    "buildID": "bld-xyz789",
}

_TEMPLATE_DATA = {
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


@pytest.fixture
def mock_http_client() -> AsyncMock:
    return AsyncMock(spec=HttpClient)


@pytest.fixture
def mock_protocol() -> AsyncMock:
    proto = AsyncMock(spec=TemplateProtocol)
    proto.create.return_value = _CREATE_RESPONSE
    proto.list.return_value = [_TEMPLATE_DATA]
    proto.get.return_value = _TEMPLATE_DATA
    proto.delete.return_value = None
    proto.get_build_status.return_value = _BUILD_STATUS_READY
    proto.wait_for_build.return_value = _BUILD_STATUS_READY
    return proto


@pytest.fixture
def manager(mock_http_client, mock_protocol) -> TemplateManager:
    mgr = TemplateManager(mock_http_client)
    mgr._protocol = mock_protocol
    return mgr


class TestBuild:
    """Test TemplateManager.build()."""

    async def test_build_returns_template_info(self, manager, mock_protocol):
        result = await manager.build("FROM python:3.11\nRUN pip install flask")

        assert isinstance(result, TemplateInfo)
        assert result.template_id == "tpl-abc123"
        assert result.build_status == BuildStatus.READY

        mock_protocol.create.assert_called_once()
        mock_protocol.wait_for_build.assert_called_once()
        mock_protocol.get.assert_called_once_with("tpl-abc123")

    async def test_build_with_alias(self, manager, mock_protocol):
        await manager.build(
            "FROM python:3.11",
            alias="my-app",
            cpu_count=4,
            memory_mb=8192,
        )
        call_kwargs = mock_protocol.create.call_args[1]
        assert call_kwargs["alias"] == "my-app"
        assert call_kwargs["cpu_count"] == 4
        assert call_kwargs["memory_mb"] == 8192


class TestBuildInBackground:
    """Test TemplateManager.build_in_background()."""

    async def test_returns_ids(self, manager, mock_protocol):
        template_id, build_id = await manager.build_in_background(
            "FROM python:3.11"
        )
        assert template_id == "tpl-abc123"
        assert build_id == "bld-xyz789"
        mock_protocol.create.assert_called_once()
        mock_protocol.wait_for_build.assert_not_called()


class TestList:
    """Test TemplateManager.list()."""

    async def test_list_returns_template_infos(self, manager, mock_protocol):
        result = await manager.list()
        assert len(result) == 1
        assert isinstance(result[0], TemplateInfo)
        assert result[0].template_id == "tpl-abc123"

    async def test_list_empty(self, manager, mock_protocol):
        mock_protocol.list.return_value = []
        result = await manager.list()
        assert result == []


class TestGet:
    """Test TemplateManager.get()."""

    async def test_get_returns_template_info(self, manager, mock_protocol):
        result = await manager.get("tpl-abc123")
        assert isinstance(result, TemplateInfo)
        assert result.template_id == "tpl-abc123"
        mock_protocol.get.assert_called_once_with("tpl-abc123")


class TestDelete:
    """Test TemplateManager.delete()."""

    async def test_delete(self, manager, mock_protocol):
        await manager.delete("tpl-abc123")
        mock_protocol.delete.assert_called_once_with("tpl-abc123")


class TestGetBuildStatus:
    """Test TemplateManager.get_build_status()."""

    async def test_get_build_status(self, manager, mock_protocol):
        result = await manager.get_build_status("tpl-abc123", "bld-xyz789")
        assert result["status"] == "ready"
        mock_protocol.get_build_status.assert_called_once_with(
            "tpl-abc123", "bld-xyz789"
        )
