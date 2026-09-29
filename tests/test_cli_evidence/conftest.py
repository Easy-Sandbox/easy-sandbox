"""Shared fixtures for the golden-file CLI evidence snapshot tests.

These tests invoke the CLI via ``CliRunner`` and compare the *human-readable*
output against committed golden files.  When run inside a CI runner the CLI
would auto-switch to JSON mode (see ``easy_sandbox.cli.output.is_ci_env``),
which breaks the snapshots.  The autouse fixture below clears the CI markers so
the suite behaves identically on a developer laptop and in GitHub Actions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Environment variables that trigger CI auto-detection in the CLI root group
#: (see ``easy_sandbox.cli.output.is_ci_env``).  When any of these is set the
#: CLI silently switches to ``--json --quiet --no-color`` mode, which changes
#: the output format and breaks assertions that expect human-readable text.
#: Clearing them makes the tests environment-agnostic: they pass identically
#: on a developer laptop and inside GitHub Actions / GitLab CI / etc.
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


@pytest.fixture(autouse=True)
def _suppress_ci_detection(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove CI environment variables so the CLI never auto-enables JSON mode.

    Without this, ``is_ci_env()`` returns ``True`` in CI runners, the
    ``OutputManager`` flips to ``json_mode=True``, and every golden-file
    comparison fails because the output is JSON instead of the recorded
    human-readable text.
    """
    for var in _CI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
