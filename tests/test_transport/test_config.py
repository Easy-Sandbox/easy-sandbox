"""Tests for transport.config module."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from serverless_sandbox.transport.config import (
    TransportConfig,
    load_config,
    reset_config,
    ENVD_PORT,
)


class TestTransportConfigDefaults:
    """Test default values of TransportConfig."""

    def test_default_api_url(self):
        cfg = TransportConfig()
        assert cfg.domain == "cn-hangzhou.e2b.fc.aliyuncs.com"
        assert cfg.api_url == "https://api.cn-hangzhou.e2b.fc.aliyuncs.com"
        # backward-compat property still works
        assert cfg.api_base_url == cfg.api_url

    def test_default_region(self):
        cfg = TransportConfig()
        assert cfg.region == "cn-hangzhou"

    def test_default_auth_fields_none(self):
        cfg = TransportConfig()
        assert cfg.api_key is None
        assert cfg.access_key_id is None
        assert cfg.access_key_secret is None

    def test_default_http_settings(self):
        cfg = TransportConfig()
        assert cfg.http_timeout == 30.0
        assert cfg.max_connections == 100
        assert cfg.max_keepalive_connections == 20
        assert cfg.keepalive_expiry == 30.0
        assert cfg.http2 is True

    def test_default_ws_settings(self):
        cfg = TransportConfig()
        assert cfg.ws_ping_interval == 30.0

    def test_default_retry_settings(self):
        cfg = TransportConfig()
        assert cfg.max_retries == 3
        assert cfg.retry_base_delay == 1.0


class TestTransportConfigValidation:
    """Test field validation constraints."""

    def test_http_timeout_minimum(self):
        with pytest.raises(ValidationError):
            TransportConfig(http_timeout=0.5)

    def test_max_connections_minimum(self):
        with pytest.raises(ValidationError):
            TransportConfig(max_connections=0)

    def test_ws_ping_interval_minimum(self):
        with pytest.raises(ValidationError):
            TransportConfig(ws_ping_interval=0.5)

    def test_retry_base_delay_minimum(self):
        with pytest.raises(ValidationError):
            TransportConfig(retry_base_delay=0.05)

    def test_max_retries_minimum(self):
        with pytest.raises(ValidationError):
            TransportConfig(max_retries=-1)

    def test_extra_fields_ignored(self):
        cfg = TransportConfig(unknown_field="value")
        assert not hasattr(cfg, "unknown_field")

    def test_valid_custom_values(self):
        cfg = TransportConfig(
            api_url="https://custom.example.com",
            region="us-west-1",
            http_timeout=60.0,
            max_retries=5,
        )
        assert cfg.api_url == "https://custom.example.com"
        assert cfg.region == "us-west-1"
        assert cfg.http_timeout == 60.0
        assert cfg.max_retries == 5


class TestLoadConfig:
    """Test load_config with various layers."""

    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_load_default_config(self):
        cfg = load_config()
        assert cfg.api_url == "https://api.cn-hangzhou.e2b.fc.aliyuncs.com"
        assert cfg.region == "cn-hangzhou"

    def test_load_config_with_overrides(self):
        cfg = load_config(region="us-east-1", http_timeout=60.0)
        assert cfg.region == "us-east-1"
        assert cfg.http_timeout == 60.0

    def test_load_config_caching(self):
        cfg1 = load_config()
        cfg2 = load_config()
        assert cfg1 is cfg2

    def test_load_config_no_cache_with_overrides(self):
        cfg1 = load_config()
        cfg2 = load_config(region="us-west-1")
        assert cfg1 is not cfg2
        assert cfg2.region == "us-west-1"

    def test_reset_config_clears_cache(self):
        cfg1 = load_config()
        reset_config()
        cfg2 = load_config()
        assert cfg1 is not cfg2

    def test_env_var_api_key(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_API_KEY", "test-key-from-env")
        cfg = load_config()
        assert cfg.api_key == "test-key-from-env"

    def test_env_var_region(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_REGION", "ap-southeast-1")
        cfg = load_config()
        assert cfg.region == "ap-southeast-1"

    def test_env_var_base_url(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_API_BASE_URL", "https://custom.api.com")
        cfg = load_config()
        assert cfg.api_url == "https://custom.api.com"

    def test_env_var_http_timeout(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_HTTP_TIMEOUT", "45.0")
        cfg = load_config()
        assert cfg.http_timeout == 45.0

    def test_env_var_ak_sk(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_ID", "ak-test")
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_SECRET", "sk-test")
        cfg = load_config()
        assert cfg.access_key_id == "ak-test"
        assert cfg.access_key_secret == "sk-test"

    def test_code_override_beats_env(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_REGION", "from-env")
        cfg = load_config(region="from-code")
        assert cfg.region == "from-code"

    def test_none_override_does_not_clobber(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_API_KEY", "env-key")
        cfg = load_config(api_key=None)
        assert cfg.api_key == "env-key"

    def test_e2b_api_key_env_var(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
        cfg = load_config()
        assert cfg.api_key == "e2b-test-key"

    def test_e2b_api_url_env_var(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("E2B_API_URL", "https://e2b-custom.api.com")
        cfg = load_config()
        assert cfg.api_url == "https://e2b-custom.api.com"

    def test_e2b_domain_env_var(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("E2B_DOMAIN", "custom.e2b.domain")
        cfg = load_config()
        assert cfg.domain == "custom.e2b.domain"

    def test_e2b_env_var_overrides_sandbox_env_var(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_API_KEY", "sandbox-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-key")
        cfg = load_config()
        assert cfg.api_key == "e2b-key"

    def test_e2b_api_url_overrides_sandbox_base_url(self, monkeypatch):
        reset_config()
        monkeypatch.setenv("SANDBOX_API_BASE_URL", "https://sandbox.api.com")
        monkeypatch.setenv("E2B_API_URL", "https://e2b.api.com")
        cfg = load_config()
        assert cfg.api_url == "https://e2b.api.com"


class TestEnvdPort:
    """Test ENVD_PORT constant and build_envd_url."""

    def test_envd_port_constant(self):
        assert ENVD_PORT == 49983

    def test_build_envd_url(self):
        cfg = TransportConfig()
        url = cfg.build_envd_url("sbx-abc123")
        assert url == f"https://49983-sbx-abc123.{cfg.domain}"

    def test_build_envd_url_custom_domain(self):
        cfg = TransportConfig(domain="custom.domain.com")
        url = cfg.build_envd_url("sbx-xyz")
        assert url == "https://49983-sbx-xyz.custom.domain.com"
