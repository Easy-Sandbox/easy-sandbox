"""Tests for global config data model."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from easy_sandbox.models.config import GlobalConfig


class TestGlobalConfig:
    def test_defaults(self):
        cfg = GlobalConfig()
        assert cfg.api_key is None
        assert cfg.access_key_id is None
        assert cfg.access_key_secret is None
        assert cfg.api_url == "https://api.cn-hangzhou.e2b.fc.aliyuncs.com"
        assert cfg.domain == "cn-hangzhou.e2b.fc.aliyuncs.com"
        assert cfg.region == "cn-hangzhou"
        assert cfg.timeout == 300
        assert cfg.max_retries == 3
        assert cfg.secure is True
        assert cfg.log_level == "WARNING"
        assert cfg.default_template == "base"

    def test_custom_values(self):
        cfg = GlobalConfig(
            api_key="my-key",
            api_url="https://custom.example.com",
            region="cn-shanghai",
            timeout=600,
            max_retries=5,
            log_level="DEBUG",
            secure=False,
        )
        assert cfg.api_key == "my-key"
        assert cfg.api_url == "https://custom.example.com"
        assert cfg.timeout == 600
        assert cfg.max_retries == 5
        assert cfg.log_level == "DEBUG"
        assert cfg.secure is False

    def test_timeout_min_validation(self):
        with pytest.raises(ValidationError):
            GlobalConfig(timeout=0)

    def test_max_retries_min_validation(self):
        with pytest.raises(ValidationError):
            GlobalConfig(max_retries=-1)

    def test_max_retries_max_validation(self):
        with pytest.raises(ValidationError):
            GlobalConfig(max_retries=11)

    def test_api_url_for_region(self):
        url = GlobalConfig.api_url_for_region("cn-shanghai")
        assert url == "https://api.cn-shanghai.e2b.fc.aliyuncs.com"

    def test_domain_for_region(self):
        domain = GlobalConfig.domain_for_region("cn-shanghai")
        assert domain == "cn-shanghai.e2b.fc.aliyuncs.com"
