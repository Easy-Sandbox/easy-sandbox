"""Tests for MCP CLI commands: install, start, status."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


# ---------------------------------------------------------------------------
# install command
# ---------------------------------------------------------------------------

class TestMcpInstall:
    """Test `ebx mcp install` command."""

    def test_install_cursor(self, runner, tmp_path):
        config_path = tmp_path / ".cursor" / "mcp.json"
        with patch(
            "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
            {"cursor": lambda: config_path, "claude": lambda: config_path, "vscode": lambda: config_path},
        ), patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="test-key-1234",
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "cursor"])
            assert result.exit_code == 0, result.output
            assert config_path.is_file()
            config = json.loads(config_path.read_text())
            assert "mcpServers" in config
            assert "easy-sandbox" in config["mcpServers"]
            srv = config["mcpServers"]["easy-sandbox"]
            assert srv["command"] == "ebx"
            assert srv["args"] == ["mcp", "start"]
            assert srv["env"]["E2B_API_KEY"] == "test-key-1234"

    def test_install_claude(self, runner, tmp_path):
        config_path = tmp_path / "claude" / "claude_desktop_config.json"
        with patch(
            "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
            {"cursor": lambda: config_path, "claude": lambda: config_path, "vscode": lambda: config_path},
        ), patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="claude-key",
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "claude"])
            assert result.exit_code == 0, result.output
            config = json.loads(config_path.read_text())
            assert "mcpServers" in config
            assert "easy-sandbox" in config["mcpServers"]

    def test_install_vscode(self, runner, tmp_path):
        config_path = tmp_path / ".vscode" / "settings.json"
        with patch(
            "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
            {"cursor": lambda: config_path, "claude": lambda: config_path, "vscode": lambda: config_path},
        ), patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="vsc-key",
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "vscode"])
            assert result.exit_code == 0, result.output
            config = json.loads(config_path.read_text())
            assert "mcp.servers" in config
            assert "easy-sandbox" in config["mcp.servers"]

    def test_install_merges_existing_config(self, runner, tmp_path):
        config_path = tmp_path / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "mcpServers": {
                "other-server": {"command": "other"}
            }
        }))
        with patch(
            "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
            {"cursor": lambda: config_path, "claude": lambda: config_path, "vscode": lambda: config_path},
        ), patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="key",
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "cursor"])
            assert result.exit_code == 0
            config = json.loads(config_path.read_text())
            # Both servers should be present
            assert "other-server" in config["mcpServers"]
            assert "easy-sandbox" in config["mcpServers"]

    def test_install_without_api_key(self, runner, tmp_path):
        config_path = tmp_path / ".cursor" / "mcp.json"
        with patch(
            "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
            {"cursor": lambda: config_path, "claude": lambda: config_path, "vscode": lambda: config_path},
        ), patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value=None,
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "cursor"])
            assert result.exit_code == 0
            config = json.loads(config_path.read_text())
            srv = config["mcpServers"]["easy-sandbox"]
            # No env block if no key
            assert "env" not in srv or "E2B_API_KEY" not in srv.get("env", {})

    def test_install_requires_target(self, runner):
        result = runner.invoke(cli, ["mcp", "install"])
        assert result.exit_code != 0

    def test_install_shows_tool_names(self, runner, tmp_path):
        config_path = tmp_path / ".cursor" / "mcp.json"
        with patch(
            "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
            {"cursor": lambda: config_path, "claude": lambda: config_path, "vscode": lambda: config_path},
        ), patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "cursor"])
            assert "create_sandbox" in result.output
            assert "run_code" in result.output
            assert "kill_sandbox" in result.output


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

class TestMcpStatus:
    """Test `ebx mcp status` command."""

    def test_status_json(self, runner):
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="test-key",
        ):
            result = runner.invoke(cli, ["--json", "mcp", "status"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["server"] == "easy-sandbox"
            assert data["tools_count"] == 7
            assert data["auth_configured"] is True

    def test_status_no_auth(self, runner):
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value=None,
        ):
            result = runner.invoke(cli, ["--json", "mcp", "status"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["auth_configured"] is False


# ---------------------------------------------------------------------------
# start command (basic test — we don't actually run the server)
# ---------------------------------------------------------------------------

class TestMcpStart:
    """Test `ebx mcp start` command options."""

    def test_start_help(self, runner):
        """start --help should work."""
        result = runner.invoke(cli, ["mcp", "start", "--help"])
        assert result.exit_code == 0
        assert "STDIO" in result.output or "template" in result.output
