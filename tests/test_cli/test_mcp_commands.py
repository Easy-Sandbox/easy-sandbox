"""Tests for MCP CLI commands: install, start, status, deploy."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from unittest.mock import AsyncMock, patch

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
            assert srv["args"][-2:] == ["mcp", "start"]
            assert srv["command"]
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
        config_path = tmp_path / ".vscode" / "mcp.json"
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
            assert "servers" in config
            srv = config["servers"]["easy-sandbox"]
            assert srv["type"] == "stdio"
            assert srv["args"][-2:] == ["mcp", "start"]
            assert "E2B_API_KEY" not in (srv.get("env") or {})

    def test_install_refuses_to_overwrite_jsonc(self, runner, tmp_path):
        config_path = tmp_path / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True)
        original = '{ // keep-me\n  "editor.fontSize": 14,\n}\n'
        config_path.write_text(original)
        with (
            patch(
                "easy_sandbox.cli.commands.mcp._IDE_CONFIG_MAP",
                {"cursor": lambda: config_path},
            ),
            patch(
                "easy_sandbox.cli.commands.mcp._read_api_key",
                return_value="k",
            ),
        ):
            result = runner.invoke(cli, ["mcp", "install", "--target", "cursor"])
        assert result.exit_code != 0
        assert config_path.read_text() == original
        assert "not strict JSON" in result.output

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
        """start --help should describe logs, HTTP, background, and stop."""
        result = runner.invoke(cli, ["mcp", "start", "--help"])
        assert result.exit_code == 0
        assert "--http" in result.output
        assert "--background" in result.output
        assert "ebx mcp stop" in result.output

    def test_stdio_banner_hides_the_api_key(self, runner, monkeypatch, tmp_path):
        """Foreground STDIO prints configuration to stderr and never the secret."""
        monkeypatch.setenv("EBX_MCP_RUNTIME_DIR", str(tmp_path))
        with patch("easy_sandbox.agent.mcp.SandboxMCPServer") as server_cls:
            server_cls.return_value.run = AsyncMock()
            result = runner.invoke(
                cli,
                [
                    "mcp",
                    "start",
                    "--api-key",
                    "super-secret-key",
                    "--template",
                    "python-hello",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Easy Sandbox MCP server" in result.output
        assert "python-hello" in result.output
        assert "configured" in result.output
        assert "Waiting for JSON-RPC on stdin" in result.output
        assert "ebx mcp stop" in result.output
        assert "super-secret-key" not in result.output

    def test_quiet_suppresses_the_banner(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("EBX_MCP_RUNTIME_DIR", str(tmp_path))
        with patch("easy_sandbox.agent.mcp.SandboxMCPServer") as server_cls:
            server_cls.return_value.run = AsyncMock()
            result = runner.invoke(cli, ["--quiet", "mcp", "start", "--api-key", "k"])
        assert result.exit_code == 0, result.output
        assert "Easy Sandbox MCP server" not in result.output

    def test_start_refuses_a_live_server(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("EBX_MCP_RUNTIME_DIR", str(tmp_path))
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            (tmp_path / "mcp-server.json").write_text(
                json.dumps({"pid": proc.pid, "mode": "stdio"})
            )
            result = runner.invoke(cli, ["mcp", "start"])
        finally:
            proc.kill()
            proc.wait(timeout=3)
        assert result.exit_code != 0
        assert "already running" in result.output

    def test_non_loopback_http_requires_a_token(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("EBX_MCP_RUNTIME_DIR", str(tmp_path))
        monkeypatch.delenv("EBX_MCP_AUTH_TOKEN", raising=False)
        result = runner.invoke(
            cli,
            ["mcp", "start", "--http", "--host", "0.0.0.0", "--auth-token", ""],
        )
        assert result.exit_code != 0
        assert "auth-token" in result.output

    def test_background_detaches_http_without_putting_secrets_on_argv(
        self, runner, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("EBX_MCP_RUNTIME_DIR", str(tmp_path))

        class _FakeProc:
            pid = 424242

            def poll(self) -> None:
                return None

        def _popen(command, **kwargs):
            assert "--http" in command
            assert "--api-key" not in command
            assert "--auth-token" not in command
            assert kwargs["env"]["E2B_API_KEY"] == "super-secret-key"
            assert kwargs["env"]["EBX_MCP_AUTH_TOKEN"] == "bearer-token"
            (tmp_path / "mcp-server.json").write_text(json.dumps({"pid": 424242, "mode": "http"}))
            return _FakeProc()

        monkeypatch.setattr("easy_sandbox.cli.commands.mcp.subprocess.Popen", _popen)
        result = runner.invoke(
            cli,
            [
                "mcp",
                "start",
                "--background",
                "--port",
                "9011",
                "--api-key",
                "super-secret-key",
                "--auth-token",
                "bearer-token",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "424242" in result.output
        assert "9011" in result.output
        assert "ebx mcp stop" in result.output
        assert "super-secret-key" not in result.output
        assert "bearer-token" not in result.output

    def test_stop_signals_the_recorded_pid(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("EBX_MCP_RUNTIME_DIR", str(tmp_path))
        (tmp_path / "mcp-server.json").write_text(json.dumps({"pid": 4242, "mode": "http"}))
        alive = {"value": True}
        sent: list[tuple[int, int]] = []

        def _alive(pid: int) -> bool:
            return pid == 4242 and alive["value"]

        def _kill(pid: int, sig: int) -> None:
            sent.append((pid, sig))
            alive["value"] = False

        monkeypatch.setattr("easy_sandbox.cli.commands.mcp._pid_alive", _alive)
        monkeypatch.setattr("easy_sandbox.cli.commands.mcp.os.kill", _kill)
        result = runner.invoke(cli, ["mcp", "stop"])
        assert result.exit_code == 0, result.output
        assert sent == [(4242, signal.SIGTERM)]
        assert "stopped" in result.output.lower()
        assert not (tmp_path / "mcp-server.json").exists()

    def test_stop_when_nothing_is_running(self, runner, monkeypatch, tmp_path):
        monkeypatch.setenv("EBX_MCP_RUNTIME_DIR", str(tmp_path))
        result = runner.invoke(cli, ["mcp", "stop"])
        assert result.exit_code == 0, result.output
        assert "not running" in result.output


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
        assert "require_auth_token" in (out / "app.py").read_text()
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
                    "--generate-token",
                ],
            )
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((out / "config.yaml").read_text())
        assert cfg["function_name"] == "my-mcp-fn"
        assert cfg["region"] == "cn-shanghai"
        assert cfg["memory"] == 1024
        assert cfg["timeout"] == 300
        assert cfg["environment_variables"]["EBX_TEMPLATE"] == "python-base"
        assert cfg["environment_variables"]["SANDBOX_TEMPLATE"] == "python-base"
        assert cfg["environment_variables"]["SANDBOX_REGION"] == "cn-shanghai"
        assert cfg["environment_variables"]["EBX_MCP_AUTH_TOKEN"]

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

    def test_deploy_empty_auth_token_file_is_refused(self, runner, tmp_path):
        """An empty token file must not produce an open or fail-closed artifact."""
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

        assert result.exit_code != 0
        assert "non-empty" in result.output
        assert not (out / "config.yaml").exists()

    def test_deploy_missing_token_is_refused(self, runner, tmp_path):
        """Omitting the Bearer token must not disable client authentication."""
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

        assert result.exit_code != 0
        assert "non-empty" in result.output
        assert not (out / "config.yaml").exists()

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
                    ["mcp", "deploy", "--output-dir", str(out), "--generate-token"],
                )
        assert result.exit_code == 0, result.output
        assert "E2B_API_KEY" in result.output

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
                    "--generate-token",
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
                    "--generate-token",
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
                    "--generate-token",
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
                    "--generate-token",
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
