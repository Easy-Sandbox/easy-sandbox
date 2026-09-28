"""Tests for sandbox capabilities and shell-stream CLI commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from easy_sandbox.cli.main import cli
from easy_sandbox.models.process import ProcessChunk, ProcessChunkType, ProcessResult

if TYPE_CHECKING:
    from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sandbox() -> MagicMock:
    """Build a lightweight mock Sandbox for system/extra-command tests."""
    sb = MagicMock()
    sb.id = "sbx-test-001"
    sb.capabilities = {"shell", "files", "code"}

    sb.commands = MagicMock()
    sb.commands.run = AsyncMock()
    sb.commands.stream = MagicMock()

    sb.kill = AsyncMock()
    return sb


def _patch_connect(sb: MagicMock):
    return patch(
        "easy_sandbox.api.sandbox.Sandbox.connect",
        new_callable=AsyncMock,
        return_value=sb,
    )


class _AsyncIter:
    """Wrap a list of chunks into an async iterator for shell-stream mock."""

    def __init__(self, chunks: list):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


# ===================================================================
# sandbox system env
# ===================================================================


class TestSystemEnv:
    """CLI coverage for the current read-only ``sandbox system env`` command."""

    def test_command_is_registered_and_help_describes_current_interface(
        self,
        runner: CliRunner,
    ) -> None:
        system_help = runner.invoke(cli, ["sandbox", "system", "--help"])
        env_help = runner.invoke(cli, ["sandbox", "system", "env", "--help"])

        assert system_help.exit_code == 0
        assert "env" in system_help.output
        assert env_help.exit_code == 0
        assert "SANDBOX_ID" in env_help.output
        assert "--filter" in env_help.output
        assert "Show environment variables" in env_help.output

    def test_requires_sandbox_id(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["sandbox", "system", "env"])

        assert result.exit_code == 2
        assert "Missing argument 'SANDBOX_ID'" in result.output

    def test_reads_sorts_and_sanitizes_environment(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run.return_value = ProcessResult(
            stdout=(
                "ZED=last\n"
                "PATH=/usr/local/bin\n"
                "API_TOKEN=hidden\n"
                "CREDENTIAL_FILE=hidden\n"
                "WITH_EQUALS=one=two\n"
                "malformed\n"
                "ALPHA=first\n"
            )
        )

        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "ALPHA=first",
            "PATH=/usr/local/bin",
            "WITH_EQUALS=one=two",
            "ZED=last",
        ]
        sb.commands.run.assert_awaited_once_with("env", timeout=10)

    def test_filter_limits_returned_variables(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run.return_value = ProcessResult(
            stdout="HOME=/home/sandbox\nLANG=C.UTF-8\nPATH=/usr/bin\n"
        )

        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                [
                    "sandbox",
                    "system",
                    "env",
                    "sbx-test-001",
                    "--filter",
                    " PATH, LANG ",
                ],
            )

        assert result.exit_code == 0
        assert result.output.splitlines() == ["LANG=C.UTF-8", "PATH=/usr/bin"]
        assert "HOME" not in result.output

    def test_no_matching_variables_has_friendly_output(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run.return_value = ProcessResult(stdout="API_KEY=hidden\n")

        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 0
        assert "No matching environment variables found." in result.output
        assert "hidden" not in result.output

    def test_remote_command_failure_is_friendly(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run.return_value = ProcessResult(stderr="env failed", exit_code=1)

        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 1
        assert "Failed to retrieve environment variables." in result.output
        assert "Traceback" not in result.output

    def test_json_output(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run.return_value = ProcessResult(
            stdout="PATH=/usr/bin\nHOME=/home/sandbox\nAPI_SECRET=hidden\n"
        )

        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "variables": {"HOME": "/home/sandbox", "PATH": "/usr/bin"}
        }

    def test_quiet_output_keeps_final_values(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run.return_value = ProcessResult(stdout="PATH=/usr/bin\nHOME=/home/sandbox\n")

        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--quiet", "sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 0
        assert result.output.splitlines() == ["HOME=/home/sandbox", "PATH=/usr/bin"]

    @staticmethod
    def _http_error(status: int) -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "https://sandbox.example/env")
        response = httpx.Response(status, request=request)
        return httpx.HTTPStatusError(str(status), request=request, response=response)

    def test_http_404_is_friendly(self, runner: CliRunner) -> None:
        with patch(
            "easy_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            side_effect=self._http_error(404),
        ):
            result = runner.invoke(
                cli,
                ["sandbox", "system", "env", "missing-sandbox"],
            )

        assert result.exit_code == 4
        assert "Resource not found (HTTP 404)." in result.output
        assert "Verify the sandbox ID" in result.output
        assert "Traceback" not in result.output

    def test_http_401_is_friendly(self, runner: CliRunner) -> None:
        with patch(
            "easy_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            side_effect=self._http_error(401),
        ):
            result = runner.invoke(
                cli,
                ["sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 3
        assert "Authentication failed (HTTP 401)." in result.output
        assert "Check your API key" in result.output
        assert "Traceback" not in result.output

    def test_http_timeout_is_friendly(self, runner: CliRunner) -> None:
        request = httpx.Request("GET", "https://sandbox.example/env")
        with patch(
            "easy_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("read timed out", request=request),
        ):
            result = runner.invoke(
                cli,
                ["sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 5
        assert "Request timed out: read timed out" in result.output
        assert "Increase HTTP timeout" in result.output
        assert "Traceback" not in result.output

    def test_protocol_error_is_friendly(self, runner: CliRunner) -> None:
        """httpx.RemoteProtocolError (HTTP/2 StreamReset) maps to E5003."""
        request = httpx.Request("GET", "https://sandbox.example/env")
        with patch(
            "easy_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            side_effect=httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body",
                request=request,
            ),
        ):
            result = runner.invoke(
                cli,
                ["sandbox", "system", "env", "sbx-test-001"],
            )

        assert result.exit_code == 1
        assert "Connection reset by remote" in result.output
        assert "E5003" in result.output
        assert "Disable HTTP/2" in result.output
        assert "Traceback" not in result.output


# ===================================================================
# sandbox capabilities
# ===================================================================


class TestCapabilities:
    def test_capabilities_happy(self, runner: CliRunner) -> None:
        """Capabilities listed in sorted order."""
        sb = _make_sandbox()
        sb.capabilities = {"shell", "files", "code"}
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "capabilities", "sbx-test-001"],
            )
        assert result.exit_code == 0
        assert "code" in result.output
        assert "files" in result.output
        assert "shell" in result.output

    def test_capabilities_empty(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.capabilities = set()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "capabilities", "sbx-test-001"],
            )
        assert result.exit_code == 0
        assert "No capabilities" in result.output

    def test_capabilities_json(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.capabilities = {"shell", "files"}
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "capabilities", "sbx-test-001"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "capabilities" in data
        assert sorted(data["capabilities"]) == ["files", "shell"]


# ===================================================================
# sandbox shell-stream
# ===================================================================


class TestShellStream:
    def test_stream_multi_chunk(self, runner: CliRunner) -> None:
        """STDOUT + STDERR + EXIT(0) streamed in order."""
        sb = _make_sandbox()
        chunks = [
            ProcessChunk(type=ProcessChunkType.STDOUT, data="hello "),
            ProcessChunk(type=ProcessChunkType.STDOUT, data="world\n"),
            ProcessChunk(type=ProcessChunkType.STDERR, data="warn\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ]
        sb.commands.stream = MagicMock(return_value=_AsyncIter(chunks))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "shell-stream", "sbx-test-001", "-c", "echo hello"],
            )
        assert result.exit_code == 0
        assert "hello " in result.output

    def test_stream_nonzero_exit(self, runner: CliRunner) -> None:
        """Non-zero exit code from stream is propagated."""
        sb = _make_sandbox()
        chunks = [
            ProcessChunk(type=ProcessChunkType.STDOUT, data="partial\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=1),
        ]
        sb.commands.stream = MagicMock(return_value=_AsyncIter(chunks))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "shell-stream", "sbx-test-001", "-c", "bad_cmd"],
            )
        assert result.exit_code == 1

    def test_stream_json(self, runner: CliRunner) -> None:
        """--json outputs exit_code after stream completes."""
        sb = _make_sandbox()
        chunks = [
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ]
        sb.commands.stream = MagicMock(return_value=_AsyncIter(chunks))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "shell-stream", "sbx-test-001", "-c", "true"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["exit_code"] == 0

    def test_stream_timeout_cwd(self, runner: CliRunner) -> None:
        """--timeout and --cwd forwarded to commands.stream."""
        sb = _make_sandbox()
        chunks = [ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0)]
        sb.commands.stream = MagicMock(return_value=_AsyncIter(chunks))
        with _patch_connect(sb):
            runner.invoke(
                cli,
                [
                    "sandbox",
                    "shell-stream",
                    "sbx-test-001",
                    "-c",
                    "make",
                    "--timeout",
                    "60",
                    "--cwd",
                    "/app",
                ],
            )
        sb.commands.stream.assert_called_once_with("make", timeout=60, cwd="/app")

    def test_stream_missing_command(self, runner: CliRunner) -> None:
        """--command is required → exit 2."""
        result = runner.invoke(
            cli,
            ["sandbox", "shell-stream", "sbx-test-001"],
        )
        assert result.exit_code == 2

    def test_stream_timeout_error(self, runner: CliRunner) -> None:
        """CommandTimeoutError → exit 5."""
        from easy_sandbox.models.errors import CommandTimeoutError

        sb = _make_sandbox()
        sb.commands.stream = MagicMock(
            side_effect=CommandTimeoutError("timed out"),
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "shell-stream", "sbx-test-001", "-c", "sleep 9999"],
            )
        assert result.exit_code == 5
