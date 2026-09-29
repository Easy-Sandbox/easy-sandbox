"""Unit tests for the remote template index client (``utils.template_index``).

Everything runs offline: HTTP is intercepted by ``pytest-httpx`` and the cache
lives in ``tmp_path``.  Covered behaviour:

* parsing / schema_version validation / duplicate + malformed entries
* ``install_ref`` construction (``owner/repo//subdir@ref``)
* cache lifecycle (fresh hit, TTL, ETag revalidation, corruption tolerance)
* degraded modes: stale-cache fallback on network errors / rate limits,
  explicit errors without a cache, and remediation suggestions
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from easy_sandbox.models.errors import (
    GitHubRateLimitError,
    NetworkError,
    TemplateNotFoundError,
    TemplateParseError,
)
from easy_sandbox.utils.github_token import FINE_GRAINED_PAT_URL
from easy_sandbox.utils.template_index import (
    INDEX_META_FILE,
    INDEX_SCHEMA_VERSION,
    fetch_index,
    parse_index,
    read_cached_index,
)

if TYPE_CHECKING:
    from pathlib import Path

INDEX_URL = (
    "https://raw.githubusercontent.com/Easy-Sandbox/awesome-templates/main/awesome-templates.yaml"
)

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


def _seed_cache(
    cache_dir: Path,
    text: str = INDEX_YAML,
    *,
    age: float = 0.0,
    etag: str | None = None,
) -> None:
    """Write an index cache file + metadata as a previous fetch would."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "awesome-templates.yaml").write_text(text, encoding="utf-8")
    (cache_dir / INDEX_META_FILE).write_text(
        json.dumps(
            {
                "source_url": INDEX_URL,
                "etag": etag,
                "fetched_at": time.time() - age,
            }
        ),
        encoding="utf-8",
    )


# =========================================================================
# parse_index
# =========================================================================


class TestParseIndex:
    """Pure parsing / validation of the index document."""

    def test_parses_entries_and_provenance(self) -> None:
        index = parse_index(INDEX_YAML, source_url=INDEX_URL)

        assert index.schema_version == INDEX_SCHEMA_VERSION
        assert index.source_url == INDEX_URL
        assert index.stale is False
        assert index.notice == ""
        names = [e.name for e in index.entries]
        assert names == ["qwen-code", "node-web"]
        qwen = index.entries[0]
        assert qwen.description == "Qwen Code agent harness"
        assert qwen.tags == ("qwen", "ai-agent")
        assert qwen.author == "Easy-Sandbox"
        assert qwen.capabilities == ("shell", "files", "code")
        assert qwen.status == "official"

    def test_missing_schema_version_is_legacy_compatible(self) -> None:
        text = INDEX_YAML.replace("schema_version: 1\n", "")
        index = parse_index(text)
        assert index.schema_version == INDEX_SCHEMA_VERSION

    def test_newer_schema_version_is_rejected(self) -> None:
        text = INDEX_YAML.replace("schema_version: 1", "schema_version: 99")
        with pytest.raises(TemplateParseError) as exc_info:
            parse_index(text)
        assert "newer than supported" in str(exc_info.value)
        assert "Upgrade easy-sandbox" in (exc_info.value.suggestion or "")

    def test_non_integer_schema_version_is_rejected(self) -> None:
        text = INDEX_YAML.replace("schema_version: 1", 'schema_version: "one"')
        with pytest.raises(TemplateParseError, match="non-integer schema_version"):
            parse_index(text)

    def test_duplicate_names_are_rejected(self) -> None:
        entry = """\
  - name: dup
    repo: Easy-Sandbox/awesome-templates
    path: dup
"""
        text = f"schema_version: 1\ntemplates:\n{entry}{entry}"
        with pytest.raises(TemplateParseError, match="duplicate entry"):
            parse_index(text)

    def test_missing_name_is_rejected(self) -> None:
        text = "schema_version: 1\ntemplates:\n  - repo: Easy-Sandbox/awesome-templates\n"
        with pytest.raises(TemplateParseError, match="missing the required 'name'"):
            parse_index(text)

    def test_missing_repo_is_rejected(self) -> None:
        text = "schema_version: 1\ntemplates:\n  - name: x\n"
        with pytest.raises(TemplateParseError, match="missing the required 'repo'"):
            parse_index(text)

    def test_unsupported_host_is_rejected(self) -> None:
        text = (
            "schema_version: 1\ntemplates:\n"
            "  - name: x\n    repo: https://gitlab.com/owner/repo\n    path: x\n"
        )
        with pytest.raises(TemplateParseError, match="Unsupported template host"):
            parse_index(text)

    def test_tags_must_be_a_string_list(self) -> None:
        text = (
            "schema_version: 1\ntemplates:\n"
            "  - name: x\n    repo: Easy-Sandbox/awesome-templates\n"
            "    path: x\n    tags: [1, 2]\n"
        )
        with pytest.raises(TemplateParseError, match="'tags' must be a list of strings"):
            parse_index(text)

    def test_invalid_yaml_is_rejected(self) -> None:
        with pytest.raises(TemplateParseError, match="not valid YAML"):
            parse_index("templates: [unclosed")

    def test_missing_templates_list_is_rejected(self) -> None:
        with pytest.raises(TemplateParseError, match="no 'templates' list"):
            parse_index("schema_version: 1\n")


