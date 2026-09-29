"""CLI tests for the one-shot GitHub-token onboarding (task 206).

``ebx template search`` / ``ebx template install`` hit GitHub's anonymous rate
limit; in an interactive terminal the user is offered a masked
``github_token`` setup and the failed operation is retried exactly once.
Everything runs offline: the index client and the registry client are mocked.
"""

from __future__ import annotations

import shutil
import sys as _sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.cli.main import cli
from easy_sandbox.models.errors import GitHubRateLimitError
from easy_sandbox.models.template import TemplateRef
from easy_sandbox.utils.github_token import (
    FINE_GRAINED_PAT_URL,
    GITHUB_TOKEN_ENV_VAR,
    rate_limit_message,
    rate_limit_suggestion,
)
from easy_sandbox.utils.template_index import TemplateIndex, parse_index

if TYPE_CHECKING:
    from collections.abc import Iterator

    from click.testing import CliRunner

_CFG_CMD = "easy_sandbox.cli.commands.config_cmd"
_TMPL_CMD = "easy_sandbox.cli.commands.template"

INDEX_YAML = """\
schema_version: 1
templates:
  - name: qwen-code
    description: "Qwen Code agent harness"
    repo: https://github.com/Easy-Sandbox/awesome-templates
    path: qwen-code
    tags: [qwen, ai-agent]
    status: official
"""

INDEX_URL = "https://example.test/awesome-templates.yaml"


def _rate_limited() -> GitHubRateLimitError:
    """A rate-limit error shaped exactly like the one the clients raise."""
    return GitHubRateLimitError(
        rate_limit_message(operation="fetching the template index"),
        suggestion=rate_limit_suggestion(),
    )


class _FakeTTYStdin:
    def isatty(self) -> bool:
        return True


class _FakeSys:
    """``sys`` shim for TTY tests (CliRunner replaces the real ``sys.stdin``)."""

    def __init__(self) -> None:
        self.stdin = _FakeTTYStdin()

    def __getattr__(self, name: str) -> Any:
        return getattr(_sys, name)


@pytest.fixture
def index() -> TemplateIndex:
    return parse_index(INDEX_YAML, source_url=INDEX_URL)


@contextmanager
def _config_storage(tmp_path: Path) -> Iterator[None]:
    """Patch config_cmd's storage locations (config.toml / .env) onto *tmp_path*."""
    with (
        patch(f"{_CFG_CMD}._CONFIG_FILE", tmp_path / "config.toml"),
        patch(f"{_CFG_CMD}._ENV_FILE", tmp_path / ".env"),
        patch(f"{_CFG_CMD}._EBX_DIR", tmp_path),
    ):
        yield


