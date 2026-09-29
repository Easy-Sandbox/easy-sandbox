"""End-to-end ``ebx install`` tests for the template catalog.

This module is the **hard gate before publishing**: it drives the real CLI,
the real reference resolver, the real fetch/cache logic and the real
``load_template_from_yaml`` pipeline.  Only one boundary is mocked:

1. the GitHub archive download — needs the network.

Everything else runs the production code path, so a template that passes here
will install identically for a real user.  The whole module is offline: a
tripwire on ``socket.getaddrinfo`` fails the test suite loudly if anything ever
tries to resolve a hostname.

Note: ``install`` only fetches template sources into the local cache — it never
builds or pushes a container image.  Build-and-push is done via
``ebx template build`` (tested elsewhere).
"""

from __future__ import annotations

import io
import json
import socket
import tarfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.cli.main import cli
from easy_sandbox.utils.registry import load_template_from_yaml

from .conftest import TEMPLATES_DIR, discover_template_dirs

if TYPE_CHECKING:
    from collections.abc import Iterator

    from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Fake GitHub coordinates (never contacted — see the tripwire below)
# ---------------------------------------------------------------------------

GITHUB_OWNER = "Easy-Sandbox"
GITHUB_REPO = "awesome-templates"
GITHUB_TAG = "v1.0.0"
GITHUB_REF = f"{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_URL = "https://github.com"

#: GitHub tarballs always wrap everything in a single ``owner-repo-sha/`` folder.
_ARCHIVE_PREFIX = f"{GITHUB_OWNER}-{GITHUB_REPO}-9f8e7d6"


# ---------------------------------------------------------------------------
# Offline guard
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    """Tripwire: any DNS resolution / TCP connect attempt fails the test.

    ``socket.socket`` itself is deliberately *not* patched because asyncio's
    self-pipe (``socketpair``) needs it; ``getaddrinfo`` and
    ``create_connection`` are the two choke points every outbound HTTP request
    has to pass through.
    """

    def _blocked(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            f"network access attempted during an offline template test (args={args!r})"
        )

    with (
        patch.object(socket, "getaddrinfo", side_effect=_blocked),
        patch.object(socket, "create_connection", side_effect=_blocked),
    ):
        yield


# ---------------------------------------------------------------------------
# Offline guard self-test
# ---------------------------------------------------------------------------


class TestOfflineGuard:
    """The tripwire itself must work, otherwise 'offline' is just a comment."""

    def test_dns_resolution_is_blocked(self) -> None:
        with pytest.raises(RuntimeError, match="network access attempted"):
            socket.getaddrinfo("github.com", 443)

    def test_tcp_connect_is_blocked(self) -> None:
        with pytest.raises(RuntimeError, match="network access attempted"):
            socket.create_connection(("github.com", 443))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _combined_output(result: Any) -> str:
    """stdout + stderr + exception text.

    ``handle_errors`` only renders :class:`SandboxError` subclasses; anything
    else (``ValueError`` from the resolver, ``ValidationError`` from the model)
    propagates and CliRunner parks it on ``result.exception`` instead of
    printing it.
    """
    # Click 8.5 separates stderr by default; Click <8.5 raises ValueError
    try:
        stderr = result.stderr or ""
    except ValueError:
        stderr = ""
    exception = getattr(result, "exception", None)
    exc_text = f"{type(exception).__name__}: {exception}" if exception else ""
    return f"{result.output}\n{stderr}\n{exc_text}"


def _json_objects(output: str) -> list[dict[str, Any]]:
    """Decode every concatenated JSON value in ``--json`` CLI output.

    In JSON mode the formatter emits one document per line-group (success
    notices included), so the stream is a *sequence* of objects rather than a
    single one.
    """
    decoder = json.JSONDecoder()
    text = output.strip()
    objects: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        brace = text.find("{", index)
        if brace == -1:
            break
        try:
            value, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            index = brace + 1
            continue
        if isinstance(value, dict):
            objects.append(value)
        index = max(end, brace + 1)
    return objects


def _install_payload(output: str) -> dict[str, Any]:
    """Return the install-result document from ``--json`` output."""
    for obj in _json_objects(output):
        if obj.get("Status") == "installed-locally":
            return obj
    raise AssertionError(f"no install payload in --json output:\n{output}")


