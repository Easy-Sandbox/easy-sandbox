"""Packaging evidence for the static agent guide.

Decision under test (ADR 2026-09-29 static SKILL.md agent guide):

- **sdist includes ``SKILL.md``** — it is a top-level distribution document, like
  ``README.md`` / ``CHANGELOG.md``, so source distributions carry it for anyone
  (including AI tooling) consuming the tarball.
- **wheel excludes ``SKILL.md``** — the wheel ships only the Python package
  (``src/easy_sandbox``); a repo-root usage guide does not belong in
  ``site-packages``.

The test builds both artifacts with the project's real build backend
(hatchling) in a temporary copy of the repository and inspects their file
lists, so the assertion covers the actual ``pyproject.toml`` configuration
rather than a re-implementation of it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytest.importorskip("hatchling", reason="build backend hatchling is not installed")

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files the sdist include list references (plus src/ and tests/ which are
# copied as trees). pyproject.toml and README.md are required for hatchling
# metadata resolution; the rest make the copied project faithful to the real
# include list.
_TOP_LEVEL_FILES = (
    "pyproject.toml",
    "README.md",
    "SKILL.md",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
    "llms.txt",
)


def _copy_project(tmp_path: Path) -> Path:
    """Create a minimal, buildable copy of the repository under *tmp_path*."""
    project = tmp_path / "project"
    project.mkdir()
    for name in _TOP_LEVEL_FILES:
        source = REPO_ROOT / name
        assert source.is_file(), f"expected {name} at repository root"
        shutil.copy2(source, project / name)
    shutil.copytree(
        REPO_ROOT / "src",
        project / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    shutil.copytree(
        REPO_ROOT / "tests",
        project / "tests",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    return project


@pytest.fixture(scope="module")
def built_dists(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Path]]:
    """Build sdist and wheel once; yield ``{"sdist": path, "wheel": path}``."""
    project = _copy_project(tmp_path_factory.mktemp("skill-md-packaging"))
    result = subprocess.run(
        [sys.executable, "-m", "hatchling", "build", "-t", "sdist", "-t", "wheel"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"hatchling build failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    dist = project / "dist"
    sdists = sorted(dist.glob("*.tar.gz"))
    wheels = sorted(dist.glob("*.whl"))
    assert len(sdists) == 1, f"expected exactly one sdist, found: {[p.name for p in sdists]}"
    assert len(wheels) == 1, f"expected exactly one wheel, found: {[p.name for p in wheels]}"
    yield {"sdist": sdists[0], "wheel": wheels[0]}


def test_sdist_contains_skill_md(built_dists: dict[str, Path]) -> None:
    """SKILL.md ships inside the source distribution."""
    with tarfile.open(built_dists["sdist"]) as tar:
        names = tar.getnames()
    assert any(name == "SKILL.md" or name.endswith("/SKILL.md") for name in names), (
        "SKILL.md is missing from the sdist; check [tool.hatch.build.targets.sdist] "
        "include in pyproject.toml"
    )


def test_wheel_excludes_skill_md(built_dists: dict[str, Path]) -> None:
    """SKILL.md stays out of the wheel: wheels ship only the Python package."""
    with zipfile.ZipFile(built_dists["wheel"]) as wheel:
        names = wheel.namelist()
    leaked = [name for name in names if name == "SKILL.md" or name.endswith("/SKILL.md")]
    assert not leaked, (
        f"SKILL.md leaked into the wheel at {leaked}; the wheel must contain only "
        "src/easy_sandbox (see [tool.hatch.build.targets.wheel] in pyproject.toml)"
    )
    # The wheel still ships the Python package itself.
    assert any(name.startswith("easy_sandbox/") for name in names)


def test_sdist_omits_llms_txt_by_config() -> None:
    """llms.txt is intentionally NOT in the sdist include list (repo-only doc).

    Guards against accidentally widening the include list when adding SKILL.md.
    """
    sdist_include = _sdist_include_list()
    assert "SKILL.md" in sdist_include
    assert "llms.txt" not in sdist_include, (
        "llms.txt was added to the sdist include list; update this test (and the "
        "ADR) if shipping it in distributions becomes an explicit decision"
    )


def _sdist_include_list() -> list[str]:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - Python 3.10 fallback
        import tomli as tomllib

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build = data["tool"]["hatch"]["build"]["targets"]["sdist"]
    include: list[str] = build["include"]
    return include
