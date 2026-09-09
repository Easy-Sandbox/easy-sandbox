"""End-to-end ``sbox install`` tests for the template catalog.

This module is the **hard gate before publishing**: it drives the real CLI,
the real reference resolver, the real fetch/cache logic and the real
``load_template_from_yaml`` → ``to_dockerfile`` pipeline.  Only two boundaries
are mocked:

1. the platform build request (``POST /templates``) — needs a live backend;
2. the GitHub archive download — needs the network.

Everything else runs the production code path, so a template that passes here
will install identically for a real user.  The whole module is offline: a
tripwire on ``socket.getaddrinfo`` fails the test suite loudly if anything ever
tries to resolve a hostname.
"""
from __future__ import annotations

import io
import json
import socket
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from serverless_sandbox.cli.main import cli
from serverless_sandbox.utils.registry import load_template_from_yaml

from .conftest import TEMPLATES_DIR, discover_template_dirs

if TYPE_CHECKING:
    from collections.abc import Iterator

    from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Fake GitHub coordinates (never contacted — see the tripwire below)
# ---------------------------------------------------------------------------

GITHUB_OWNER = "anycodes"
GITHUB_REPO = "awesome-serverless-sandbox-templates"
GITHUB_TAG = "v1.0.0"
GITHUB_REF = f"{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_URL = "https://github.com"

#: GitHub zipballs always wrap everything in a single ``owner-repo-sha/`` folder.
_ZIP_PREFIX = f"{GITHUB_OWNER}-{GITHUB_REPO}-9f8e7d6"


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
            "network access attempted during an offline template test "
            f"(args={args!r})"
        )

    with patch.object(socket, "getaddrinfo", side_effect=_blocked), patch.object(
        socket, "create_connection", side_effect=_blocked
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
# Platform-build boundary mock
# ---------------------------------------------------------------------------

@contextmanager
def _mocked_platform_build(
    template_id: str = "tpl-test-0001",
    build_id: str = "bld-test-0001",
) -> Iterator[MagicMock]:
    """Mock only the backend ``POST /templates`` boundary; yield the HttpClient.

    ``cli/commands/template.py`` imports these lazily *inside* the command body,
    so patching the source modules is what the running code picks up (same
    technique as ``tests/test_cli/test_template_commands.py``).
    """
    response = MagicMock()
    response.json.return_value = {"templateID": template_id, "buildID": build_id}

    http_client = MagicMock()
    http_client.platform_request = AsyncMock(return_value=response)
    http_client.close = AsyncMock()

    config = MagicMock()
    config.api_key = "test-api-key"
    config.access_key_id = None
    config.access_key_secret = None

    with patch(
        "serverless_sandbox.transport.config.load_config", return_value=config
    ), patch(
        "serverless_sandbox.transport.auth.create_auth_provider"
    ), patch(
        "serverless_sandbox.transport.http.HttpClient", return_value=http_client
    ):
        yield http_client


def _posted_body(http_client: MagicMock) -> dict[str, Any]:
    """Extract the JSON body of the ``POST /templates`` build request."""
    http_client.platform_request.assert_awaited()
    call = http_client.platform_request.await_args_list[0]
    assert call.args[0] == "POST"
    assert call.args[1] == "/templates"
    body = call.kwargs["json"]
    assert isinstance(body, dict)
    return body


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


def _build_payload(output: str) -> dict[str, Any]:
    """Return the ``POST /templates`` result document from ``--json`` output."""
    for obj in _json_objects(output):
        if "TemplateID" in obj:
            return obj
    raise AssertionError(f"no build payload in --json output:\n{output}")


# ---------------------------------------------------------------------------
# Local install — real resolve / fetch / parse / dockerfile pipeline
# ---------------------------------------------------------------------------

class TestLocalInstall:
    """``sbox install <path> --registry-type local`` for every catalog template."""

    def test_local_install_succeeds(self, runner: CliRunner, template_dir: Path) -> None:
        expected = load_template_from_yaml(template_dir / "template.yaml")

        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli,
                ["install", str(template_dir), "--registry-type", "local"],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert "Using local template from" in result.output

        body = _posted_body(http_client)
        dockerfile = body["dockerfile"]
        assert dockerfile.startswith(f"FROM {expected.base}"), (
            f"{template_dir.name}: generated Dockerfile does not start from the "
            f"YAML base image:\n{dockerfile}"
        )
        # alias defaults to the template name declared in the YAML
        assert body["alias"] == expected.name

        assert "tpl-test-0001" in result.output
        assert "bld-test-0001" in result.output

    def test_local_install_dockerfile_reflects_yaml(
        self, runner: CliRunner, template_dir: Path
    ) -> None:
        """The build request must carry the *YAML-derived* Dockerfile, not the file."""
        expected = load_template_from_yaml(template_dir / "template.yaml")

        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli, ["install", str(template_dir), "--registry-type", "local"]
            )

        assert result.exit_code == 0, _combined_output(result)
        dockerfile = _posted_body(http_client)["dockerfile"]
        assert dockerfile == expected.to_dockerfile()

        for pkg in expected.system_packages[:1]:
            assert pkg in dockerfile
        for pkg in expected.python_packages[:1]:
            assert pkg in dockerfile
        for pkg in expected.node_packages[:1]:
            assert pkg in dockerfile

    def test_local_install_relative_path_autodetected(
        self, runner: CliRunner, template_dir: Path
    ) -> None:
        """A ``./``-prefixed ref is local even without ``--registry-type``."""
        relative = f"./{template_dir.relative_to(Path.cwd())}" if _under_cwd(
            template_dir
        ) else str(template_dir)

        with _mocked_platform_build() as http_client:
            result = runner.invoke(cli, ["install", relative])

        assert result.exit_code == 0, _combined_output(result)
        assert "Using local template from" in result.output
        assert _posted_body(http_client)["dockerfile"].startswith("FROM ")

    def test_local_install_alias_override(
        self, runner: CliRunner, template_dir: Path
    ) -> None:
        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli,
                [
                    "install",
                    str(template_dir),
                    "--registry-type",
                    "local",
                    "--alias",
                    f"custom-{template_dir.name}",
                ],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert _posted_body(http_client)["alias"] == f"custom-{template_dir.name}"
        assert f"custom-{template_dir.name}" in result.output

    def test_local_install_long_form_equivalent(
        self, runner: CliRunner, template_dir: Path
    ) -> None:
        """``sbox template install`` and ``sbox install`` behave identically."""
        with _mocked_platform_build() as shortcut_client:
            shortcut = runner.invoke(
                cli, ["install", str(template_dir), "--registry-type", "local"]
            )
        with _mocked_platform_build() as long_client:
            long_form = runner.invoke(
                cli,
                ["template", "install", str(template_dir), "--registry-type", "local"],
            )

        assert shortcut.exit_code == 0, _combined_output(shortcut)
        assert long_form.exit_code == 0, _combined_output(long_form)
        assert _posted_body(shortcut_client) == _posted_body(long_client)

    def test_local_install_json_output(
        self, runner: CliRunner, template_dir: Path
    ) -> None:
        with _mocked_platform_build():
            result = runner.invoke(
                cli,
                ["--json", "install", str(template_dir), "--registry-type", "local"],
            )

        assert result.exit_code == 0, _combined_output(result)
        payload = _build_payload(result.output)
        assert payload["TemplateID"] == "tpl-test-0001"
        assert payload["BuildID"] == "bld-test-0001"
        assert payload["Alias"] == template_dir.name
        assert payload["Status"] == "building"


