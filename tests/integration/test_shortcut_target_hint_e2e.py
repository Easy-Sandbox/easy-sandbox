"""End-to-end shortcut target hints through a real ``ebx`` process.

Each invocation is a new interpreter with ``HOME`` pointed at a temporary
directory, so ``~/.ebx/config.toml`` is read at startup the same way a user
shell does. The root command group loads ``[shortcuts]`` once; an in-process
``CliRunner`` cannot observe an alias written after that group was built.

Run with: pytest tests/integration/test_shortcut_target_hint_e2e.py -m integration -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_CI_ENV_VARS = (
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


def _env(home: Path) -> dict[str, str]:
    """Environment for one ``ebx`` process rooted at *home*."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    for name in _CI_ENV_VARS:
        env.pop(name, None)
    return env


def _shown(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout or "") + (result.stderr or "")


def _ebx(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``ebx`` in a fresh process whose home directory is *home*."""
    return subprocess.run(
        [sys.executable, "-c", "from easy_sandbox.cli.main import main; main()", *args],
        cwd=home,
        env=_env(home),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def ebx_home(tmp_path: Path) -> Path:
    """Temporary ``HOME`` that ``Path.home()`` must actually honour.

    ``config set`` writes ``~/.ebx/config.toml``. If ``HOME`` were ignored the
    command would edit the developer's real config, so the probe runs before
    any ``ebx`` invocation.
    """
    home = tmp_path / "home"
    home.mkdir()
    probe = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; print(Path.home())"],
        cwd=home,
        env=_env(home),
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == str(home)
    return home


@pytest.mark.integration
def test_ebx_prefix_is_rejected_then_the_alias_runs(ebx_home: Path) -> None:
    """The reported first-use sequence, across process boundaries.

    ``"ebx template init"`` is refused with the command to retry and is not
    stored. ``"template init"`` is stored. A new process then runs the alias
    as ``template init``. Clearing the alias removes it from the next process.
    """
    rejected = _ebx(ebx_home, "config", "set", "shortcuts.aaaaa", "ebx template init")
    rejected_text = _shown(rejected)
    assert rejected.returncode == 2, rejected_text
    assert "Invalid shortcut target: 'ebx template init'" in rejected_text
    assert 'Drop the leading "ebx"' in rejected_text
    assert 'Try: ebx config set shortcuts.aaaaa "template init"' in rejected_text
    assert "Available targets:" not in rejected_text

    config_path = ebx_home / ".ebx" / "config.toml"
    assert config_path.is_file()
    stored = config_path.read_text(encoding="utf-8")
    assert "aaaaa =" not in stored
    assert 'create = "sandbox create"' in stored

    upper = _ebx(ebx_home, "config", "set", "shortcuts.aaaaa", "EBX template init")
    upper_text = _shown(upper)
    assert upper.returncode == 2, upper_text
    assert 'Try: ebx config set shortcuts.aaaaa "template init"' in upper_text

    unknown = _ebx(ebx_home, "config", "set", "shortcuts.aaaaa", "not-a-command")
    unknown_text = _shown(unknown)
    assert unknown.returncode == 2, unknown_text
    assert 'without the "ebx" prefix' in unknown_text
    assert "template: build, init, install, search" in unknown_text

    accepted = _ebx(ebx_home, "config", "set", "shortcuts.aaaaa", "template init")
    accepted_text = _shown(accepted)
    assert accepted.returncode == 0, accepted_text
    assert "Set shortcut aaaaa = template init" in accepted_text
    assert 'aaaaa = "template init"' in config_path.read_text(encoding="utf-8")

    fetched = _ebx(ebx_home, "config", "get", "shortcuts.aaaaa")
    assert fetched.returncode == 0, _shown(fetched)
    assert fetched.stdout.strip() == "template init"

    via_alias = _ebx(ebx_home, "aaaaa", "--list")
    via_target = _ebx(ebx_home, "template", "init", "--list")
    assert via_alias.returncode == 0, _shown(via_alias)
    assert via_target.returncode == 0, _shown(via_target)
    assert via_alias.stdout == via_target.stdout
    assert "python" in via_alias.stdout

    removed = _ebx(ebx_home, "config", "set", "shortcuts.aaaaa", "")
    assert removed.returncode == 0, _shown(removed)
    assert "Removed shortcut 'aaaaa'" in _shown(removed)
    gone = _ebx(ebx_home, "aaaaa", "--list")
    gone_text = _shown(gone)
    assert gone.returncode == 2, gone_text
    assert "No such command 'aaaaa'" in gone_text


@pytest.mark.integration
def test_stored_ebx_prefix_is_ignored_and_other_aliases_keep_working(ebx_home: Path) -> None:
    """A bad line already in the file is skipped; factory aliases still run.

    The documented recovery path is a hand edit of ``~/.ebx/config.toml``,
    then a new process. One invalid alias must not disable ``init``.
    """
    seeded = _ebx(ebx_home, "config", "get", "shortcuts")
    assert seeded.returncode == 0, _shown(seeded)
    config_path = ebx_home / ".ebx" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + 'aaaaa = "ebx template init"\n',
        encoding="utf-8",
    )

    via_init = _ebx(ebx_home, "init", "--list")
    via_target = _ebx(ebx_home, "template", "init", "--list")
    assert via_init.returncode == 0, _shown(via_init)
    assert via_target.returncode == 0, _shown(via_target)
    assert via_init.stdout == via_target.stdout
    assert "python" in via_init.stdout
    assert "Invalid shortcut ignored" in (via_init.stderr or "")
    assert 'Drop the leading "ebx"' in (via_init.stderr or "")
    assert 'Try: ebx config set shortcuts.aaaaa "template init"' in (via_init.stderr or "")

    missing = _ebx(ebx_home, "aaaaa", "--list")
    missing_text = _shown(missing)
    assert missing.returncode == 2, missing_text
    assert "No such command 'aaaaa'" in missing_text


@pytest.mark.integration
def test_ebx_prefix_plus_unknown_path_lists_grouped_targets(ebx_home: Path) -> None:
    """``ebx`` plus a path that is still unknown keeps the prefix rule and the list."""
    result = _ebx(ebx_home, "config", "set", "shortcuts.aaaaa", "ebx not-a-command")
    text = _shown(result)
    assert result.returncode == 2, text
    assert 'Drop the leading "ebx"' in text
    assert '"not-a-command" is not a command path' in text
    assert "Available targets:" in text
    assert "template: build, init, install, search" in text
    stored = (ebx_home / ".ebx" / "config.toml").read_text(encoding="utf-8")
    assert "aaaaa =" not in stored


@pytest.mark.integration
def test_config_set_help_states_the_prefix_rule(ebx_home: Path) -> None:
    """``ebx config set --help`` is the description a first attempt can read."""
    result = _ebx(ebx_home, "config", "set", "--help")
    text = _shown(result)
    assert result.returncode == 0, text
    assert 'without the "ebx" prefix' in text
    assert '"template init"' in text
    assert '"ebx template init"' in text


@pytest.mark.integration
def test_unknown_command_shows_a_prefix_free_shortcut_example(ebx_home: Path) -> None:
    """``ebx ccc`` points at a shortcut target that does not start with ``ebx``."""
    result = _ebx(ebx_home, "ccc")
    text = _shown(result)
    assert result.returncode == 2, text
    assert "No such command 'ccc'" in text
    assert 'ebx config set shortcuts.NAME "template init"' in text
    assert "custom_commands" in text
    assert "ebx run COMMAND" in text


@pytest.mark.integration
def test_json_suggestion_names_the_corrected_command(ebx_home: Path) -> None:
    """``--json`` returns the same correction without the text-mode indent."""
    result = _ebx(
        ebx_home,
        "--json",
        "config",
        "set",
        "shortcuts.aaaaa",
        "ebx template init",
    )
    text = _shown(result)
    assert result.returncode == 2, text
    assert '"status": "error"' in text
    assert 'Try: ebx config set shortcuts.aaaaa \\"template init\\"' in text
    assert "              Try:" not in text
