"""Tests for `sbox run` CLI command."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from serverless_sandbox.cli.main import cli
from serverless_sandbox.models.process import ProcessResult


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_run_patches(mock_sandbox):
    """Return a context manager that mocks Sandbox.connect as AsyncMock.

    After the event-loop fix, ``run_cmd`` merges connect + dispatch
    into a single ``run_sync(_connect_and_run())`` call, so we only
    need to mock ``Sandbox.connect`` and let the real ``run_sync``
    execute the merged async function.
    """
    return patch(
        "serverless_sandbox.api.sandbox.Sandbox.connect",
        new=AsyncMock(return_value=mock_sandbox),
    )


class TestRunCommand:
    """Test ``sbox run <sandbox_id> <command_name> [--arg ...]``."""

    def test_run_dispatches_custom_command(self, runner: CliRunner) -> None:
        """Basic happy-path: sbox run sbx-1 build."""
        mock_result = ProcessResult(
            stdout="built!\n",
            stderr="",
            exit_code=0,
            execution_time=1.2,
        )
        mock_sandbox = MagicMock()
        mock_sandbox.run = AsyncMock(return_value=mock_result)

        with _make_run_patches(mock_sandbox):
            result = runner.invoke(cli, ["run", "sbx-1", "build"])

        assert result.exit_code == 0
        assert "built!" in result.output

    def test_run_with_args(self, runner: CliRunner) -> None:
        """sbox run sbx-1 deploy --arg target=staging."""
        mock_result = ProcessResult(
            stdout="deployed\n",
            stderr="",
            exit_code=0,
            execution_time=2.0,
        )
        mock_sandbox = MagicMock()
        mock_sandbox.run = AsyncMock(return_value=mock_result)

        with _make_run_patches(mock_sandbox):
            result = runner.invoke(
                cli,
                ["run", "sbx-1", "deploy", "--arg", "target=staging"],
            )

        assert result.exit_code == 0
        assert "deployed" in result.output

    def test_run_invalid_arg_format(self, runner: CliRunner) -> None:
        """--arg without '=' should report error."""
        result = runner.invoke(
            cli,
            ["run", "sbx-1", "build", "--arg", "badformat"],
        )
        assert result.exit_code == 2

    def test_run_json_output(self, runner: CliRunner) -> None:
        """sbox --json run sbx-1 test."""
        mock_result = ProcessResult(
            stdout="pass\n",
            stderr="",
            exit_code=0,
            execution_time=0.5,
        )
        mock_sandbox = MagicMock()
        mock_sandbox.run = AsyncMock(return_value=mock_result)

        with _make_run_patches(mock_sandbox):
            result = runner.invoke(cli, ["--json", "run", "sbx-1", "test"])

        assert result.exit_code == 0
        assert "exit_code" in result.output

    def test_run_registered_in_cli(self, runner: CliRunner) -> None:
        """The 'run' subcommand should appear in --help."""
        result = runner.invoke(cli, ["--help"])
        assert "run" in result.output

    def test_exec_still_works(self, runner: CliRunner) -> None:
        """'exec' should remain in --help (backward compat)."""
        result = runner.invoke(cli, ["--help"])
        assert "exec" in result.output