class TestLocalInstallFailures:
    """Negative paths must fail loudly rather than silently building garbage."""

    def test_missing_directory(self, runner: CliRunner, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli, ["install", str(missing), "--registry-type", "local"]
            )
        assert result.exit_code != 0
        http_client.platform_request.assert_not_awaited()

    def test_directory_without_yaml_or_dockerfile(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty-template"
        empty.mkdir()
        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli, ["install", str(empty), "--registry-type", "local"]
            )
        assert result.exit_code != 0
        combined = _combined_output(result)
        assert "template.yaml" in combined or "sandbox-template.yaml" in combined or "sandbox.yaml" in combined
        http_client.platform_request.assert_not_awaited()

    def test_dockerfile_only_is_accepted_but_has_no_yaml(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """A bare Dockerfile passes fetch() but install still needs the YAML."""
        folder = tmp_path / "dockerfile-only"
        folder.mkdir()
        (folder / "Dockerfile").write_text("FROM ubuntu:22.04\n", encoding="utf-8")

        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli, ["install", str(folder), "--registry-type", "local"]
            )

        assert result.exit_code != 0
        combined = _combined_output(result)
        assert "template.yaml" in combined or "sandbox-template.yaml" in combined or "sandbox.yaml" in combined
        http_client.platform_request.assert_not_awaited()

    def test_invalid_yaml_is_rejected(self, runner: CliRunner, tmp_path: Path) -> None:
        folder = tmp_path / "broken"
        folder.mkdir()
        (folder / "template.yaml").write_text(
            "name: broken\ncapabilities:\n  - not-a-real-capability\n",
            encoding="utf-8",
        )
        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli, ["install", str(folder), "--registry-type", "local"]
            )
        assert result.exit_code != 0
        assert "capability" in _combined_output(result).lower()
        http_client.platform_request.assert_not_awaited()


