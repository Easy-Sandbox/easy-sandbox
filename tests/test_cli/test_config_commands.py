"""Tests for config CLI commands: get, set, list (plus reset removal)."""

from __future__ import annotations

import json
import os
import sys as _sys
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import click
import pytest

from easy_sandbox.cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner

_CONFIG_ENV_VARS = (
    "E2B_API_KEY",
    "SANDBOX_API_KEY",
    "E2B_API_URL",
    "E2B_DOMAIN",
    "SANDBOX_API_BASE_URL",
    "SANDBOX_REGION",
    "SANDBOX_HTTP_TIMEOUT",
    "ALICLOUD_ACCESS_KEY_ID",
    "ALICLOUD_ACCESS_KEY_SECRET",
    "AccessKey",
    "AccessSecret",
    "EBX_LLM_API_KEY",
    "EBX_QWEN_CODE_API_KEY",
    "EBX_LLM_BASE_URL",
    "EBX_LLM_MODEL",
    "BAILIAN_CODING_PLAN_API_KEY",
    "DASHSCOPE_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "GITHUB_TOKEN",
)


def _clean_env(**overrides: str) -> dict[str, str]:
    """os.environ copy with every config-affecting variable removed/tuned."""
    env = os.environ.copy()
    for var in _CONFIG_ENV_VARS:
        env.pop(var, None)
    env.update(overrides)
    return env


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