class TestSearchOnboarding:
    """`ebx template search` rate-limit recovery."""

    def test_tty_offers_setup_and_retries_once(
        self, runner: CliRunner, index: TemplateIndex, tmp_path: Path
    ) -> None:
        mocked = AsyncMock(side_effect=[_rate_limited(), index])
        env_file = tmp_path / ".env"

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
            patch(f"{_TMPL_CMD}.sys", _FakeSys()),
            patch(f"{_CFG_CMD}._prompt_secret", return_value="ghp_pasted1234567890") as prompt,
        ):
            result = runner.invoke(cli, ["template", "search", "qwen"], input="y\n")

        assert result.exit_code == 0, result.output
        # The user saw the verified URL and the masked input was reused.
        assert FINE_GRAINED_PAT_URL in result.output
        assert prompt.call_count == 1
        # First attempt anonymous, the retry carries the freshly stored token.
        assert mocked.call_count == 2
        assert mocked.call_args_list[0].kwargs["token"] is None
        assert mocked.call_args_list[1].kwargs["token"] == "ghp_pasted1234567890"
        assert env_file.read_text() == f"{GITHUB_TOKEN_ENV_VAR}=ghp_pasted1234567890\n"
        assert "qwen-code" in result.output
        # The token itself is never echoed anywhere.
        assert "ghp_pasted1234567890" not in result.output

    def test_tty_decline_reports_the_original_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        mocked = AsyncMock(side_effect=_rate_limited())

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
            patch(f"{_TMPL_CMD}.sys", _FakeSys()),
        ):
            result = runner.invoke(cli, ["template", "search", "qwen"], input="n\n")

        assert result.exit_code == 1
        combined = result.output + (result.stderr or "")
        assert "rate limit" in combined.lower()
        assert FINE_GRAINED_PAT_URL in combined
        assert "ebx config set github_token" in combined
        # Declining must not consume a retry or store anything.
        assert mocked.call_count == 1
        assert not (tmp_path / ".env").exists()

    def test_tty_empty_token_reports_the_original_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        mocked = AsyncMock(side_effect=_rate_limited())

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
            patch(f"{_TMPL_CMD}.sys", _FakeSys()),
            patch(f"{_CFG_CMD}._prompt_secret", return_value="   "),
        ):
            result = runner.invoke(cli, ["template", "search", "qwen"], input="y\n")

        assert result.exit_code == 1
        assert mocked.call_count == 1
        assert not (tmp_path / ".env").exists()

    def test_retry_failing_again_is_not_looped(self, runner: CliRunner, tmp_path: Path) -> None:
        mocked = AsyncMock(side_effect=[_rate_limited(), _rate_limited()])

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
            patch(f"{_TMPL_CMD}.sys", _FakeSys()),
            patch(f"{_CFG_CMD}._prompt_secret", return_value="ghp_pasted1234567890"),
        ):
            result = runner.invoke(cli, ["template", "search", "qwen"], input="y\n")

        assert result.exit_code == 1
        # Exactly one automatic retry - never a loop.
        assert mocked.call_count == 2
        combined = result.output + (result.stderr or "")
        assert "rate limit" in combined.lower()

    def test_non_tty_never_prompts(self, runner: CliRunner, tmp_path: Path) -> None:
        mocked = AsyncMock(side_effect=_rate_limited())

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
        ):
            result = runner.invoke(cli, ["template", "search", "qwen"])

        assert result.exit_code == 1
        assert mocked.call_count == 1
        assert "Configure github_token now?" not in result.output
        combined = result.output + (result.stderr or "")
        # Non-TTY users are pointed at secret injection and the config command.
        assert "GITHUB_TOKEN" in combined
        assert "secret" in combined.lower()
        assert "ebx config set github_token" in combined

    def test_json_mode_never_prompts(self, runner: CliRunner, tmp_path: Path) -> None:
        mocked = AsyncMock(side_effect=_rate_limited())

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
            patch(f"{_TMPL_CMD}.sys", _FakeSys()),
        ):
            result = runner.invoke(cli, ["--json", "template", "search", "qwen"])

        assert result.exit_code == 1
        assert mocked.call_count == 1
        assert "Configure github_token now?" not in result.output

    def test_explicit_token_skips_onboarding(self, runner: CliRunner, tmp_path: Path) -> None:
        mocked = AsyncMock(side_effect=_rate_limited())

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
            patch(f"{_TMPL_CMD}.sys", _FakeSys()),
        ):
            result = runner.invoke(
                cli, ["template", "search", "qwen", "--token", "gh-explicit-token"]
            )

        assert result.exit_code == 1
        assert mocked.call_count == 1
        assert mocked.call_args_list[0].kwargs["token"] == "gh-explicit-token"
        assert "Configure github_token now?" not in result.output

    def test_stored_token_is_used(
        self, runner: CliRunner, index: TemplateIndex, tmp_path: Path
    ) -> None:
        (tmp_path / ".env").write_text(f"{GITHUB_TOKEN_ENV_VAR}=ghp_stored1234567890\n")
        mocked = AsyncMock(return_value=index)

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
        ):
            result = runner.invoke(cli, ["template", "search", "qwen"])

        assert result.exit_code == 0, result.output
        assert mocked.call_args.kwargs["token"] == "ghp_stored1234567890"
        # The token must never be echoed.
        assert "ghp_stored1234567890" not in result.output

    def test_process_env_token_wins_over_stored(
        self, runner: CliRunner, index: TemplateIndex, tmp_path: Path
    ) -> None:
        (tmp_path / ".env").write_text(f"{GITHUB_TOKEN_ENV_VAR}=ghp_stored1234567890\n")
        mocked = AsyncMock(return_value=index)

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.template_index.fetch_index", new=mocked),
            patch.dict("os.environ", {GITHUB_TOKEN_ENV_VAR: "ghp-env1234567890"}, clear=False),
        ):
            result = runner.invoke(cli, ["template", "search", "qwen"])

        assert result.exit_code == 0, result.output
        assert mocked.call_args.kwargs["token"] == "ghp-env1234567890"
        assert "ghp-env1234567890" not in result.output


