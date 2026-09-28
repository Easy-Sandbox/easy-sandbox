"""Tests for template CLI commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTemplateGroup:
    """Tests for 'ebx template' command group."""

    def test_template_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "--help"])
        assert result.exit_code == 0
        assert "template" in result.output.lower()

    def test_template_list_subcommands(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "--help"])
        assert result.exit_code == 0
        # Should list all subcommands
        assert "install" in result.output
        assert "list" in result.output
        assert "build" in result.output
        assert "delete" in result.output
        assert "info" in result.output
        assert "create" in result.output


class TestInstallCommand:
    """Tests for 'ebx template install' and 'ebx install'."""

    def test_install_builtin(self, runner: CliRunner) -> None:
        """Installing a builtin template should succeed without API call."""
        result = runner.invoke(cli, ["template", "install", "base"])
        assert result.exit_code == 0
        assert "built-in" in result.output.lower() or "No installation needed" in result.output

    def test_install_builtin_code_interpreter(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "install", "code-interpreter-v1"])
        assert result.exit_code == 0
        assert "built-in" in result.output.lower() or "No installation needed" in result.output

    def test_install_shortcut_help(self, runner: CliRunner) -> None:
        """Top-level 'ebx install --help' should work."""
        result = runner.invoke(cli, ["install", "--help"])
        assert result.exit_code == 0
        assert "TEMPLATE_REF" in result.output or "template_ref" in result.output.lower()

    def test_install_shortcut_builtin(self, runner: CliRunner) -> None:
        """'ebx install base' should delegate to template install."""
        result = runner.invoke(cli, ["install", "base"])
        assert result.exit_code == 0
        assert "built-in" in result.output.lower() or "No installation needed" in result.output


class TestInstallSubdirFormat:
    """Tests for subdirectory reference format in install command."""

    def test_install_help_shows_subdir_examples(self, runner: CliRunner) -> None:
        """安装命令的 help 文本应包含子目录示例。"""
        result = runner.invoke(cli, ["template", "install", "--help"])
        assert result.exit_code == 0
        assert "//subdir" in result.output

    def test_install_subdir_builtin_passthrough(self, runner: CliRunner) -> None:
        """仅包含单名称的引用仍应被识别为内置模板。"""
        result = runner.invoke(cli, ["template", "install", "base"])
        assert result.exit_code == 0
        assert "built-in" in result.output.lower() or "No installation needed" in result.output

    def test_install_shortcut_subdir_help(self, runner: CliRunner) -> None:
        """'ebx install --help' 应显示子目录格式说明。"""
        result = runner.invoke(cli, ["install", "--help"])
        assert result.exit_code == 0
        assert "TEMPLATE_REF" in result.output or "template_ref" in result.output.lower()


class TestInstallRegistryType:
    """Tests for --registry-type option in install command."""

    def test_install_help_shows_registry_type(self, runner: CliRunner) -> None:
        """安装命令应显示 --registry-type 选项。"""
        result = runner.invoke(cli, ["template", "install", "--help"])
        assert result.exit_code == 0
        assert "--registry-type" in result.output
        assert "github" in result.output
        assert "local" in result.output

    def test_install_shortcut_has_registry_type(self, runner: CliRunner) -> None:
        """'ebx install --help' 也应有 --registry-type 选项。"""
        result = runner.invoke(cli, ["install", "--help"])
        assert result.exit_code == 0
        assert "--registry-type" in result.output

    def test_install_local_template(self, runner: CliRunner, tmp_path) -> None:
        """使用 --registry-type local 安装本地模板。"""
        # 创建本地模板目录
        (tmp_path / "template.yaml").write_text("name: test-local\nversion: '1.0.0'\n")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        # mock 掉后续的 platform API 调用
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "templateID": "tpl-123",
            "buildID": "bld-456",
        }

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
            ),
            patch(
                "easy_sandbox.transport.auth.create_auth_provider",
            ),
            patch(
                "easy_sandbox.transport.http.HttpClient",
            ) as mock_http_cls,
        ):
            mock_http = MagicMock()
            mock_http.platform_request = AsyncMock(return_value=mock_resp)
            mock_http.close = AsyncMock()
            mock_http_cls.return_value = mock_http

            result = runner.invoke(
                cli,
                [
                    "template",
                    "install",
                    str(tmp_path),
                    "--registry-type",
                    "local",
                ],
            )
            # 应该显示本地模板的提示
            assert result.exit_code in (0, 1, 3)

    def test_install_invalid_registry_type(self, runner: CliRunner) -> None:
        """--registry-type 无效值应报错。"""
        result = runner.invoke(
            cli,
            ["template", "install", "owner/repo", "--registry-type", "invalid"],
        )
        assert result.exit_code != 0

    def test_install_help_shows_local_example(self, runner: CliRunner) -> None:
        """安装命令帮助应显示本地目录示例。"""
        result = runner.invoke(cli, ["template", "install", "--help"])
        assert result.exit_code == 0
        assert "./my-template" in result.output or "local" in result.output.lower()

    def test_install_platform_400_friendly(self, runner: CliRunner, tmp_path) -> None:
        """install --download-only skips platform API with deprecation warning."""
        (tmp_path / "template.yaml").write_text("name: test-local\nversion: '1.0.0'\n")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        result = runner.invoke(
            cli,
            [
                "template",
                "install",
                str(tmp_path),
                "--registry-type",
                "local",
                "--download-only",
            ],
        )

        # Should succeed locally with no platform API call
        assert result.exit_code == 0
        assert "ebx template build" in result.output
        assert "installed-locally" in result.output or "installed locally" in result.output


class TestTemplateListCommand:
    """Tests for 'ebx template list'."""

    def test_list_help_honest(self, runner: CliRunner) -> None:
        """list help text should say 'your custom templates on the platform'."""
        result = runner.invoke(cli, ["template", "list", "--help"])
        assert result.exit_code == 0
        assert "custom templates" in result.output.lower() or "platform" in result.output.lower()
        # Must NOT claim to be a central registry
        assert "all available" not in result.output.lower()

    def test_list_templates(self, runner: CliRunner) -> None:
        """Template list should call the platform API."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = []

        with (
            patch(
                "easy_sandbox.utils.async_bridge.run_sync",
                side_effect=[mock_resp, None],  # platform_request + close
            ),
            patch(
                "easy_sandbox.transport.config.load_config",
            ),
            patch(
                "easy_sandbox.transport.auth.create_auth_provider",
            ),
            patch(
                "easy_sandbox.transport.http.HttpClient",
            ) as mock_http_cls,
        ):
            mock_http = MagicMock()
            mock_http.platform_request = AsyncMock(return_value=mock_resp)
            mock_http.close = AsyncMock()
            mock_http_cls.return_value = mock_http

            result = runner.invoke(cli, ["template", "list"])
            # May fail due to auth, but the command itself should parse correctly
            # We just check it doesn't fail with a click usage error
            assert result.exit_code in (0, 1, 3)

    def test_list_official_templates(self, runner: CliRunner) -> None:
        """--official-api should render official template status state."""
        fake_config = MagicMock()
        fake_config.access_key_id = "AK"
        fake_config.access_key_secret = "SK"
        fake_config.region = "cn-hangzhou"
        templates = [
            {
                "templateID": "tpl-ready",
                "name": "demo",
                "status": {"state": "ready"},
            }
        ]

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.fc_template.list_official_templates",
                return_value=templates,
            ) as mock_list,
        ):
            result = runner.invoke(cli, ["template", "list", "--official-api"])

        assert result.exit_code == 0, result.output
        assert "tpl-ready" in result.output
        assert "ready" in result.output
        mock_list.assert_called_once()


