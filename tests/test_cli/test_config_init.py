"""Tests for the `ebx config init` guided wizard.

Covers the TTY wizard (asterisk-masked / fallback secret input, stored
locations) and the non-interactive fallback that must never block in CI.
"""

from __future__ import annotations

import sys as _sys
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from easy_sandbox.cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


def _stderr(result: Any) -> str:
    """Return result.stderr safely across Click versions."""
    try:
        return result.stderr or ""
    except ValueError:
        return ""


class _FakeTTYStdin:
    def isatty(self) -> bool:
        return True


class _FakeSys:
    """``sys`` shim for config_cmd TTY tests.

    ``CliRunner`` replaces the real ``sys.stdin`` while a command runs, so
    TTY detection has to be faked at the module-reference level instead.
    """

    def __init__(self) -> None:
        self.stdin = _FakeTTYStdin()

    def __getattr__(self, name: str) -> Any:
        return getattr(_sys, name)


class TestConfigInitNonInteractive:
    def test_non_tty_prints_commands_without_blocking(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "init"])

        assert result.exit_code == 0
        assert "Non-interactive setup" in result.output
        assert "ebx config set sandbox_api_key" in result.output
        assert "ebx config set region" in result.output
        assert "ebx config set llm_api_key" in result.output
        assert "ebx config set acr_namespace" in result.output
        assert "ebx config set access_key_id" in result.output
        assert "ebx config set access_key_secret" in result.output
        assert "qwen_code_" not in result.output
        # Nothing may be written without explicit user input.
        assert not (tmp_path / ".env").exists()

    def test_yes_flag_behaves_like_non_tty(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "init", "--yes"])

        assert result.exit_code == 0
        assert "Non-interactive setup" in result.output
        assert not (tmp_path / ".env").exists()


class TestConfigInitWizard:
    def test_wizard_stores_platform_and_qwen_keys(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
        ):
            result = runner.invoke(
                cli,
                ["config", "init"],
                input="sk-platform\ncn-shanghai\nsk-qwen\nmy-ns\nLTAIexampleAk\nSecretValue123456\n",
            )

        assert result.exit_code == 0, result.output
        env_content = env_file.read_text(encoding="utf-8")
        assert "E2B_API_KEY=sk-platform" in env_content
        assert "EBX_LLM_API_KEY=sk-qwen" in env_content
        assert "ACR_NAMESPACE=my-ns" in env_content
        assert "ALICLOUD_ACCESS_KEY_ID=LTAIexampleAk" in env_content
        assert "ALICLOUD_ACCESS_KEY_SECRET=SecretValue123456" in env_content
        assert "Set acr_namespace = my-ns" in result.output
        assert "Stored access_key_id" in result.output
        assert "Stored access_key_secret" in result.output
        assert "SecretValue123456" not in result.output
        assert "EBX_QWEN_CODE_API_KEY" not in env_content
        config_content = config_file.read_text(encoding="utf-8")
        assert 'region = "cn-shanghai"' in config_content
        assert "Stored sandbox_api_key" in result.output
        assert "Stored llm_api_key" in result.output
        assert "Configuration complete" in result.output

    def test_sensitive_values_are_not_echoed(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
        ):
            result = runner.invoke(
                cli,
                ["config", "init"],
                input="sk-platform-secret\n\nsk-qwen-secret\n\n\nsk-cloud-secret\n",
            )

        assert result.exit_code == 0, result.output
        assert "sk-platform-secret" not in result.output
        assert "sk-qwen-secret" not in result.output
        assert "sk-cloud-secret" not in result.output

    def test_empty_inputs_skip_secrets_and_keep_default_region(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
        ):
            result = runner.invoke(cli, ["config", "init"], input="\n\n\n\n\n\n")

        assert result.exit_code == 0, result.output
        # No secrets were typed → the .env file must not be created.
        assert not env_file.exists()
        # The region prompt accepts its default and persists it.
        assert 'region = "cn-hangzhou"' in config_file.read_text(encoding="utf-8")

    def test_existing_region_becomes_default(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nregion = "cn-shanghai"\n', encoding="utf-8")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
        ):
            result = runner.invoke(cli, ["config", "init"], input="\n\n\n\n\n\n")

        assert result.exit_code == 0, result.output
        assert 'region = "cn-shanghai"' in config_file.read_text(encoding="utf-8")


class TestConfigInitMaskedInput:
    """Secret prompts: asterisk masking when supported, safe fallback otherwise."""

    def test_fallback_notice_when_masking_unsupported(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """_FakeSys reports a TTY but has no fileno() → no-echo fallback + notice."""
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
        ):
            result = runner.invoke(cli, ["config", "init"], input="sk-a\n\nsk-b\n\n\n\n")

        assert result.exit_code == 0, result.output
        assert "asterisk masking is not supported" in _stderr(result)

    def test_init_uses_masked_prompt_when_supported(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """The wizard must route the three secrets through _prompt_secret."""
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd.sys", _FakeSys()),
            patch(
                "easy_sandbox.cli.commands.config_cmd._prompt_secret",
                side_effect=["sk-platform", "sk-qwen", "sk-cloud"],
            ) as mock_prompt,
        ):
            result = runner.invoke(cli, ["config", "init"], input="\nmy-ns\nLTAIexample\n")

        assert result.exit_code == 0, result.output
        assert mock_prompt.call_count == 3
        env_content = env_file.read_text(encoding="utf-8")
        assert "E2B_API_KEY=sk-platform" in env_content
        assert "EBX_LLM_API_KEY=sk-qwen" in env_content
        assert "ACR_NAMESPACE=my-ns" in env_content
        assert "ALICLOUD_ACCESS_KEY_ID=LTAIexample" in env_content
        assert "ALICLOUD_ACCESS_KEY_SECRET=sk-cloud" in env_content


class TestLegacyQwenConfig:
    """Older qwen_code_* storage is read as the unified llm_* profile."""

    def test_legacy_qwen_key_is_listed_as_llm_api_key(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("EBX_QWEN_CODE_API_KEY=abcdef123456\n", encoding="utf-8")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0, result.output
        assert "abcdef123456" not in result.output
        assert "qwen_code_" not in result.output
        line = next(ln for ln in result.output.splitlines() if ln.startswith("llm_api_key"))
        assert "abc***456" in line
        assert "(user)" in line

    def test_llm_api_key_wins_over_legacy_qwen_key(self, runner: CliRunner, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "EBX_LLM_API_KEY=sk-newkey123456\nEBX_QWEN_CODE_API_KEY=abcdef123456\n",
            encoding="utf-8",
        )

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "get", "llm_api_key"])

        assert result.exit_code == 0, result.output
        assert "abcdef123456" not in result.output
        assert "sk-***456" in result.output or "***" in result.output
        assert "sk-newkey123456" not in result.output

    def test_legacy_endpoint_is_listed_as_llm_base_url(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[transport]\nqwen_code_base_url = "https://example.test/v1"\n'
            'qwen_code_model = "qwen3.8-plus"\n',
            encoding="utf-8",
        )

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0, result.output
        assert "qwen_code_" not in result.output
        base = next(ln for ln in result.output.splitlines() if ln.startswith("llm_base_url"))
        model = next(ln for ln in result.output.splitlines() if ln.startswith("llm_model"))
        assert "https://example.test/v1 (user)" in base
        assert "qwen3.8-plus (user)" in model

    def test_removed_qwen_key_points_at_llm_api_key(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "qwen_code_api_key", "sk-old"])

        assert result.exit_code == 2
        assert "was removed" in result.output
        assert "llm_api_key" in result.output
        assert not (tmp_path / ".env").exists()
