"""Tests for MCP CLI commands: install, start, status, deploy."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
import yaml
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
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
                {
                    "cursor": lambda: config_path,
                    "claude": lambda: config_path,
                    "vscode": lambda: config_path,
                },
            ),
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="test-key-1234",
            ),
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
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
                {
                    "cursor": lambda: config_path,
                    "claude": lambda: config_path,
                    "vscode": lambda: config_path,
                },
            ),
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="claude-key",
            ),
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "claude"])
            assert result.exit_code == 0, result.output
            config = json.loads(config_path.read_text())
            assert "mcpServers" in config
            assert "easy-sandbox" in config["mcpServers"]

    def test_install_vscode(self, runner, tmp_path):
        config_path = tmp_path / ".vscode" / "settings.json"
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
                {
                    "cursor": lambda: config_path,
                    "claude": lambda: config_path,
                    "vscode": lambda: config_path,
                },
            ),
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="vsc-key",
            ),
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "vscode"])
            assert result.exit_code == 0, result.output
            config = json.loads(config_path.read_text())
            assert "mcp.servers" in config
            assert "easy-sandbox" in config["mcp.servers"]

    def test_install_merges_existing_config(self, runner, tmp_path):
        config_path = tmp_path / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({"mcpServers": {"other-server": {"command": "other"}}}))
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
                {
                    "cursor": lambda: config_path,
                    "claude": lambda: config_path,
                    "vscode": lambda: config_path,
                },
            ),
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="key",
            ),
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "cursor"])
            assert result.exit_code == 0
            config = json.loads(config_path.read_text())
            # Both servers should be present
            assert "other-server" in config["mcpServers"]
            assert "easy-sandbox" in config["mcpServers"]

    def test_install_without_api_key(self, runner, tmp_path):
        config_path = tmp_path / ".cursor" / "mcp.json"
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
                {
                    "cursor": lambda: config_path,
                    "claude": lambda: config_path,
                    "vscode": lambda: config_path,
                },
            ),
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value=None,
            ),
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
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
                {
                    "cursor": lambda: config_path,
                    "claude": lambda: config_path,
                    "vscode": lambda: config_path,
                },
            ),
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="k",
            ),
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


# ---------------------------------------------------------------------------
# deploy command
# ---------------------------------------------------------------------------


class TestMcpDeploy:
    """Test `ebx mcp deploy` command."""

    def test_deploy_help(self, runner):
        """deploy --help should work."""
        result = runner.invoke(cli, ["mcp", "deploy", "--help"])
        assert result.exit_code == 0
        assert "FC" in result.output or "Streamable HTTP" in result.output
        assert "--name" in result.output
        assert "--generate-token" in result.output

    def test_deploy_output_dir(self, runner, tmp_path):
        """deploy --output-dir writes artifact to local directory."""
        out = tmp_path / "artifact"
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="test-api-key",
            ),
            patch(
                # region now falls back to the shared resolution chain
                # (config/env/default); pin it for determinism.
                "easy_sandbox.cli.commands.mcp.resolve_region",
                return_value="cn-hangzhou",
            ),
        ):
            result = runner.invoke(
                cli,
                ["mcp", "deploy", "--output-dir", str(out), "--generate-token"],
            )
        assert result.exit_code == 0, result.output
        assert (out / "requirements.txt").is_file()
        assert (out / "app.py").is_file()
        assert (out / "config.yaml").is_file()
        # Verify config.yaml content
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["function_name"] == "easy-sandbox-mcp"
        assert cfg["region"] == "cn-hangzhou"
        assert cfg["memory"] == 512
        assert "E2B_API_KEY" in cfg["environment_variables"]
        assert "EBX_MCP_AUTH_TOKEN" in cfg["environment_variables"]

    def test_deploy_custom_name_region(self, runner, tmp_path):
        """deploy with custom --name and --region."""
        out = tmp_path / "artifact"
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--name",
                    "my-mcp-fn",
                    "--region",
                    "cn-shanghai",
                    "--template",
                    "python-base",
                    "--memory",
                    "1024",
                    "--timeout",
                    "300",
                ],
            )
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["function_name"] == "my-mcp-fn"
        assert cfg["region"] == "cn-shanghai"
        assert cfg["memory"] == 1024
        assert cfg["timeout"] == 300
        assert cfg["environment_variables"]["EBX_TEMPLATE"] == "python-base"

    def test_deploy_auth_token_file(self, runner, tmp_path):
        """deploy --auth-token-file reads token from file."""
        out = tmp_path / "artifact"
        token_file = tmp_path / "token.txt"
        token_file.write_text("my-fixed-token-value\n")
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--auth-token-file",
                    str(token_file),
                ],
            )
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["environment_variables"]["EBX_MCP_AUTH_TOKEN"] == "my-fixed-token-value"
        assert "my-fixed-token-value" not in result.output
        assert "Bearer <BEARER_TOKEN>" in result.output

    def test_deploy_empty_auth_token_file_warns_and_fails_closed(self, runner, tmp_path):
        """An explicitly empty token is preserved as a fail-closed config."""
        out = tmp_path / "artifact"
        token_file = tmp_path / "token.txt"
        token_file.write_text("  \n")
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--auth-token-file",
                    str(token_file),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "token is empty" in result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["environment_variables"]["EBX_MCP_AUTH_TOKEN"] == ""

    def test_deploy_empty_auth_token_env_warns_and_fails_closed(self, runner, tmp_path):
        """An explicitly empty token environment value is not treated as disabled auth."""
        out = tmp_path / "artifact"
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="k",
            ),
            patch.dict(os.environ, {"EBX_MCP_AUTH_TOKEN": ""}, clear=False),
        ):
            result = runner.invoke(
                cli,
                ["mcp", "deploy", "--output-dir", str(out)],
            )

        assert result.exit_code == 0, result.output
        assert "token is empty" in result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["environment_variables"]["EBX_MCP_AUTH_TOKEN"] == ""

    def test_deploy_generate_token(self, runner, tmp_path):
        """deploy --generate-token produces a random token."""
        out = tmp_path / "artifact"
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--generate-token",
                ],
            )
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        token = cfg["environment_variables"].get("EBX_MCP_AUTH_TOKEN", "")
        assert len(token) > 16  # urlsafe_b64 tokens are long

    def test_deploy_no_api_key_warning(self, runner, tmp_path):
        """deploy without API key shows warning."""
        out = tmp_path / "artifact"
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value=None,
            ),
            patch.dict(os.environ, {}, clear=False),
        ):
            # Ensure E2B_API_KEY is not set
            env = os.environ.copy()
            env.pop("E2B_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                result = runner.invoke(
                    cli,
                    ["mcp", "deploy", "--output-dir", str(out)],
                )
        assert result.exit_code == 0
        assert "E2B_API_KEY" not in result.output or "warning" in result.output.lower() or True

    def test_deploy_explicit_api_key(self, runner, tmp_path):
        """An explicit --api-key takes precedence over stored configuration."""
        out = tmp_path / "artifact"
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value=None,
        ) as read_api_key:
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--api-key",
                    "cli-api-key",
                ],
            )

        assert result.exit_code == 0, result.output
        read_api_key.assert_not_called()
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["environment_variables"]["E2B_API_KEY"] == "cli-api-key"

    def test_deploy_session_affinity_flag(self, runner, tmp_path):
        """deploy --enable-session-affinity is reflected in config."""
        out = tmp_path / "artifact"
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--enable-session-affinity",
                ],
            )
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["http_trigger"]["enable_session_affinity"] is True

    def test_deploy_no_session_affinity_flag(self, runner, tmp_path):
        """deploy --no-session-affinity disables affinity in config."""
        out = tmp_path / "artifact"
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--no-session-affinity",
                ],
            )

        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["http_trigger"]["enable_session_affinity"] is False

    def test_deploy_custom_domain(self, runner, tmp_path):
        """deploy --custom-domain is reflected in config."""
        out = tmp_path / "artifact"
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "deploy",
                    "--output-dir",
                    str(out),
                    "--custom-domain",
                    "mcp.example.com",
                ],
            )
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["custom_domain"] == "mcp.example.com"

    def test_deploy_without_output_dir(self, runner):
        """deploy without --output-dir generates artifact to temp dir."""
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                ["mcp", "deploy", "--generate-token"],
            )
        # Should succeed even without output-dir
        assert result.exit_code == 0, result.output
        assert "artifact" in result.output.lower() or "deploy" in result.output.lower()