class TestInstallRef:
    """``install_ref`` → the exact reference handed to the registry client."""

    def _entry(self, yaml_fragment: str) -> Any:
        text = f"schema_version: 1\ntemplates:\n{yaml_fragment}"
        return parse_index(text).entries[0]

    def test_with_path(self) -> None:
        entry = self._entry("  - name: x\n    repo: Easy-Sandbox/awesome-templates\n    path: x\n")
        assert entry.install_ref == "Easy-Sandbox/awesome-templates//x"

    def test_without_path(self) -> None:
        entry = self._entry("  - name: x\n    repo: Easy-Sandbox/awesome-templates\n")
        assert entry.install_ref == "Easy-Sandbox/awesome-templates"

    def test_with_ref_pin(self) -> None:
        entry = self._entry(
            "  - name: x\n    repo: Easy-Sandbox/awesome-templates\n    path: x\n    ref: v1.2.0\n"
        )
        assert entry.install_ref == "Easy-Sandbox/awesome-templates//x@v1.2.0"

    def test_github_url_repo_is_normalised(self) -> None:
        entry = self._entry(
            "  - name: x\n    repo: https://github.com/owner/repo.git\n    path: x\n"
        )
        assert entry.install_ref == "owner/repo//x"


class TestLookup:
    """``find`` / ``filter`` semantics used by search and install-by-name."""

    def test_find_is_case_insensitive(self) -> None:
        index = parse_index(INDEX_YAML)
        assert index.find("QWEN-CODE") is not None
        assert index.find("qwen") is None

    def test_filter_matches_name_description_tags_and_author(self) -> None:
        index = parse_index(INDEX_YAML)
        assert [e.name for e in index.filter("web")] == ["node-web"]
        assert [e.name for e in index.filter("qwen")] == ["qwen-code"]
        assert [e.name for e in index.filter("easy-sandbox")] == ["qwen-code", "node-web"]

    def test_filter_by_tag_and_status(self) -> None:
        index = parse_index(INDEX_YAML)
        assert [e.name for e in index.filter("", tag="deploy")] == ["node-web"]
        assert index.filter("", status="community") == []
        assert [e.name for e in index.filter("", status="official")] == [
            "qwen-code",
            "node-web",
        ]


# =========================================================================
# fetch_index — local files, cache lifecycle, degraded modes
# =========================================================================