class TestInstallOnboarding:
    """`ebx template install` rate-limit recovery and token plumbing."""

    @staticmethod
    def _fetched_copy(tmp_path: Path) -> Path:
        src = Path(__file__).resolve().parents[2] / "examples" / "templates" / "python-hello"
        dst = tmp_path / "fetched" / "repo"
        shutil.copytree(src, dst)
        return dst

    @staticmethod
    def _client(fetched: Path | BaseException) -> MagicMock:
        client = MagicMock()
        client.resolve = AsyncMock(
            return_value=TemplateRef(
                owner="owner", repo="repo", tag="default", registry_type="github"
            )
        )
        if isinstance(fetched, BaseException):
            client.fetch = AsyncMock(side_effect=fetched)
        else:
            client.fetch = AsyncMock(return_value=fetched)
        return client

    def test_tty_offers_setup_and_retries_once(self, runner: CliRunner, tmp_path: Path) -> None:
        fetched = self._fetched_copy(tmp_path)
        first = self._client(_rate_limited())
        second = self._client(fetched)
        env_file = tmp_path / ".env"

        with (
            _config_storage(tmp_path),
            patch(
                "easy_sandbox.utils.registry.RegistryClient", side_effect=[first, second]
            ) as ctor,
            patch(f"{_TMPL_CMD}.sys", _FakeSys()),
            patch(f"{_CFG_CMD}._prompt_secret", return_value="ghp_pasted1234567890") as prompt,
        ):
            result = runner.invoke(
                cli,
                ["template", "install", "owner/repo", "--download-only"],
                input="y\n",
            )

        assert result.exit_code == 0, result.output
        assert FINE_GRAINED_PAT_URL in result.output
        assert prompt.call_count == 1
        # First attempt anonymous, retry with the freshly stored token.
        assert ctor.call_count == 2
        assert ctor.call_args_list[0].kwargs["token"] is None
        assert ctor.call_args_list[1].kwargs["token"] == "ghp_pasted1234567890"
        assert env_file.read_text() == f"{GITHUB_TOKEN_ENV_VAR}=ghp_pasted1234567890\n"
        assert "ghp_pasted1234567890" not in result.output

    def test_stored_token_is_passed_to_the_registry_client(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        fetched = self._fetched_copy(tmp_path)
        (tmp_path / ".env").write_text(f"{GITHUB_TOKEN_ENV_VAR}=ghp_stored1234567890\n")
        client = self._client(fetched)

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.registry.RegistryClient", return_value=client) as ctor,
        ):
            result = runner.invoke(cli, ["template", "install", "owner/repo", "--download-only"])

        assert result.exit_code == 0, result.output
        assert ctor.call_args.kwargs["token"] == "ghp_stored1234567890"

    def test_non_tty_reports_error_with_onboarding_suggestion(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        first = self._client(_rate_limited())

        with (
            _config_storage(tmp_path),
            patch("easy_sandbox.utils.registry.RegistryClient", return_value=first) as ctor,
        ):
            result = runner.invoke(cli, ["template", "install", "owner/repo", "--download-only"])

        assert result.exit_code == 1
        assert ctor.call_count == 1
        assert "Configure github_token now?" not in result.output
        combined = result.output + (result.stderr or "")
        assert FINE_GRAINED_PAT_URL in combined
        assert "ebx config set github_token" in combined
