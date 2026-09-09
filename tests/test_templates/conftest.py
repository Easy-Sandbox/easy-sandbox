"""Shared fixtures / helpers for the offline template-catalog tests.

Everything here is **offline**: no network, no real platform API, no docker
daemon.  The only boundary that gets mocked in ``test_local_install.py`` is the
backend build request (and, for the GitHub flavour, the archive download).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

# tests/test_templates/conftest.py → parents[2] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "examples" / "templates"
CATALOG_README = TEMPLATES_DIR / "README.md"

#: Files every template folder must contain.
REQUIRED_TEMPLATE_FILES = ("template.yaml", "Dockerfile", "README.md")

#: Template YAML keys that must be present *explicitly* in every catalog entry.
#: (The Pydantic model gives most of them defaults, but a published template is
#: expected to spell them out so the index table stays meaningful.)
REQUIRED_YAML_KEYS = ("name", "version", "description", "base", "author", "tags")


def discover_template_dirs() -> list[Path]:
    """Return every template folder under ``examples/templates/`` (sorted).

    Hidden directories are skipped so ``.gitkeep``-style helpers or editor
    droppings never become phantom templates.
    """
    if not TEMPLATES_DIR.is_dir():  # pragma: no cover - guards a broken checkout
        return []
    return sorted(
        p
        for p in TEMPLATES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize any test asking for ``template_dir`` over the whole catalog."""
    if "template_dir" in metafunc.fixturenames:
        dirs = discover_template_dirs()
        metafunc.parametrize(
            "template_dir",
            dirs,
            ids=[d.name for d in dirs],
        )


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
