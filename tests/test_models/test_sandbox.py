"""Tests for sandbox data models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from serverless_sandbox.models.sandbox import (
    SandboxStatus,
    SandboxConfig,
    SandboxInfo,
)


class TestSandboxStatus:
    def test_enum_values(self):
        assert SandboxStatus.CREATING == "creating"
        assert SandboxStatus.RUNNING == "running"
        assert SandboxStatus.PAUSED == "paused"
        assert SandboxStatus.STOPPING == "stopping"
        assert SandboxStatus.STOPPED == "stopped"
        assert SandboxStatus.ERROR == "error"

    def test_enum_count(self):
        assert len(SandboxStatus) == 6


class TestSandboxConfig:
    def test_defaults(self):
        cfg = SandboxConfig()
        assert cfg.template == "base"
        assert cfg.timeout == 300
        assert cfg.metadata == {}
        assert cfg.env_vars == {}
        assert cfg.auto_pause is False

    def test_custom_values(self):
        cfg = SandboxConfig(
            template="python3",
            timeout=600,
            metadata={"owner": "test"},
            env_vars={"FOO": "bar"},
            auto_pause=True,
        )
        assert cfg.template == "python3"
        assert cfg.timeout == 600
        assert cfg.metadata == {"owner": "test"}
        assert cfg.env_vars == {"FOO": "bar"}
        assert cfg.auto_pause is True

    def test_timeout_min_validation(self):
        with pytest.raises(ValidationError):
            SandboxConfig(timeout=0)

    def test_timeout_max_validation(self):
        with pytest.raises(ValidationError):
            SandboxConfig(timeout=86401)

    def test_to_create_payload(self):
        cfg = SandboxConfig(
            template="python3",
            timeout=600,
            env_vars={"FOO": "bar"},
            metadata={"owner": "test"},
            auto_pause=True,
        )
        payload = cfg.to_create_payload()
        assert payload["templateID"] == "python3"
        assert payload["timeout"] == 600
        assert payload["envVars"] == {"FOO": "bar"}
        assert payload["metadata"] == {"owner": "test"}
        assert payload["autoPause"] is True

    def test_to_create_payload_defaults(self):
        cfg = SandboxConfig()
        payload = cfg.to_create_payload()
        assert payload["templateID"] == "base"
        assert payload["timeout"] == 300
        assert payload["envVars"] == {}
        assert payload["autoPause"] is False

    def test_alias_construction(self):
        """Test constructing SandboxConfig via camelCase aliases."""
        cfg = SandboxConfig.model_validate({
            "templateID": "node-base",
            "timeout": 600,
            "envVars": {"X": "1"},
            "autoPause": True,
        })
        assert cfg.template == "node-base"
        assert cfg.env_vars == {"X": "1"}
        assert cfg.auto_pause is True


class TestSandboxInfo:
    def test_from_alias_dict(self):
        data = {
            "sandboxID": "sbx-123",
            "templateID": "python3",
            "status": "running",
            "startedAt": "2025-01-01T00:00:00Z",
            "envdUrl": "https://env.example.com",
            "envdAccessToken": "tok-abc",
        }
        info = SandboxInfo(**data)
        assert info.sandbox_id == "sbx-123"
        assert info.template == "python3"
        assert info.status == SandboxStatus.RUNNING
        assert info.started_at is not None
        assert info.envd_url == "https://env.example.com"
        assert info.envd_access_token == "tok-abc"

    def test_from_python_names(self):
        info = SandboxInfo(sandbox_id="sbx-456", template="node")
        assert info.sandbox_id == "sbx-456"

    def test_json_roundtrip(self):
        data = {
            "sandboxID": "sbx-789",
            "templateID": "go",
            "status": "creating",
        }
        info = SandboxInfo(**data)
        json_str = info.model_dump_json(by_alias=True)
        info2 = SandboxInfo.model_validate_json(json_str)
        assert info2.sandbox_id == info.sandbox_id
        assert info2.template == info.template
        assert info2.status == info.status

    def test_defaults(self):
        info = SandboxInfo(sandbox_id="sbx-def")
        assert info.template == ""
        assert info.status == SandboxStatus.RUNNING
        assert info.started_at is None
        assert info.metadata == {}
        assert info.timeout == 300
        assert info.region == "cn-hangzhou"

    def test_new_fields(self):
        data = {
            "sandboxID": "sbx-new",
            "envdAccessToken": "tok-new",
            "envdVersion": "1.2.3",
            "clientID": "client-abc",
            "accountID": "acct-xyz",
            "userID": "user-123",
        }
        info = SandboxInfo(**data)
        assert info.envd_access_token == "tok-new"
        assert info.envd_version == "1.2.3"
        assert info.client_id == "client-abc"
        assert info.account_id == "acct-xyz"
        assert info.user_id == "user-123"

    def test_model_validate(self):
        """Test model_validate with camelCase dict."""
        data = {
            "sandboxID": "sbx-mv",
            "templateID": "base",
            "status": "running",
            "envdAccessToken": "tok",
            "timeout": 300,
            "region": "cn-hangzhou",
        }
        info = SandboxInfo.model_validate(data)
        assert info.sandbox_id == "sbx-mv"
        assert info.template == "base"
        assert info.envd_access_token == "tok"
