"""Shared fixtures for API layer tests.

Mocks at the protocol level so we test the API layer in isolation.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from easy_sandbox.models.sandbox import SandboxInfo, SandboxStatus
from easy_sandbox.models.process import (
    ProcessResult,
    ProcessChunk,
    ProcessChunkType,
    ProcessInfo,
    CodeResult,
)
from easy_sandbox.models.filesystem import FileInfo, FileType, WatchEvent, WatchEventType
from easy_sandbox.transport.config import TransportConfig
from easy_sandbox.transport.http import HttpClient
from easy_sandbox.transport.auth import (
    AuthProvider,
    EnvdTokenManager,
    ApiKeyAuth,
)
from easy_sandbox.protocol.sandbox import SandboxProtocol
from easy_sandbox.protocol.process import ProcessProtocol
from easy_sandbox.protocol.filesystem import FilesystemProtocol
from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol
from easy_sandbox.api.sandbox import Sandbox
from easy_sandbox.api.commands import CommandsModule
from easy_sandbox.api.files import FilesModule
from easy_sandbox.api.network import NetworkModule
from easy_sandbox.api.code import CodeContextModule
from easy_sandbox.api.capability import ResolvedCapabilities
from easy_sandbox.models.template import DEFAULT_CAPABILITIES, STANDARD_CAPABILITIES


# ---- Constants ----

TEST_SANDBOX_ID = "sbx-test-api-123456"
TEST_ENVD_URL = "https://sbx-test-api-123456.cn-hangzhou.e2b.fc.aliyuncs.com"
TEST_ENVD_TOKEN = "test-envd-access-token-abc"
TEST_API_KEY = "test-api-key-xyz"


# ---- Model Factories ----


def make_sandbox_info(
    sandbox_id: str = TEST_SANDBOX_ID,
    status: SandboxStatus = SandboxStatus.RUNNING,
    envd_url: str = TEST_ENVD_URL,
    envd_access_token: str = TEST_ENVD_TOKEN,
    template: str = "python-base",
) -> SandboxInfo:
    """Create a SandboxInfo for testing."""
    return SandboxInfo.model_validate({
        "sandboxID": sandbox_id,
        "status": status.value,
        "envdUrl": envd_url,
        "envdAccessToken": envd_access_token,
        "templateID": template,
        "timeout": 300,
        "region": "cn-hangzhou",
    })


# ---- Async iterable helper for process mocking ----


class _MockStreamReader:
    """A minimal async iterable that mimics StreamReader for testing."""
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def collect(self):
        result = []
        async for item in self:
            result.append(item)
        return result


# ---- Protocol Mocks ----


@pytest.fixture
def mock_sandbox_protocol() -> AsyncMock:
    """Mock SandboxProtocol with sensible defaults."""
    proto = AsyncMock(spec=SandboxProtocol)
    proto.create.return_value = make_sandbox_info()
    proto.get_info.return_value = make_sandbox_info()
    proto.connect.return_value = make_sandbox_info()
    proto.kill.return_value = None
    proto.set_timeout.return_value = None
    proto.is_running.return_value = True
    proto.pause.return_value = None
    proto.resume.return_value = None
    proto.list.return_value = [make_sandbox_info()]
    return proto


@pytest.fixture
def mock_process_protocol() -> AsyncMock:
    """Mock ProcessProtocol with sensible defaults."""
    proto = AsyncMock(spec=ProcessProtocol)
    # start() returns an async iterable of ProcessChunks
    default_chunks = [
        ProcessChunk(type=ProcessChunkType.STDOUT, data="hello\n"),
        ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
    ]
    proto.start.return_value = _MockStreamReader(default_chunks)
    proto.list_processes.return_value = [
        ProcessInfo(pid=1234, command="python3 app.py", status="running"),
    ]
    proto.kill.return_value = None
    proto.send_input.return_value = None
    proto.send_signal.return_value = None
    return proto


@pytest.fixture
def mock_filesystem_protocol() -> AsyncMock:
    """Mock FilesystemProtocol with sensible defaults."""
    proto = AsyncMock(spec=FilesystemProtocol)
    proto.read_text.return_value = "file content"
    proto.read.return_value = b"file bytes"
    proto.write.return_value = None
    proto.list_dir.return_value = [
        FileInfo(name="app.py", path="/app/app.py", type=FileType.FILE, size=1024),
        FileInfo(name="data", path="/app/data", type=FileType.DIRECTORY, size=0),
    ]
    proto.exists.return_value = True
    proto.remove.return_value = None
    proto.make_dir.return_value = None
    proto.move.return_value = None
    proto.get_info.return_value = FileInfo(
        name="app.py", path="/app/app.py", type=FileType.FILE, size=1024
    )
    return proto


@pytest.fixture
def mock_code_interpreter_protocol() -> AsyncMock:
    """Mock CodeInterpreterProtocol with sensible defaults."""
    proto = AsyncMock(spec=CodeInterpreterProtocol)
    proto.run_code.return_value = {
        "stdout": "42\n",
        "stderr": "",
        "exitCode": 0,
        "executionTime": 0.05,
    }
    proto.create_context.return_value = {"contextId": "ctx-001", "language": "python"}
    proto.list_contexts.return_value = [{"contextId": "ctx-001", "language": "python"}]
    proto.restart_context.return_value = {"contextId": "ctx-001", "status": "active"}
    proto.remove_context.return_value = None
    return proto


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Mock HttpClient."""
    client = AsyncMock(spec=HttpClient)
    client.close.return_value = None
    return client