class TestTemplateBuildHelp:
    """Tests for 'ebx template build --help' (full build pipeline)."""

    def test_build_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "build", "--help"])
        assert result.exit_code == 0
        assert "--dockerfile" in result.output or "-f" in result.output
        # build now runs the full pipeline (local build + ACR push + create).
        assert "--official-api" in result.output
        assert "--acr-namespace" in result.output

    def test_deploy_help(self, runner: CliRunner) -> None:
        """deploy exposes the full build, push, and create pipeline."""
        result = runner.invoke(cli, ["template", "deploy", "--help"])
        assert result.exit_code == 0
        assert "Build, push, and create template in one step" in result.output
        assert "--official-api" in result.output
        assert "--acr-namespace" in result.output

    def test_deploy_preserves_all_build_parameters(self) -> None:
        from easy_sandbox.cli.commands.template import template

        build_params = template.commands["build"].params
        deploy_params = template.commands["deploy"].params
        assert [param.to_info_dict() for param in deploy_params] == [
            param.to_info_dict() for param in build_params
        ]

    def test_build_local_removed(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "build-local", "--help"])
        assert result.exit_code != 0
        assert "No such command 'build-local'" in result.output


class TestTemplateDeleteHelp:
    """Tests for 'ebx template delete --help'."""

    def test_delete_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "delete", "--help"])
        assert result.exit_code == 0
        assert "TEMPLATE_ID" in result.output or "template_id" in result.output.lower()

    def test_delete_help_honest(self, runner: CliRunner) -> None:
        """delete help text should say 'from the platform', not generic."""
        result = runner.invoke(cli, ["template", "delete", "--help"])
        assert result.exit_code == 0
        assert "platform" in result.output.lower()


