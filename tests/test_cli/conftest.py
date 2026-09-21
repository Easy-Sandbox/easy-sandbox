"""Shared fixtures for CLI tests."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_sandbox_info() -> dict:
    """Sandbox info as returned by the API (dict form for model_validate)."""
    return {
        "sandboxID": "sbx-cli-test-001",
        "templateID": "python-base",
        "status": "running",
        "region": "cn-hangzhou",
        "timeout": 300,
        "envdUrl": "https://sbx-cli-test-001.cn-hangzhou.e2b.fc.aliyuncs.com",
        "envdAccessToken": "test-envd-token-abc",
    }
