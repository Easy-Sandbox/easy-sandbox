"""Shared fixtures / helpers for the offline template-fixture tests.

``examples/templates/`` is **not** a publishable template collection: the
single source of truth for template content, the index and releases is the
``Easy-Sandbox/awesome-templates`` repository.  What remains here is a minimal
fixture (``python-hello``) used to exercise the install/server pipelines
**offline**: no network, no real platform API, no docker daemon.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Iterator

# tests/test_templates/conftest.py → parents[2] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "examples" / "templates"
CATALOG_README = TEMPLATES_DIR / "README.md"

#: The fixture template(s) intentionally kept in this repository so that the
#: offline test-suite has something real to install/load.  Everything else
#: belongs to the catalog repository (see :data:`SOURCE_OF_TRUTH_URL`).
EXPECTED_FIXTURE_TEMPLATES: tuple[str, ...] = ("python-hello",)

#: Single source of truth for official & community template content, the
#: machine-readable index (``awesome-templates.yaml``) and publication.
SOURCE_OF_TRUTH_URL = "https://github.com/Easy-Sandbox/awesome-templates"

#: Files every template folder must contain.
REQUIRED_TEMPLATE_FILES = ("template.yaml", "Dockerfile", "README.md")

#: Template YAML keys that must be present *explicitly* in every catalog entry.
#: (The Pydantic model gives most of them defaults, but a published template is
#: expected to spell them out so the index table stays meaningful.)
REQUIRED_YAML_KEYS = ("name", "version", "description", "author", "tags")


def discover_template_dirs() -> list[Path]:
    """Return every template folder under ``examples/templates/`` (sorted).

    Hidden directories are skipped so ``.gitkeep``-style helpers or editor
    droppings never become phantom templates.
    """
    if not TEMPLATES_DIR.is_dir():  # pragma: no cover - guards a broken checkout
        return []
    return sorted(p for p in TEMPLATES_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize any test asking for ``template_dir`` over the whole catalog."""
    if "template_dir" in metafunc.fixturenames:
        dirs = discover_template_dirs()
        metafunc.parametrize(
            "template_dir",
            dirs,
            ids=[d.name for d in dirs],
        )


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
    ``OutputManager`` flips to ``json_mode=True``, and every assertion that
    checks for human-readable output (e.g. ``"Using local template from"``)
    fails because the output is JSON instead.
    """
    for var in _CI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner (same flavour as ``tests/test_cli/conftest.py``)."""
    return CliRunner()


@pytest.fixture
def templates_dir() -> Path:
    """Absolute path of ``examples/templates/``."""
    return TEMPLATES_DIR


@pytest.fixture
def template_dirs() -> list[Path]:
    """Every discovered template folder (for non-parametrized, whole-catalog tests)."""
    return discover_template_dirs()


@pytest.fixture
def catalog_readme() -> Path:
    """Absolute path of the catalog index ``examples/templates/README.md``."""
    return CATALOG_README
