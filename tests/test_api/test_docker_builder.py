"""Tests for DockerBuilder, ACRConfig, and ACR auth helpers."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from easy_sandbox.api.docker_builder import (
    ACRConfig,
    BuildResult,
    DockerBuilder,
    _get_acr_auth_token,
    get_acr_auth_token,
)

# ---------------------------------------------------------------------------
# Backward-compatible alias tests (task #66 / review item 1)
# ---------------------------------------------------------------------------


class TestACRAuthTokenAlias:
    """Verify that ``_get_acr_auth_token`` is a backward-compatible alias."""

    def test_alias_is_same_function(self) -> None:
        """Old private name must point to exactly the same function object."""
        assert _get_acr_auth_token is get_acr_auth_token

    def test_importable_via_old_name(self) -> None:
        """Scripts can ``from ... import _get_acr_auth_token``."""
        from easy_sandbox.api.docker_builder import (
            _get_acr_auth_token as old_name,
        )

        assert old_name is get_acr_auth_token

    def test_importable_via_new_name(self) -> None:
        """The canonical public name is importable."""
        from easy_sandbox.api.docker_builder import (
            get_acr_auth_token as new_name,
        )

        assert callable(new_name)

    @patch("easy_sandbox.api.docker_builder._get_acr_auth_token_personal")
    def test_old_name_delegates_to_same_impl(self, mock_personal: MagicMock) -> None:
        """Calling via old name must reach the same implementation."""
        mock_personal.return_value = {
            "tempUserName": "u",
            "authorizationToken": "t",
        }
        result = _get_acr_auth_token("ak", "sk", "cn-hangzhou")
        assert result["tempUserName"] == "u"
        mock_personal.assert_called_once()


# ---------------------------------------------------------------------------
# ACRConfig tests
# ---------------------------------------------------------------------------


class TestACRConfig:
    """Basic ACRConfig dataclass tests."""

    def test_full_image_ref(self) -> None:
        acr = ACRConfig(
            registry="registry.cn-hangzhou.aliyuncs.com",
            namespace="ns",
            repo="repo",
        )
        assert acr.full_image_ref == "registry.cn-hangzhou.aliyuncs.com/ns/repo"

    def test_tagged_ref(self) -> None:
        acr = ACRConfig(registry="reg", namespace="ns", repo="r")
        assert acr.tagged_ref("v1") == "reg/ns/r:v1"

    def test_registry_type_auto_detect_acr(self) -> None:
        acr = ACRConfig(registry="reg", namespace="ns", repo="r")
        headers = acr.to_platform_headers()
        assert headers["X-E2B-Template-Source-Registry-Type"] == "acr"

    def test_registry_type_auto_detect_acree(self) -> None:
        acr = ACRConfig(
            registry="reg",
            namespace="ns",
            repo="r",
            acree_instance_id="cri-xxx",
        )
        headers = acr.to_platform_headers()
        assert headers["X-E2B-Template-Source-Registry-Type"] == "acree"
        assert headers["X-E2B-Template-Source-ACREE-Instance-ID"] == "cri-xxx"


# ---------------------------------------------------------------------------
# BuildResult tests
# ---------------------------------------------------------------------------


class TestBuildResult:
    """BuildResult dataclass tests."""

    def test_success_statuses(self) -> None:
        for st in ("ready", "building", "pushed"):
            assert BuildResult(build_status=st).success

    def test_failure_status(self) -> None:
        assert not BuildResult(build_status="error").success
        assert not BuildResult(build_status="unknown").success


# ---------------------------------------------------------------------------
# DockerBuilder.build_and_register_official — full mock test (task #66 / item 3)
# ---------------------------------------------------------------------------


class TestBuildAndRegisterOfficial:
    """Full mock coverage of the official CreateTemplate API path.

    Mocks: Docker daemon, wheel injection, ACR token, tag, push, and
    ``create_official_template``.  Asserts forwarded parameters including
    image ref, cpu, memory, disk, internet, generation, envdInject,
    team_id, registry_type; ACREE instance triggers ``acree`` type.

    No real Docker, network, or cloud API calls are made.
    """

    @pytest.fixture
    def acr_config(self) -> ACRConfig:
        return ACRConfig(
            registry="registry.cn-hangzhou.aliyuncs.com",
            namespace="test-ns",
            repo="test-repo",
            username="ak-test",
            password="sk-test",
        )

    @pytest.fixture
    def acr_config_acree(self) -> ACRConfig:
        return ACRConfig(
            registry="registry.cn-hangzhou.aliyuncs.com",
            namespace="test-ns",
            repo="test-repo",
            username="ak-test",
            password="sk-test",
            acree_instance_id="cri-test-123",
        )

    @pytest.fixture
    def builder(self) -> DockerBuilder:
        return DockerBuilder()

    def _apply_mocks(
        self,
        builder: DockerBuilder,
        mock_create: MagicMock,
    ) -> None:
        """Patch all subprocess-based methods on the builder."""
        builder.check_docker = MagicMock(return_value=True)  # type: ignore[method-assign]
        builder.build = MagicMock(return_value="test-repo:latest")  # type: ignore[method-assign]
        builder.login_acr_with_aksk = MagicMock(  # type: ignore[method-assign]
            return_value={
                "tempUserName": "tmp-user",
                "authorizationToken": "tmp-token",
            }
        )
        builder.tag = MagicMock()  # type: ignore[method-assign]
        builder.push = MagicMock()  # type: ignore[method-assign]

        mock_create.return_value = {
            "templateID": "tpl-official-001",
            "requestId": "req-001",
            "code": "200",
            "message": "",
            "statusCode": 200,
        }

    @pytest.mark.asyncio
    async def test_basic_official_flow(
        self,
        builder: DockerBuilder,
        acr_config: ACRConfig,
        tmp_path: Path,
    ) -> None:
        """Basic end-to-end official flow: build → push → CreateTemplate."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            result = await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr_config,
                name="test-tpl",
                tag="v1",
                cpu_count=4,
                memory_mb=4096,
                disk_size=10240,
                internet_access=True,
                generation=2,
                envd_inject=True,
                team_id="team-abc",
                region="cn-shanghai",
                acr_access_key_id="acr-ak",
                acr_access_key_secret="acr-sk",
                api_access_key_id="api-ak",
                api_access_key_secret="api-sk",
            )

        # Result assertions
        assert result.template_id == "tpl-official-001"
        assert result.build_status in ("ready", "submitted")
        assert result.acr_ref == "registry.cn-hangzhou.aliyuncs.com/test-ns/test-repo:v1"

        # Docker build was called
        builder.build.assert_called_once()

        # ACR login used ACR-specific credentials (not API creds)
        builder.login_acr_with_aksk.assert_called_once()
        login_args = builder.login_acr_with_aksk.call_args
        assert login_args[0][1] == "acr-ak"
        assert login_args[0][2] == "acr-sk"

        # create_official_template called with platform API creds
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["name"] == "test-tpl"
        assert call_kwargs["access_key_id"] == "api-ak"
        assert call_kwargs["access_key_secret"] == "api-sk"
        assert call_kwargs["cpu"] == 4
        assert call_kwargs["memory_size"] == 4096
        assert call_kwargs["disk_size"] == 10240
        assert call_kwargs["internet_access"] is True
        assert call_kwargs["generation"] == 2
        assert call_kwargs["envd_inject"] is True
        assert call_kwargs["team_id"] == "team-abc"
        assert call_kwargs["region"] == "cn-shanghai"
        assert call_kwargs["registry_type"] == "acr"  # no ACREE → acr
        assert call_kwargs["registry_username"] == "tmp-user"
        assert call_kwargs["registry_password"] == "tmp-token"

    @pytest.mark.asyncio
    async def test_acree_instance_sets_registry_type(
        self,
        builder: DockerBuilder,
        acr_config_acree: ACRConfig,
        tmp_path: Path,
    ) -> None:
        """When ACREE instance ID is present, registry_type must be 'acree'."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            result = await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr_config_acree,
                name="acree-tpl",
            )

        assert result.template_id == "tpl-official-001"
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["registry_type"] == "acree"
        assert call_kwargs["acr_instance_id"] == "cri-test-123"

    @pytest.mark.asyncio
    async def test_image_ref_format(
        self,
        builder: DockerBuilder,
        acr_config: ACRConfig,
        tmp_path: Path,
    ) -> None:
        """Image ref forwarded to create_official_template matches ACR tagged ref."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr_config,
                tag="build-42",
            )

        call_kwargs = mock_create.call_args.kwargs
        expected_image = "registry.cn-hangzhou.aliyuncs.com/test-ns/test-repo:build-42"
        assert call_kwargs["image"] == expected_image

    @pytest.mark.asyncio
    async def test_defaults(
        self,
        builder: DockerBuilder,
        acr_config: ACRConfig,
        tmp_path: Path,
    ) -> None:
        """Default values: cpu=2, memory=2048, disk=None, internet=None, generation=1."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr_config,
            )

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["cpu"] == 2
        assert call_kwargs["memory_size"] == 2048
        assert call_kwargs["disk_size"] is None
        assert call_kwargs["internet_access"] is None
        assert call_kwargs["generation"] == 1
        assert call_kwargs["envd_inject"] is False  # default for template deploy

    @pytest.mark.asyncio
    async def test_wheel_injection_called(
        self,
        builder: DockerBuilder,
        acr_config: ACRConfig,
        tmp_path: Path,
    ) -> None:
        """inject_sdk_wheel is called and returned wheels are cleaned up."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        fake_wheel = tmp_path / "easy_sandbox-0.0.0-py3-none-any.whl"
        fake_wheel.write_text("fake wheel")

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[fake_wheel],
            ) as mock_inject,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr_config,
            )

        mock_inject.assert_called_once()

    @pytest.mark.asyncio
    async def test_progress_callback(
        self,
        builder: DockerBuilder,
        acr_config: ACRConfig,
        tmp_path: Path,
    ) -> None:
        """Progress callback receives step messages."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")
        progress: list[str] = []

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr_config,
                on_progress=progress.append,
            )

        assert len(progress) >= 4
        assert any("Docker" in m for m in progress)
        assert any("ACR" in m or "Pushing" in m for m in progress)
        assert any(
            "official" in m.lower() or "CreateTemplate" in m or "Creating" in m for m in progress
        )

    @pytest.mark.asyncio
    async def test_no_docker_raises(
        self,
        builder: DockerBuilder,
        acr_config: ACRConfig,
        tmp_path: Path,
    ) -> None:
        """If Docker is not available, DockerBuildError is raised."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")
        from easy_sandbox.models.errors import DockerBuildError

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ):
            builder.check_docker = MagicMock(return_value=False)  # type: ignore[method-assign]

            with pytest.raises(DockerBuildError, match="not running"):
                await builder.build_and_register_official(
                    template_dir=tmp_path,
                    acr=acr_config,
                )

    # ------------------------------------------------------------------ #
    # Credential separation tests (task #68)
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_credential_separation(
        self,
        builder: DockerBuilder,
        tmp_path: Path,
    ) -> None:
        """ACR creds and platform API creds must be routed independently.

        Verifies that:
        - ``login_acr_with_aksk`` receives the ACR-specific credentials.
        - ``create_official_template`` receives the platform API credentials.
        - The two sets never leak into each other's call site.
        """
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        acr = ACRConfig(
            registry="registry.cn-hangzhou.aliyuncs.com",
            namespace="ns",
            repo="repo",
            username="acr-cfg-user",
            password="test-placeholder-token",
        )

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr,
                acr_access_key_id="explicit-acr-ak",
                acr_access_key_secret="test-placeholder-token",
                api_access_key_id="platform-api-ak",
                api_access_key_secret="test-placeholder-token",
            )

        # ACR login must use the explicit ACR credentials
        login_args = builder.login_acr_with_aksk.call_args
        assert login_args[0][1] == "explicit-acr-ak"
        assert login_args[0][2] == "test-placeholder-token"

        # CreateTemplate must use the platform API credentials
        api_kwargs = mock_create.call_args.kwargs
        assert api_kwargs["access_key_id"] == "platform-api-ak"
        assert api_kwargs["access_key_secret"] == "test-placeholder-token"

    @pytest.mark.asyncio
    async def test_acr_config_fallback_for_acr_creds(
        self,
        builder: DockerBuilder,
        tmp_path: Path,
    ) -> None:
        """When acr_access_key_id is not set, ACRConfig.username is used for ACR login."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        acr = ACRConfig(
            registry="registry.cn-hangzhou.aliyuncs.com",
            namespace="ns",
            repo="repo",
            username="cfg-user",
            password="test-placeholder-token",
        )

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr,
                # No acr_access_key_id → should fall back to acr.username
                api_access_key_id="platform-ak",
                api_access_key_secret="test-placeholder-token",
            )

        login_args = builder.login_acr_with_aksk.call_args
        assert login_args[0][1] == "cfg-user"
        assert login_args[0][2] == "test-placeholder-token"

        api_kwargs = mock_create.call_args.kwargs
        assert api_kwargs["access_key_id"] == "platform-ak"
        assert api_kwargs["access_key_secret"] == "test-placeholder-token"

    @pytest.mark.asyncio
    async def test_legacy_fallback_compat(
        self,
        builder: DockerBuilder,
        tmp_path: Path,
    ) -> None:
        """Legacy access_key_id/secret params still work as fallback for both."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        acr = ACRConfig(
            registry="registry.cn-hangzhou.aliyuncs.com",
            namespace="ns",
            repo="repo",
            # No username/password in ACRConfig
        )

        with (
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
                return_value=[],
            ),
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
        ):
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr,
                # Old-style: only legacy params, no acr_*/api_* params
                access_key_id="legacy-ak",
                access_key_secret="test-placeholder-token",
            )

        # Both should fall back to legacy params
        login_args = builder.login_acr_with_aksk.call_args
        assert login_args[0][1] == "legacy-ak"
        assert login_args[0][2] == "test-placeholder-token"

        api_kwargs = mock_create.call_args.kwargs
        assert api_kwargs["access_key_id"] == "legacy-ak"
        assert api_kwargs["access_key_secret"] == "test-placeholder-token"


