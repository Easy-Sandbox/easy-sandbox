"""Tests for LLM-related config commands: llm_api_key, llm_model, llm_base_url."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from easy_sandbox.cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from click.testing import CliRunner


class TestConfigLLMApiKey:
    """Tests for llm_api_key config set/get (secure ~/.ebx/.env storage)."""

    def test_set_llm_api_key(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "llm_api_key", "sk-test123"])

        assert result.exit_code == 0
        assert "llm_api_key" in result.output
        # Value should be masked in output
        assert "sk-test123" not in result.output
        assert "***" in result.output
        # The key is stored in ~/.ebx/.env as EBX_LLM_API_KEY (never TOML).
        assert env_file.read_text() == "EBX_LLM_API_KEY=sk-test123\n"
        assert not config_file.exists()
        # The env file holds credentials, so it stays owner-only.
        assert env_file.stat().st_mode & 0o777 == 0o600

    def test_set_migrates_legacy_toml_copy(self, runner: CliRunner, tmp_path: Path) -> None:
        """Re-setting llm_api_key removes the legacy plaintext TOML copy."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_api_key = "sk-placeholder-old"\n')
        env_file = tmp_path / ".env"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "llm_api_key", "sk-new-secret"])

        assert result.exit_code == 0
        assert env_file.read_text() == "EBX_LLM_API_KEY=sk-new-secret\n"
        # The old copy never resurrects from config.toml. An empty file is removed.
        assert not config_file.exists()

    def test_get_reads_legacy_toml_copy(self, runner: CliRunner, tmp_path: Path) -> None:
        """A pre-migration llm_api_key in config.toml is still readable."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_api_key = "sk-placeholder-legacy456"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
        ):
            result = runner.invoke(cli, ["config", "get", "llm_api_key"])

        assert result.exit_code == 0
        assert "sk-placeholder-legacy456" not in result.output
        assert "***" in result.output

    def test_secure_storage_wins_over_legacy_toml(self, runner: CliRunner, tmp_path: Path) -> None:
        """~/.ebx/.env (and the process env) outrank the legacy TOML copy."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_api_key = "sk-placeholder-legacy456"\n')
        env_file = tmp_path / ".env"
        env_file.write_text("EBX_LLM_API_KEY=sk-secure-key-654321\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["--json", "config", "get", "llm_api_key"])

        assert result.exit_code == 0
        # The masked value derives from the secure copy, not the legacy one.
        assert "sk-***321" in result.output
        assert "456" not in result.output

    def test_clear_removes_both_locations(self, runner: CliRunner, tmp_path: Path) -> None:
        """`config set llm_api_key ""` clears .env AND the legacy TOML copy."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[transport]\nllm_api_key = "sk-placeholder-legacy456"\nregion = "cn-shanghai"\n'
        )
        env_file = tmp_path / ".env"
        env_file.write_text("EBX_LLM_API_KEY=sk-secure-key-654321\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "set", "llm_api_key", ""])

        assert result.exit_code == 0
        assert "Cleared llm_api_key" in result.output
        assert not env_file.exists()
        # The TOML copy is gone too, while unrelated keys survive.
        assert "llm_api_key" not in config_file.read_text()
        assert 'region = "cn-shanghai"' in config_file.read_text()

    def test_get_llm_api_key_masked(self, runner: CliRunner, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("EBX_LLM_API_KEY=sk-test123abcdef\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "get", "llm_api_key"])

        assert result.exit_code == 0
        # Should show masked value
        assert "***" in result.output
        # Full key should NOT be shown
        assert "sk-test123abcdef" not in result.output

    def test_get_llm_api_key_not_set(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
        ):
            result = runner.invoke(cli, ["config", "get", "llm_api_key"])

        assert result.exit_code == 0


class TestConfigLLMModel:
    """Tests for llm_model config set/get."""

    def test_set_llm_model(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "llm_model", "qwen-plus"])

        assert result.exit_code == 0
        assert "qwen-plus" in result.output
        content = config_file.read_text()
        assert "qwen-plus" in content

    def test_get_llm_model(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_model = "qwen-plus"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "get", "llm_model"])

        assert result.exit_code == 0
        assert "qwen-plus" in result.output


class TestConfigLLMBaseURL:
    """Tests for llm_base_url config set/get."""

    def test_set_llm_base_url(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(
                cli,
                ["config", "set", "llm_base_url", "https://example.com/v1"],
            )

        assert result.exit_code == 0
        assert "https://example.com/v1" in result.output
        content = config_file.read_text()
        assert "https://example.com/v1" in content

    def test_get_llm_base_url(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_base_url = "https://example.com/v1"\n')

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "get", "llm_base_url"])

        assert result.exit_code == 0
        assert "https://example.com/v1" in result.output


class TestConfigListLLM:
    """Tests for `config list` including LLM keys."""

    def test_list_includes_llm_keys(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "llm_api_key" in result.output
        assert "llm_model" in result.output
        assert "llm_base_url" in result.output

    def test_list_shows_user_llm_values(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[transport]\n"
            'llm_api_key = "sk-test999abc"\n'
            'llm_model = "qwen-plus"\n'
            'llm_base_url = "https://example.com/v1"\n'
        )

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        # llm_api_key should be masked
        assert "***" in result.output
        assert "sk-test999abc" not in result.output
        # llm_model and llm_base_url should be visible
        assert "qwen-plus" in result.output
        assert "https://example.com/v1" in result.output
        # All should show "(user)" label
        assert "user" in result.output


class TestCredentialPriority:
    """Process environment wins over ~/.ebx; the stored value is the fallback."""

    def test_env_api_key_beats_stored_file(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("EBX_LLM_API_KEY=sk-stored-key-aaa111\n")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-env-key-bbb222")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "sk-***222 (env)" in result.output
        assert "sk-***111" not in result.output

    def test_stored_api_key_when_env_unset(self, runner: CliRunner, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("EBX_LLM_API_KEY=sk-stored-key-aaa111\n")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", tmp_path / "config.toml"),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", env_file),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "sk-***111 (user)" in result.output

    def test_env_base_url_and_model_beat_stored(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[transport]\nllm_base_url = "https://stored.example/v1"\nllm_model = "stored-model"\n'
        )
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
        monkeypatch.setenv("OPENAI_MODEL", "env-model")

        with (
            patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file),
            patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path),
            patch("easy_sandbox.cli.commands.config_cmd._ENV_FILE", tmp_path / ".env"),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "https://env.example/v1 (env)" in result.output
        assert "env-model (env)" in result.output
        assert "stored.example" not in result.output
        assert "stored-model" not in result.output
