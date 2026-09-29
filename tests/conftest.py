"""Global pytest fixtures for Easy Sandbox tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# CI auto-detection suppression
# ---------------------------------------------------------------------------
# The CLI's ``is_ci_env()`` flips output to JSON mode when any of these env
# vars is set.  Golden-file / text-assertion tests expect human-readable
# output, so we unconditionally clear these vars for every test.  The fixture
# is autouse + session-wide-safe via monkeypatch (function-scoped by default).

_CI_ENV_VARS: tuple[str, ...] = (
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "JENKINS_URL",
    "TRAVIS",
    "CIRCLECI",
    "BITBUCKET_PIPELINES",
    "TF_BUILD",
    "CODEBUILD_BUILD_ID",
)

# A developer machine may export GITHUB_TOKEN; the CLI resolves it for
# template downloads (task 206) and would otherwise leak into tests that
# expect no token to be configured.  This lives in its own autouse fixture
# (not in ``_suppress_ci_detection``, which sub-directory conftests override)
# so it applies to every test directory.
_CREDENTIAL_ENV_VARS: tuple[str, ...] = ("GITHUB_TOKEN",)


@pytest.fixture(autouse=True)
def _suppress_ci_detection(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove CI environment variables so the CLI never auto-enables JSON mode.

    Without this, ``is_ci_env()`` returns ``True`` in CI runners, the
    ``OutputManager`` flips to ``json_mode=True``, and every assertion that
    checks for human-readable output fails because the output is JSON instead.
    """
    for var in _CI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolate_credential_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove credential env vars (GITHUB_TOKEN) so tests stay deterministic."""
    for var in _CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


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