# ---------------------------------------------------------------------------
# SDK wheel injection: source checkout vs. installed / standalone binary
# ---------------------------------------------------------------------------


class TestInjectSdkWheel:
    """``inject_sdk_wheel`` must yield a wheel wherever ebx is installed."""

    WHEEL = b"PK-fake-wheel-bytes"

    def _client_factory(self, handler: Any) -> Any:
        """Build a stand-in for ``httpx.Client`` served by *handler*."""
        real = httpx.Client

        def factory(**kwargs: Any) -> httpx.Client:
            return real(transport=httpx.MockTransport(handler), **kwargs)

        return factory

    def _pypi_handler(self, *, digest: str | None = None, wheels: bool = True) -> Any:
        sha = digest or hashlib.sha256(self.WHEEL).hexdigest()
        filename = "easy_sandbox-0.1.0-py3-none-any.whl"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/json"):
                urls = (
                    [
                        {
                            "packagetype": "sdist",
                            "filename": "easy_sandbox-0.1.0.tar.gz",
                            "url": "x",
                        },
                        {
                            "packagetype": "bdist_wheel",
                            "filename": filename,
                            "url": "https://files.example/" + filename,
                            "digests": {"sha256": sha},
                        },
                    ]
                    if wheels
                    else []
                )
                return httpx.Response(200, json={"urls": urls})
            return httpx.Response(200, content=self.WHEEL)

        return handler

    def test_installed_sdk_downloads_the_matching_release(self, tmp_path: Path) -> None:
        """Outside a source checkout the released wheel is injected into the context."""
        seen: list[str] = []
        inner = self._pypi_handler()

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return inner(request)

        with (
            patch.object(DockerBuilder, "_is_sdk_source_tree", return_value=False),
            patch("easy_sandbox.api.docker_builder.httpx.Client", self._client_factory(handler)),
        ):
            wheels = DockerBuilder.inject_sdk_wheel(tmp_path)

        assert [w.name for w in wheels] == ["easy_sandbox-0.1.0-py3-none-any.whl"]
        assert wheels[0].read_bytes() == self.WHEEL
        from easy_sandbox._version import __version__

        assert seen[0] == f"https://pypi.org/pypi/easy-sandbox/{__version__}/json"

    def test_frozen_binary_never_shells_out_to_pip(self, tmp_path: Path) -> None:
        """A PyInstaller binary has no pip: it must use the release download path."""
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(DockerBuilder, "_is_sdk_source_tree", return_value=True),
            patch("easy_sandbox.api.docker_builder.subprocess.run") as run,
            patch(
                "easy_sandbox.api.docker_builder.httpx.Client",
                self._client_factory(self._pypi_handler()),
            ),
        ):
            wheels = DockerBuilder.inject_sdk_wheel(tmp_path)

        run.assert_not_called()
        assert len(wheels) == 1

    def test_digest_mismatch_injects_nothing(self, tmp_path: Path) -> None:
        with (
            patch.object(DockerBuilder, "_is_sdk_source_tree", return_value=False),
            patch(
                "easy_sandbox.api.docker_builder.httpx.Client",
                self._client_factory(self._pypi_handler(digest="0" * 64)),
            ),
        ):
            assert DockerBuilder.inject_sdk_wheel(tmp_path) == []
        assert list(tmp_path.iterdir()) == []

    def test_unpublished_version_falls_back_quietly(self, tmp_path: Path) -> None:
        """A dev build (404 on PyPI) injects nothing; the Dockerfile installs from PyPI."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        with (
            patch.object(DockerBuilder, "_is_sdk_source_tree", return_value=False),
            patch("easy_sandbox.api.docker_builder.httpx.Client", self._client_factory(handler)),
        ):
            assert DockerBuilder.inject_sdk_wheel(tmp_path) == []

    def test_no_published_wheel_injects_nothing(self, tmp_path: Path) -> None:
        with (
            patch.object(DockerBuilder, "_is_sdk_source_tree", return_value=False),
            patch(
                "easy_sandbox.api.docker_builder.httpx.Client",
                self._client_factory(self._pypi_handler(wheels=False)),
            ),
        ):
            assert DockerBuilder.inject_sdk_wheel(tmp_path) == []

    def test_network_error_injects_nothing(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline")

        with (
            patch.object(DockerBuilder, "_is_sdk_source_tree", return_value=False),
            patch("easy_sandbox.api.docker_builder.httpx.Client", self._client_factory(handler)),
        ):
            assert DockerBuilder.inject_sdk_wheel(tmp_path) == []

    def test_source_checkout_still_builds_from_the_working_tree(self, tmp_path: Path) -> None:
        """In a dev checkout unreleased code must reach the image: no PyPI download."""
        built = MagicMock(returncode=0, stderr="")

        def fake_run(cmd: list[str], **_: Any) -> MagicMock:
            out_dir = Path(cmd[cmd.index("-w") + 1])
            (out_dir / "easy_sandbox-9.9.9-py3-none-any.whl").write_bytes(b"local")
            return built

        ctx = tmp_path / "ctx"
        ctx.mkdir()
        with (
            patch.object(sys, "frozen", False, create=True),
            patch.object(DockerBuilder, "_is_sdk_source_tree", return_value=True),
            patch("easy_sandbox.api.docker_builder.subprocess.run", side_effect=fake_run),
            patch.object(DockerBuilder, "_download_release_wheel") as download,
        ):
            wheels = DockerBuilder.inject_sdk_wheel(ctx)

        download.assert_not_called()
        assert [w.name for w in wheels] == ["easy_sandbox-9.9.9-py3-none-any.whl"]

    def test_source_tree_detection_requires_the_sdk_project(self, tmp_path: Path) -> None:
        """A venv living inside some *other* project must not be mistaken for the SDK."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-app"\n')
        assert DockerBuilder._is_sdk_source_tree(tmp_path) is False
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "easy-sandbox"\n')
        assert DockerBuilder._is_sdk_source_tree(tmp_path) is True
        assert DockerBuilder._is_sdk_source_tree(tmp_path / "missing") is False

    def test_this_checkout_is_detected_as_the_sdk_source_tree(self) -> None:
        root = Path(__file__).resolve().parents[2]
        assert DockerBuilder._is_sdk_source_tree(root) is True