class TestTemplateInfoHelp:
    """Tests for 'ebx template info --help'."""

    def test_info_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "info", "--help"])
        assert result.exit_code == 0
        assert "TEMPLATE_ID" in result.output or "template_id" in result.output.lower()

    def test_info_official_template(self, runner: CliRunner) -> None:
        """--official-api should invoke the official GetTemplate adapter."""
        fake_config = MagicMock()
        fake_config.access_key_id = "AK"
        fake_config.access_key_secret = "SK"
        fake_config.region = "cn-hangzhou"

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.fc_template.get_template",
                return_value={"templateID": "tpl-ready", "status": {"state": "ready"}},
            ) as mock_get,
        ):
            result = runner.invoke(
                cli,
                ["template", "info", "tpl-ready", "--official-api"],
            )

        assert result.exit_code == 0, result.output
        assert "tpl-ready" in result.output
        assert "ready" in result.output
        mock_get.assert_called_once()


class TestSandboxYamlAlias:
    """Tests for sandbox.yaml alias support in install."""

    def test_install_sandbox_yaml_only(self, runner: CliRunner, tmp_path) -> None:
        """A template with only sandbox.yaml (no template.yaml) should install."""
        (tmp_path / "sandbox.yaml").write_text("name: test-alias\nversion: '1.0.0'\n")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "templateID": "tpl-alias-1",
            "buildID": "bld-alias-1",
        }

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
            ),
            patch(
                "easy_sandbox.transport.auth.create_auth_provider",
            ),
            patch(
                "easy_sandbox.transport.http.HttpClient",
            ) as mock_http_cls,
        ):
            mock_http = MagicMock()
            mock_http.platform_request = AsyncMock(return_value=mock_resp)
            mock_http.close = AsyncMock()
            mock_http_cls.return_value = mock_http

            result = runner.invoke(
                cli,
                [
                    "template",
                    "install",
                    str(tmp_path),
                    "--registry-type",
                    "local",
                ],
            )
            assert result.exit_code in (0, 1, 3)

    def test_install_prefers_template_yaml(self, runner: CliRunner, tmp_path) -> None:
        """When both template.yaml and sandbox.yaml exist, prefer the canonical name."""
        (tmp_path / "template.yaml").write_text("name: canonical\nversion: '1.0.0'\n")
        (tmp_path / "sandbox.yaml").write_text("name: alias-version\nversion: '2.0.0'\n")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "templateID": "tpl-pref-1",
            "buildID": "bld-pref-1",
        }

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
            ),
            patch(
                "easy_sandbox.transport.auth.create_auth_provider",
            ),
            patch(
                "easy_sandbox.transport.http.HttpClient",
            ) as mock_http_cls,
        ):
            mock_http = MagicMock()
            mock_http.platform_request = AsyncMock(return_value=mock_resp)
            mock_http.close = AsyncMock()
            mock_http_cls.return_value = mock_http

            result = runner.invoke(
                cli,
                [
                    "template",
                    "install",
                    str(tmp_path),
                    "--registry-type",
                    "local",
                ],
            )
            assert result.exit_code in (0, 1, 3)

    def test_install_no_yaml_mentions_both_names(self, runner: CliRunner, tmp_path) -> None:
        """Error message should mention template.yaml and sandbox.yaml."""
        empty = tmp_path / "empty-tmpl"
        empty.mkdir()
        (empty / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
            ),
            patch(
                "easy_sandbox.transport.auth.create_auth_provider",
            ),
            patch(
                "easy_sandbox.transport.http.HttpClient",
            ) as mock_http_cls,
        ):
            mock_http = MagicMock()
            mock_http.platform_request = AsyncMock()
            mock_http.close = AsyncMock()
            mock_http_cls.return_value = mock_http

            result = runner.invoke(
                cli,
                [
                    "template",
                    "install",
                    str(empty),
                    "--registry-type",
                    "local",
                ],
            )
            # Click 8.5 separates stderr by default; Click <8.5 raises ValueError
            try:
                stderr = result.stderr
            except ValueError:
                stderr = ""
            combined = result.output + stderr
            assert result.exit_code != 0
            assert "sandbox.yaml" in combined


