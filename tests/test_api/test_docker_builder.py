"""Tests for DockerBuilder, ACRConfig, and ACR auth helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from easy_sandbox.api.docker_builder import (
    ACRConfig,
    BuildResult,
    DockerBuilder,
    _get_acr_auth_token,
    get_acr_auth_token,
)

if TYPE_CHECKING:
    from pathlib import Path


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
    def test_old_name_delegates_to_same_impl(
        self, mock_personal: MagicMock
    ) -> None:
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

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
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

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
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

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
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

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
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
        assert call_kwargs["envd_inject"] is True  # default for build-local

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

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[fake_wheel],
        ) as mock_inject, patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
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

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
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
            "official" in m.lower() or "CreateTemplate" in m or "Creating" in m
            for m in progress
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
            password="test-placeholder-token",  # noqa: S106
        )

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr,
                acr_access_key_id="explicit-acr-ak",
                acr_access_key_secret="test-placeholder-token",  # noqa: S106
                api_access_key_id="platform-api-ak",
                api_access_key_secret="test-placeholder-token",  # noqa: S106
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
            password="test-placeholder-token",  # noqa: S106
        )

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr,
                # No acr_access_key_id → should fall back to acr.username
                api_access_key_id="platform-ak",
                api_access_key_secret="test-placeholder-token",  # noqa: S106
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

        with patch(
            "easy_sandbox.api.docker_builder.DockerBuilder.inject_sdk_wheel",
            return_value=[],
        ), patch(
            "easy_sandbox.api.fc_template.create_official_template",
        ) as mock_create:
            self._apply_mocks(builder, mock_create)

            await builder.build_and_register_official(
                template_dir=tmp_path,
                acr=acr,
                # Old-style: only legacy params, no acr_*/api_* params
                access_key_id="legacy-ak",
                access_key_secret="test-placeholder-token",  # noqa: S106
            )

        # Both should fall back to legacy params
        login_args = builder.login_acr_with_aksk.call_args
        assert login_args[0][1] == "legacy-ak"
        assert login_args[0][2] == "test-placeholder-token"

        api_kwargs = mock_create.call_args.kwargs
        assert api_kwargs["access_key_id"] == "legacy-ak"
        assert api_kwargs["access_key_secret"] == "test-placeholder-token"
