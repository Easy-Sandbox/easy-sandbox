"""Tests for transport.config module."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from easy_sandbox.transport import config as config_module
from easy_sandbox.transport.config import (
    ENVD_PORT,
    TransportConfig,
    http_timeout_configured,
    load_config,
    reset_config,
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


class TestDotenvIsolation:
    """Regression tests for the .env / process-env isolation contract.

    Guards against the real repository ``.env`` (discovered via the CWD-relative
    ``Path(".env")`` candidate) leaking real credentials into tests, while
    confirming that explicit dotenv paths still load and that process env keeps
    priority over ``.env`` values. All values used here are fabricated fakes.
    """

    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_repo_dotenv_in_cwd_is_not_read(self, monkeypatch, tmp_path):
        """A ``.env`` sitting in the CWD must not leak into the loaded config.

        Simulates running the suite from a directory that contains a real
        ``.env`` full of credentials; the autouse isolation fixture must keep
        those values out of ``load_config()``.
        """
        cwd_env = tmp_path / ".env"
        cwd_env.write_text(
            "E2B_API_KEY=fake-should-not-load\n"
            "ALICLOUD_ACCESS_KEY_ID=fake-ak\n"
            "ALICLOUD_ACCESS_KEY_SECRET=fake-sk\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        # Sanity: the CWD-relative candidate would resolve to our fake file.
        assert Path(".env").resolve() == cwd_env.resolve()

        cfg = load_config()
        assert cfg.api_key is None
        assert cfg.access_key_id is None
        assert cfg.access_key_secret is None

    def test_explicit_dotenv_path_is_loaded(self, monkeypatch, tmp_path):
        """Pointing the candidate list at an explicit ``.env`` still works."""
        explicit_env = tmp_path / "explicit.env"
        explicit_env.write_text("SANDBOX_REGION=explicit-region\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [explicit_env])
        reset_config()

        cfg = load_config()
        assert cfg.region == "explicit-region"

    def test_project_dotenv_falls_through_to_system_file(self, monkeypatch, tmp_path):
        """A project .env that omits a key must not hide ~/.ebx/.env."""
        project = tmp_path / "project.env"
        system = tmp_path / "system.env"
        project.write_text("SANDBOX_REGION=from-project\n", encoding="utf-8")
        system.write_text("E2B_API_KEY=from-system\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [project, system])
        reset_config()

        cfg = load_config()
        assert cfg.api_key == "from-system"
        assert cfg.region == "from-project"

    def test_project_dotenv_key_beats_system_file(self, monkeypatch, tmp_path):
        project = tmp_path / "project.env"
        system = tmp_path / "system.env"
        project.write_text("E2B_API_KEY=from-project\n", encoding="utf-8")
        system.write_text("E2B_API_KEY=from-system\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [project, system])
        reset_config()

        cfg = load_config()
        assert cfg.api_key == "from-project"

    def test_process_env_beats_dotenv(self, monkeypatch, tmp_path):
        """Process env vars (layer 2) keep priority over ``.env`` (layer 3)."""
        explicit_env = tmp_path / "explicit.env"
        explicit_env.write_text("SANDBOX_REGION=from-dotenv\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [explicit_env])
        monkeypatch.setenv("SANDBOX_REGION", "from-env")
        reset_config()

        cfg = load_config()
        assert cfg.region == "from-env"

    def test_blank_process_env_and_override_fall_through(self, monkeypatch, tmp_path):
        """Whitespace does not hide a key stored in .env or config.toml."""
        dotenv = tmp_path / "system.env"
        dotenv.write_text("E2B_API_KEY=from-dotenv\n", encoding="utf-8")
        toml = tmp_path / "config.toml"
        toml.write_text('[transport]\nregion = "cn-beijing"\n', encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [dotenv])
        monkeypatch.setattr(config_module, "_CONFIG_FILE", toml)
        monkeypatch.setenv("E2B_API_KEY", "   ")
        monkeypatch.setenv("SANDBOX_REGION", "  ")
        reset_config()

        cfg = load_config(api_key="  ", region="   ")
        assert cfg.api_key == "from-dotenv"
        assert cfg.region == "cn-beijing"


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


class TestHttpTimeoutConfigured:
    """Test http_timeout_configured() source detection (no defaults applied)."""

    def _isolate(self, monkeypatch, tmp_path):
        """Point all config sources at empty temp locations."""
        monkeypatch.delenv("SANDBOX_HTTP_TIMEOUT", raising=False)
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [])
        cfg_file = tmp_path / "config.toml"
        monkeypatch.setattr(config_module, "_CONFIG_FILE", cfg_file)
        return cfg_file

    def test_false_when_nothing_set(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        assert http_timeout_configured() is False

    def test_true_when_env_var_set(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        monkeypatch.setenv("SANDBOX_HTTP_TIMEOUT", "60")
        assert http_timeout_configured() is True

    def test_true_when_toml_has_key(self, monkeypatch, tmp_path):
        cfg_file = self._isolate(monkeypatch, tmp_path)
        cfg_file.write_text("[transport]\nhttp_timeout = 90.0\n", encoding="utf-8")
        assert http_timeout_configured() is True

    def test_true_when_dotenv_has_key(self, monkeypatch, tmp_path):
        self._isolate(monkeypatch, tmp_path)
        dotenv = tmp_path / ".env"
        dotenv.write_text("SANDBOX_HTTP_TIMEOUT=75\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [dotenv])
        assert http_timeout_configured() is True
