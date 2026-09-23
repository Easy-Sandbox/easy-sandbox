"""Tests for the official FCSandbox CreateTemplate API adapter."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRequireSDK:
    """Tests for _require_sdk() guard."""

    def test_missing_sdk_raises_friendly_error(self) -> None:
        """When alibabacloud SDK is not importable, raise SandboxError."""
        import importlib
        import sys

        from easy_sandbox.models.errors import SandboxError

        # Remove the module from cache so _require_sdk re-attempts import
        mod_name = "alibabacloud_fcsandbox20260509"
        saved = sys.modules.pop(mod_name, None)
        try:
            # Inject a module entry that makes import raise
            sys.modules[mod_name] = None  # type: ignore[assignment]
            # Force re-import of fc_template to reset state
            if "easy_sandbox.api.fc_template" in sys.modules:
                importlib.reload(sys.modules["easy_sandbox.api.fc_template"])
            from easy_sandbox.api.fc_template import _require_sdk

            with pytest.raises(SandboxError, match="not installed"):
                _require_sdk()
        finally:
            # Restore
            if saved is not None:
                sys.modules[mod_name] = saved
            elif mod_name in sys.modules:
                del sys.modules[mod_name]


class TestBuildCreateTemplateRequestMap:
    """Tests for request body construction (requires SDK)."""

    def test_basic_request_map(self) -> None:
        """Basic request map with minimal params."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-template",
            image="registry.cn-hangzhou.aliyuncs.com/ns/repo:latest",
            team_id="team-123",
            cpu=2,
            memory_size=2048,
            generation=1,
        )

        body = result.get("body", {})
        assert body["name"] == "test-template"
        assert body["teamID"] == "team-123"

        runtime = body.get("runtimeConfig", {})
        assert runtime["cpu"] == 2
        assert runtime["memorySize"] == 2048

        sandbox = runtime.get("sandboxConfig", {})
        assert sandbox["image"] == "registry.cn-hangzhou.aliyuncs.com/ns/repo:latest"
        assert sandbox["generation"] == 1

    def test_envd_inject_enabled(self) -> None:
        """Request map with envdInject enabled."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-envd",
            image="img",
            team_id="t",
            envd_inject=True,
        )

        body = result.get("body", {})
        build_config = body.get("buildConfig", {})
        assert build_config["envdInject"]["enabled"] is True

    def test_envd_inject_disabled(self) -> None:
        """Request map without envdInject — buildConfig should be absent."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-no-envd",
            image="img",
            team_id="t",
            envd_inject=False,
        )

        body = result.get("body", {})
        # buildConfig should be None/absent when envdInject is False
        build_config = body.get("buildConfig")
        assert build_config is None or not build_config

    def test_registry_type_auto_detected_acree(self) -> None:
        """registryType should be 'acree' when acr_instance_id is set."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-acree",
            image="img",
            team_id="t",
            acr_instance_id="cri-xxx",
        )

        sandbox = result["body"]["runtimeConfig"]["sandboxConfig"]
        assert sandbox["registryType"] == "acree"
        assert sandbox["acrInstanceId"] == "cri-xxx"

    def test_registry_credentials(self) -> None:
        """Registry auth config should be set when credentials provided."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-creds",
            image="img",
            team_id="t",
            registry_username="user",
            registry_password="pass",
        )

        sandbox = result["body"]["runtimeConfig"]["sandboxConfig"]
        reg_config = sandbox.get("registryConfig", {})
        auth = reg_config.get("authConfig", {})
        assert auth["userName"] == "user"
        assert auth["password"] == "pass"

    def test_start_and_ready_commands(self) -> None:
        """start_command and ready_command should appear in sandboxConfig."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-cmds",
            image="img",
            team_id="t",
            start_command="/start.sh",
            ready_command="/ready.sh",
        )

        sandbox = result["body"]["runtimeConfig"]["sandboxConfig"]
        assert sandbox["startCommand"] == "/start.sh"
        assert sandbox["readyCommand"] == "/ready.sh"


class TestCreateOfficialTemplate:
    """Tests for create_official_template with mocked SDK client."""

    def test_successful_create(self) -> None:
        """Mocked successful CreateTemplate call."""
        from easy_sandbox.api.fc_template import create_official_template

        mock_body = MagicMock()
        mock_body.template_id = "tpl-abc123"
        mock_body.request_id = "req-xyz"
        mock_body.code = "200"
        mock_body.message = ""

        mock_response = MagicMock()
        mock_response.body = mock_body
        mock_response.status_code = 200

        # Mock ListTeams for auto team_id resolution
        mock_team = MagicMock()
        mock_team.team_id = "team-auto"
        mock_teams_body = MagicMock()
        mock_teams_body.teams = [mock_team]
        mock_teams_resp = MagicMock()
        mock_teams_resp.body = mock_teams_body

        with patch(
            "alibabacloud_fcsandbox20260509.client.Client"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_template.return_value = mock_response
            mock_client.list_teams.return_value = mock_teams_resp
            mock_client_cls.return_value = mock_client

            result = create_official_template(
                name="test",
                image="registry.cn-hangzhou.aliyuncs.com/ns/repo:latest",
                access_key_id="AK",
                access_key_secret="SK",
                region="cn-hangzhou",
            )

        assert result["templateID"] == "tpl-abc123"
        assert result["requestId"] == "req-xyz"
        assert result["statusCode"] == 200

    def test_create_with_explicit_team_id(self) -> None:
        """When team_id is provided, ListTeams should NOT be called."""
        from easy_sandbox.api.fc_template import create_official_template

        mock_body = MagicMock()
        mock_body.template_id = "tpl-explicit"
        mock_body.request_id = "req-002"
        mock_body.code = "200"
        mock_body.message = ""

        mock_response = MagicMock()
        mock_response.body = mock_body
        mock_response.status_code = 200

        with patch(
            "alibabacloud_fcsandbox20260509.client.Client"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_template.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = create_official_template(
                name="test",
                image="img",
                access_key_id="AK",
                access_key_secret="SK",
                team_id="team-explicit",
            )

        assert result["templateID"] == "tpl-explicit"
        # ListTeams should not be called when team_id is explicit
        mock_client.list_teams.assert_not_called()

    def test_api_failure_raises_template_build_error(self) -> None:
        """API failure should raise TemplateBuildError."""
        from easy_sandbox.api.fc_template import create_official_template
        from easy_sandbox.models.errors import TemplateBuildError

        with patch(
            "alibabacloud_fcsandbox20260509.client.Client"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_template.side_effect = Exception("API error")
            mock_client_cls.return_value = mock_client

            with pytest.raises(TemplateBuildError, match="API call failed"):
                create_official_template(
                    name="test",
                    image="img",
                    access_key_id="AK",
                    access_key_secret="SK",
                    team_id="team-x",
                )


class TestGetTemplate:
    """Tests for get_template with mocked SDK client."""

    def test_get_template_success(self) -> None:
        """Successful GetTemplate call."""
        from easy_sandbox.api.fc_template import get_template

        mock_body = MagicMock()
        mock_body.to_map.return_value = {
            "templateID": "tpl-xyz",
            "buildStatus": "ready",
        }

        mock_response = MagicMock()
        mock_response.body = mock_body
        mock_response.status_code = 200

        with patch(
            "alibabacloud_fcsandbox20260509.client.Client"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_template.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = get_template(
                "tpl-xyz",
                access_key_id="AK",
                access_key_secret="SK",
            )

        assert result["templateID"] == "tpl-xyz"
        assert result["statusCode"] == 200
