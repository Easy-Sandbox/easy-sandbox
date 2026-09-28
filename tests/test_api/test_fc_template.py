"""Tests for the official FCSandbox CreateTemplate API adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestDeriveTargetImage:
    """Tests for _derive_target_image helper."""

    def test_simple_tag(self) -> None:
        from easy_sandbox.api.fc_template import _derive_target_image

        result = _derive_target_image("registry.cn-hangzhou.aliyuncs.com/ns/repo:v1")
        assert result.startswith("registry.cn-hangzhou.aliyuncs.com/ns/repo:v1-fcsandbox-")
        assert result != "registry.cn-hangzhou.aliyuncs.com/ns/repo:v1"

    def test_latest_tag(self) -> None:
        from easy_sandbox.api.fc_template import _derive_target_image

        result = _derive_target_image("registry.cn-hangzhou.aliyuncs.com/ns/repo:latest")
        assert ":latest-fcsandbox-" in result

    def test_no_tag(self) -> None:
        from easy_sandbox.api.fc_template import _derive_target_image

        result = _derive_target_image("registry.cn-hangzhou.aliyuncs.com/ns/repo")
        assert result.startswith("registry.cn-hangzhou.aliyuncs.com/ns/repo:fcsandbox-")

    def test_port_in_registry(self) -> None:
        """host:port/path:tag — colon before '/' is port, not tag."""
        from easy_sandbox.api.fc_template import _derive_target_image

        result = _derive_target_image("registry.example.com:5000/ns/repo:v1")
        # Should append suffix to :v1, not :5000
        assert result.startswith("registry.example.com:5000/ns/repo:v1-fcsandbox-")

    def test_port_only_no_tag(self) -> None:
        """host:port/path with no tag."""
        from easy_sandbox.api.fc_template import _derive_target_image

        result = _derive_target_image("registry.example.com:5000/ns/repo")
        assert result.startswith("registry.example.com:5000/ns/repo:fcsandbox-")

    def test_suffix_is_unique(self) -> None:
        from easy_sandbox.api.fc_template import _derive_target_image

        r1 = _derive_target_image("img:v1")
        r2 = _derive_target_image("img:v1")
        assert r1 != r2  # random suffix


class TestResolveTargetImage:
    """Tests for _resolve_target_image helper."""

    def test_none_target_derives(self) -> None:
        from easy_sandbox.api.fc_template import _resolve_target_image

        result = _resolve_target_image("img:v1", None)
        assert result != "img:v1"
        assert "-fcsandbox-" in result

    def test_same_as_source_derives(self) -> None:
        """target == source must be treated as 'not specified'."""
        from easy_sandbox.api.fc_template import _resolve_target_image

        result = _resolve_target_image("img:v1", "img:v1")
        assert result != "img:v1"
        assert "-fcsandbox-" in result

    def test_different_target_returned_as_is(self) -> None:
        from easy_sandbox.api.fc_template import _resolve_target_image

        result = _resolve_target_image("img:v1", "other:v2")
        assert result == "other:v2"


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
        """Request map with envdInject enabled — copy.image must differ from sandbox image."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-envd",
            image="img:v1",
            team_id="t",
            envd_inject=True,
        )

        body = result.get("body", {})
        build_config = body.get("buildConfig", {})
        assert build_config["envdInject"]["enabled"] is True
        copy_image = build_config["copy"]["image"]
        sandbox_image = body["runtimeConfig"]["sandboxConfig"]["image"]
        assert copy_image != sandbox_image
        assert "-fcsandbox-" in copy_image

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

    def test_explicit_target_image_honored(self) -> None:
        """Explicit target_image should be used as copy.image."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        result = build_create_template_request_map(
            name="test-explicit",
            image="source:v1",
            team_id="t",
            envd_inject=True,
            target_image="custom-target:v1",
        )

        body = result.get("body", {})
        copy_image = body["buildConfig"]["copy"]["image"]
        assert copy_image == "custom-target:v1"
        assert body["runtimeConfig"]["sandboxConfig"]["image"] == "source:v1"

    def test_target_image_equals_source_forces_derivation(self) -> None:
        """target_image == source image must be auto-derived (never equal)."""
        from easy_sandbox.api.fc_template import build_create_template_request_map

        src = "registry.cn-hangzhou.aliyuncs.com/ns/repo:v1"
        result = build_create_template_request_map(
            name="test-same",
            image=src,
            team_id="t",
            envd_inject=True,
            target_image=src,  # explicit but == source
        )

        body = result.get("body", {})
        copy_image = body["buildConfig"]["copy"]["image"]
        sandbox_image = body["runtimeConfig"]["sandboxConfig"]["image"]
        assert copy_image != sandbox_image
        assert "-fcsandbox-" in copy_image

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

        with patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls:
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

        with patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls:
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

    def test_envd_inject_target_image_in_create(self) -> None:
        """Create with envd_inject: copy.image must differ from source."""
        from easy_sandbox.api.fc_template import create_official_template

        mock_body = MagicMock()
        mock_body.template_id = "tpl-envd"
        mock_body.request_id = "req-e"
        mock_body.code = "200"
        mock_body.message = ""

        mock_response = MagicMock()
        mock_response.body = mock_body
        mock_response.status_code = 200

        with patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_template.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = create_official_template(
                name="test",
                image="registry/ns/repo:v1",
                access_key_id="AK",
                access_key_secret="SK",
                team_id="team-x",
                envd_inject=True,
            )

        assert result["templateID"] == "tpl-envd"
        # Inspect the request passed to create_template
        call_args = mock_client.create_template.call_args
        req = call_args[0][0]  # positional arg
        body = req.body
        copy_img = body.build_config.copy.image
        sandbox_img = body.runtime_config.sandbox_config.image
        assert copy_img != sandbox_img
        assert "-fcsandbox-" in copy_img
        assert sandbox_img == "registry/ns/repo:v1"

    def test_409_update_uses_same_target_image(self) -> None:
        """409→update path receives the same target_image as create."""
        from easy_sandbox.api.fc_template import create_official_template

        # Make create raise 409
        with patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_template.side_effect = Exception("TemplateAlreadyExists 409")
            # Mock _find_template_by_name for the update fallback
            tpl_mock = MagicMock()
            tpl_mock.name = "test"
            tpl_mock.template_id = "tpl-existing"
            list_body = MagicMock()
            list_body.templates = [tpl_mock]
            list_body.next_token = None
            list_resp = MagicMock()
            list_resp.body = list_body
            mock_client.list_templates.return_value = list_resp

            update_body = MagicMock()
            update_body.request_id = "req-u"
            update_resp = MagicMock()
            update_resp.body = update_body
            update_resp.status_code = 200
            mock_client.update_template.return_value = update_resp

            mock_client_cls.return_value = mock_client

            result = create_official_template(
                name="test",
                image="registry/ns/repo:v1",
                access_key_id="AK",
                access_key_secret="SK",
                team_id="team-x",
                envd_inject=True,
                target_image="explicit-target:v1",
            )

        assert result["templateID"] == "tpl-existing"
        # The update call should use the explicit target
        update_args = mock_client.update_template.call_args
        update_req = update_args[0][1]  # second positional arg (request)
        copy_img = update_req.body.build_config.copy.image
        assert copy_img == "explicit-target:v1"

    def test_409_update_target_equals_source_forces_derivation(self) -> None:
        """409→update with target==source: both paths derive and agree."""
        from easy_sandbox.api.fc_template import create_official_template

        src = "registry/ns/repo:v1"

        with patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls:
            mock_client = MagicMock()

            # Capture the create_template request to inspect resolved target
            create_req_holder: list[Any] = []

            def capture_create(req: Any) -> None:
                create_req_holder.append(req)
                raise Exception("TemplateAlreadyExists 409")

            mock_client.create_template.side_effect = capture_create

            tpl_mock = MagicMock()
            tpl_mock.name = "test"
            tpl_mock.template_id = "tpl-existing"
            list_body = MagicMock()
            list_body.templates = [tpl_mock]
            list_body.next_token = None
            list_resp = MagicMock()
            list_resp.body = list_body
            mock_client.list_templates.return_value = list_resp

            update_body = MagicMock()
            update_body.request_id = "req-u"
            update_resp = MagicMock()
            update_resp.body = update_body
            update_resp.status_code = 200
            mock_client.update_template.return_value = update_resp

            mock_client_cls.return_value = mock_client

            create_official_template(
                name="test",
                image=src,
                access_key_id="AK",
                access_key_secret="SK",
                team_id="team-x",
                envd_inject=True,
                target_image=src,  # same as source!
            )

        # Create path: copy.image differs from source
        create_req = create_req_holder[0]
        create_copy_img = create_req.body.build_config.copy.image
        assert create_copy_img != src
        assert "-fcsandbox-" in create_copy_img

        # Update path: must use the SAME derived target (no second derivation)
        update_args = mock_client.update_template.call_args
        update_req = update_args[0][1]
        update_copy_img = update_req.body.build_config.copy.image
        assert update_copy_img == create_copy_img

    def test_api_failure_raises_template_build_error(self) -> None:
        """API failure should raise TemplateBuildError."""
        from easy_sandbox.api.fc_template import create_official_template
        from easy_sandbox.models.errors import TemplateBuildError

        with patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls:
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

        with patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls:
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


class TestListOfficialTemplates:
    """Tests for list_official_templates with mocked SDK client."""

    def test_list_paginated_success(self) -> None:
        """Iterate all pages and flatten results."""
        from easy_sandbox.api.fc_template import list_official_templates

        tpl1 = MagicMock()
        tpl1.to_map.return_value = {"templateID": "t1", "name": "a", "status": "READY"}
        tpl2 = MagicMock()
        tpl2.to_map.return_value = {"templateID": "t2", "name": "b", "status": "BUILDING"}

        page1_body = MagicMock()
        page1_body.templates = [tpl1]
        page1_body.next_token = "tok-2"
        page1_resp = MagicMock()
        page1_resp.body = page1_body

        page2_body = MagicMock()
        page2_body.templates = [tpl2]
        page2_body.next_token = None
        page2_resp = MagicMock()
        page2_resp.body = page2_body

        with (
            patch("alibabacloud_fcsandbox20260509.client.Client") as mock_client_cls,
            patch(
                "easy_sandbox.api.fc_template.get_team_id",
                return_value="team-x",
            ),
        ):
            mock_client = MagicMock()
            mock_client.list_templates.side_effect = [page1_resp, page2_resp]
            mock_client_cls.return_value = mock_client

            results = list_official_templates(
                access_key_id="AK",
                access_key_secret="SK",
            )

        assert [r["templateID"] for r in results] == ["t1", "t2"]
        assert mock_client.list_templates.call_count == 2


class TestWaitForTemplateReady:
    """Tests for strict final-state polling."""

    def test_returns_only_after_ready(self) -> None:
        from easy_sandbox.api.fc_template import wait_for_template_ready

        with (
            patch(
                "easy_sandbox.api.fc_template.get_team_id",
                return_value="team-x",
            ),
            patch(
                "easy_sandbox.api.fc_template.get_template",
                side_effect=[
                    {"status": {"state": "building"}},
                    {"templateID": "tpl-1", "status": {"state": "ready"}},
                ],
            ) as mock_get,
            patch("easy_sandbox.api.fc_template.time.sleep"),
        ):
            result = wait_for_template_ready(
                "tpl-1",
                access_key_id="AK",
                access_key_secret="SK",
                poll_interval=0,
            )

        assert result["status"]["state"] == "ready"
        assert mock_get.call_count == 2

    def test_error_state_raises(self) -> None:
        from easy_sandbox.api.fc_template import wait_for_template_ready
        from easy_sandbox.models.errors import TemplateBuildError

        with (
            patch(
                "easy_sandbox.api.fc_template.get_team_id",
                return_value="team-x",
            ),
            patch(
                "easy_sandbox.api.fc_template.get_template",
                return_value={
                    "status": {"state": "error", "reason": {"message": "bad image"}},
                },
            ),
            pytest.raises(TemplateBuildError, match="bad image"),
        ):
            wait_for_template_ready(
                "tpl-1",
                access_key_id="AK",
                access_key_secret="SK",
            )