class TestFetchIndexLocal:
    """Local-file indexes bypass both network and cache."""

    async def test_local_path_direct_read(self, tmp_path: Path) -> None:
        local = tmp_path / "index.yaml"
        local.write_text(INDEX_YAML, encoding="utf-8")

        index = await fetch_index(str(local), cache_dir=tmp_path / "cache")

        assert [e.name for e in index.entries] == ["qwen-code", "node-web"]
        assert index.source_url == str(local)
        assert not (tmp_path / "cache").exists()

    async def test_local_path_missing_raises_template_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(TemplateNotFoundError, match="index file not found"):
            await fetch_index(str(tmp_path / "nope.yaml"), cache_dir=tmp_path / "cache")


class TestFetchIndexNetwork:
    """Network fetch, cache writes and conditional requests (httpx mocked)."""

    async def test_success_writes_cache_and_metadata(self, httpx_mock: Any, tmp_path: Path) -> None:
        httpx_mock.add_response(url=INDEX_URL, text=INDEX_YAML, headers={"ETag": '"abc123"'})
        cache_dir = tmp_path / "cache"

        index = await fetch_index(INDEX_URL, cache_dir=cache_dir)

        assert [e.name for e in index.entries] == ["qwen-code", "node-web"]
        assert index.fetched_at is not None
        assert (cache_dir / "awesome-templates.yaml").is_file()
        meta = json.loads((cache_dir / INDEX_META_FILE).read_text(encoding="utf-8"))
        assert meta["etag"] == '"abc123"'
        assert meta["source_url"] == INDEX_URL

        # The cache round-trips through the same parser.
        cached = read_cached_index(cache_dir)
        assert cached is not None
        assert [e.name for e in cached.entries] == ["qwen-code", "node-web"]

    async def test_fresh_cache_short_circuits_network(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        _seed_cache(tmp_path, age=10.0)

        index = await fetch_index(INDEX_URL, cache_dir=tmp_path)

        assert index.stale is False
        assert not httpx_mock.get_requests(), "fresh cache must not hit the network"

    async def test_force_bypasses_fresh_cache(self, httpx_mock: Any, tmp_path: Path) -> None:
        _seed_cache(tmp_path, age=10.0)
        httpx_mock.add_response(url=INDEX_URL, text=INDEX_YAML.replace("qwen-code", "qwen-code-v2"))

        index = await fetch_index(INDEX_URL, cache_dir=tmp_path, force=True)

        assert [e.name for e in index.entries] == ["qwen-code-v2", "node-web"]
        # The refreshed body replaced the cached one.
        assert "qwen-code-v2" in (tmp_path / "awesome-templates.yaml").read_text(encoding="utf-8")

    async def test_expired_cache_sends_conditional_request(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        _seed_cache(tmp_path, age=99999.0, etag='"v1"')
        httpx_mock.add_response(url=INDEX_URL, status_code=304)

        index = await fetch_index(INDEX_URL, cache_dir=tmp_path)

        request = httpx_mock.get_request()
        assert request is not None
        assert request.headers["if-none-match"] == '"v1"'
        assert index.stale is False
        meta = json.loads((tmp_path / INDEX_META_FILE).read_text(encoding="utf-8"))
        assert meta["fetched_at"] > time.time() - 60  # metadata refreshed

    async def test_token_sets_authorization_header(self, httpx_mock: Any, tmp_path: Path) -> None:
        httpx_mock.add_response(url=INDEX_URL, text=INDEX_YAML)

        await fetch_index(INDEX_URL, token="secret-token", cache_dir=tmp_path / "cache")

        request = httpx_mock.get_request()
        assert request is not None
        assert request.headers["authorization"] == "Bearer secret-token"

    async def test_env_var_overrides_default_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / "env-index.yaml"
        local.write_text(INDEX_YAML, encoding="utf-8")
        monkeypatch.setenv("EBX_TEMPLATE_INDEX_URL", str(local))

        index = await fetch_index(cache_dir=tmp_path / "cache")

        assert index.source_url == str(local)

    async def test_newer_schema_from_network_fails_loudly(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(url=INDEX_URL, text="schema_version: 99\ntemplates: []\n")
        with pytest.raises(TemplateParseError, match="newer than supported"):
            await fetch_index(INDEX_URL, cache_dir=tmp_path / "cache")


class TestFetchIndexDegradedModes:
    """Network failures / rate limits / bad URLs degrade explicitly."""

    async def test_network_error_without_cache_raises(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))

        with pytest.raises(NetworkError, match="Could not reach the template index") as exc:
            await fetch_index(INDEX_URL, cache_dir=tmp_path / "cache")
        # The persistent config flow is the recommended remedy (task 206).
        assert "ebx config set github_token" in (exc.value.suggestion or "")

    async def test_network_error_with_cache_serves_stale(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        _seed_cache(tmp_path, age=99999.0)
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))

        index = await fetch_index(INDEX_URL, cache_dir=tmp_path)

        assert index.stale is True
        assert "cached index" in index.notice.lower()
        assert [e.name for e in index.entries] == ["qwen-code", "node-web"]

    async def test_rate_limit_with_cache_serves_stale_with_hint(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        _seed_cache(tmp_path, age=99999.0)
        httpx_mock.add_response(
            url=INDEX_URL,
            status_code=403,
            headers={"X-RateLimit-Remaining": "0"},
            text="API rate limit exceeded",
        )

        index = await fetch_index(INDEX_URL, cache_dir=tmp_path)

        assert index.stale is True
        # The unified rate-limit wording (task 206) drives the notice.
        assert "rate limit" in index.notice.lower()
        assert "60/hour" in index.notice
        assert "cached index" in index.notice.lower()

    async def test_rate_limit_without_cache_raises_onboarding_error(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(url=INDEX_URL, status_code=429)

        with pytest.raises(GitHubRateLimitError) as exc:
            await fetch_index(INDEX_URL, cache_dir=tmp_path / "cache")

        assert "rate limit" in str(exc.value).lower()
        assert "while fetching the template index" in str(exc.value)
        suggestion = exc.value.suggestion or ""
        # Persistent, masked config first; leak-prone --token stays documented.
        assert "ebx config set github_token" in suggestion
        assert FINE_GRAINED_PAT_URL in suggestion
        assert "may leak" in suggestion
        # CI sessions are pointed at secret injection…
        assert "GITHUB_TOKEN" in suggestion
        assert "secret" in suggestion.lower()
        # …plus the index-specific mirror alternative (kept as last sentence).
        assert "install directly with" not in suggestion
        assert "--index-url" in suggestion

    async def test_404_without_cache_mentions_url_check(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(url=INDEX_URL, status_code=404)

        with pytest.raises(NetworkError, match="HTTP 404") as exc:
            await fetch_index(INDEX_URL, cache_dir=tmp_path / "cache")
        assert "Verify the index URL" in (exc.value.suggestion or "")

    async def test_server_error_with_cache_serves_stale(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        _seed_cache(tmp_path, age=99999.0)
        httpx_mock.add_response(url=INDEX_URL, status_code=503)

        index = await fetch_index(INDEX_URL, cache_dir=tmp_path)

        assert index.stale is True
        assert "server error" in index.notice.lower()

    async def test_unexpected_status_degrades_explicitly(
        self, httpx_mock: Any, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(url=INDEX_URL, status_code=418)

        with pytest.raises(NetworkError, match="Unexpected HTTP 418"):
            await fetch_index(INDEX_URL, cache_dir=tmp_path / "cache")

    async def test_corrupt_cache_is_ignored(self, httpx_mock: Any, tmp_path: Path) -> None:
        _seed_cache(tmp_path, text="not: [valid", age=10.0)

        # The corrupt cache is discarded → a network fetch happens instead of
        # serving garbage (marked stale or otherwise).
        httpx_mock.add_response(url=INDEX_URL, text=INDEX_YAML)
        index = await fetch_index(INDEX_URL, cache_dir=tmp_path)

        assert not index.stale
        assert [e.name for e in index.entries] == ["qwen-code", "node-web"]
        assert len(httpx_mock.get_requests()) == 1
