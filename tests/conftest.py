"""Global pytest fixtures for Easy Sandbox tests."""

import pytest


@pytest.fixture
def sandbox_api_key() -> str:
    """Provide a test API key."""
    return "test-api-key-for-unit-tests"


@pytest.fixture
def sandbox_envd_token() -> str:
    """Provide a test envd access token."""
    return "test-envd-access-token"


@pytest.fixture
def sandbox_id() -> str:
    """Provide a test sandbox ID."""
    return "sbx-test-1234567890"


@pytest.fixture
def sandbox_api_url() -> str:
    """Provide a test sandbox API URL."""
    return "https://api.cn-hangzhou.e2b.fc.aliyuncs.com"