class TestBuildProgress:
    def test_buildkit_build_streams_plain_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKER_BUILDKIT", "1")
        proc = MagicMock()
        proc.stdout = ["#2 [1/2] FROM python:3.12\n"]
        proc.returncode = 0
        seen: list[str] = []
        with patch("easy_sandbox.api.docker_builder.subprocess.Popen", return_value=proc) as popen:
            DockerBuilder().build(tmp_path, "app:latest", on_output=seen.append)
        command = popen.call_args.args[0]
        assert "--provenance=false" in command
        assert "--progress=plain" in command
        assert seen == ["#2 [1/2] FROM python:3.12"]

    def test_build_arg_values_are_redacted_in_the_info_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("DOCKER_BUILDKIT", "0")
        proc = MagicMock()
        proc.stdout = []
        proc.returncode = 0
        with (
            caplog.at_level("INFO", logger="easy_sandbox"),
            patch("easy_sandbox.api.docker_builder.subprocess.Popen", return_value=proc) as popen,
        ):
            DockerBuilder().build(
                tmp_path, "app:latest", build_args={"ACR_PASSWORD": "s3cret-value"}
            )
        command = popen.call_args.args[0]
        assert "ACR_PASSWORD=s3cret-value" in command
        assert "s3cret-value" not in caplog.text
        assert "ACR_PASSWORD=***" in caplog.text