def _under_cwd(path: Path) -> bool:
    try:
        path.relative_to(Path.cwd())
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Mocked GitHub install — real ref parsing, real zip extraction, real cache
# ---------------------------------------------------------------------------

def build_repo_zipball(templates_dir: Path) -> bytes:
    """Build an in-memory GitHub-style release zipball of the whole catalog.

    Layout mirrors what ``codeload.github.com`` returns for a tag::

        anycodes-awesome-serverless-sandbox-templates-9f8e7d6/
        ├── README.md
        ├── browser-automation/{template.yaml,Dockerfile,README.md}
        └── ...

    This is the "fixture pointing at a local copy" that replaces the download.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        readme = templates_dir / "README.md"
        if readme.is_file():
            zf.writestr(f"{_ZIP_PREFIX}/README.md", readme.read_bytes())
        for folder in sorted(templates_dir.iterdir()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            for path in sorted(folder.rglob("*")):
                if not path.is_file():
                    continue
                arcname = (
                    f"{_ZIP_PREFIX}/{folder.name}/"
                    f"{path.relative_to(folder).as_posix()}"
                )
                zf.writestr(arcname, path.read_bytes())
    return buffer.getvalue()


def _fake_download(zipball: bytes) -> MagicMock:
    response = MagicMock()
    response.content = zipball
    response.raise_for_status = MagicMock()
    return response


@contextmanager
def _mocked_github(
    zipball: bytes, cache_dir: Path, tag: str = GITHUB_TAG
) -> Iterator[MagicMock]:
    """Patch the GitHub boundary: release lookup + archive bytes.

    ``_download_and_extract`` itself stays real, so prefix stripping and
    ``//subdir`` extraction are genuinely exercised.
    """
    release = {
        "tag_name": tag,
        "zipball_url": f"https://codeload.github.com/{GITHUB_REF}/zip/refs/tags/{tag}",
    }
    with patch(
        "serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", cache_dir
    ), patch(
        "serverless_sandbox.utils.registry.RegistryClient._get_release",
        new=AsyncMock(return_value=release),
    ) as get_release, patch(
        "httpx.AsyncClient.get", new=AsyncMock(return_value=_fake_download(zipball))
    ):
        yield get_release


class TestMockedGithubInstall:
    """``sbox install owner/repo//<template> --registry-type github`` offline."""

    def test_github_install_subdir(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        zipball = build_repo_zipball(TEMPLATES_DIR)
        cache_dir = tmp_path / "sbox-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}@{GITHUB_TAG}"
        expected = load_template_from_yaml(template_dir / "template.yaml")

        with _mocked_github(zipball, cache_dir) as get_release, \
                _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli,
                [
                    "install",
                    ref,
                    "--registry-type",
                    "github",
                    "--registry-url",
                    GITHUB_URL,
                ],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert f"Fetching template from {GITHUB_REF}" in result.output
        get_release.assert_awaited_once()

        # real cache layout: ~/.sbox/templates/<owner>/<repo>/<tag>/<subdir>
        cached = cache_dir / GITHUB_OWNER / GITHUB_REPO / GITHUB_TAG / template_dir.name
        assert (cached / "template.yaml").is_file(), (
            f"template was not cached at {cached}"
        )
        assert (cached / "Dockerfile").is_file()
        assert (cached / "README.md").is_file()
        # sibling templates must NOT leak into this cache entry
        assert not any(
            p.is_dir() for p in cached.iterdir()
        ), "subdir extraction pulled in unrelated folders"

        body = _posted_body(http_client)
        assert body["dockerfile"] == expected.to_dockerfile()
        assert body["alias"] == expected.name
        assert "tpl-test-0001" in result.output

    def test_github_install_uses_cache_on_second_run(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        zipball = build_repo_zipball(TEMPLATES_DIR)
        cache_dir = tmp_path / "sbox-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}@{GITHUB_TAG}"

        with _mocked_github(zipball, cache_dir) as get_release, \
                _mocked_platform_build():
            first = runner.invoke(
                cli, ["install", ref, "--registry-type", "github"]
            )
            second = runner.invoke(
                cli, ["install", ref, "--registry-type", "github"]
            )

        assert first.exit_code == 0, _combined_output(first)
        assert second.exit_code == 0, _combined_output(second)
        # second run is served from cache → no extra release lookup / download
        get_release.assert_awaited_once()

    def test_github_install_latest_resolves_release_tag(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        """A ref without ``@tag`` asks GitHub for ``latest`` and caches under it."""
        zipball = build_repo_zipball(TEMPLATES_DIR)
        cache_dir = tmp_path / "sbox-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}"

        with _mocked_github(zipball, cache_dir, tag=GITHUB_TAG) as get_release, \
                _mocked_platform_build():
            result = runner.invoke(
                cli, ["install", ref, "--registry-type", "github"]
            )

        assert result.exit_code == 0, _combined_output(result)
        # resolve() must have produced a GitHub ref, not a builtin/local one
        get_release.assert_awaited_once()
        assert get_release.await_args.args[2] is None, (
            "latest release should be queried without an explicit tag"
        )
        cached = cache_dir / GITHUB_OWNER / GITHUB_REPO / GITHUB_TAG / template_dir.name
        assert (cached / "template.yaml").is_file()

    def test_github_install_alias_override(
        self, runner: CliRunner, template_dir: Path, tmp_path: Path
    ) -> None:
        zipball = build_repo_zipball(TEMPLATES_DIR)
        cache_dir = tmp_path / "sbox-cache"
        ref = f"{GITHUB_REF}//{template_dir.name}@{GITHUB_TAG}"

        with _mocked_github(zipball, cache_dir), _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli,
                ["install", ref, "--registry-type", "github", "--alias", "gh-alias"],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert _posted_body(http_client)["alias"] == "gh-alias"

    def test_github_install_whole_repo_without_subdir_fails(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """This catalog is multi-template: the repo root has no YAML of its own."""
        zipball = build_repo_zipball(TEMPLATES_DIR)
        cache_dir = tmp_path / "sbox-cache"

        with _mocked_github(zipball, cache_dir), _mocked_platform_build() as http_client:
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
        assert "template.yaml" in combined or "sandbox-template.yaml" in combined or "sandbox.yaml" in combined
        http_client.platform_request.assert_not_awaited()


class TestSandboxYamlAliasInstall:
    """Verify that templates using sandbox.yaml (not template.yaml) install."""

    def test_local_install_sandbox_yaml_only(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
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

        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli,
                ["install", str(tmpl_dir), "--registry-type", "local"],
            )

        assert result.exit_code == 0, _combined_output(result)
        assert "Using local template from" in result.output

        body = _posted_body(http_client)
        assert body["dockerfile"].startswith("FROM ubuntu:22.04")
        assert body["alias"] == "alias-template"

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

        with _mocked_platform_build() as http_client:
            result = runner.invoke(
                cli,
                ["install", str(tmpl_dir), "--registry-type", "local"],
            )

        assert result.exit_code == 0, _combined_output(result)
        body = _posted_body(http_client)
        # The canonical template.yaml should be used (python base, not node)
        assert body["dockerfile"].startswith("FROM python:3.11-slim")
        assert body["alias"] == "both-yamls"


class TestMockedGithubInstallFailures:
    """Failure paths for mocked GitHub installs."""

    def test_github_install_missing_subdir_fails(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        zipball = build_repo_zipball(TEMPLATES_DIR)
        cache_dir = tmp_path / "sbox-cache"

        with _mocked_github(zipball, cache_dir), _mocked_platform_build() as http_client:
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
        http_client.platform_request.assert_not_awaited()


class TestZipballFixture:
    """The offline GitHub fixture must faithfully represent the catalog."""

    def test_zipball_contains_every_template(self) -> None:
        zipball = build_repo_zipball(TEMPLATES_DIR)
        with zipfile.ZipFile(io.BytesIO(zipball)) as zf:
            names = zf.namelist()

        assert names, "zipball fixture is empty"
        assert all(n.startswith(f"{_ZIP_PREFIX}/") for n in names)

        for folder in discover_template_dirs():
            for filename in ("template.yaml", "Dockerfile", "README.md"):
                expected = f"{_ZIP_PREFIX}/{folder.name}/{filename}"
                assert expected in names, f"zipball fixture is missing {expected}"

    def test_zipball_extracts_to_loadable_templates(self, tmp_path: Path) -> None:
        """Round-trip: extract the fixture and load every template from it."""
        zipball = build_repo_zipball(TEMPLATES_DIR)
        with zipfile.ZipFile(io.BytesIO(zipball)) as zf:
            zf.extractall(tmp_path)

        root = tmp_path / _ZIP_PREFIX
        for folder in discover_template_dirs():
            extracted = root / folder.name / "template.yaml"
            assert extracted.is_file()
            tmpl = load_template_from_yaml(extracted)
            assert tmpl.name == folder.name
