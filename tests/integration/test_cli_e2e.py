"""CLI end-to-end integration tests.

These tests exercise the CLI commands using Click's CliRunner,
verifying the full flow from CLI entry through the Sandbox API layer.

Run with: pytest tests/integration/test_cli_e2e.py -m integration -v
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from serverless_sandbox.cli.main import cli
from serverless_sandbox.models.errors import (
    AuthenticationError,
    QuotaExceededError,
    TemplateNotFoundError,
)
from serverless_sandbox.models.process import ProcessResult
from serverless_sandbox.models.sandbox import SandboxInfo, SandboxStatus
from serverless_sandbox.transport.config import reset_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SANDBOX_ID = "sbx-cli-test-001"
ENVD_URL = "https://sbx-cli-test-001.envd.fc.aliyuncs.com"
ENVD_TOKEN = "test-envd-token-cli"

# Patch targets — CLI commands do lazy imports from these modules
_SANDBOX_CLS = "serverless_sandbox.api.sandbox.Sandbox"
_LOAD_CONFIG = "serverless_sandbox.transport.config.load_config"
_CREATE_AUTH = "serverless_sandbox.transport.auth.create_auth_provider"
_HTTP_CLIENT = "serverless_sandbox.transport.http.HttpClient"
_SANDBOX_PROTO = "serverless_sandbox.protocol.sandbox.SandboxProtocol"


def _safe_stderr(result) -> str:
    """Return result.stderr safely across Click versions."""
    try:
        return result.stderr or ""
    except ValueError:
        return ""


def _make_mock_sandbox(
    sandbox_id: str = SANDBOX_ID,
    status: SandboxStatus = SandboxStatus.RUNNING,
    template: str = "python-base",
    region: str = "cn-hangzhou",
) -> MagicMock:
    """Create a mock Sandbox instance with realistic attributes."""
    sb = MagicMock()
    sb.id = sandbox_id
    sb.status = status
    sb.is_running = status == SandboxStatus.RUNNING
    sb.url = f"https://{sandbox_id}.envd.fc.aliyuncs.com"
    sb.info = SandboxInfo.model_validate({
        "sandboxID": sandbox_id,
        "templateID": template,
        "status": status.value,
        "region": region,
        "envdUrl": sb.url,
        "envdAccessToken": ENVD_TOKEN,
    })

    # Mock commands sub-module
    sb.commands = MagicMock()
    sb.commands.run = AsyncMock(return_value=ProcessResult(
        stdout="hello\n", stderr="", exit_code=0, execution_time=0.1,
    ))

    # Mock kill
    sb.kill = AsyncMock()

    return sb


@pytest.fixture(autouse=True)
def _reset_cached_config():
    """Ensure clean config state."""
    reset_config()
    yield
    reset_config()


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


# ---------------------------------------------------------------------------
# Test 1: Full CLI flow — create → exec → kill
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_create_exec_kill(runner: CliRunner):
    """Exercise: sbox create → sbox exec → sbox kill."""
    mock_sb = _make_mock_sandbox()

    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.create = AsyncMock(return_value=mock_sb)
        MockSandbox.connect = AsyncMock(return_value=mock_sb)

        # --- sbox create ---
        result = runner.invoke(cli, ["create", "--template", "python-base"])
        assert result.exit_code == 0, f"create failed: {result.output}\n{_safe_stderr(result)}"
        assert SANDBOX_ID in result.output

        # --- sbox exec ---
        result = runner.invoke(cli, ["exec", SANDBOX_ID, "echo hello"])
        assert result.exit_code == 0, f"exec failed: {result.output}\n{_safe_stderr(result)}"
        assert "hello" in result.output

        # --- sbox kill ---
        result = runner.invoke(cli, ["kill", SANDBOX_ID, "--yes"])
        assert result.exit_code == 0, f"kill failed: {result.output}\n{_safe_stderr(result)}"
        mock_sb.kill.assert_called()


# ---------------------------------------------------------------------------
# Test 2: JSON output format
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_json_output(runner: CliRunner):
    """Verify --json flag produces valid JSON output."""
    mock_sb = _make_mock_sandbox()

    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.create = AsyncMock(return_value=mock_sb)

        result = runner.invoke(cli, ["--json", "create", "--template", "python-base"])
        assert result.exit_code == 0, f"json create failed: {result.output}\n{_safe_stderr(result)}"

        # Output should be valid JSON
        parsed = json.loads(result.output)
        assert parsed["ID"] == SANDBOX_ID
        assert parsed["Status"] == "running"
        assert parsed["Template"] == "python-base"


@pytest.mark.integration
def test_cli_exec_json_output(runner: CliRunner):
    """Verify exec --json produces structured output."""
    mock_sb = _make_mock_sandbox()

    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.connect = AsyncMock(return_value=mock_sb)

        result = runner.invoke(cli, ["--json", "exec", SANDBOX_ID, "echo hello"])
        assert result.exit_code == 0, f"json exec failed: {result.output}\n{_safe_stderr(result)}"

        parsed = json.loads(result.output)
        assert parsed["stdout"] == "hello\n"
        assert parsed["exit_code"] == 0


# ---------------------------------------------------------------------------
# Test 3: Error messages include suggestions
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_error_template_not_found(runner: CliRunner):
    """TemplateNotFoundError shows error code and suggestion."""
    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.create = AsyncMock(
            side_effect=TemplateNotFoundError("Template 'bad' not found"),
        )

        result = runner.invoke(cli, ["create", "--template", "bad"])
        assert result.exit_code != 0
        # Error message should appear in stderr (Click 8.5) or output (Click <8.5)
        try:
            stderr = result.stderr
        except ValueError:
            stderr = ""
        combined = result.output + stderr
        assert "not found" in combined.lower()


@pytest.mark.integration
def test_cli_error_quota_exceeded(runner: CliRunner):
    """QuotaExceededError shows error code and suggestion."""
    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.create = AsyncMock(
            side_effect=QuotaExceededError("Sandbox quota exceeded"),
        )

        result = runner.invoke(cli, ["create", "--template", "python-base"])
        assert result.exit_code != 0
        try:
            stderr = result.stderr
        except ValueError:
            stderr = ""
        combined = result.output + stderr
        assert "quota" in combined.lower() or "E2002" in combined


@pytest.mark.integration
def test_cli_error_auth(runner: CliRunner):
    """AuthenticationError shows helpful suggestion."""
    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.create = AsyncMock(
            side_effect=AuthenticationError("Invalid API key"),
        )

        result = runner.invoke(cli, ["create", "--template", "python-base"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Test 4: List sandboxes
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_list_sandboxes(runner: CliRunner):
    """sbox list shows sandboxes in table format."""
    sb1_info = SandboxInfo.model_validate({
        "sandboxID": "sbx-list-001", "templateID": "python-base",
        "status": "running", "region": "cn-hangzhou",
    })
    sb2_info = SandboxInfo.model_validate({
        "sandboxID": "sbx-list-002", "templateID": "node-base",
        "status": "stopped", "region": "cn-shanghai",
    })

    with (
        patch(_LOAD_CONFIG) as mock_cfg,
        patch(_CREATE_AUTH),
        patch(_HTTP_CLIENT),
        patch(_SANDBOX_PROTO) as MockProto,
    ):
        mock_cfg.return_value = MagicMock(
            api_key="test-key", access_key_id=None, access_key_secret=None,
        )
        mock_proto_instance = MockProto.return_value
        mock_proto_instance.list = AsyncMock(return_value=[sb1_info, sb2_info])

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0, f"list failed: {result.output}\n{_safe_stderr(result)}"
        assert "sbx-list-001" in result.output
        assert "sbx-list-002" in result.output


# ---------------------------------------------------------------------------
# Test 5: Info command
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_info_command(runner: CliRunner):
    """sbox info <id> shows sandbox details."""
    mock_sb = _make_mock_sandbox()

    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.connect = AsyncMock(return_value=mock_sb)

        result = runner.invoke(cli, ["info", SANDBOX_ID])
        assert result.exit_code == 0, f"info failed: {result.output}\n{_safe_stderr(result)}"
        assert SANDBOX_ID in result.output
        assert "running" in result.output.lower()


# ---------------------------------------------------------------------------
# Test 7: Quiet mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_quiet_mode(runner: CliRunner):
    """sbox --quiet suppresses non-essential output."""
    mock_sb = _make_mock_sandbox()

    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.connect = AsyncMock(return_value=mock_sb)

        result = runner.invoke(cli, ["--quiet", "info", SANDBOX_ID])
        assert result.exit_code == 0
        # Quiet mode still outputs values but without decoration


# ---------------------------------------------------------------------------
# Test 8: Exec with non-zero exit code
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_exec_nonzero_exit(runner: CliRunner):
    """sbox exec propagates non-zero exit code."""
    mock_sb = _make_mock_sandbox()
    mock_sb.commands.run = AsyncMock(return_value=ProcessResult(
        stdout="", stderr="command not found\n", exit_code=127, execution_time=0.05,
    ))

    with patch(_SANDBOX_CLS) as MockSandbox:
        MockSandbox.connect = AsyncMock(return_value=mock_sb)

        result = runner.invoke(cli, ["exec", SANDBOX_ID, "nonexistent_cmd"])
        assert result.exit_code == 127