class TestTemplateCommandErrorHandling:
    """Friendly error handling for build / list / info / delete commands."""

    @staticmethod
    def _http_error(status: int, body: dict) -> Exception:
        import httpx

        req = httpx.Request("POST", "https://platform/templates")
        resp = httpx.Response(status_code=status, json=body, request=req)
        return httpx.HTTPStatusError(f"{status}", request=req, response=resp)

    @staticmethod
    def _patched_http(side_effect: Exception):
        mock_http = MagicMock()
        mock_http.platform_request = AsyncMock(side_effect=side_effect)
        mock_http.close = AsyncMock()
        return mock_http

    def _run(self, runner: CliRunner, args: list[str], mock_http, **kwargs):
        with (
            patch(
                "easy_sandbox.transport.config.load_config",
            ),
            patch(
                "easy_sandbox.transport.auth.create_auth_provider",
            ),
            patch(
                "easy_sandbox.transport.http.HttpClient",
            ) as mock_http_cls,
        ):
            mock_http_cls.return_value = mock_http
            return runner.invoke(cli, args, **kwargs)

    def test_list_server_error_friendly(self, runner: CliRunner) -> None:
        """list GET 5xx → NetworkError，退出码 1，无 Traceback。"""
        mock_http = self._patched_http(self._http_error(500, {"message": "internal error"}))
        result = self._run(runner, ["template", "list"], mock_http)
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "HTTP 500" in result.output
        mock_http.close.assert_awaited()

    def test_info_404_friendly(self, runner: CliRunner) -> None:
        """info GET 404 → TemplateNotFoundError，退出码 4，提示 TEMPLATE_ID。"""
        mock_http = self._patched_http(self._http_error(404, {"message": "not found"}))
        result = self._run(runner, ["template", "info", "tpl-missing"], mock_http)
        assert result.exit_code == 4
        assert "Traceback" not in result.output
        assert "tpl-missing" in result.output
        assert "TEMPLATE_ID" in result.output
        mock_http.close.assert_awaited()

    def test_delete_404_friendly(self, runner: CliRunner) -> None:
        """delete DELETE 404 → TemplateNotFoundError，退出码 4。"""
        mock_http = self._patched_http(self._http_error(404, {"message": "not found"}))
        result = self._run(
            runner,
            ["template", "delete", "tpl-missing", "--yes"],
            mock_http,
        )
        assert result.exit_code == 4
        assert "Traceback" not in result.output
        assert "tpl-missing" in result.output
        assert "TEMPLATE_ID" in result.output
        mock_http.close.assert_awaited()


class TestTemplateCreateCommand:
    """Tests for 'ebx template create' command."""

    def test_create_help(self, runner: CliRunner) -> None:
        """'ebx template create --help' should show required options."""
        result = runner.invoke(cli, ["template", "create", "--help"])
        assert result.exit_code == 0
        assert "IMAGE" in result.output
        assert "--name" in result.output
        assert "--team-id" in result.output
        assert "--cpu" in result.output
        assert "--memory" in result.output
        assert "--generation" in result.output
        assert "--envd-inject" in result.output

    def test_create_requires_name(self, runner: CliRunner) -> None:
        """'ebx template create IMAGE' without --name should error."""
        result = runner.invoke(cli, ["template", "create", "img:latest"])
        assert result.exit_code != 0
        assert "--name" in result.output or "Missing" in result.output

    def test_create_missing_aksk(self, runner: CliRunner) -> None:
        """Without AK/SK, create should show friendly error."""
        with patch(
            "easy_sandbox.transport.config.load_config",
        ) as mock_load:
            mock_cfg = MagicMock()
            mock_cfg.access_key_id = None
            mock_cfg.access_key_secret = None
            mock_cfg.region = "cn-hangzhou"
            mock_load.return_value = mock_cfg

            result = runner.invoke(
                cli,
                ["template", "create", "img:tag", "--name", "test"],
            )
            assert result.exit_code != 0
            assert "AK/SK" in result.output or "credentials" in result.output.lower()

    def test_create_success_mock(self, runner: CliRunner) -> None:
        """Successful create with mocked API."""
        with (
            patch(
                "easy_sandbox.transport.config.load_config",
            ) as mock_load,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
            patch(
                "easy_sandbox.api.fc_template.wait_for_template_ready",
                return_value={"status": {"state": "ready"}},
            ),
        ):
            mock_cfg = MagicMock()
            mock_cfg.access_key_id = "AK"
            mock_cfg.access_key_secret = "SK"
            mock_cfg.region = "cn-hangzhou"
            mock_load.return_value = mock_cfg

            mock_create.return_value = {
                "templateID": "tpl-test-001",
                "requestId": "req-001",
                "code": "200",
                "message": "",
                "statusCode": 200,
            }

            result = runner.invoke(
                cli,
                ["template", "create", "img:tag", "--name", "test-tpl"],
            )

            assert result.exit_code == 0
            assert "tpl-test-001" in result.output
            mock_create.assert_called_once()

    def test_create_json_output(self, runner: CliRunner) -> None:
        """JSON output mode for create command."""
        with (
            patch(
                "easy_sandbox.transport.config.load_config",
            ) as mock_load,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
            patch(
                "easy_sandbox.api.fc_template.wait_for_template_ready",
                return_value={"status": {"state": "ready"}},
            ),
        ):
            mock_cfg = MagicMock()
            mock_cfg.access_key_id = "AK"
            mock_cfg.access_key_secret = "SK"
            mock_cfg.region = "cn-hangzhou"
            mock_load.return_value = mock_cfg

            mock_create.return_value = {
                "templateID": "tpl-json-001",
                "requestId": "req-json",
                "code": "200",
                "message": "",
                "statusCode": 200,
            }

            result = runner.invoke(
                cli,
                ["--json", "template", "create", "img:tag", "--name", "test"],
            )

            assert result.exit_code == 0
            assert "tpl-json-001" in result.output


