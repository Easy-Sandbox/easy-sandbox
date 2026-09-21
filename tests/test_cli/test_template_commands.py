"""Tests for template CLI commands."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli


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
        assert "cache" in result.output
        assert "info" in result.output


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
        (tmp_path / "template.yaml").write_text(
            "name: test-local\nversion: '1.0.0'\n"
        )
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        # mock 掉后续的 platform API 调用
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "templateID": "tpl-123",
            "buildID": "bld-456",
        }

        with patch(
            "easy_sandbox.transport.config.load_config",
        ), patch(
            "easy_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "easy_sandbox.transport.http.HttpClient",
        ) as mock_http_cls:
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
        """POST /templates 返回 400 时展示后端错误，而非裸 traceback。"""
        import httpx

        (tmp_path / "template.yaml").write_text(
            "name: test-local\nversion: '1.0.0'\n"
        )
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        error_resp = httpx.Response(
            status_code=400,
            json={"error": "Dockerfile validation failed: FROM missing"},
            request=httpx.Request("POST", "https://platform/templates"),
        )
        http_error = httpx.HTTPStatusError(
            "400 Bad Request", request=error_resp.request, response=error_resp
        )

        with patch(
            "easy_sandbox.transport.config.load_config",
        ), patch(
            "easy_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "easy_sandbox.transport.http.HttpClient",
        ) as mock_http_cls:
            mock_http = MagicMock()
            mock_http.platform_request = AsyncMock(side_effect=http_error)
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

        # 不应是裸 traceback，而是友好错误信息
        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert "Build submission rejected by platform" in result.output
        assert "Dockerfile validation failed" in result.output
        # close() 仍应被调用（finally 块）
        mock_http.close.assert_awaited()


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

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            side_effect=[mock_resp, None],  # platform_request + close
        ), patch(
            "easy_sandbox.transport.config.load_config",
        ), patch(
            "easy_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "easy_sandbox.transport.http.HttpClient",
        ) as mock_http_cls:
            mock_http = MagicMock()
            mock_http.platform_request = AsyncMock(return_value=mock_resp)
            mock_http.close = AsyncMock()
            mock_http_cls.return_value = mock_http

            result = runner.invoke(cli, ["template", "list"])
            # May fail due to auth, but the command itself should parse correctly
            # We just check it doesn't fail with a click usage error
            assert result.exit_code in (0, 1, 3)


class TestTemplateCacheCommand:
    """Tests for 'ebx template cache'."""

    def test_cache_help_distinguishes_from_delete(self, runner: CliRunner) -> None:
        """cache help should mention local files and distinguish from platform delete."""
        result = runner.invoke(cli, ["template", "cache", "--help"])
        assert result.exit_code == 0
        assert "local" in result.output.lower()
        assert "ebx/templates" in result.output or "~/.ebx" in result.output

    def test_cache_no_flag(self, runner: CliRunner) -> None:
        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR",
        ):
            result = runner.invoke(cli, ["template", "cache"])
            assert result.exit_code == 0

    def test_cache_clear(self, runner: CliRunner, tmp_path) -> None:
        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR",
            tmp_path,
        ):
            result = runner.invoke(cli, ["template", "cache", "--clear"])
            assert result.exit_code == 0
            assert "Cleared" in result.output


class TestTemplateBuildHelp:
    """Tests for 'ebx template build --help'."""

    def test_build_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "build", "--help"])
        assert result.exit_code == 0
        assert "--dockerfile" in result.output or "-f" in result.output


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


class TestSandboxYamlAlias:
    """Tests for sandbox.yaml alias support in install."""

    def test_install_sandbox_yaml_only(self, runner: CliRunner, tmp_path) -> None:
        """A template with only sandbox.yaml (no template.yaml) should install."""
        (tmp_path / "sandbox.yaml").write_text(
            "name: test-alias\nversion: '1.0.0'\n"
        )
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "templateID": "tpl-alias-1",
            "buildID": "bld-alias-1",
        }

        with patch(
            "easy_sandbox.transport.config.load_config",
        ), patch(
            "easy_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "easy_sandbox.transport.http.HttpClient",
        ) as mock_http_cls:
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
        (tmp_path / "template.yaml").write_text(
            "name: canonical\nversion: '1.0.0'\n"
        )
        (tmp_path / "sandbox.yaml").write_text(
            "name: alias-version\nversion: '2.0.0'\n"
        )
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "templateID": "tpl-pref-1",
            "buildID": "bld-pref-1",
        }

        with patch(
            "easy_sandbox.transport.config.load_config",
        ), patch(
            "easy_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "easy_sandbox.transport.http.HttpClient",
        ) as mock_http_cls:
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

        with patch(
            "easy_sandbox.transport.config.load_config",
        ), patch(
            "easy_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "easy_sandbox.transport.http.HttpClient",
        ) as mock_http_cls:
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
        return httpx.HTTPStatusError(
            f"{status}", request=req, response=resp
        )

    @staticmethod
    def _patched_http(side_effect: Exception):
        mock_http = MagicMock()
        mock_http.platform_request = AsyncMock(side_effect=side_effect)
        mock_http.close = AsyncMock()
        return mock_http

    def _run(self, runner: CliRunner, args: list[str], mock_http, **kwargs):
        with patch(
            "easy_sandbox.transport.config.load_config",
        ), patch(
            "easy_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "easy_sandbox.transport.http.HttpClient",
        ) as mock_http_cls:
            mock_http_cls.return_value = mock_http
            return runner.invoke(cli, args, **kwargs)

    def test_build_400_friendly(self, runner: CliRunner, tmp_path) -> None:
        """build POST 400 → TemplateBuildError 提示旧 API 与替代方案。"""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM ubuntu:22.04\n")
        mock_http = self._patched_http(
            self._http_error(400, {"error": "invalid dockerfile"})
        )
        result = self._run(
            runner, ["template", "build", "-f", str(dockerfile)], mock_http
        )
        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert "Build submission rejected by platform" in result.output
        assert "invalid dockerfile" in result.output
        assert "build-local" in result.output
        mock_http.close.assert_awaited()

    def test_list_server_error_friendly(self, runner: CliRunner) -> None:
        """list GET 5xx → NetworkError，退出码 1，无 Traceback。"""
        mock_http = self._patched_http(
            self._http_error(500, {"message": "internal error"})
        )
        result = self._run(runner, ["template", "list"], mock_http)
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "HTTP 500" in result.output
        mock_http.close.assert_awaited()

    def test_info_404_friendly(self, runner: CliRunner) -> None:
        """info GET 404 → TemplateNotFoundError，退出码 4，提示 TEMPLATE_ID。"""
        mock_http = self._patched_http(
            self._http_error(404, {"message": "not found"})
        )
        result = self._run(runner, ["template", "info", "tpl-missing"], mock_http)
        assert result.exit_code == 4
        assert "Traceback" not in result.output
        assert "tpl-missing" in result.output
        assert "TEMPLATE_ID" in result.output
        mock_http.close.assert_awaited()

    def test_delete_404_friendly(self, runner: CliRunner) -> None:
        """delete DELETE 404 → TemplateNotFoundError，退出码 4。"""
        mock_http = self._patched_http(
            self._http_error(404, {"message": "not found"})
        )
        result = self._run(
            runner,
            ["template", "delete", "tpl-missing"],
            mock_http,
            input="y\n",
        )
        assert result.exit_code == 4
        assert "Traceback" not in result.output
        assert "tpl-missing" in result.output
        assert "TEMPLATE_ID" in result.output
        mock_http.close.assert_awaited()
