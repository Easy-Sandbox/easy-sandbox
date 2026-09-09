"""Tests for deploy CLI commands — NL deploy + traditional modes."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from serverless_sandbox.cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with a requirements.txt."""
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
    return tmp_path


def _make_mock_sandbox(
    sandbox_id: str = "sbx-deploy-001",
    status: str = "success",
    url: str = "",
    port: int = 0,
) -> MagicMock:
    """Create a mock Sandbox with a deploy result attached."""
    mock_sandbox = MagicMock()
    mock_sandbox.id = sandbox_id

    mock_deploy_result = MagicMock()
    mock_deploy_result.status = status
    mock_deploy_result.url = url
    mock_deploy_result.port = port
    mock_deploy_result.logs = ""
    mock_deploy_result.success = (status == "success")

    mock_sandbox._deploy_result = mock_deploy_result
    return mock_sandbox


class TestDeployShortcutNL:
    """Test NL deploy mode (default)."""

    def test_deploy_nonexistent_path(self, runner: CliRunner) -> None:
        """Test deploy with non-existent path."""
        result = runner.invoke(cli, ["deploy", "/nonexistent/path/xyz"])
        assert result.exit_code != 0

    def test_deploy_traditional_mode(self, runner: CliRunner, temp_project: Path) -> None:
        """Test deploy --traditional falls through to traditional mode."""
        result = runner.invoke(
            cli,
            ["deploy", str(temp_project), "--traditional"],
        )
        assert result.exit_code == 0
        # Should show project type detection
        assert "python" in result.output.lower() or "Template" in result.output

    def test_deploy_with_instruction(self, runner: CliRunner, temp_project: Path) -> None:
        """Test deploy with NL instruction triggers Sandbox.deploy."""
        mock_sandbox = _make_mock_sandbox(
            url="http://localhost:8080", port=8080,
        )

        # Patch at the actual import location used inside _run_nl_deploy
        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.deploy",
            new_callable=AsyncMock,
            return_value=mock_sandbox,
        ):
            result = runner.invoke(
                cli,
                ["deploy", str(temp_project), "部署这个 Flask 应用"],
            )

        assert result.exit_code == 0
        assert "sbx-deploy-001" in result.output or "success" in result.output.lower()

    def test_deploy_with_instruction_flag(self, runner: CliRunner, temp_project: Path) -> None:
        """Test deploy with --instruction flag."""
        mock_sandbox = _make_mock_sandbox(sandbox_id="sbx-deploy-002")

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.deploy",
            new_callable=AsyncMock,
            return_value=mock_sandbox,
        ):
            result = runner.invoke(
                cli,
                ["deploy", str(temp_project), "-i", "Deploy to port 8080"],
            )

        assert result.exit_code == 0

    def test_deploy_llm_key_missing(self, runner: CliRunner, temp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test deploy raises clear error when no LLM key is set."""
        monkeypatch.delenv("BAILIAN_CODING_PLAN_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from serverless_sandbox.models.errors import DeployLLMKeyMissingError

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.deploy",
            new_callable=AsyncMock,
            side_effect=DeployLLMKeyMissingError(
                "No LLM API key found for qwen-code agent."
            ),
        ):
            result = runner.invoke(
                cli,
                ["deploy", str(temp_project), "部署项目"],
            )

        # Should fail with error exit code (handle_errors maps SandboxError to exit 1)
        assert result.exit_code != 0

    def test_deploy_default_instruction_generated(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that a default instruction is generated when none is provided."""
        mock_sandbox = _make_mock_sandbox()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.deploy",
            new_callable=AsyncMock,
            return_value=mock_sandbox,
        ) as mock_deploy:
            result = runner.invoke(
                cli,
                ["deploy", str(temp_project)],
            )

        assert result.exit_code == 0
        # Verify deploy was called with a generated instruction
        mock_deploy.assert_called_once()
        call_kwargs = mock_deploy.call_args
        description = call_kwargs.kwargs.get("description") or call_kwargs[1].get("description", "")
        assert "python" in description.lower() or "部署" in description


class TestDeployBuild:
    """Test deploy build subcommand."""

    def test_build_nonexistent_path(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["deploy", "/nonexistent/path", "--traditional"])
        assert result.exit_code != 0


class TestDeployOptions:
    """Test deploy command options parsing."""

    def test_max_wall_time_option(self, runner: CliRunner, temp_project: Path) -> None:
        """Test --max-wall-time option is accepted."""
        mock_sandbox = _make_mock_sandbox()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.deploy",
            new_callable=AsyncMock,
            return_value=mock_sandbox,
        ) as mock_deploy:
            result = runner.invoke(
                cli,
                ["deploy", str(temp_project), "deploy", "--max-wall-time", "20m"],
            )

        assert result.exit_code == 0
        # Verify max_wall_time was passed
        call_kwargs = mock_deploy.call_args
        assert call_kwargs.kwargs.get("max_wall_time") == "20m"

    def test_max_tool_calls_option(self, runner: CliRunner, temp_project: Path) -> None:
        """Test --max-tool-calls option is accepted."""
        mock_sandbox = _make_mock_sandbox()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.deploy",
            new_callable=AsyncMock,
            return_value=mock_sandbox,
        ) as mock_deploy:
            result = runner.invoke(
                cli,
                ["deploy", str(temp_project), "deploy", "--max-tool-calls", "50"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_deploy.call_args
        assert call_kwargs.kwargs.get("max_tool_calls") == 50