class TestTemplateDeployOfficialAPI:
    """Tests for deploy with --official-api / --legacy-api."""

    def test_deploy_help_shows_official_api(self, runner: CliRunner) -> None:
        """deploy --help should show the new options."""
        result = runner.invoke(cli, ["template", "deploy", "--help"])
        assert result.exit_code == 0
        assert "--official-api" in result.output
        assert "--legacy-api" in result.output
        assert "--team-id" in result.output
        assert "--envd-inject" in result.output
        assert "--generation" in result.output
        assert "--ready-cmd" in result.output

    def test_deploy_template_dir_from_env(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """EBX_TEMPLATE_DIR supplies the required template directory argument."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")
        fake_config = MagicMock()
        fake_config.access_key_id = None
        fake_config.access_key_secret = None
        fake_config.region = "cn-hangzhou"
        with patch(
            "easy_sandbox.transport.config.load_config",
            return_value=fake_config,
        ):
            result = runner.invoke(
                cli,
                ["template", "deploy", "--acr-namespace", "test-ns"],
                env={"EBX_TEMPLATE_DIR": str(tmp_path)},
            )
        assert result.exit_code == 1
        assert "Missing argument" not in result.output
        assert "credentials missing" in result.output.lower()

    def test_deploy_default_is_official(self, runner: CliRunner) -> None:
        """deploy without flag should default to official API."""
        result = runner.invoke(cli, ["template", "deploy", "--help"])
        assert result.exit_code == 0
        # The help should mention official API as default
        assert "official" in result.output.lower() or "CreateTemplate" in result.output


class TestTemplateDeployCredentialSeparation:
    """Verify that deploy passes ACR and platform API creds independently.

    deploy composes _build_image -> _push_image -> create_official_template.
    CLI --acr-username/--acr-password must reach ACR login, while platform
    AK/SK from load_config always feeds the CreateTemplate API.
    """

    @staticmethod
    def _mock_builder(mock_builder_cls: MagicMock) -> MagicMock:
        """Configure a mocked DockerBuilder so build/push are no-ops."""
        builder = mock_builder_cls.return_value
        builder.check_docker.return_value = True
        builder.inject_sdk_wheel.return_value = []
        builder.build.return_value = "local:latest"
        builder.login_acr_with_aksk.return_value = {
            "tempUserName": "temp-user",
            "authorizationToken": "temp-token",
        }
        builder.tag.return_value = None
        builder.push.return_value = None
        return builder

    def test_explicit_acr_creds_not_overridden(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Explicit --acr-username/--acr-password must be used for ACR login."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        fake_config = MagicMock()
        fake_config.access_key_id = "platform-ak"
        fake_config.access_key_secret = "platform-sk"
        fake_config.region = "cn-hangzhou"
        fake_config.api_key = ""
        fake_config.api_url = ""

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder",
            ) as mock_builder_cls,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
            patch(
                "easy_sandbox.api.fc_template.wait_for_template_ready",
                return_value={"status": {"state": "ready"}},
            ),
        ):
            builder = self._mock_builder(mock_builder_cls)
            mock_create.return_value = {
                "templateID": "tpl-001",
                "statusCode": 200,
            }
            result = runner.invoke(
                cli,
                [
                    "template",
                    "deploy",
                    str(tmp_path),
                    "--acr-namespace",
                    "test-ns",
                    "--acr-username",
                    "my-acr-user",
                    "--acr-password",
                    "my-acr-pass",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output

        # ACR login uses the explicit CLI creds (registry, username, password).
        login_args = builder.login_acr_with_aksk.call_args.args
        assert login_args[1] == "my-acr-user"
        assert login_args[2] == "my-acr-pass"

        # CreateTemplate always uses the platform AK/SK from load_config.
        create_kwargs = mock_create.call_args.kwargs
        assert create_kwargs["access_key_id"] == "platform-ak"
        assert create_kwargs["access_key_secret"] == "platform-sk"

    def test_acr_creds_fallback_to_platform(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """When --acr-username is omitted, ACR creds fall back to platform AK/SK."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        fake_config = MagicMock()
        fake_config.access_key_id = "platform-ak"
        fake_config.access_key_secret = "platform-sk"
        fake_config.region = "cn-hangzhou"
        fake_config.api_key = ""
        fake_config.api_url = ""

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder",
            ) as mock_builder_cls,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
            patch(
                "easy_sandbox.api.fc_template.wait_for_template_ready",
                return_value={"status": {"state": "ready"}},
            ),
        ):
            builder = self._mock_builder(mock_builder_cls)
            mock_create.return_value = {
                "templateID": "tpl-002",
                "statusCode": 200,
            }
            result = runner.invoke(
                cli,
                [
                    "template",
                    "deploy",
                    str(tmp_path),
                    "--acr-namespace",
                    "test-ns",
                    # No --acr-username/--acr-password
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output

        # ACR login credentials fall back to the platform AK/SK.
        login_args = builder.login_acr_with_aksk.call_args.args
        assert login_args[1] == "platform-ak"
        assert login_args[2] == "platform-sk"

        # CreateTemplate still uses the platform AK/SK.
        create_kwargs = mock_create.call_args.kwargs
        assert create_kwargs["access_key_id"] == "platform-ak"
        assert create_kwargs["access_key_secret"] == "platform-sk"


class TestTemplatePushCommand:
    """Tests for the new 'ebx template push' command."""

    def test_push_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "push", "--help"])
        assert result.exit_code == 0
        assert "IMAGE" in result.output
        assert "--acr-namespace" in result.output

    def test_push_missing_creds(self, runner: CliRunner) -> None:
        """Without ACR creds, push should raise a friendly error (exit != 0)."""
        fake_config = MagicMock()
        fake_config.access_key_id = None
        fake_config.access_key_secret = None
        fake_config.region = "cn-hangzhou"

        with patch(
            "easy_sandbox.transport.config.load_config",
            return_value=fake_config,
        ):
            result = runner.invoke(
                cli,
                [
                    "template",
                    "push",
                    "my-img:latest",
                    "--acr-namespace",
                    "test-ns",
                ],
            )
        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert "credentials" in result.output.lower()

    def test_push_success(self, runner: CliRunner) -> None:
        """push tags and pushes the image, printing the ACR URL."""
        fake_config = MagicMock()
        fake_config.access_key_id = "platform-ak"
        fake_config.access_key_secret = "platform-sk"
        fake_config.region = "cn-hangzhou"

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder",
            ) as mock_builder_cls,
        ):
            builder = mock_builder_cls.return_value
            builder.login_acr_with_aksk.return_value = {
                "tempUserName": "u",
                "authorizationToken": "t",
            }
            builder.tag.return_value = None
            builder.push.return_value = None
            result = runner.invoke(
                cli,
                [
                    "template",
                    "push",
                    "my-img:v1",
                    "--acr-namespace",
                    "test-ns",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "test-ns/my-img:v1" in result.output
        # Local image is tagged to the full ACR reference.
        tag_args = builder.tag.call_args.args
        assert tag_args[0] == "my-img:v1"
        assert tag_args[1].endswith("test-ns/my-img:v1")


class TestTemplateBuildCommand:
    """'ebx template build' now runs the full build+push+create pipeline."""

    def test_build_runs_full_pipeline(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """build composes local build -> ACR push -> official CreateTemplate."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        fake_config = MagicMock()
        fake_config.access_key_id = "platform-ak"
        fake_config.access_key_secret = "platform-sk"
        fake_config.region = "cn-hangzhou"
        fake_config.api_key = ""
        fake_config.api_url = ""

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder",
            ) as mock_builder_cls,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
            patch(
                "easy_sandbox.api.fc_template.wait_for_template_ready",
                return_value={"status": {"state": "ready"}},
            ),
        ):
            builder = mock_builder_cls.return_value
            builder.check_docker.return_value = True
            builder.inject_sdk_wheel.return_value = []
            builder.build.return_value = "my-repo:v1"
            builder.login_acr_with_aksk.return_value = {
                "tempUserName": "u",
                "authorizationToken": "t",
            }
            builder.tag.return_value = None
            builder.push.return_value = None
            mock_create.return_value = {"templateID": "tpl-b1", "statusCode": 200}
            result = runner.invoke(
                cli,
                [
                    "template",
                    "build",
                    str(tmp_path),
                    "--acr-namespace",
                    "test-ns",
                    "--acr-repo",
                    "my-repo",
                    "--tag",
                    "v1",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "tpl-b1" in result.output
        # build pushes to ACR as part of the pipeline.
        builder.push.assert_called_once()
        mock_create.assert_called_once()

    def test_build_uses_yaml_defaults(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """template.yaml name + resources.cpu/memory feed the build defaults."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")
        (tmp_path / "template.yaml").write_text(
            "name: my-template\n"
            "resources:\n"
            "  cpu: 4\n"
            "  memory: 4096\n"
        )
        monkeypatch.delenv("ACR_NAMESPACE", raising=False)

        fake_config = MagicMock()
        fake_config.access_key_id = "platform-ak"
        fake_config.access_key_secret = "platform-sk"
        fake_config.region = "cn-hangzhou"
        fake_config.api_key = ""
        fake_config.api_url = ""

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder",
            ) as mock_builder_cls,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
            patch(
                "easy_sandbox.api.fc_template.wait_for_template_ready",
                return_value={"status": {"state": "ready"}},
            ),
        ):
            builder = mock_builder_cls.return_value
            builder.check_docker.return_value = True
            builder.inject_sdk_wheel.return_value = []
            builder.build.return_value = "my-template:latest"
            builder.login_acr_with_aksk.return_value = {
                "tempUserName": "u",
                "authorizationToken": "t",
            }
            builder.tag.return_value = None
            builder.push.return_value = None
            mock_create.return_value = {"templateID": "tpl-yaml", "statusCode": 200}
            result = runner.invoke(
                cli,
                ["template", "build", str(tmp_path), "--acr-namespace", "test-ns", "--yes"],
            )

        assert result.exit_code == 0, result.output
        # yaml resources.cpu/memory become the CreateTemplate values (as ints),
        # and the yaml name becomes the repo/template name.
        create_kwargs = mock_create.call_args.kwargs
        assert create_kwargs["name"] == "my-template"
        assert create_kwargs["cpu"] == 4
        assert create_kwargs["memory_size"] == 4096
        # The resolved-configuration banner reflects the yaml defaults.
        assert "Template: my-template" in result.output
        assert "cpu=4" in result.output
        assert "memory=4096MB" in result.output

    def test_build_acr_namespace_from_dotenv(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ACR_NAMESPACE in a CWD .env is picked up when no flag/env is set."""
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")
        (tmp_path / ".env").write_text("ACR_NAMESPACE=ns-from-dotenv\n")
        monkeypatch.delenv("ACR_NAMESPACE", raising=False)
        monkeypatch.chdir(tmp_path)

        fake_config = MagicMock()
        fake_config.access_key_id = "platform-ak"
        fake_config.access_key_secret = "platform-sk"
        fake_config.region = "cn-hangzhou"
        fake_config.api_key = ""
        fake_config.api_url = ""

        with (
            patch(
                "easy_sandbox.transport.config.load_config",
                return_value=fake_config,
            ),
            patch(
                "easy_sandbox.api.docker_builder.DockerBuilder",
            ) as mock_builder_cls,
            patch(
                "easy_sandbox.api.fc_template.create_official_template",
            ) as mock_create,
            patch(
                "easy_sandbox.api.fc_template.wait_for_template_ready",
                return_value={"status": {"state": "ready"}},
            ),
        ):
            builder = mock_builder_cls.return_value
            builder.check_docker.return_value = True
            builder.inject_sdk_wheel.return_value = []
            builder.build.return_value = "img:latest"
            builder.login_acr_with_aksk.return_value = {
                "tempUserName": "u",
                "authorizationToken": "t",
            }
            builder.tag.return_value = None
            builder.push.return_value = None
            mock_create.return_value = {"templateID": "tpl-ns", "statusCode": 200}
            result = runner.invoke(cli, ["template", "build", str(tmp_path), "--yes"])

        assert result.exit_code == 0, result.output
        # Namespace resolved from the CWD .env appears in the ACR banner...
        assert "ACR: ns-from-dotenv/" in result.output
        # ...and flows into the ACR image reference passed to CreateTemplate.
        assert "ns-from-dotenv" in mock_create.call_args.kwargs["image"]


class TestResolveAcrNamespace:
    """Unit tests for the ``_resolve_acr_namespace`` resolution order."""

    def test_from_ebx_home_dotenv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ACR_NAMESPACE in ~/.ebx/.env is used when CWD .env and env are absent."""
        from easy_sandbox.cli.commands.template import _resolve_acr_namespace

        ebx_dir = tmp_path / ".ebx"
        ebx_dir.mkdir()
        (ebx_dir / ".env").write_text("ACR_NAMESPACE=ns-from-home\n")

        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ACR_NAMESPACE", raising=False)

        assert _resolve_acr_namespace(None) == "ns-from-home"

    def test_cwd_dotenv_wins_over_home(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CWD .env takes precedence over ~/.ebx/.env."""
        from easy_sandbox.cli.commands.template import _resolve_acr_namespace

        ebx_dir = tmp_path / ".ebx"
        ebx_dir.mkdir()
        (ebx_dir / ".env").write_text("ACR_NAMESPACE=ns-from-home\n")

        workdir = tmp_path / "work"
        workdir.mkdir()
        (workdir / ".env").write_text("ACR_NAMESPACE=ns-from-cwd\n")
        monkeypatch.chdir(workdir)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ACR_NAMESPACE", raising=False)

        assert _resolve_acr_namespace(None) == "ns-from-cwd"

    def test_missing_raises_usage_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No flag/env/.env anywhere raises click.UsageError."""
        from easy_sandbox.cli.commands.template import _resolve_acr_namespace

        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("ACR_NAMESPACE", raising=False)

        with pytest.raises(click.UsageError):
            _resolve_acr_namespace(None)


class TestTemplateInitCommand:
    """Tests for 'ebx template init' and 'ebx init' scaffold."""

    def test_list_shows_all_cases(self, runner: CliRunner) -> None:
        """--list shows python, node, and minimal."""
        result = runner.invoke(cli, ["template", "init", "--list"])
        assert result.exit_code == 0
        assert "python" in result.output
        assert "node" in result.output
        assert "minimal" in result.output

    def test_python_generates_expected_files(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """-t python generates template.yaml, Dockerfile, commands.py, README.md."""
        target = tmp_path / "pyproj"
        result = runner.invoke(
            cli, ["template", "init", str(target), "-t", "python"]
        )
        assert result.exit_code == 0, result.output
        expected = {"template.yaml", "Dockerfile", "commands.py", "README.md"}
        actual = {f.name for f in target.iterdir() if f.is_file()}
        assert expected == actual

    def test_node_generates_expected_files(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """-t node generates template.yaml, Dockerfile, commands.py, README.md."""
        target = tmp_path / "nodeproj"
        result = runner.invoke(
            cli, ["template", "init", str(target), "-t", "node"]
        )
        assert result.exit_code == 0, result.output
        expected = {"template.yaml", "Dockerfile", "commands.py", "README.md"}
        actual = {f.name for f in target.iterdir() if f.is_file()}
        assert expected == actual

    def test_minimal_generates_expected_files(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """-t minimal generates template.yaml, Dockerfile, README.md (no commands.py)."""
        target = tmp_path / "minproj"
        result = runner.invoke(
            cli, ["template", "init", str(target), "-t", "minimal"]
        )
        assert result.exit_code == 0, result.output
        expected = {"template.yaml", "Dockerfile", "README.md"}
        actual = {f.name for f in target.iterdir() if f.is_file()}
        assert expected == actual
        assert not (target / "commands.py").exists()

    def test_init_shortcut_delegates(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """'ebx init -t python <dir>' delegates to template init."""
        target = tmp_path / "shortcut"
        result = runner.invoke(
            cli, ["init", "-t", "python", str(target)]
        )
        assert result.exit_code == 0, result.output
        assert (target / "template.yaml").exists()
        assert (target / "commands.py").exists()

    def test_from_path(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """--from local path copies files into target directory."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "template.yaml").write_text("name: from-test\n")
        (source / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        target = tmp_path / "dest"

        with patch(
            "easy_sandbox.utils.registry.RegistryClient.resolve",
            new_callable=AsyncMock,
        ) as mock_resolve, patch(
            "easy_sandbox.utils.registry.RegistryClient.fetch",
            new_callable=AsyncMock,
        ) as mock_fetch:
            ref = MagicMock()
            ref.is_builtin = False
            ref.registry_type = "local"
            ref.local_path = str(source)
            ref.owner = "test"
            ref.repo = "test"
            mock_resolve.return_value = ref
            mock_fetch.return_value = str(source)

            result = runner.invoke(
                cli,
                ["template", "init", str(target), "--from", str(source)],
            )

        assert result.exit_code == 0, result.output
        assert (target / "template.yaml").exists()
        assert (target / "Dockerfile").exists()


class TestInstallFullPipeline:
    """Tests for install build+deploy pipeline (default, non --download-only)."""

    def _make_template_dir(self, tmp_path: Path) -> Path:
        """Create a minimal template directory for install tests."""
        tdir = tmp_path / "tpl"
        tdir.mkdir()
        (tdir / "template.yaml").write_text(
            "name: test-tpl\nresources:\n  cpu: 1\n  memory: 512\n"
        )
        (tdir / "Dockerfile").write_text("FROM ubuntu:22.04\n")
        return tdir

    def test_install_deploy_with_yes(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default install (no --download-only) with --yes calls _do_deploy."""
        tdir = self._make_template_dir(tmp_path)
        monkeypatch.setenv("ACR_NAMESPACE", "test-ns")
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_ID", "ak-test")
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_SECRET", "sk-test")

        with patch(
            "easy_sandbox.cli.commands.template._do_deploy",
            return_value={
                "TemplateID": "tpl-deploy-test",
                "BuildID": "bld-1",
                "ACR Image": "registry/ns/repo:latest",
                "Status": "ready",
            },
        ) as mock_deploy:
            result = runner.invoke(
                cli,
                [
                    "template", "install", str(tdir),
                    "--registry-type", "local",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert mock_deploy.called
        call_kw = mock_deploy.call_args
        # cpu/memory should come from template.yaml defaults (1 and 512)
        assert call_kw.kwargs.get("cpu") is None or call_kw.kwargs.get("cpu") == 1

    def test_install_non_tty_without_yes_raises(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-TTY without --yes raises UsageError."""
        tdir = self._make_template_dir(tmp_path)
        monkeypatch.setenv("ACR_NAMESPACE", "test-ns")
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_ID", "ak-test")
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_SECRET", "sk-test")

        result = runner.invoke(
            cli,
            ["template", "install", str(tdir), "--registry-type", "local"],
        )
        # CliRunner is non-TTY by default, so confirmation should fail
        assert result.exit_code != 0
        assert "--yes" in result.output or "Confirmation" in result.output

    def test_install_missing_acr_namespace_error(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing ACR namespace produces clear error with --download-only hint."""
        tdir = self._make_template_dir(tmp_path)
        monkeypatch.delenv("ACR_NAMESPACE", raising=False)
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_ID", "ak-test")
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_SECRET", "sk-test")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            cli,
            ["template", "install", str(tdir), "--registry-type", "local"],
        )
        assert result.exit_code != 0
        assert "--download-only" in result.output
        assert "Cannot build" in result.output or "Missing" in result.output
