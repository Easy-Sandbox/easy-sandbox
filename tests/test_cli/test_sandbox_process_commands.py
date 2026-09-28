"""Tests for sandbox process CLI commands: list, start, info, signal."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from easy_sandbox.cli.main import cli
from easy_sandbox.models.process import ProcessInfo, ProcessResult

if TYPE_CHECKING:
    from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sandbox() -> MagicMock:
    """Build a lightweight mock Sandbox for process-command tests."""
    sb = MagicMock()
    sb.id = "sbx-test-001"
    sb.capabilities = {"shell", "files", "code"}

    sb.commands = MagicMock()
    sb.commands.run = AsyncMock()
    sb.commands.list = AsyncMock(return_value=[])
    sb.commands.send_signal = AsyncMock()

    sb.kill = AsyncMock()
    return sb


def _patch_connect(sb: MagicMock):
    return patch(
        "easy_sandbox.api.sandbox.Sandbox.connect",
        new_callable=AsyncMock,
        return_value=sb,
    )


# ===================================================================
# sandbox process list
# ===================================================================


class TestProcessList:
    def test_list_non_empty(self, runner: CliRunner) -> None:
        """Three processes returned → table output."""
        sb = _make_sandbox()
        sb.commands.list = AsyncMock(
            return_value=[
                ProcessInfo(pid=1, command="/sbin/init", status="running"),
                ProcessInfo(pid=42, command="python app.py", status="running"),
                ProcessInfo(pid=99, command="node server.js", status="sleeping"),
            ]
        )
        with _patch_connect(sb):
            result = runner.invoke(cli, ["sandbox", "process", "list", "sbx-test-001"])
        assert result.exit_code == 0
        assert "42" in result.output
        assert "python" in result.output

    def test_list_empty(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.list = AsyncMock(return_value=[])
        with _patch_connect(sb):
            result = runner.invoke(cli, ["sandbox", "process", "list", "sbx-test-001"])
        assert result.exit_code == 0
        assert "No processes" in result.output

    def test_list_json(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.list = AsyncMock(
            return_value=[
                ProcessInfo(pid=10, command="bash", status="running"),
            ]
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "process", "list", "sbx-test-001"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["pid"] == 10

    def test_list_missing_sandbox_id(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["sandbox", "process", "list"])
        assert result.exit_code == 2


# ===================================================================
# sandbox process start
# ===================================================================


class TestProcessStart:
    def test_start_happy(self, runner: CliRunner) -> None:
        """exit_code=0 → runner exit_code=0."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="ok\n",
                stderr="",
                exit_code=0,
                execution_time=0.5,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "start", "sbx-test-001", "-c", "echo ok"],
            )
        assert result.exit_code == 0
        assert "ok" in result.output

    def test_start_nonzero_exit(self, runner: CliRunner) -> None:
        """Nonzero exit_code is propagated to the CLI runner."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="",
                stderr="fail\n",
                exit_code=42,
                execution_time=0.1,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "start", "sbx-test-001", "-c", "badcmd"],
            )
        assert result.exit_code == 42

    def test_start_timeout_cwd(self, runner: CliRunner) -> None:
        """--timeout and --cwd are forwarded to commands.run."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="",
                stderr="",
                exit_code=0,
                execution_time=0.01,
            )
        )
        with _patch_connect(sb):
            runner.invoke(
                cli,
                [
                    "sandbox",
                    "process",
                    "start",
                    "sbx-test-001",
                    "-c",
                    "make build",
                    "--timeout",
                    "60",
                    "--cwd",
                    "/app",
                ],
            )
        sb.commands.run.assert_called_once_with("make build", timeout=60, cwd="/app")

    def test_start_json(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="hi\n",
                stderr="",
                exit_code=0,
                execution_time=0.2,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "process", "start", "sbx-test-001", "-c", "echo hi"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stdout"] == "hi\n"
        assert data["exit_code"] == 0

    def test_start_missing_command(self, runner: CliRunner) -> None:
        """--command is required → exit 2."""
        result = runner.invoke(cli, ["sandbox", "process", "start", "sbx-test-001"])
        assert result.exit_code == 2

    def test_start_timeout_error(self, runner: CliRunner) -> None:
        from easy_sandbox.models.errors import CommandTimeoutError

        sb = _make_sandbox()
        sb.commands.run = AsyncMock(side_effect=CommandTimeoutError("timed out"))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "start", "sbx-test-001", "-c", "sleep 9999"],
            )
        assert result.exit_code == 5


# ===================================================================
# sandbox process info
# ===================================================================


class TestProcessInfo:
    def test_info_happy(self, runner: CliRunner) -> None:
        """ps returns one data line → info printed."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="  1234   1  root  Ss  4096  00:05:12  python\n",
                stderr="",
                exit_code=0,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "info", "sbx-test-001", "1234"],
            )
        assert result.exit_code == 0
        assert "1234" in result.output

    def test_info_not_found(self, runner: CliRunner) -> None:
        """ps exits 1 with empty stdout → not found, exit 1."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="",
                stderr="",
                exit_code=1,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "info", "sbx-test-001", "99999"],
            )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_info_pid_non_integer(self, runner: CliRunner) -> None:
        """PID argument type=int rejects non-integer."""
        result = runner.invoke(
            cli,
            ["sandbox", "process", "info", "sbx-test-001", "abc"],
        )
        assert result.exit_code == 2


# ===================================================================
# sandbox process signal
# ===================================================================


class TestProcessSignal:
    def test_signal_default_sigterm(self, runner: CliRunner) -> None:
        """Default signal is 15 (SIGTERM)."""
        sb = _make_sandbox()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "signal", "sbx-test-001", "1234"],
            )
        assert result.exit_code == 0
        sb.commands.send_signal.assert_called_once_with(1234, 15)

    def test_signal_explicit_9(self, runner: CliRunner) -> None:
        """--signal 9 sends SIGKILL."""
        sb = _make_sandbox()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "signal", "sbx-test-001", "1234", "--signal", "9"],
            )
        assert result.exit_code == 0
        sb.commands.send_signal.assert_called_once_with(1234, 9)

    def test_signal_pid_non_integer(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["sandbox", "process", "signal", "sbx-test-001", "abc"],
        )
        assert result.exit_code == 2

    def test_signal_not_found(self, runner: CliRunner) -> None:
        from easy_sandbox.models.errors import ExecutionError

        sb = _make_sandbox()
        sb.commands.send_signal = AsyncMock(
            side_effect=ExecutionError("process not found"),
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "process", "signal", "sbx-test-001", "9999"],
            )
        assert result.exit_code == 1
