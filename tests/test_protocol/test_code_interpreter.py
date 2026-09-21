"""Tests for protocol.code_interpreter module — Code Interpreter RPC."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol
from easy_sandbox.transport.auth import EnvdTokenManager


@pytest.fixture
def envd_token():
    return EnvdTokenManager("test-envd-token")


@pytest.fixture
def envd_url():
    return "https://envd-sbx-123.example.com"


def _make_mock_http(envd_request_return: dict[str, Any] | None = None) -> MagicMock:
    """Create a mock HttpClient with envd_request behavior."""
    mock = MagicMock()
    if envd_request_return is not None:
        mock.envd_request = AsyncMock(return_value=envd_request_return)
    else:
        mock.envd_request = AsyncMock(return_value={})
    return mock


SANDBOX_ID = "sbx-test-123"


class TestRunCode:
    """Test CodeInterpreterProtocol.run_code()."""

    async def test_run_code_basic(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "stdout": "42\n",
            "stderr": "",
            "exitCode": 0,
            "executionTime": 0.05,
        })
        proto = CodeInterpreterProtocol(mock_http)
        result = await proto.run_code(
            SANDBOX_ID, envd_url, envd_token,
            code="print(42)",
            language="python",
        )
        assert result["stdout"] == "42\n"
        assert result["exitCode"] == 0

        mock_http.envd_request.assert_awaited_once()
        call_kwargs = mock_http.envd_request.call_args
        payload = call_kwargs.kwargs["payload"]
        assert payload["code"] == "print(42)"
        assert payload["language"] == "python"
        assert payload["timeout"] == 30

    async def test_run_code_with_context_id(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={"stdout": "ok\n"})
        proto = CodeInterpreterProtocol(mock_http)
        await proto.run_code(
            SANDBOX_ID, envd_url, envd_token,
            code="x = 1",
            context_id="ctx-123",
        )
        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload["contextId"] == "ctx-123"

    async def test_run_code_custom_timeout(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={})
        proto = CodeInterpreterProtocol(mock_http)
        await proto.run_code(
            SANDBOX_ID, envd_url, envd_token,
            code="x = 1",
            timeout=120,
        )
        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload["timeout"] == 120


class TestCreateContext:
    """Test CodeInterpreterProtocol.create_context()."""

    async def test_create_context(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "contextId": "ctx-new-001",
            "language": "python",
        })
        proto = CodeInterpreterProtocol(mock_http)
        result = await proto.create_context(
            SANDBOX_ID, envd_url, envd_token,
            language="python",
        )
        assert result["contextId"] == "ctx-new-001"

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload["language"] == "python"


class TestListContexts:
    """Test CodeInterpreterProtocol.list_contexts()."""

    async def test_list_contexts(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "contexts": [
                {"contextId": "ctx-1", "language": "python"},
                {"contextId": "ctx-2", "language": "javascript"},
            ]
        })
        proto = CodeInterpreterProtocol(mock_http)
        result = await proto.list_contexts(SANDBOX_ID, envd_url, envd_token)
        assert len(result) == 2
        assert result[0]["contextId"] == "ctx-1"
        assert result[1]["language"] == "javascript"

    async def test_list_contexts_empty(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={"contexts": []})
        proto = CodeInterpreterProtocol(mock_http)
        result = await proto.list_contexts(SANDBOX_ID, envd_url, envd_token)
        assert result == []

    async def test_list_contexts_result_wrapper(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "result": {"contexts": [{"contextId": "ctx-wrapped"}]}
        })
        proto = CodeInterpreterProtocol(mock_http)
        result = await proto.list_contexts(SANDBOX_ID, envd_url, envd_token)
        assert len(result) == 1
        assert result[0]["contextId"] == "ctx-wrapped"


class TestRestartContext:
    """Test CodeInterpreterProtocol.restart_context()."""

    async def test_restart_context(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "contextId": "ctx-restarted",
            "status": "active",
        })
        proto = CodeInterpreterProtocol(mock_http)
        result = await proto.restart_context(
            SANDBOX_ID, envd_url, envd_token,
            context_id="ctx-restarted",
        )
        assert result["status"] == "active"

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload["contextId"] == "ctx-restarted"


class TestRemoveContext:
    """Test CodeInterpreterProtocol.remove_context()."""

    async def test_remove_context(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = CodeInterpreterProtocol(mock_http)
        await proto.remove_context(
            SANDBOX_ID, envd_url, envd_token,
            context_id="ctx-to-remove",
        )

        mock_http.envd_request.assert_awaited_once()
        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload["contextId"] == "ctx-to-remove"
