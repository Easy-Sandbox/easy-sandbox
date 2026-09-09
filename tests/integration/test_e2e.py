"""End-to-end integration tests.

These tests exercise the full stack with mocked HTTP responses,
verifying the complete flow from high-level API through protocol
and transport layers.

Run with: pytest tests/integration/ -m integration -v
"""
from __future__ import annotations

import base64
import json
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from serverless_sandbox.api.sandbox import Sandbox
from serverless_sandbox.models.errors import (
    CommandTimeoutError,
    QuotaExceededError,
    TemplateNotFoundError,
)
from serverless_sandbox.models.filesystem import FileInfo, FileType
from serverless_sandbox.models.process import ProcessChunk, ProcessChunkType
from serverless_sandbox.models.sandbox import SandboxInfo, SandboxStatus
from serverless_sandbox.transport.auth import ApiKeyAuth, EnvdTokenManager
from serverless_sandbox.transport.config import TransportConfig, reset_config
from serverless_sandbox.transport.http import HttpClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLATFORM_BASE = "https://api.cn-hangzhou.e2b.fc.aliyuncs.com"
ENVD_BASE = "https://sbx-test-123.cn-hangzhou.e2b.fc.aliyuncs.com"
SANDBOX_ID = "sbx-test-123"
ENVD_TOKEN = "test-envd-token-xyz"
API_KEY = "test-api-key-integration"

SANDBOX_INFO_JSON: dict[str, Any] = {
    "sandboxID": SANDBOX_ID,
    "envdUrl": ENVD_BASE,
    "envdAccessToken": ENVD_TOKEN,
    "status": "running",
    "templateID": "python-base",
    "region": "cn-hangzhou",
    "timeout": 300,
}


def _make_httpx_response(
    status_code: int = 200,
    json_data: Any = None,
    text: str | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://fake"),
    )
    if json_data is not None:
        resp._content = json.dumps(json_data).encode()
    elif text is not None:
        resp._content = text.encode()
    else:
        resp._content = b"{}"
    return resp


