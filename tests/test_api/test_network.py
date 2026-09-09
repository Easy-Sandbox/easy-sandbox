"""Tests for the NetworkModule API."""
from __future__ import annotations

import pytest

from serverless_sandbox.api.network import NetworkModule

from tests.test_api.conftest import TEST_SANDBOX_ID, TEST_ENVD_TOKEN


DOMAIN = "cn-hangzhou.e2b.fc.aliyuncs.com"


class TestNetworkGetHost:
    """Test NetworkModule.get_host()."""

    def test_get_host_returns_expected_format(
        self,
        network_module: NetworkModule,
    ) -> None:
        host = network_module.get_host(8080)
        assert host == f"8080-{TEST_SANDBOX_ID}.{DOMAIN}"

    def test_get_host_different_port(
        self,
        network_module: NetworkModule,
    ) -> None:
        host = network_module.get_host(3000)
        assert host == f"3000-{TEST_SANDBOX_ID}.{DOMAIN}"


class TestNetworkGetUrl:
    """Test NetworkModule.get_url()."""

    def test_get_url_secure(
        self,
        network_module: NetworkModule,
    ) -> None:
        url = network_module.get_url(8080)
        assert url == f"https://8080-{TEST_SANDBOX_ID}.{DOMAIN}"

    def test_get_url_insecure(self) -> None:
        mod = NetworkModule(
            sandbox_id=TEST_SANDBOX_ID,
            domain=DOMAIN,
            secure=False,
            capabilities={"ports"},
        )
        url = mod.get_url(8080)
        assert url == f"http://8080-{TEST_SANDBOX_ID}.{DOMAIN}"


class TestNetworkGetAccessHeaders:
    """Test NetworkModule.get_access_headers()."""

    def test_get_access_headers_with_token(
        self,
        network_module: NetworkModule,
    ) -> None:
        headers = network_module.get_access_headers()
        assert headers == {"X-Access-Token": TEST_ENVD_TOKEN}

    def test_get_access_headers_no_token(self) -> None:
        mod = NetworkModule(
            sandbox_id=TEST_SANDBOX_ID,
            domain=DOMAIN,
            secure=True,
            access_token=None,
            capabilities={"ports"},
        )
        headers = mod.get_access_headers()
        assert headers == {}

    def test_get_access_headers_insecure_with_token(self) -> None:
        mod = NetworkModule(
            sandbox_id=TEST_SANDBOX_ID,
            domain=DOMAIN,
            secure=False,
            access_token="some-token",
            capabilities={"ports"},
        )
        headers = mod.get_access_headers()
        # Non-secure mode doesn't include access headers
        assert headers == {}


class TestNetworkModuleInit:
    """Test NetworkModule initialization."""

    def test_default_secure(self) -> None:
        mod = NetworkModule(sandbox_id="sbx-1", domain="example.com", capabilities={"ports"})
        url = mod.get_url(8080)
        assert url.startswith("https://")

    def test_custom_domain(self) -> None:
        mod = NetworkModule(sandbox_id="sbx-1", domain="custom.domain.com", capabilities={"ports"})
        host = mod.get_host(3000)
        assert "custom.domain.com" in host
