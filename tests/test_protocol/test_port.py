"""Tests for protocol.port module — 端口 URL 本地计算。"""
from __future__ import annotations

import pytest

from easy_sandbox.protocol.port import PortClient


class TestGetHost:
    """Test PortClient.get_host() static method."""

    def test_returns_expected_format(self):
        host = PortClient.get_host("sbx-123", 8080, "e2b.dev")
        assert host == "8080-sbx-123.e2b.dev"

    def test_different_port(self):
        host = PortClient.get_host("sbx-abc", 3000, "cn-hangzhou.e2b.fc.aliyuncs.com")
        assert host == "3000-sbx-abc.cn-hangzhou.e2b.fc.aliyuncs.com"

    def test_different_sandbox_id(self):
        host = PortClient.get_host("my-sandbox-999", 443, "example.com")
        assert host == "443-my-sandbox-999.example.com"


class TestGetPortUrl:
    """Test PortClient.get_port_url() static method."""

    def test_secure_url(self):
        url = PortClient.get_port_url("sbx-123", 8080, "e2b.dev", secure=True)
        assert url == "https://8080-sbx-123.e2b.dev"

    def test_insecure_url(self):
        url = PortClient.get_port_url("sbx-123", 8080, "e2b.dev", secure=False)
        assert url == "http://8080-sbx-123.e2b.dev"

    def test_default_is_secure(self):
        url = PortClient.get_port_url("sbx-123", 3000, "cn-hangzhou.e2b.fc.aliyuncs.com")
        assert url.startswith("https://")
        assert "3000-sbx-123.cn-hangzhou.e2b.fc.aliyuncs.com" in url

    def test_url_contains_host(self):
        host = PortClient.get_host("sbx-test", 9090, "domain.io")
        url = PortClient.get_port_url("sbx-test", 9090, "domain.io")
        assert host in url

    def test_various_ports(self):
        for port in [80, 443, 3000, 5173, 8080, 9090]:
            url = PortClient.get_port_url("sbx-1", port, "e2b.dev")
            assert f"{port}-sbx-1.e2b.dev" in url


class TestStaticMethods:
    """Verify methods are usable as static methods without instantiation."""

    def test_get_host_is_static(self):
        # Should work without creating an instance
        result = PortClient.get_host("sbx-1", 8080, "e2b.dev")
        assert isinstance(result, str)

    def test_get_port_url_is_static(self):
        result = PortClient.get_port_url("sbx-1", 8080, "e2b.dev")
        assert isinstance(result, str)