# ---------------------------------------------------------------------------
# Local install — real resolve / fetch / parse pipeline
# ---------------------------------------------------------------------------


class TestLocalInstall:
    """``ebx install <path> --registry-type local`` for every catalog template.

    The ``install`` command only fetches template sources into the local cache;
    it never builds or pushes a container image.
    """

    def test_local_install_succeeds(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        expected = load_template_from_yaml(template_dir / "template.yaml")
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            result = runner.invoke(
                cli,
                ["install", str(template_dir), "--registry-type", "local", "--download-only"],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert "Using local template from" in result.output

        # Template should be cached under the install name (defaults to YAML name)
        cached = cache_dir / expected.name
        assert cached.is_dir(), f"template not cached at {cached}"
        assert (cached / "template.yaml").is_file()

    def test_local_install_caches_template_files(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        """Cached template must contain the essential files from the source."""
        expected = load_template_from_yaml(template_dir / "template.yaml")
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            result = runner.invoke(
                cli,
                ["install", str(template_dir), "--registry-type", "local", "--download-only"],
            )

        assert result.exit_code == 0, _combined_output(result)
        cached = cache_dir / expected.name
        # The cached template.yaml should be loadable and match the original
        cached_tmpl = load_template_from_yaml(cached / "template.yaml")
        assert cached_tmpl.name == expected.name
        assert cached_tmpl.description == expected.description

    def test_local_install_relative_path_autodetected(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        """A ``./``-prefixed ref is local even without ``--registry-type``."""
        relative = (
            f"./{template_dir.relative_to(Path.cwd())}"
            if _under_cwd(template_dir)
            else str(template_dir)
        )
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            result = runner.invoke(cli, ["install", relative, "--download-only"])

        assert result.exit_code == 0, _combined_output(result)
        assert "Using local template from" in result.output

    def test_local_install_alias_override(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            result = runner.invoke(
                cli,
                [
                    "install",
                    str(template_dir),
                    "--registry-type",
                    "local",
                    "--alias",
                    f"custom-{template_dir.name}",
                    "--download-only",
                ],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert f"custom-{template_dir.name}" in result.output
        # Alias should determine the cache directory name
        cached = cache_dir / f"custom-{template_dir.name}"
        assert cached.is_dir(), f"template not cached under alias at {cached}"

    def test_local_install_long_form_equivalent(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        """``ebx template install`` and ``ebx install`` behave identically."""
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            shortcut = runner.invoke(
                cli, ["install", str(template_dir), "--registry-type", "local", "--download-only"]
            )
        cache_dir2 = tmp_path / "ebx-cache-2"
        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir2):
            long_form = runner.invoke(
                cli,
                [
                    "template",
                    "install",
                    str(template_dir),
                    "--registry-type",
                    "local",
                    "--download-only",
                ],
            )

        assert shortcut.exit_code == 0, _combined_output(shortcut)
        assert long_form.exit_code == 0, _combined_output(long_form)

    def test_local_install_json_output(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        expected = load_template_from_yaml(template_dir / "template.yaml")
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "install",
                    str(template_dir),
                    "--registry-type",
                    "local",
                    "--download-only",
                ],
            )

        assert result.exit_code == 0, _combined_output(result)
        payload = _install_payload(result.output)
        assert payload["Alias"] == expected.name
        assert payload["Status"] == "installed-locally"
        assert "Cached" in payload
        assert "Source" in payload


class TestLocalInstallFailures:
    """Negative paths must fail loudly rather than silently proceeding."""

    def test_missing_directory(self, runner: CliRunner, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        result = runner.invoke(cli, ["install", str(missing), "--registry-type", "local"])
        assert result.exit_code != 0

    def test_directory_without_yaml_or_dockerfile(self, runner: CliRunner, tmp_path: Path) -> None:
        empty = tmp_path / "empty-template"
        empty.mkdir()
        result = runner.invoke(cli, ["install", str(empty), "--registry-type", "local"])
        assert result.exit_code != 0
        combined = _combined_output(result)
        assert (
            "template.yaml" in combined
            or "sandbox-template.yaml" in combined
            or "sandbox.yaml" in combined
        )

    def test_dockerfile_only_is_accepted_but_has_no_yaml(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """A bare Dockerfile passes fetch() but install still needs the YAML."""
        folder = tmp_path / "dockerfile-only"
        folder.mkdir()
        (folder / "Dockerfile").write_text("FROM ubuntu:22.04\n", encoding="utf-8")

        result = runner.invoke(cli, ["install", str(folder), "--registry-type", "local"])

        assert result.exit_code != 0
        combined = _combined_output(result)
        assert (
            "template.yaml" in combined
            or "sandbox-template.yaml" in combined
            or "sandbox.yaml" in combined
        )

    def test_invalid_yaml_is_rejected(self, runner: CliRunner, tmp_path: Path) -> None:
        folder = tmp_path / "broken"
        folder.mkdir()
        (folder / "template.yaml").write_text(
            "name: broken\ncapabilities:\n  - not-a-real-capability\n",
            encoding="utf-8",
        )
        result = runner.invoke(cli, ["install", str(folder), "--registry-type", "local"])
        assert result.exit_code != 0
        assert "capability" in _combined_output(result).lower()


def _under_cwd(path: Path) -> bool:
    try:
        path.relative_to(Path.cwd())
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Mocked GitHub install — real ref parsing, real zip extraction, real cache
# ---------------------------------------------------------------------------


def build_repo_tarball(templates_dir: Path) -> bytes:
    """Build an in-memory GitHub-style tarball (.tar.gz) of the fixtures.

    Layout mirrors what ``codeload.github.com`` returns for a ref::

        Easy-Sandbox-awesome-templates-9f8e7d6/
        ├── README.md
        └── python-hello/{template.yaml,Dockerfile,commands.py,README.md}

    This is the "fixture pointing at a local copy" that replaces the download.
    Local dev artifacts (``__pycache__`` / ``*.pyc`` / dotfiles) are excluded,
    matching what GitHub archives actually contain (``.gitignore``-d files).
    """

    def _add(tf: tarfile.TarFile, arcname: str, data: bytes) -> None:
        info = tarfile.TarInfo(name=arcname)
        info.size = len(data)
        info.mtime = int(time.time())
        tf.addfile(info, io.BytesIO(data))

    def _skip(path: Path) -> bool:
        return (
            any(part == "__pycache__" or part.startswith(".") for part in path.parts)
            or path.suffix == ".pyc"
        )

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        readme = templates_dir / "README.md"
        if readme.is_file():
            _add(tf, f"{_ARCHIVE_PREFIX}/README.md", readme.read_bytes())
        for folder in sorted(templates_dir.iterdir()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            for path in sorted(folder.rglob("*")):
                if not path.is_file() or _skip(path.relative_to(folder)):
                    continue
                arcname = f"{_ARCHIVE_PREFIX}/{folder.name}/{path.relative_to(folder).as_posix()}"
                _add(tf, arcname, path.read_bytes())
    return buffer.getvalue()


def _fake_download(tarball: bytes) -> MagicMock:
    response = MagicMock()
    response.content = tarball
    response.raise_for_status = MagicMock()
    return response


@contextmanager
def _mocked_github(tarball: bytes, cache_dir: Path, tag: str = GITHUB_TAG) -> Iterator[MagicMock]:
    """Patch the GitHub boundary: only the tarball archive bytes.

    ``_download_and_extract`` itself stays real, so prefix stripping and
    ``//subdir`` extraction are genuinely exercised.  There is no Release
    lookup anymore — the tarball endpoint is the single network call.
    """
    downloader = AsyncMock(return_value=_fake_download(tarball))
    with (
        patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir),
        patch("httpx.AsyncClient.get", new=downloader),
    ):
        yield downloader


class TestMockedGithubInstall:
    """``ebx install owner/repo//<template> --registry-type github`` offline."""

    def test_github_install_subdir(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        tarball = build_repo_tarball(TEMPLATES_DIR)
        cache_dir = tmp_path / "ebx-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}@{GITHUB_TAG}"
        expected = load_template_from_yaml(template_dir / "template.yaml")

        with _mocked_github(tarball, cache_dir) as downloader:
            result = runner.invoke(
                cli,
                [
                    "install",
                    ref,
                    "--registry-type",
                    "github",
                    "--registry-url",
                    GITHUB_URL,
                    "--download-only",
                ],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert f"Fetching template from {GITHUB_REF}" in result.output
        downloader.assert_awaited_once()

        # real cache layout: ~/.ebx/templates/<owner>/<repo>/<ref>/<subdir>
        cached = cache_dir / GITHUB_OWNER / GITHUB_REPO / GITHUB_TAG / template_dir.name
        assert (cached / "template.yaml").is_file(), f"template was not cached at {cached}"
        assert (cached / "Dockerfile").is_file()
        assert (cached / "README.md").is_file()
        # sibling templates must NOT leak into this cache entry
        assert not any(p.is_dir() for p in cached.iterdir()), (
            "subdir extraction pulled in unrelated folders"
        )

        # Verify the cached template matches the expected one
        cached_tmpl = load_template_from_yaml(cached / "template.yaml")
        assert cached_tmpl.name == expected.name

    def test_github_install_uses_cache_on_second_run(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        tarball = build_repo_tarball(TEMPLATES_DIR)
        cache_dir = tmp_path / "ebx-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}@{GITHUB_TAG}"

        with _mocked_github(tarball, cache_dir) as downloader:
            first = runner.invoke(
                cli, ["install", ref, "--registry-type", "github", "--download-only"]
            )
            second = runner.invoke(
                cli, ["install", ref, "--registry-type", "github", "--download-only"]
            )

        assert first.exit_code == 0, _combined_output(first)
        assert second.exit_code == 0, _combined_output(second)
        # second run is served from cache → no extra tarball download
        downloader.assert_awaited_once()

    def test_github_install_default_branch_no_ref(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        """A ref without ``@ref`` fetches the default-branch tarball, cached as 'default'."""
        tarball = build_repo_tarball(TEMPLATES_DIR)
        cache_dir = tmp_path / "ebx-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}"

        with _mocked_github(tarball, cache_dir) as downloader:
            result = runner.invoke(
                cli, ["install", ref, "--registry-type", "github", "--download-only"]
            )

        assert result.exit_code == 0, _combined_output(result)
        # no ref → tarball endpoint without a ref segment
        downloader.assert_awaited_once()
        called_url = downloader.await_args.args[0]
        assert called_url.endswith(f"/repos/{GITHUB_REF}/tarball"), called_url
        # cached under the stable 'default' placeholder
        cached = cache_dir / GITHUB_OWNER / GITHUB_REPO / "default" / template_dir.name
        assert (cached / "template.yaml").is_file()

    def test_github_install_alias_override(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        tarball = build_repo_tarball(TEMPLATES_DIR)
        cache_dir = tmp_path / "ebx-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}@{GITHUB_TAG}"

        with _mocked_github(tarball, cache_dir):
            result = runner.invoke(
                cli,
                [
                    "install",
                    ref,
                    "--registry-type",
                    "github",
                    "--alias",
                    "gh-alias",
                    "--download-only",
                ],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert "gh-alias" in result.output

    def test_github_install_whole_repo_without_subdir_fails(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """This catalog is multi-template: the repo root has no YAML of its own."""
        tarball = build_repo_tarball(TEMPLATES_DIR)
        cache_dir = tmp_path / "ebx-cache"

        with _mocked_github(tarball, cache_dir):
            result = runner.invoke(
                cli,
                [
                    "install",
                    f"{GITHUB_REF}@{GITHUB_TAG}",
                    "--registry-type",
                    "github",
                ],
            )

        assert result.exit_code != 0
        combined = _combined_output(result)
        assert (
            "template.yaml" in combined
            or "sandbox-template.yaml" in combined
            or "sandbox.yaml" in combined
        )


class TestSandboxYamlAliasInstall:
    """Verify that templates using sandbox.yaml (not template.yaml) install."""

    def test_local_install_sandbox_yaml_only(self, runner: CliRunner, tmp_path: Path) -> None:
        """A directory with only sandbox.yaml should install successfully."""
        tmpl_dir = tmp_path / "alias-template"
        tmpl_dir.mkdir()
        (tmpl_dir / "sandbox.yaml").write_text(
            "name: alias-template\n"
            "version: '1.0.0'\n"
            "description: Template using sandbox.yaml alias\n"
            "base: ubuntu:22.04\n"
            "author: test\n"
            "tags:\n  - test\n"
            "capabilities:\n  - shell\n  - files\n  - code\n",
            encoding="utf-8",
        )
        (tmpl_dir / "Dockerfile").write_text("FROM ubuntu:22.04\n", encoding="utf-8")
        (tmpl_dir / "README.md").write_text("# Alias template\n", encoding="utf-8")
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            result = runner.invoke(
                cli,
                ["install", str(tmpl_dir), "--registry-type", "local", "--download-only"],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert "Using local template from" in result.output
        # Verify template was cached
        cached = cache_dir / "alias-template"
        assert cached.is_dir()

    def test_template_yaml_preferred_over_sandbox_yaml(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """When both files exist, template.yaml takes priority."""
        tmpl_dir = tmp_path / "both-yamls"
        tmpl_dir.mkdir()
        (tmpl_dir / "template.yaml").write_text(
            "name: both-yamls\n"
            "version: '1.0.0'\n"
            "description: Canonical file\n"
            "base: python:3.11-slim\n"
            "author: test\n"
            "tags:\n  - test\n"
            "capabilities:\n  - shell\n  - files\n  - code\n",
            encoding="utf-8",
        )
        (tmpl_dir / "sandbox.yaml").write_text(
            "name: both-yamls-alt\n"
            "version: '2.0.0'\n"
            "description: Alias file - should not be used\n"
            "base: node:20-slim\n"
            "author: test\n"
            "tags:\n  - test\n"
            "capabilities:\n  - shell\n  - files\n  - code\n",
            encoding="utf-8",
        )
        (tmpl_dir / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
        cache_dir = tmp_path / "ebx-cache"

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir):
            result = runner.invoke(
                cli,
                ["install", str(tmpl_dir), "--registry-type", "local", "--download-only"],
            )

        assert result.exit_code == 0, _combined_output(result)
        # The canonical template.yaml name should be used (both-yamls, not both-yamls-alt)
        assert "both-yamls" in result.output
        cached = cache_dir / "both-yamls"
        assert cached.is_dir()


class TestMockedGithubInstallFailures:
    """Failure paths for mocked GitHub installs."""

    def test_github_install_missing_subdir_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        tarball = build_repo_tarball(TEMPLATES_DIR)
        cache_dir = tmp_path / "ebx-cache"

        with _mocked_github(tarball, cache_dir):
            result = runner.invoke(
                cli,
                [
                    "install",
                    f"{GITHUB_REF}//no-such-template@{GITHUB_TAG}",
                    "--registry-type",
                    "github",
                ],
            )

        assert result.exit_code != 0


class TestTarballFixture:
    """The offline GitHub fixture must faithfully represent the fixture folder."""

    def test_tarball_contains_every_fixture_template(self) -> None:
        tarball = build_repo_tarball(TEMPLATES_DIR)
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
            names = tf.getnames()

        assert names, "tarball fixture is empty"
        assert all(n.startswith(f"{_ARCHIVE_PREFIX}/") for n in names)

        for folder in discover_template_dirs():
            for filename in ("template.yaml", "Dockerfile", "README.md"):
                expected = f"{_ARCHIVE_PREFIX}/{folder.name}/{filename}"
                assert expected in names, f"tarball fixture is missing {expected}"

    def test_tarball_extracts_to_loadable_templates(self, tmp_path: Path) -> None:
        """Round-trip: extract the fixture and load every template from it."""
        tarball = build_repo_tarball(TEMPLATES_DIR)
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
            tf.extractall(tmp_path)

        root = tmp_path / _ARCHIVE_PREFIX
        for folder in discover_template_dirs():
            extracted = root / folder.name / "template.yaml"
            assert extracted.is_file()
            tmpl = load_template_from_yaml(extracted)
            assert tmpl.name == folder.name
