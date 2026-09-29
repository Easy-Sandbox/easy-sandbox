"""CLI integration tests for the remote template index.

``ebx template search`` queries the index and ``ebx template install <name>``
resolves bare, non-builtin names through it.  Both commands are exercised
fully offline: ``easy_sandbox.utils.template_index.fetch_index`` is mocked, so
nothing here touches the network (or GitHub rate limits).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.cli.main import cli
from easy_sandbox.models.template import TemplateRef
from easy_sandbox.utils.template_index import TemplateIndex, parse_index

if TYPE_CHECKING:
    from click.testing import CliRunner

INDEX_YAML = """\
schema_version: 1
templates:
  - name: qwen-code
    description: "Qwen Code agent harness"
    repo: https://github.com/Easy-Sandbox/awesome-templates
    path: qwen-code
    tags: [qwen, ai-agent]
    author: Easy-Sandbox
    capabilities: [shell, files, code]
    status: official
  - name: node-web
    description: "Node.js web service"
    repo: https://github.com/Easy-Sandbox/awesome-templates
    path: node-web
    tags: [nodejs, web, deploy]
    author: Easy-Sandbox
    capabilities: [shell, files, code]
    status: official
"""

INDEX_URL = "https://example.test/awesome-templates.yaml"
SOURCE_OF_TRUTH_REPO = "Easy-Sandbox/awesome-templates"


@pytest.fixture
def index() -> TemplateIndex:
    return parse_index(INDEX_YAML, source_url=INDEX_URL)


def _patch_index(index: TemplateIndex) -> Any:
    return patch(
        "easy_sandbox.utils.template_index.fetch_index",
        new=AsyncMock(return_value=index),
    )


def _template_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / "templates" / "python-hello"


def _fetched_copy(tmp_path: Path) -> Path:
    """Copy the python-hello fixture so ``install`` can load a real template."""
    dst = tmp_path / "fetched" / "qwen-code"
    shutil.copytree(_template_dir(), dst)
    return dst


def _json_entries(output: str) -> list[dict[str, Any]]:
    """Collect every JSON object/array element from JSON-mode CLI output."""
    values: list[Any] = []
    decoder = json.JSONDecoder()
    idx = 0
    text = output.strip()
    while idx < len(text):
        while idx < len(text) and text[idx] in " \n\r\t":
            idx += 1
        if idx >= len(text):
            break
        value, idx = decoder.raw_decode(text, idx)
        values.append(value)
    entries: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, list):
            entries.extend(v for v in value if isinstance(v, dict))
        elif isinstance(value, dict):
            entries.append(value)
    return entries


# =========================================================================
# ebx template search
# =========================================================================


class TestSearchCommand:
    """``ebx template search`` reads the remote index (mocked)."""

    def test_search_lists_matching_entries(self, runner: CliRunner, index: TemplateIndex) -> None:
        with _patch_index(index):
            result = runner.invoke(cli, ["template", "search", "qwen"])

        assert result.exit_code == 0, result.output
        assert "qwen-code" in result.output
        assert "node-web" not in result.output

    def test_search_matches_tags_and_descriptions(
        self, runner: CliRunner, index: TemplateIndex
    ) -> None:
        with _patch_index(index):
            result = runner.invoke(cli, ["template", "search", "web"])

        assert result.exit_code == 0, result.output
        assert "node-web" in result.output
        assert "qwen-code" not in result.output

    def test_search_tag_filter(self, runner: CliRunner, index: TemplateIndex) -> None:
        with _patch_index(index):
            result = runner.invoke(cli, ["template", "search", "ai-agent", "--tag", "qwen"])

        assert result.exit_code == 0, result.output
        assert "qwen-code" in result.output

    def test_search_status_filter(self, runner: CliRunner, index: TemplateIndex) -> None:
        with _patch_index(index):
            result = runner.invoke(cli, ["template", "search", "qwen", "--status", "community"])

        assert result.exit_code == 0, result.output
        assert "No templates matching" in result.output

    def test_search_no_match_message(self, runner: CliRunner, index: TemplateIndex) -> None:
        with _patch_index(index):
            result = runner.invoke(cli, ["template", "search", "zzz-not-there"])

        assert result.exit_code == 0, result.output
        assert "No templates matching" in result.output

    def test_search_prints_install_hint_with_index_source(
        self, runner: CliRunner, index: TemplateIndex
    ) -> None:
        with _patch_index(index):
            result = runner.invoke(cli, ["template", "search", "qwen"])

        assert result.exit_code == 0, result.output
        assert "ebx template install" in result.output
        assert INDEX_URL in result.output

    def test_search_json_output(self, runner: CliRunner, index: TemplateIndex) -> None:
        with _patch_index(index):
            result = runner.invoke(cli, ["-j", "template", "search", "qwen"])

        assert result.exit_code == 0, result.output
        entries = _json_entries(result.output)
        names = [e.get("name") for e in entries if e.get("name")]
        assert "qwen-code" in names

    def test_search_forwards_index_url_token_and_refresh(
        self, runner: CliRunner, index: TemplateIndex
    ) -> None:
        mocked = AsyncMock(return_value=index)
        with patch("easy_sandbox.utils.template_index.fetch_index", new=mocked):
            result = runner.invoke(
                cli,
                [
                    "template",
                    "search",
                    "qwen",
                    "--index-url",
                    "https://mirror.test/idx.yaml",
                    "--token",
                    "gh-token-123",
                    "--refresh",
                ],
            )

        assert result.exit_code == 0, result.output
        args, kwargs = mocked.call_args
        assert args[0] == "https://mirror.test/idx.yaml"
        assert kwargs["token"] == "gh-token-123"
        assert kwargs["force"] is True

    def test_search_index_url_env_override(
        self,
        runner: CliRunner,
        index: TemplateIndex,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EBX_TEMPLATE_INDEX_URL", "https://mirror.test/from-env.yaml")
        mocked = AsyncMock(return_value=index)
        with patch("easy_sandbox.utils.template_index.fetch_index", new=mocked):
            result = runner.invoke(cli, ["template", "search", "qwen"])

        assert result.exit_code == 0, result.output
        args, _ = mocked.call_args
        assert args[0] == "https://mirror.test/from-env.yaml"

    def test_search_shows_stale_cache_notice(self, runner: CliRunner, index: TemplateIndex) -> None:
        index.stale = True
        index.notice = "GitHub rate limit exceeded while fetching the template index."

        with _patch_index(index):
            result = runner.invoke(cli, ["template", "search", "qwen"])

        assert result.exit_code == 0, result.output
        combined = result.output + (result.stderr or "")
        assert "rate limit" in combined.lower()


# =========================================================================
# ebx template install <bare-name> → index resolution
# =========================================================================


def _mock_registry_client(
    *,
    resolved: TemplateRef,
    fetched: Path,
) -> MagicMock:
    """A RegistryClient whose *second* resolve (the index ref) is pinned."""
    client = MagicMock()
    client.resolve = AsyncMock(
        side_effect=[
            # 1st: bare name → not builtin (simulates the real resolver)
            TemplateRef(is_builtin=True, tag="qwen-code"),
            # 2nd: concrete owner/repo//subdir[@ref] from the index
            resolved,
        ]
    )
    client.fetch = AsyncMock(return_value=fetched)
    return client


class TestInstallBareNameResolution:
    """Bare (non-builtin) names are resolved through the remote index."""

    def test_install_bare_name_resolves_via_index(
        self, runner: CliRunner, index: TemplateIndex, tmp_path: Path
    ) -> None:
        fetched = _fetched_copy(tmp_path)
        client = _mock_registry_client(
            resolved=TemplateRef(
                owner="Easy-Sandbox",
                repo="awesome-templates",
                path="qwen-code",
                registry_type="github",
            ),
            fetched=fetched,
        )

        with (
            _patch_index(index),
            patch("easy_sandbox.utils.registry.RegistryClient", return_value=client),
        ):
            result = runner.invoke(cli, ["template", "install", "qwen-code", "--download-only"])

        assert result.exit_code == 0, result.output
        assert "Resolved 'qwen-code' via the template index" in result.output
        # The second resolve must receive the concrete index ref.
        assert client.resolve.call_args_list[1].args[0] == (f"{SOURCE_OF_TRUTH_REPO}//qwen-code")
        # …and the fetched ref is that same concrete ref.
        fetched_ref = client.fetch.call_args.args[0]
        assert fetched_ref.path == "qwen-code"
        assert fetched_ref.owner == "Easy-Sandbox"

    def test_install_honours_pinned_ref_from_index(self, runner: CliRunner, tmp_path: Path) -> None:
        pinned_yaml = INDEX_YAML.replace(
            "    path: qwen-code\n", "    path: qwen-code\n    ref: v1.2.0\n"
        )
        pinned_index = parse_index(pinned_yaml, source_url=INDEX_URL)
        fetched = _fetched_copy(tmp_path)
        client = _mock_registry_client(
            resolved=TemplateRef(
                owner="Easy-Sandbox",
                repo="awesome-templates",
                path="qwen-code",
                tag="v1.2.0",
                registry_type="github",
            ),
            fetched=fetched,
        )

        with (
            _patch_index(pinned_index),
            patch("easy_sandbox.utils.registry.RegistryClient", return_value=client),
        ):
            result = runner.invoke(cli, ["template", "install", "qwen-code", "--download-only"])

        assert result.exit_code == 0, result.output
        assert client.resolve.call_args_list[1].args[0] == (
            f"{SOURCE_OF_TRUTH_REPO}//qwen-code@v1.2.0"
        )

    def test_install_builtin_name_does_not_touch_index(
        self, runner: CliRunner, index: TemplateIndex
    ) -> None:
        mocked = AsyncMock(return_value=index)
        with patch("easy_sandbox.utils.template_index.fetch_index", new=mocked):
            result = runner.invoke(cli, ["template", "install", "base"])

        assert result.exit_code == 0, result.output
        assert "built-in" in result.output.lower()
        mocked.assert_not_called()

    def test_install_unknown_bare_name_raises_friendly_not_found(
        self, runner: CliRunner, index: TemplateIndex
    ) -> None:
        mocked = AsyncMock(return_value=index)
        with patch("easy_sandbox.utils.template_index.fetch_index", new=mocked):
            result = runner.invoke(cli, ["template", "install", "no-such-template"])

        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert "not found in the template index" in combined
        assert "ebx template search" in combined
        # The cache may predate a fresh release — a forced refresh is attempted.
        assert mocked.call_args_list[-1].kwargs.get("force") is True

    def test_install_shortcut_bare_name_resolves_via_index(
        self, runner: CliRunner, index: TemplateIndex, tmp_path: Path
    ) -> None:
        fetched = _fetched_copy(tmp_path)
        client = _mock_registry_client(
            resolved=TemplateRef(
                owner="Easy-Sandbox",
                repo="awesome-templates",
                path="qwen-code",
                registry_type="github",
            ),
            fetched=fetched,
        )

        with (
            _patch_index(index),
            patch("easy_sandbox.utils.registry.RegistryClient", return_value=client),
        ):
            result = runner.invoke(cli, ["install", "qwen-code", "--download-only"])

        assert result.exit_code == 0, result.output
        assert client.resolve.call_args_list[1].args[0] == (f"{SOURCE_OF_TRUTH_REPO}//qwen-code")
