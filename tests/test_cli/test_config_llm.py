"""Tests for LLM-related config commands: llm_api_key, llm_model, llm_base_url."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli


class TestConfigLLMApiKey:
    """Tests for llm_api_key config set/get."""

    def test_set_llm_api_key(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
            result = runner.invoke(
                cli, ["config", "set", "llm_api_key", "sk-test123"]
            )

        assert result.exit_code == 0
        assert "llm_api_key" in result.output
        # Value should be masked in output
        assert "sk-test123" not in result.output
        assert "***" in result.output
        # TOML file should contain the key
        content = config_file.read_text()
        assert "llm_api_key" in content
        assert "sk-test123" in content

    def test_get_llm_api_key_masked(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_api_key = "sk-test123abcdef"\n')

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
            result = runner.invoke(cli, ["config", "get", "llm_api_key"])

        assert result.exit_code == 0
        # Should show masked value
        assert "***" in result.output
        # Full key should NOT be shown
        assert "sk-test123abcdef" not in result.output

    def test_get_llm_api_key_not_set(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
            result = runner.invoke(cli, ["config", "get", "llm_api_key"])

        assert result.exit_code == 0


class TestConfigLLMModel:
    """Tests for llm_model config set/get."""

    def test_set_llm_model(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
            result = runner.invoke(
                cli, ["config", "set", "llm_model", "qwen-plus"]
            )

        assert result.exit_code == 0
        assert "qwen-plus" in result.output
        content = config_file.read_text()
        assert "qwen-plus" in content

    def test_get_llm_model(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[transport]\nllm_model = "qwen-plus"\n')

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
            result = runner.invoke(cli, ["config", "get", "llm_model"])

        assert result.exit_code == 0
        assert "qwen-plus" in result.output


class TestConfigLLMBaseURL:
    """Tests for llm_base_url config set/get."""

    def test_set_llm_base_url(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
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

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
            result = runner.invoke(cli, ["config", "get", "llm_base_url"])

        assert result.exit_code == 0
        assert "https://example.com/v1" in result.output


class TestConfigListLLM:
    """Tests for `config list` including LLM keys."""

    def test_list_includes_llm_keys(self, runner: CliRunner, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        assert "llm_api_key" in result.output
        assert "llm_model" in result.output
        assert "llm_base_url" in result.output

    def test_list_shows_user_llm_values(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[transport]\n'
            'llm_api_key = "sk-test999abc"\n'
            'llm_model = "qwen-plus"\n'
            'llm_base_url = "https://example.com/v1"\n'
        )

        with patch("easy_sandbox.cli.commands.config_cmd._CONFIG_FILE", config_file), \
             patch("easy_sandbox.cli.commands.config_cmd._EBX_DIR", tmp_path):
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