class TestConfigAlicloudCredentials:
    """Tests for Alibaba Cloud AK/SK config (stored in .env)."""

    def test_set_access_key_id_plain(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "access_key_id", "LTAI5tExampleAkId"])

        assert result.exit_code == 0
        # AK id is not sensitive: shown in full, written to .env, not config.toml.
        assert "LTAI5tExampleAkId" in result.output
        assert env_file.is_file()
        content = env_file.read_text()
        assert "ALICLOUD_ACCESS_KEY_ID=LTAI5tExampleAkId" in content
        assert not config_file.exists()

    def test_set_acr_namespace_writes_env(self, runner: CliRunner, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "acr_namespace", "serverless-sandbox"])
            listed = runner.invoke(cli, ["config", "get", "acr_namespace"])

        assert result.exit_code == 0, result.output
        assert "Set acr_namespace = serverless-sandbox" in result.output
        assert "ACR_NAMESPACE=serverless-sandbox" in env_file.read_text()
        assert listed.exit_code == 0
        assert "serverless-sandbox" in listed.output

    def test_set_access_key_secret_masked(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(
                cli, ["config", "set", "access_key_secret", "SecretValue1234567890"]
            )

        assert result.exit_code == 0
        # SK is sensitive: masked in output but written verbatim to .env.
        assert "SecretValue1234567890" not in result.output
        assert "***" in result.output
        assert env_file.is_file()
        content = env_file.read_text()
        assert "ALICLOUD_ACCESS_KEY_SECRET=SecretValue1234567890" in content

    def test_get_access_key_id_plain(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("ALICLOUD_ACCESS_KEY_ID=LTAI5tExampleAkId\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "get", "access_key_id"])

        assert result.exit_code == 0
        # Not sensitive: full value shown.
        assert "LTAI5tExampleAkId" in result.output

    def test_get_access_key_secret_masked(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("ALICLOUD_ACCESS_KEY_SECRET=SecretValue1234567890\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "get", "access_key_secret"])

        assert result.exit_code == 0
        assert "***" in result.output
        assert "SecretValue1234567890" not in result.output

    def test_get_access_key_secret_not_set(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            import os

            env = os.environ.copy()
            env.pop("ALICLOUD_ACCESS_KEY_SECRET", None)
            with patch.dict("os.environ", env, clear=True):
                result = runner.invoke(cli, ["config", "get", "access_key_secret"])

        assert result.exit_code == 0
        assert "not set" in result.output

    def test_list_masks_access_key_secret(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text(
            "ALICLOUD_ACCESS_KEY_ID=LTAI5tExampleAkId\n"
            "ALICLOUD_ACCESS_KEY_SECRET=SecretValue1234567890\n"
        )

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "access_key_id" in result.output
        assert "access_key_secret" in result.output
        # AK id shown in full, SK masked.
        assert "LTAI5tExampleAkId" in result.output
        assert "SecretValue1234567890" not in result.output
        assert "***" in result.output

    def test_set_get_round_trip_env_var_names(self, runner: CliRunner, tmp_path: Path) -> None:
        """config set must write the env-var names the transport layer reads."""
        from easy_sandbox.transport.config import _ENV_VAR_MAP

        env_vars = {ev for ev, _field, _e2b in _ENV_VAR_MAP}
        assert "ALICLOUD_ACCESS_KEY_ID" in env_vars
        assert "ALICLOUD_ACCESS_KEY_SECRET" in env_vars

        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            runner.invoke(cli, ["config", "set", "access_key_id", "Ak1"])
            runner.invoke(cli, ["config", "set", "access_key_secret", "Sk1"])

        content = env_file.read_text()
        assert "ALICLOUD_ACCESS_KEY_ID=Ak1" in content
        assert "ALICLOUD_ACCESS_KEY_SECRET=Sk1" in content


class TestConfigSetEmpty:
    """`ebx config set KEY ""` clears the stored value (empty is never stored)."""

    def test_clear_toml_value_falls_back_to_default(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "cn-shanghai"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "region", ""])

        assert result.exit_code == 0
        assert "Cleared region" in result.output
        assert "cn-hangzhou" in result.output  # falls back to the built-in default
        assert not config_file.exists()

    def test_clear_then_get_falls_back_to_default(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "cn-shanghai"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            runner.invoke(cli, ["config", "set", "region", ""])
            result = runner.invoke(cli, ["config", "get", "region"])

        assert result.exit_code == 0
        assert result.output.strip() == "cn-hangzhou"

    def test_clear_value_without_default_becomes_not_set(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_model = "qwen-plus"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "llm_model", ""])

        assert result.exit_code == 0
        assert "Cleared llm_model" in result.output
        assert "falls back to default: qwen3-coder-plus" in result.output

    def test_clear_credential_removes_env_entry(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("E2B_API_KEY=sk-test-abcdef123456\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "api_key", ""])
            get_result = runner.invoke(cli, ["config", "get", "api_key"])

        assert result.exit_code == 0
        assert "Cleared sandbox_api_key" in result.output
        assert "sk-test-abcdef123456" not in result.output
        # The key truly returns to not-set: no empty-string credential remains.
        assert "not set" in get_result.output
        assert not env_file.exists()

    def test_clear_keeps_other_env_entries(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("E2B_API_KEY=sk-test-abcdef123456\nGITHUB_TOKEN=gh-token-12345678\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "api_key", ""])

        assert result.exit_code == 0
        content = env_file.read_text()
        assert "E2B_API_KEY" not in content
        assert "GITHUB_TOKEN=gh-token-12345678" in content

    def test_clear_without_stored_value(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "region", ""])

        assert result.exit_code == 0
        assert "No stored value for region" in result.output

    def test_clear_reports_env_override_without_value(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "cn-shanghai"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(SANDBOX_REGION="cn-zhangjiakou"), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "region", ""])

        assert result.exit_code == 0
        assert "Cleared region" in result.output
        assert "SANDBOX_REGION still overrides" in result.output
        # The env value itself must never be printed.
        assert "cn-zhangjiakou" not in result.output


class TestConfigResetRemoved:
    def test_reset_subcommand_is_gone(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "reset", "--yes"])

        assert result.exit_code == 2
        assert "No such command" in result.output


class TestConfigDelete:
    """``ebx config delete KEY`` removes one stored value."""

    def test_delete_removes_one_credential_and_keeps_the_rest(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("E2B_API_KEY=sk-test-abcdef123456\nACR_NAMESPACE=my-ns\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "delete", "sandbox_api_key"])
            remaining = runner.invoke(cli, ["config", "get", "acr_namespace"])

        assert result.exit_code == 0, result.output
        assert "Cleared sandbox_api_key" in result.output
        assert "sk-test-abcdef123456" not in result.output
        assert "E2B_API_KEY" not in env_file.read_text()
        assert "ACR_NAMESPACE=my-ns" in env_file.read_text()
        assert "my-ns" in remaining.output

    def test_delete_region_falls_back_to_the_default(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "cn-shanghai"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "delete", "region"])
            got = runner.invoke(cli, ["config", "get", "region"])

        assert result.exit_code == 0, result.output
        assert "Cleared region" in result.output
        assert "cn-hangzhou" in got.output
        # The file held only the region, so removing it deletes the file.
        assert not config_file.exists()

    def test_delete_unknown_key_is_rejected(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "delete", "not_a_key"])

        assert result.exit_code == 2
        assert "Unknown config key" in result.output

    def test_delete_reports_an_env_override_without_its_value(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "cn-shanghai"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(SANDBOX_REGION="cn-zhangjiakou"), clear=True),
        ):
            result = runner.invoke(cli, ["config", "delete", "region"])

        assert result.exit_code == 0, result.output
        assert "SANDBOX_REGION still overrides" in result.output
        assert "cn-zhangjiakou" not in result.output

    def test_delete_removes_one_shortcut(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[shortcuts]\nps = "sandbox process list"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "delete", "shortcuts.ps"])

        assert result.exit_code == 0, result.output
        assert "Removed shortcut 'ps'" in result.output
        assert "ps" not in config_file.read_text()


class TestConfigListSources:
    """config list shows effective values and their sources; secrets masked."""

    def test_list_groups_keys_by_function(self, runner: CliRunner, tmp_path: Path) -> None:
        """config list renders the functional groups in a stable order."""
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        titles = [ln for ln in result.output.splitlines() if ln.startswith("── ")]
        expected_titles = [
            "Sandbox authentication",
            "Alibaba Cloud credentials",
            "Connection",
            "LLM",
            "Integrations",
            "Shortcuts",
        ]
        assert [t[3:].rstrip("─").strip() for t in titles] == expected_titles
        # Every group header renders as a full 64-character rule.
        assert all(len(t) == 64 for t in titles)
        # No qwen_code_* keys remain on the config surface.
        assert "qwen_code_" not in result.output
        # Grouped key order: connection keys follow the cloud credentials.
        lines = result.output.splitlines()
        region_idx = next(i for i, ln in enumerate(lines) if ln.startswith("region"))
        domain_idx = next(i for i, ln in enumerate(lines) if ln.startswith("domain"))
        assert region_idx < domain_idx

    def test_list_shows_not_set_for_keys_without_default(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        line = next(ln for ln in result.output.splitlines() if ln.startswith("llm_api_key"))
        assert "(not set)" in line
        for key, default in (
            ("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ("llm_model", "qwen3-coder-plus"),
        ):
            line = next(ln for ln in result.output.splitlines() if ln.startswith(key))
            assert f"{default} (default)" in line

    def test_list_marks_env_source(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch.dict("os.environ", _clean_env(SANDBOX_REGION="cn-shanghai"), clear=True),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        line = next(ln for ln in result.output.splitlines() if ln.startswith("region"))
        assert "cn-shanghai (env)" in line

    def test_list_masks_secret_with_user_source(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("E2B_API_KEY=sk-test-abcdef123456\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        line = next(ln for ln in result.output.splitlines() if ln.startswith("sandbox_api_key"))
        assert "***" in line
        assert "(user)" in line
        assert "sk-test-abcdef123456" not in result.output


class TestConfigGithubToken:
    """github_token: env-stored, masked, clearable, mapped to GITHUB_TOKEN (206)."""

    def test_set_writes_env_file_and_masks_output(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "github_token", "ghp_test1234567890"])

        assert result.exit_code == 0
        assert "github_token" in result.output
        # Sensitive: masked in output, stored verbatim under the env-var name.
        assert "ghp_test1234567890" not in result.output
        assert "***" in result.output
        assert env_file.read_text() == "GITHUB_TOKEN=ghp_test1234567890\n"
        assert not config_file.exists()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_set_restricts_env_file_permissions(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "github_token", "ghp_test1234567890"])

        assert result.exit_code == 0
        assert os.stat(env_file).st_mode & 0o777 == 0o600

    def test_get_masks_stored_token(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("GITHUB_TOKEN=ghp_stored1234567890\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "get", "github_token"])

        assert result.exit_code == 0
        assert "***" in result.output
        assert "ghp_stored1234567890" not in result.output

    def test_get_prefers_process_env_and_masks_both(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("GITHUB_TOKEN=ghp_stored1234567890\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(GITHUB_TOKEN="ghp_placeholder_token"), clear=True),
        ):
            result = runner.invoke(cli, ["config", "get", "github_token"])

        assert result.exit_code == 0
        # The process environment wins; neither value is ever printed.
        assert "ghp_placeholder_token" not in result.output
        assert "ghp_stored1234567890" not in result.output
        assert "***" in result.output

    def test_get_not_set(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "get", "github_token"])

        assert result.exit_code == 0
        assert "not set" in result.output

    def test_list_masks_github_token(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("GITHUB_TOKEN=ghp_stored1234567890\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        line = next(ln for ln in result.output.splitlines() if ln.startswith("github_token"))
        assert "***" in line
        assert "(user)" in line
        assert "ghp_stored1234567890" not in result.output

    def test_clear_removes_stored_token_but_keeps_others(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("GITHUB_TOKEN=ghp_stored1234567890\nE2B_API_KEY=sk-test-abcdef123456\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "github_token", ""])
            get_result = runner.invoke(cli, ["config", "get", "github_token"])

        assert result.exit_code == 0
        assert "Cleared github_token" in result.output
        assert "ghp_stored1234567890" not in result.output
        assert "not set" in get_result.output
        content = env_file.read_text()
        assert "GITHUB_TOKEN" not in content
        assert "E2B_API_KEY=sk-test-abcdef123456" in content

    def test_clear_reports_env_override_without_value(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"
        env_file.write_text("GITHUB_TOKEN=ghp_stored1234567890\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch.dict("os.environ", _clean_env(GITHUB_TOKEN="ghp_placeholder_token"), clear=True),
        ):
            result = runner.invoke(cli, ["config", "set", "github_token", ""])

        assert result.exit_code == 0
        assert "GITHUB_TOKEN still overrides" in result.output
        assert "ghp_placeholder_token" not in result.output


class TestResolveGithubToken:
    """Precedence: --token > process GITHUB_TOKEN > ./.env > stored github_token."""

    @staticmethod
    def _patches(tmp_path: Path, *, stored: str | None = None, env: str | None = None):
        """Patch the .env file (optionally pre-seeded) and the process env."""
        from contextlib import ExitStack

        stack = ExitStack()
        env_file = tmp_path / ".env"
        if stored is not None:
            env_file.write_text(f"GITHUB_TOKEN={stored}\n")
        stack.enter_context(patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path))
        stack.enter_context(patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file))
        overrides = _clean_env(GITHUB_TOKEN=env) if env is not None else _clean_env()
        stack.enter_context(patch.dict("os.environ", overrides, clear=True))
        return stack

    def test_explicit_flag_beats_env_and_stored(self, tmp_path: Path) -> None:
        from easy_sandbox.cli.commands.config_cmd import resolve_github_token

        with self._patches(tmp_path, stored="stored-token", env="env-token"):
            assert resolve_github_token("explicit-token") == "explicit-token"

    def test_process_env_beats_stored(self, tmp_path: Path) -> None:
        from easy_sandbox.cli.commands.config_cmd import resolve_github_token

        with self._patches(tmp_path, stored="stored-token", env="env-token"):
            assert resolve_github_token() == "env-token"

    def test_stored_token_is_used_as_last_resort(self, tmp_path: Path) -> None:
        from easy_sandbox.cli.commands.config_cmd import resolve_github_token

        with self._patches(tmp_path, stored="stored-token"):
            assert resolve_github_token() == "stored-token"

    def test_no_token_returns_none(self, tmp_path: Path) -> None:
        from easy_sandbox.cli.commands.config_cmd import resolve_github_token

        with self._patches(tmp_path):
            assert resolve_github_token(None) is None

    def test_blank_values_are_ignored(self, tmp_path: Path) -> None:
        from easy_sandbox.cli.commands.config_cmd import resolve_github_token

        with self._patches(tmp_path, stored="stored-token", env="   "):
            # A whitespace-only --token must not shadow the stored token.
            assert resolve_github_token("  ") == "stored-token"
            # …and the returned value is stripped.
            assert resolve_github_token(" explicit ") == "explicit"


class _FakeTTYStdin:
    def isatty(self) -> bool:
        return True


class _FakeSys:
    """``sys`` shim for TTY tests.

    ``CliRunner`` replaces the real ``sys.stdin`` while a command runs, so TTY
    detection has to be faked at the module-reference level instead.
    """

    def __init__(self) -> None:
        self.stdin = _FakeTTYStdin()

    def __getattr__(self, name: str) -> Any:
        return getattr(_sys, name)


class TestConfigSetMissingValue:
    """``ebx config set KEY`` without VALUE: masked prompt in a TTY, exit 2 otherwise."""

    def test_non_tty_exits_2_with_ci_secret_hint(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "github_token"])

        assert result.exit_code == 2
        assert "Missing VALUE" in result.output
        stderr = result.stderr or ""
        assert "ebx config set github_token <VALUE>" in stderr
        # Env-stored keys point CI users at secret injection.
        assert "GITHUB_TOKEN" in stderr
        assert "secret" in stderr.lower()
        assert not (tmp_path / ".env").exists()

    def test_non_tty_plain_key_omits_secret_hint(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "region"])

        assert result.exit_code == 2
        stderr = result.stderr or ""
        assert "ebx config set region <VALUE>" in stderr
        assert "secret" not in stderr.lower()

    def test_tty_sensitive_key_reuses_masked_prompt(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
            patch(
                "easy_sandbox.cli.commands.config_cmd._prompt_secret",
                return_value="ghp_masked1234567890",
            ) as mock_prompt,
        ):
            result = runner.invoke(cli, ["config", "set", "github_token"])

        assert result.exit_code == 0, result.output
        # The task-201 asterisk input is reused, not re-implemented.
        assert mock_prompt.call_count == 1
        assert env_file.read_text() == "GITHUB_TOKEN=ghp_masked1234567890\n"
        assert "ghp_masked1234567890" not in result.output
        assert "***" in result.output

    def test_tty_empty_input_changes_nothing(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
            patch("easy_sandbox.cli.commands.config_cmd._prompt_secret", return_value="   "),
        ):
            result = runner.invoke(cli, ["config", "set", "github_token"])

        assert result.exit_code == 0, result.output
        # Enter means "cancel", never "clear" - clearing needs the explicit "".
        assert "No value entered" in result.output
        assert not (tmp_path / ".env").exists()

    def test_tty_abort_exits_without_writing(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
            patch(
                "easy_sandbox.cli.commands.config_cmd._prompt_secret",
                side_effect=click.Abort(),
            ),
        ):
            result = runner.invoke(cli, ["config", "set", "github_token"])

        assert result.exit_code == 1
        assert not (tmp_path / ".env").exists()

    def test_tty_plain_key_prompts_visibly(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
        ):
            result = runner.invoke(cli, ["config", "set", "region"], input="cn-shanghai\n")

        assert result.exit_code == 0, result.output
        assert 'region = "cn-shanghai"' in config_file.read_text()
        assert "cn-shanghai" in result.output
