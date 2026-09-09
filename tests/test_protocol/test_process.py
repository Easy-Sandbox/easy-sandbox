"""Tests for protocol.process module — envd process management."""
from __future__ import annotations

import base64
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from serverless_sandbox.models.process import (
    ProcessChunk,
    ProcessChunkType,
    ProcessInfo,
)
from serverless_sandbox.protocol.process import ProcessProtocol, _parse_process_chunk
from serverless_sandbox.transport.auth import EnvdTokenManager


@pytest.fixture
def envd_token():
    return EnvdTokenManager("test-envd-token")


@pytest.fixture
def envd_url():
    return "https://envd-sbx-123.example.com"


def _make_mock_http(
    envd_request_return: dict[str, Any] | None = None,
    stream_frames: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Create a mock HttpClient with optional envd_request/envd_stream behaviour."""
    mock = MagicMock()
    if envd_request_return is not None:
        mock.envd_request = AsyncMock(return_value=envd_request_return)
    else:
        mock.envd_request = AsyncMock(return_value={})

    if stream_frames is not None:
        async def fake_envd_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            for frame in stream_frames:
                yield frame

        mock.envd_stream = fake_envd_stream
    else:
        async def empty_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            return
            yield  # make it a generator

        mock.envd_stream = empty_stream

    return mock


# =============================================================================
# Tests for _parse_process_chunk
# =============================================================================


class TestParseProcessChunk:
    """Test the _parse_process_chunk helper function (NDJSON event format)."""

    def test_stdout_frame(self):
        raw = base64.b64encode(b"hello world\n").decode()
        chunk = _parse_process_chunk({"event": {"data": {"stdout": raw}}})
        assert chunk.type == ProcessChunkType.STDOUT
        assert chunk.data == "hello world\n"

    def test_stderr_frame(self):
        raw = base64.b64encode(b"error msg\n").decode()
        chunk = _parse_process_chunk({"event": {"data": {"stderr": raw}}})
        assert chunk.type == ProcessChunkType.STDERR
        assert chunk.data == "error msg\n"

    def test_exit_frame(self):
        chunk = _parse_process_chunk({"event": {"end": {"exitCode": 0}}})
        assert chunk.type == ProcessChunkType.EXIT
        assert chunk.exit_code == 0

    def test_exit_frame_nonzero(self):
        chunk = _parse_process_chunk({"event": {"end": {"exitCode": 42}}})
        assert chunk.type == ProcessChunkType.EXIT
        assert chunk.exit_code == 42

    def test_start_event(self):
        chunk = _parse_process_chunk({"event": {"start": {"pid": 123}}})
        assert chunk.type == ProcessChunkType.STDOUT
        assert chunk.pid == 123

    def test_empty_frame(self):
        chunk = _parse_process_chunk({})
        assert chunk.type == ProcessChunkType.STDOUT
        assert chunk.data == ""


# =============================================================================
# Tests for ProcessProtocol
# =============================================================================


class TestStart:
    """Test ProcessProtocol.start()."""

    async def test_start_returns_stream_reader(self, envd_url, envd_token):
        stdout_b64 = base64.b64encode(b"hello").decode()
        mock_http = _make_mock_http(stream_frames=[
            {"event": {"start": {"pid": 1}}},
            {"event": {"data": {"stdout": stdout_b64}}},
            {"event": {"end": {"exitCode": 0}}},
        ])
        proto = ProcessProtocol(mock_http)
        reader = await proto.start(envd_url, envd_token, cmd="echo", args=["hello"])

        chunks: list[ProcessChunk] = []
        async for chunk in reader:
            chunks.append(chunk)

        # Filter out empty start event
        data_chunks = [c for c in chunks if c.data or c.type == ProcessChunkType.EXIT]
        assert any(c.type == ProcessChunkType.STDOUT and c.data == "hello" for c in data_chunks)
        assert any(c.type == ProcessChunkType.EXIT and c.exit_code == 0 for c in data_chunks)


class TestListProcesses:
    """Test ProcessProtocol.list_processes()."""

    async def test_parses_response(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "processes": [
                {"pid": 1, "command": "bash", "status": "running"},
                {"pid": 42, "command": "python", "status": "running"},
            ],
        })
        proto = ProcessProtocol(mock_http)
        result = await proto.list_processes(envd_url, envd_token)

        assert len(result) == 2
        assert all(isinstance(p, ProcessInfo) for p in result)
        assert result[0].pid == 1
        assert result[1].pid == 42
        assert result[1].command == "python"

    async def test_empty_list(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={"processes": []})
        proto = ProcessProtocol(mock_http)
        result = await proto.list_processes(envd_url, envd_token)
        assert result == []

    async def test_result_wrapper(self, envd_url, envd_token):
        mock_http = _make_mock_http(envd_request_return={
            "result": {"processes": [{"pid": 5, "command": "node"}]},
        })
        proto = ProcessProtocol(mock_http)
        result = await proto.list_processes(envd_url, envd_token)
        assert len(result) == 1
        assert result[0].pid == 5


class TestSendStdin:
    """Test ProcessProtocol.send_stdin() (backward compat alias for send_input)."""

    async def test_sends_payload(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = ProcessProtocol(mock_http)
        await proto.send_stdin(envd_url, envd_token, pid=42, data="input\n")

        mock_http.envd_request.assert_awaited_once()
        call_kwargs = mock_http.envd_request.call_args
        assert call_kwargs.kwargs["payload"] == {"pid": 42, "data": "input\n"}


class TestKillProcess:
    """Test ProcessProtocol.kill() — now delegates to send_signal(signal=9)."""

    async def test_sends_payload(self, envd_url, envd_token):
        mock_http = _make_mock_http()
        proto = ProcessProtocol(mock_http)
        await proto.kill(envd_url, envd_token, pid=42)

        mock_http.envd_request.assert_awaited_once()
        call_kwargs = mock_http.envd_request.call_args
        assert call_kwargs.kwargs["payload"] == {"pid": 42, "signal": 9}
