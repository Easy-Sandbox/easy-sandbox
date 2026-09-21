"""Tests for the CommandsModule API."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from easy_sandbox.api.commands import CommandsModule
from easy_sandbox.models.process import (
    ProcessChunk,
    ProcessChunkType,
    ProcessInfo,
    ProcessResult,
)

from easy_sandbox.transport.streaming import StreamReader

from tests.test_api.conftest import TEST_ENVD_URL, TEST_ENVD_TOKEN, _MockStreamReader


class TestCommandsParsing:
    """Test command string parsing."""

    def test_parse_simple_command(self) -> None:
        cmd, args = CommandsModule._parse_cmd("echo hello")
        assert cmd == "echo"
        assert args == ["hello"]

    def test_parse_command_no_args(self) -> None:
        cmd, args = CommandsModule._parse_cmd("ls")
        assert cmd == "ls"
        assert args == []

    def test_parse_command_with_quotes(self) -> None:
        cmd, args = CommandsModule._parse_cmd('echo "hello world"')
        assert cmd == "echo"
        assert args == ["hello world"]

    def test_parse_complex_command(self) -> None:
        cmd, args = CommandsModule._parse_cmd("python3 -c 'print(1)'")
        assert cmd == "python3"
        assert args == ["-c", "print(1)"]


class TestCommandsRun:
    """Test CommandsModule.run()."""

    @pytest.mark.asyncio
    async def test_run_returns_process_result(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        result = await commands_module.run("echo hello")
        assert isinstance(result, ProcessResult)
        assert result.stdout == "hello\n"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_passes_parsed_command(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        # Reset mock to provide fresh chunks
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.STDOUT, data="output\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        await commands_module.run("ls -la /app")
        call_kwargs = mock_process_protocol.start.call_args
        assert call_kwargs[1]["cmd"] == "ls"
        assert call_kwargs[1]["args"] == ["-la", "/app"]

    @pytest.mark.asyncio
    async def test_run_passes_env_and_cwd(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        await commands_module.run(
            "echo test",
            env={"FOO": "bar"},
            cwd="/tmp",
            timeout=120,
        )
        call_kwargs = mock_process_protocol.start.call_args
        assert call_kwargs[1]["env"] == {"FOO": "bar"}
        assert call_kwargs[1]["cwd"] == "/tmp"
        assert call_kwargs[1]["timeout"] == 120

    @pytest.mark.asyncio
    async def test_run_uses_envd_url_and_token(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        await commands_module.run("echo hello")
        call_args = mock_process_protocol.start.call_args
        assert call_args[0][0] == TEST_ENVD_URL  # envd_url positional arg


class TestCommandsStream:
    """Test CommandsModule.stream()."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        chunks = [
            ProcessChunk(type=ProcessChunkType.STDOUT, data="line1\n"),
            ProcessChunk(type=ProcessChunkType.STDOUT, data="line2\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ]

        # Create a proper async-iterable mock
        class _MockReader:
            def __init__(self, items):
                self._items = items

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self._items:
                    raise StopAsyncIteration
                return self._items.pop(0)

        mock_process_protocol.start.return_value = _MockReader(list(chunks))

        collected = []
        async for chunk in commands_module.stream("echo test"):
            collected.append(chunk)

        assert len(collected) == 3
        assert collected[0].type == ProcessChunkType.STDOUT
        assert collected[0].data == "line1\n"
        assert collected[2].type == ProcessChunkType.EXIT


class TestCommandsList:
    """Test CommandsModule.list()."""

    @pytest.mark.asyncio
    async def test_list_returns_processes(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        result = await commands_module.list()
        assert len(result) == 1
        assert isinstance(result[0], ProcessInfo)
        assert result[0].pid == 1234


class TestCommandsKill:
    """Test CommandsModule.kill()."""

    @pytest.mark.asyncio
    async def test_kill_calls_protocol(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        await commands_module.kill(1234)
        mock_process_protocol.kill.assert_called_once()
        call_kwargs = mock_process_protocol.kill.call_args[1]
        assert call_kwargs["pid"] == 1234


class TestCommandsSendStdin:
    """Test CommandsModule.send_stdin()."""

    @pytest.mark.asyncio
    async def test_send_stdin_forwards_data(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        await commands_module.send_stdin(1234, "input data\n")
        mock_process_protocol.send_input.assert_called_once()
        call_kwargs = mock_process_protocol.send_input.call_args[1]
        assert call_kwargs["pid"] == 1234
        assert call_kwargs["data"] == "input data\n"


class TestCommandsUserParam:
    """Test that the `user` parameter propagates into the protocol payload."""

    @pytest.mark.asyncio
    async def test_run_passes_user_to_protocol(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        await commands_module.run("echo hi", user="root")
        call_kwargs = mock_process_protocol.start.call_args[1]
        assert call_kwargs["user"] == "root"

    @pytest.mark.asyncio
    async def test_run_default_user(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        await commands_module.run("echo hi")
        call_kwargs = mock_process_protocol.start.call_args[1]
        assert call_kwargs["user"] == ""

    @pytest.mark.asyncio
    async def test_stream_passes_user_to_protocol(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        async for _ in commands_module.stream("echo hi", user="admin"):
            pass
        call_kwargs = mock_process_protocol.start.call_args[1]
        assert call_kwargs["user"] == "admin"

    @pytest.mark.asyncio
    async def test_start_passes_user_to_protocol(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        await commands_module.start("echo hi", user="deploy")
        call_kwargs = mock_process_protocol.start.call_args[1]
        assert call_kwargs["user"] == "deploy"


class TestCommandsBackground:
    """Test that background=True delegates to start() and returns a handle."""

    @pytest.mark.asyncio
    async def test_background_returns_stream_reader(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """background=True should return a StreamReader-like handle, not ProcessResult."""
        mock_reader = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.STDOUT, data="bg\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        mock_process_protocol.start.return_value = mock_reader
        result = await commands_module.run("sleep 10", background=True)
        # Should NOT be a ProcessResult — it should be the reader handle
        assert not isinstance(result, ProcessResult)
        # Should be async-iterable (the handle from start())
        assert hasattr(result, "__aiter__")

    @pytest.mark.asyncio
    async def test_background_false_returns_process_result(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.STDOUT, data="done\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        result = await commands_module.run("echo done", background=False)
        assert isinstance(result, ProcessResult)
        assert result.stdout == "done\n"

    @pytest.mark.asyncio
    async def test_background_propagates_all_params(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """background=True should forward timeout, env, cwd, user to start()."""
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        await commands_module.run(
            "ls",
            timeout=30,
            env={"A": "1"},
            cwd="/tmp",
            user="root",
            background=True,
        )
        call_kwargs = mock_process_protocol.start.call_args[1]
        assert call_kwargs["timeout"] == 30
        assert call_kwargs["env"] == {"A": "1"}
        assert call_kwargs["cwd"] == "/tmp"
        assert call_kwargs["user"] == "root"


class TestCommandsSyncVariants:
    """Test sync wrappers exist."""

    def test_run_sync_exists(self) -> None:
        assert hasattr(CommandsModule, "run_sync")

    def test_list_sync_exists(self) -> None:
        assert hasattr(CommandsModule, "list_sync")

    def test_kill_sync_exists(self) -> None:
        assert hasattr(CommandsModule, "kill_sync")

    def test_send_stdin_sync_exists(self) -> None:
        assert hasattr(CommandsModule, "send_stdin_sync")

    def test_stream_sync_exists(self) -> None:
        assert hasattr(CommandsModule, "stream_sync")


class TestStreamSync:
    """Test stream_sync collects async generator chunks synchronously."""

    def test_stream_sync_returns_collected_chunks(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """stream_sync should return a list of ProcessChunk items."""
        expected_chunks = [
            ProcessChunk(type=ProcessChunkType.STDOUT, data="line1\n"),
            ProcessChunk(type=ProcessChunkType.STDERR, data="warn\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ]
        mock_process_protocol.start.return_value = _MockStreamReader(
            list(expected_chunks),
        )
        result = commands_module.stream_sync("echo test")
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0].type == ProcessChunkType.STDOUT
        assert result[0].data == "line1\n"
        assert result[1].type == ProcessChunkType.STDERR
        assert result[2].type == ProcessChunkType.EXIT
        assert result[2].exit_code == 0

    def test_stream_sync_forwards_parameters(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """stream_sync should forward timeout/env/cwd/user to stream()."""
        mock_process_protocol.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        commands_module.stream_sync(
            "ls",
            timeout=30,
            env={"A": "1"},
            cwd="/tmp",
            user="root",
        )
        call_kwargs = mock_process_protocol.start.call_args[1]
        assert call_kwargs["timeout"] == 30
        assert call_kwargs["env"] == {"A": "1"}
        assert call_kwargs["cwd"] == "/tmp"
        assert call_kwargs["user"] == "root"

    def test_stream_sync_empty_output(
        self,
        commands_module: CommandsModule,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """stream_sync should return an empty list when no chunks are produced."""
        mock_process_protocol.start.return_value = _MockStreamReader([])
        result = commands_module.stream_sync("true")
        assert result == []