async def _async_gen_frames(
    frames: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Turn a list of dicts into an async iterator (simulates envd_stream)."""
    for frame in frames:
        yield frame


@pytest.fixture(autouse=True)
def _reset_cached_config():
    """Ensure every test starts with a clean config cache."""
    reset_config()
    yield
    reset_config()


# ---------------------------------------------------------------------------
# Test 1: Full sandbox lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_full_sandbox_lifecycle():
    """Create → get info → run command → read/write file → kill."""
    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "envd_request", new_callable=AsyncMock) as mock_envd,
        patch.object(HttpClient, "envd_http_request", new_callable=AsyncMock) as mock_envd_http,
        patch.object(HttpClient, "envd_stream") as mock_stream,
        patch.object(HttpClient, "close", new_callable=AsyncMock),
    ):
        # --- 1. Create sandbox ---
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )

        sb = await Sandbox.create(
            template="python-base",
            api_key=API_KEY,
            api_url=PLATFORM_BASE,
        )
        assert sb.id == SANDBOX_ID
        assert sb.status == SandboxStatus.RUNNING
        assert sb.url == ENVD_BASE

        # --- 2. Get info (refresh) ---
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )
        info = await sb.refresh_info()
        assert info.sandbox_id == SANDBOX_ID
        assert info.template == "python-base"

        # --- 3. Run command (streaming start_and_wait) ---
        mock_stream.return_value = _async_gen_frames([
            {"event": {"start": {"pid": 1}}},
            {"event": {"data": {"stdout": base64.b64encode(b"hello\n").decode()}}},
            {"event": {"end": {"exitCode": 0}}},
        ])

        result = await sb.commands.run("echo hello")
        assert result.stdout == "hello\n"
        assert result.exit_code == 0

        # --- 4. Write file (via envd_http_request) ---
        mock_envd_http.return_value = httpx.Response(
            status_code=201,
            request=httpx.Request("POST", "https://fake"),
        )
        await sb.files.write("/app/test.txt", "hello world")
        mock_envd_http.assert_called()

        # --- 5. Read file (via envd_http_request) ---
        mock_envd_http.return_value = httpx.Response(
            status_code=200,
            request=httpx.Request("GET", "https://fake"),
            content=b"hello world",
        )
        content = await sb.files.read("/app/test.txt")
        assert content == "hello world"

        # --- 6. Kill ---
        mock_platform.return_value = _make_httpx_response(json_data={})
        await sb.kill()


# ---------------------------------------------------------------------------
# Test 2: Sandbox as context manager
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_sandbox_context_manager():
    """async with await Sandbox.create() — kill is called on exit."""
    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "envd_request", new_callable=AsyncMock) as mock_envd,
        patch.object(HttpClient, "envd_stream") as mock_stream,
        patch.object(HttpClient, "close", new_callable=AsyncMock) as mock_close,
    ):
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )

        async with await Sandbox.create(
            template="python-base",
            api_key=API_KEY,
            api_url=PLATFORM_BASE,
        ) as sb:
            assert sb.id == SANDBOX_ID

            # code.run() now calls CodeInterpreterProtocol.run_code()
            # which uses envd_request (not envd_stream)
            mock_envd.return_value = {
                "stdout": "hello\n",
                "stderr": "",
                "exitCode": 0,
                "executionTime": 0.01,
            }
            result = await sb.run_code("print('hello')")
            assert result.text == "hello"
            assert result.stdout == "hello\n"
            assert result.exit_code == 0

        # Verify kill was called (platform DELETE + close)
        delete_calls = [
            c for c in mock_platform.call_args_list
            if c.args[0] == "DELETE"
        ]
        assert len(delete_calls) >= 1
        mock_close.assert_called()


# ---------------------------------------------------------------------------
# Test 3: Command execution with streaming
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_command_streaming():
    """Create → stream command → collect chunks → verify stdout/stderr."""
    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "envd_stream") as mock_stream,
        patch.object(HttpClient, "close", new_callable=AsyncMock),
    ):
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )
        sb = await Sandbox.create(
            template="python-base",
            api_key=API_KEY,
            api_url=PLATFORM_BASE,
        )

        # Simulate interleaved stdout/stderr
        mock_stream.return_value = _async_gen_frames([
            {"event": {"start": {"pid": 1}}},
            {"event": {"data": {"stdout": base64.b64encode(b"line1\n").decode()}}},
            {"event": {"data": {"stderr": base64.b64encode(b"warn: something\n").decode()}}},
            {"event": {"data": {"stdout": base64.b64encode(b"line2\n").decode()}}},
            {"event": {"end": {"exitCode": 0}}},
        ])

        chunks: list[ProcessChunk] = []
        async for chunk in sb.commands.stream("python script.py"):
            chunks.append(chunk)

        stdout_chunks = [c for c in chunks if c.type == ProcessChunkType.STDOUT and c.data]
        stderr_chunks = [c for c in chunks if c.type == ProcessChunkType.STDERR]
        exit_chunks = [c for c in chunks if c.type == ProcessChunkType.EXIT]

        assert len(stdout_chunks) == 2
        assert stdout_chunks[0].data == "line1\n"
        assert stdout_chunks[1].data == "line2\n"
        assert len(stderr_chunks) == 1
        assert stderr_chunks[0].data == "warn: something\n"
        assert len(exit_chunks) == 1
        assert exit_chunks[0].exit_code == 0


# ---------------------------------------------------------------------------
# Test 4: File operations end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_file_operations_e2e():
    """Create → write → read → list → exists → remove → verify."""
    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "envd_request", new_callable=AsyncMock) as mock_envd,
        patch.object(HttpClient, "envd_http_request", new_callable=AsyncMock) as mock_envd_http,
        patch.object(HttpClient, "close", new_callable=AsyncMock),
    ):
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )
        sb = await Sandbox.create(
            template="python-base",
            api_key=API_KEY,
            api_url=PLATFORM_BASE,
        )

        # Write a file (via envd_http_request)
        mock_envd_http.return_value = httpx.Response(
            status_code=201,
            request=httpx.Request("POST", "https://fake"),
        )
        await sb.files.write("/app/data.json", '{"key": "value"}')

        # Read it back (via envd_http_request)
        mock_envd_http.return_value = httpx.Response(
            status_code=200,
            request=httpx.Request("GET", "https://fake"),
            content=b'{"key": "value"}',
        )
        content = await sb.files.read("/app/data.json")
        assert content == '{"key": "value"}'

        # List directory
        mock_envd.return_value = {
            "entries": [
                {"name": "data.json", "path": "/app/data.json", "isDir": False, "size": 16},
                {"name": "src", "path": "/app/src", "isDir": True, "size": 0},
            ]
        }
        files = await sb.files.list("/app")
        assert len(files) == 2
        assert files[0].name == "data.json"
        assert files[0].type == FileType.FILE
        assert files[1].name == "src"
        assert files[1].type == FileType.DIRECTORY

        # Check exists (via stat — success means exists)
        mock_envd.return_value = {"name": "data.json", "size": 16, "isDir": False}
        exists = await sb.files.exists("/app/data.json")
        assert exists is True

        # Make directory
        mock_envd.return_value = {}
        await sb.files.make_dir("/app/output")

        # Remove file
        mock_envd.return_value = {}
        await sb.files.remove("/app/data.json")

        # Verify exists returns False after removal (stat raises exception)
        mock_envd.side_effect = Exception("not found")
        exists = await sb.files.exists("/app/data.json")
        assert exists is False


# ---------------------------------------------------------------------------
# Test 5: Error handling end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_error_template_not_found():
    """Create with bad template → TemplateNotFoundError."""
    with patch.object(
        HttpClient, "platform_request", new_callable=AsyncMock,
    ) as mock_platform:
        # Simulate 404 from Platform API
        resp_404 = httpx.Response(
            status_code=404,
            request=httpx.Request("POST", f"{PLATFORM_BASE}/sandboxes"),
            json={"message": "Template 'nonexistent' not found"},
        )
        mock_platform.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=resp_404.request,
            response=resp_404,
        )

        with pytest.raises(TemplateNotFoundError) as exc_info:
            await Sandbox.create(
                template="nonexistent",
                api_key=API_KEY,
                api_url=PLATFORM_BASE,
            )
        assert "not found" in exc_info.value.message.lower()
        assert exc_info.value.code == "E2001"


@pytest.mark.integration
async def test_error_quota_exceeded():
    """Create with quota exceeded → QuotaExceededError."""
    with patch.object(
        HttpClient, "platform_request", new_callable=AsyncMock,
    ) as mock_platform:
        resp_429 = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", f"{PLATFORM_BASE}/sandboxes"),
            json={"message": "Sandbox quota exceeded"},
        )
        mock_platform.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=resp_429.request,
            response=resp_429,
        )

        with pytest.raises(QuotaExceededError) as exc_info:
            await Sandbox.create(
                template="python-base",
                api_key=API_KEY,
                api_url=PLATFORM_BASE,
            )
        assert exc_info.value.code == "E2002"


@pytest.mark.integration
async def test_error_command_timeout():
    """Command timeout raises CommandTimeoutError via protocol layer."""
    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "envd_stream") as mock_stream,
        patch.object(HttpClient, "close", new_callable=AsyncMock),
    ):
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )
        sb = await Sandbox.create(
            template="python-base",
            api_key=API_KEY,
            api_url=PLATFORM_BASE,
        )

        # Simulate a stream that raises CommandTimeoutError
        async def _timeout_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            raise CommandTimeoutError("Command timed out after 5s")
            yield  # make it a generator  # pragma: no cover

        mock_stream.side_effect = _timeout_stream

        with pytest.raises(CommandTimeoutError):
            await sb.commands.run("sleep 999", timeout=5)


# ---------------------------------------------------------------------------
# Test 6: Connect to existing sandbox
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_connect_to_existing_sandbox():
    """Connect to an existing sandbox by ID and run operations."""
    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "envd_stream") as mock_stream,
        patch.object(HttpClient, "close", new_callable=AsyncMock),
    ):
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )

        sb = await Sandbox.connect(
            SANDBOX_ID,
            api_key=API_KEY,
            api_url=PLATFORM_BASE,
        )
        assert sb.id == SANDBOX_ID

        # Run a command
        mock_stream.return_value = _async_gen_frames([
            {"event": {"start": {"pid": 1}}},
            {"event": {"data": {"stdout": base64.b64encode(b"connected!\n").decode()}}},
            {"event": {"end": {"exitCode": 0}}},
        ])
        result = await sb.commands.run("echo connected!")
        assert result.stdout == "connected!\n"
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test 7: Multiple sandbox management
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_multiple_sandbox_management():
    """Create two sandboxes → list → kill both."""
    sb1_info = {**SANDBOX_INFO_JSON, "sandboxID": "sbx-multi-001", "envdUrl": "https://sbx-multi-001.cn-hangzhou.e2b.fc.aliyuncs.com"}
    sb2_info = {**SANDBOX_INFO_JSON, "sandboxID": "sbx-multi-002", "envdUrl": "https://sbx-multi-002.cn-hangzhou.e2b.fc.aliyuncs.com"}

    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "close", new_callable=AsyncMock),
    ):
        # Create sandbox 1
        mock_platform.return_value = _make_httpx_response(json_data=sb1_info)
        sandbox1 = await Sandbox.create(
            template="python-base", api_key=API_KEY, api_url=PLATFORM_BASE,
        )
        assert sandbox1.id == "sbx-multi-001"

        # Create sandbox 2
        mock_platform.return_value = _make_httpx_response(json_data=sb2_info)
        sandbox2 = await Sandbox.create(
            template="python-base", api_key=API_KEY, api_url=PLATFORM_BASE,
        )
        assert sandbox2.id == "sbx-multi-002"

        # List sandboxes
        mock_platform.return_value = _make_httpx_response(
            json_data=[sb1_info, sb2_info],
        )
        from serverless_sandbox.protocol.sandbox import SandboxProtocol
        proto = SandboxProtocol(sandbox1._http_client)
        sandboxes = await proto.list()
        assert len(sandboxes) == 2
        assert {sb.sandbox_id for sb in sandboxes} == {"sbx-multi-001", "sbx-multi-002"}

        # Kill both
        mock_platform.return_value = _make_httpx_response(json_data={})
        await sandbox1.kill()
        await sandbox2.kill()


# ---------------------------------------------------------------------------
# Test 8: Code execution with multiple languages
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_code_execution_languages():
    """Run code snippets in multiple languages through code interpreter."""
    with (
        patch.object(HttpClient, "platform_request", new_callable=AsyncMock) as mock_platform,
        patch.object(HttpClient, "envd_request", new_callable=AsyncMock) as mock_envd,
        patch.object(HttpClient, "envd_stream") as mock_stream,
        patch.object(HttpClient, "close", new_callable=AsyncMock),
    ):
        mock_platform.return_value = _make_httpx_response(
            json_data=SANDBOX_INFO_JSON,
        )
        sb = await Sandbox.create(
            template="python-base", api_key=API_KEY, api_url=PLATFORM_BASE,
        )

        # Code execution now goes through CodeInterpreterProtocol.run_code()
        # which calls envd_request (not envd_stream)

        # Python code
        mock_envd.return_value = {
            "stdout": "42\n",
            "stderr": "",
            "exitCode": 0,
            "executionTime": 0.01,
        }
        result = await sb.run_code("print(42)", language="python")
        assert result.text == "42"
        assert result.exit_code == 0

        # JavaScript code
        mock_envd.return_value = {
            "stdout": "hello from js\n",
            "stderr": "",
            "exitCode": 0,
            "executionTime": 0.01,
        }
        result = await sb.run_code("console.log('hello from js')", language="javascript")
        assert result.text == "hello from js"
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test 9 and 10 removed: is_running is now async method, keep_alive removed
# ---------------------------------------------------------------------------
