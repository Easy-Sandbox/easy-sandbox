"""Tests for config CLI commands: get, set, list, reset."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from easy_sandbox.cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


class TestConfigGet:
    def test_get_default_region(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "get", "region"])

        assert result.exit_code == 0
        assert "cn-hangzhou" in result.output

    def test_get_unknown_key(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "get", "nonexistent"])

        assert result.exit_code == 2

    def test_get_json_mode(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["--json", "config", "get", "region"])

        assert result.exit_code == 0
        # JSON output
        assert "cn-hangzhou" in result.output


class TestConfigSet:
    def test_set_region(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "region", "cn-shanghai"])

        assert result.exit_code == 0
        assert "cn-shanghai" in result.output
        assert config_file.is_file()
        content = config_file.read_text()
        assert "cn-shanghai" in content

    def test_set_unknown_key(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "badkey", "value"])

        assert result.exit_code == 2

    def test_set_numeric_value(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "http_timeout", "60.0"])

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "60.0" in content

    def test_set_invalid_numeric(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "http_timeout", "not_a_number"])

        assert result.exit_code == 2

    def test_set_http2_false(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "http2", "false"])

        assert result.exit_code == 0
        # Serialised as a TOML boolean, not a quoted string.
        assert "http2 = false" in config_file.read_text()

    def test_set_http2_true_accepts_yes(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "http2", "yes"])

        assert result.exit_code == 0
        assert "http2 = true" in config_file.read_text()

    def test_set_http2_invalid(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "http2", "maybe"])

        assert result.exit_code == 2


class TestConfigList:
    def test_list_defaults(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "region" in result.output
        assert "default" in result.output

    def test_list_json_mode(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["--json", "config", "list"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "region" in data


class TestConfigApiKey:
    """Tests for api_key config (get/set via .env file)."""

    def test_set_api_key(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "api_key", "e2b_test1234abcdc1"])

        assert result.exit_code == 0
        assert "api_key" in result.output
        # Key should be masked
        assert "e2b_test1234abcdc1" not in result.output
        assert "***" in result.output
        # Env file should contain the key
        assert env_file.is_file()
        content = env_file.read_text()
        assert "E2B_API_KEY=e2b_test1234abcdc1" in content

    def test_get_api_key_from_env_file(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("E2B_API_KEY=e2b_mykey12345dc1\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "get", "api_key"])

        assert result.exit_code == 0
        # Should show masked value
        assert "***" in result.output
        # Full key should NOT be shown
        assert "e2b_mykey12345dc1" not in result.output

    def test_get_api_key_not_set(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", {}, clear=False),
        ):
            import os

            env = os.environ.copy()
            env.pop("E2B_API_KEY", None)
            with patch.dict("os.environ", env, clear=True):
                result = runner.invoke(cli, ["config", "get", "api_key"])

        assert result.exit_code == 0
        assert "not set" in result.output

    def test_list_shows_masked_api_key(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("E2B_API_KEY=e2b_testkey123dc1\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "api_key" in result.output
        assert "***" in result.output
        assert "e2b_testkey123dc1" not in result.output


class TestConfigReset:
    def test_reset_with_yes(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "cn-shanghai"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "reset", "--yes"])

        assert result.exit_code == 0
        assert "reset" in result.output.lower()
        assert not config_file.exists()

    def test_reset_no_file(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "reset", "--yes"])

        assert result.exit_code == 0
        assert "defaults" in result.output.lower()

    def test_reset_abort(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "x"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "reset"], input="n\n")

        assert result.exit_code != 0
        # File should still exist
        assert config_file.exists()