@pytest.fixture
def mock_auth() -> AsyncMock:
    """Mock AuthProvider."""
    auth = AsyncMock(spec=AuthProvider)
    auth.get_headers.return_value = {"X-API-KEY": TEST_API_KEY}
    return auth


@pytest.fixture
def envd_token_manager() -> EnvdTokenManager:
    """Real EnvdTokenManager with test token."""
    return EnvdTokenManager(TEST_ENVD_TOKEN)


@pytest.fixture
def transport_config() -> TransportConfig:
    """Test transport config."""
    return TransportConfig(api_key=TEST_API_KEY)


# ---- All capabilities for backward-compat test fixtures ----

ALL_CAPABILITIES: set[str] = set(STANDARD_CAPABILITIES)
"""All standard capabilities — used by default in test fixtures so
existing tests that call any API method aren't blocked by gating."""


# ---- Assembled Sandbox Fixture ----


@pytest.fixture
def sandbox(
    mock_http_client: AsyncMock,
    mock_auth: AsyncMock,
    envd_token_manager: EnvdTokenManager,
    transport_config: TransportConfig,
    mock_sandbox_protocol: AsyncMock,
    mock_process_protocol: AsyncMock,
    mock_filesystem_protocol: AsyncMock,
    mock_code_interpreter_protocol: AsyncMock,
) -> Sandbox:
    """Create a fully-mocked Sandbox instance for testing.

    Grants ALL capabilities so existing tests aren't blocked by gating.
    """
    info = make_sandbox_info()
    resolved = ResolvedCapabilities(capabilities=ALL_CAPABILITIES)
    return Sandbox(
        info=info,
        config=transport_config,
        http_client=mock_http_client,
        auth=mock_auth,
        envd_token=envd_token_manager,
        sandbox_protocol=mock_sandbox_protocol,
        process_protocol=mock_process_protocol,
        filesystem_protocol=mock_filesystem_protocol,
        code_interpreter_protocol=mock_code_interpreter_protocol,
        resolved_capabilities=resolved,
    )


# ---- Sub-module Fixtures ----


@pytest.fixture
def commands_module(
    envd_token_manager: EnvdTokenManager,
    mock_process_protocol: AsyncMock,
) -> CommandsModule:
    return CommandsModule(
        envd_url=TEST_ENVD_URL,
        envd_token=envd_token_manager,
        process_protocol=mock_process_protocol,
        capabilities=ALL_CAPABILITIES,
    )


@pytest.fixture
def files_module(
    envd_token_manager: EnvdTokenManager,
    mock_filesystem_protocol: AsyncMock,
    mock_sandbox_protocol: AsyncMock,
) -> FilesModule:
    return FilesModule(
        envd_url=TEST_ENVD_URL,
        envd_token=envd_token_manager,
        filesystem_protocol=mock_filesystem_protocol,
        sandbox_protocol=mock_sandbox_protocol,
        sandbox_id=TEST_SANDBOX_ID,
        capabilities=ALL_CAPABILITIES,
    )


@pytest.fixture
def network_module() -> NetworkModule:
    return NetworkModule(
        sandbox_id=TEST_SANDBOX_ID,
        domain="cn-hangzhou.e2b.fc.aliyuncs.com",
        secure=True,
        access_token=TEST_ENVD_TOKEN,
        capabilities=ALL_CAPABILITIES,
    )


@pytest.fixture
def code_module(
    envd_token_manager: EnvdTokenManager,
    mock_code_interpreter_protocol: AsyncMock,
) -> CodeContextModule:
    return CodeContextModule(
        sandbox_id=TEST_SANDBOX_ID,
        envd_url=TEST_ENVD_URL,
        envd_token=envd_token_manager,
        code_interpreter_protocol=mock_code_interpreter_protocol,
        capabilities=ALL_CAPABILITIES,
    )
