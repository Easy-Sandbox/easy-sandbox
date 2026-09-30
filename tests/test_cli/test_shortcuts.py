"""Tests for CLI shortcuts: LazyGroup merge + ``ebx config`` shortcut commands.

Covered contracts:

* ``LazyGroup(merge_shortcuts=True)`` treats the ``[shortcuts]`` section of
  ``~/.ebx/config.toml`` as the single source of truth — user-defined aliases
  are registered, remapped defaults point at their new targets, deleted
  defaults disappear, reserved names cannot be overridden, invalid targets
  are skipped with a stderr warning, and a corrupted config only disables
  shortcuts (the core command groups keep working).
* ``ebx config`` shortcuts surface: ``get shortcuts[.<name>]``, ``set
  shortcuts.<name> VALUE|""``, ``list``, ``init`` and ``init
  --reset-shortcuts``.
* TOML round-trip: writing one section never drops the other
  (``[transport]`` vs ``[shortcuts]``).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import click

from easy_sandbox.cli.main import _CORE_COMMANDS, _DEFAULT_SHORTCUTS, LazyGroup, cli

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner

_CFG = "easy_sandbox.cli.commands.config_cmd"


def _parse_toml(text: str) -> dict[str, Any]:
    """Parse TOML text (stdlib ``tomllib`` on 3.11+, ``tomli`` fallback)."""
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11
        import tomli as tomllib
    return tomllib.loads(text)


class _FakeTTYStdin:
    def isatty(self) -> bool:
        return True


class _FakeSys:
    """``sys`` shim so the guided ``config init`` wizard runs interactively.

    ``CliRunner`` replaces the real ``sys.stdin`` with a non-TTY stream, which
    would make the wizard print the non-interactive commands and exit; the
    shim forces the interactive path instead.
    """

    def __init__(self) -> None:
        self.stdin = _FakeTTYStdin()

    def __getattr__(self, name: str) -> Any:
        return getattr(sys, name)


# ---------------------------------------------------------------------------
# Part 1a — LazyGroup merge behaviour (config file is the source of truth)
# ---------------------------------------------------------------------------


class TestLazyGroupShortcutMerge:
    """``LazyGroup(merge_shortcuts=True)`` honours the config file as-is."""

    @staticmethod
    def _build_group(tmp_path: Path, shortcuts: dict[str, str]) -> LazyGroup:
        """Build a fresh LazyGroup with the config layer patched out."""
        with (
            patch(f"{_CFG}._CONFIG_FILE", tmp_path / "config.toml"),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
            patch(f"{_CFG}._config_file_exists", return_value=True),
            patch(f"{_CFG}._create_default_config"),
            patch(f"{_CFG}.load_shortcuts", return_value=dict(shortcuts)),
        ):
            return LazyGroup(
                name="ebx-test",
                lazy_subcommands=dict(_CORE_COMMANDS),
                merge_shortcuts=True,
            )

    def test_missing_section_triggers_default_config_creation(self, tmp_path: Path) -> None:
        """Fresh install / pre-shortcuts file: defaults are materialised first."""
        with (
            patch(f"{_CFG}._CONFIG_FILE", tmp_path / "config.toml"),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
            patch(f"{_CFG}._config_file_exists", return_value=False),
            patch(f"{_CFG}._create_default_config") as mock_create,
            patch(f"{_CFG}.load_shortcuts", return_value={}),
        ):
            LazyGroup(
                name="ebx-test",
                lazy_subcommands=dict(_CORE_COMMANDS),
                merge_shortcuts=True,
            )
        mock_create.assert_called_once()

    def test_user_defined_alias_is_registered(self, tmp_path: Path) -> None:
        """A custom alias like ``ps = "sandbox process list"`` becomes a command."""
        group = self._build_group(tmp_path, {"ps": "sandbox process list"})
        ctx = click.Context(group)
        assert "ps" in group.list_commands(ctx)
        assert group.get_command(ctx, "ps") is not None

    def test_remapped_default_alias_targets_new_command(self, tmp_path: Path) -> None:
        """``create = "sandbox info"`` re-points the alias at the info command."""
        group = self._build_group(tmp_path, {"create": "sandbox info"})
        ctx = click.Context(group)
        cmd = group.get_command(ctx, "create")
        assert cmd is not None
        assert cmd.name == "info"

    def test_deleted_default_alias_is_not_registered(self, tmp_path: Path) -> None:
        """No implicit fallback: deleting ``create`` from the file removes it."""
        group = self._build_group(tmp_path, {"list": "sandbox list"})
        ctx = click.Context(group)
        assert group.get_command(ctx, "create") is None
        assert "create" not in group.list_commands(ctx)

    def test_reserved_name_cannot_be_overridden(self, tmp_path: Path, capsys) -> None:
        """``config`` is a built-in command group: shortcut is ignored, warning shown."""
        group = self._build_group(tmp_path, {"config": "sandbox create"})
        captured = capsys.readouterr()
        assert "conflicts with" in captured.err
        assert "ignored" in captured.err
        ctx = click.Context(group)
        cmd = group.get_command(ctx, "config")
        assert cmd is not None
        assert cmd.name == "config"

    def test_invalid_target_is_skipped_with_warning(self, tmp_path: Path, capsys) -> None:
        """A target outside ``_SHORTCUT_TARGET_MAP`` is dropped with a warning."""
        group = self._build_group(tmp_path, {"xyz": "nonexistent command"})
        captured = capsys.readouterr()
        assert "Invalid shortcut ignored" in captured.err
        assert 'without the "ebx" prefix' in captured.err
        assert "Available targets:" in captured.err
        ctx = click.Context(group)
        assert "xyz" not in group.list_commands(ctx)
        assert group.get_command(ctx, "xyz") is None

    def test_corrupted_config_keeps_core_commands_working(self, tmp_path: Path) -> None:
        """``load_shortcuts()`` returns {} on a corrupted file: core groups survive."""
        group = self._build_group(tmp_path, {})
        ctx = click.Context(group)
        for name in sorted(_CORE_COMMANDS):
            cmd = group.get_command(ctx, name)
            assert cmd is not None, f"core command {name!r} disappeared"
            assert cmd.name == name


# ---------------------------------------------------------------------------
# Part 1b — config subcommands: TOML round-trip
# ---------------------------------------------------------------------------


class TestConfigSetShortcutsTomlRoundTrip:
    """``ebx config set`` keeps the untouched TOML sections intact."""

    def test_set_shortcut_preserves_transport_section(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Adding a shortcut never damages the existing ``[transport]`` table."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[transport]\n"
            'region = "cn-hangzhou"\n'
            "http_timeout = 60\n"
            "\n"
            "[shortcuts]\n"
            'create = "sandbox create"\n'
        )
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "shortcuts.ps", "sandbox process list"])

        assert result.exit_code == 0, result.output
        assert "Set shortcut ps = sandbox process list" in result.output
        data = _parse_toml(config_file.read_text())
        assert data["transport"] == {"region": "cn-hangzhou", "http_timeout": 60}
        assert data["shortcuts"]["ps"] == "sandbox process list"
        assert data["shortcuts"]["create"] == "sandbox create"

    def test_set_region_preserves_shortcuts_section(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Rewriting ``[transport]`` never drops the configured shortcuts."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[transport]\n"
            'region = "cn-hangzhou"\n'
            "\n"
            "[shortcuts]\n"
            'create = "sandbox create"\n'
            'ps = "sandbox process list"\n'
        )
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "region", "cn-shanghai"])

        assert result.exit_code == 0, result.output
        data = _parse_toml(config_file.read_text())
        assert data["transport"]["region"] == "cn-shanghai"
        assert data["shortcuts"] == {
            "create": "sandbox create",
            "ps": "sandbox process list",
        }


# ---------------------------------------------------------------------------
# Part 1c — config init: section generation and reset
# ---------------------------------------------------------------------------


class TestConfigInitShortcuts:
    """``ebx config init`` writes / resets the ``[shortcuts]`` section."""

    def test_interactive_init_writes_full_shortcuts_section(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Guided setup materialises a config file carrying the default shortcuts."""
        config_file = tmp_path / "config.toml"
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
            patch(f"{_CFG}.sys", _FakeSys()),
        ):
            result = runner.invoke(cli, ["config", "init"], input="\ncn-shanghai\n\n\n\n\n")

        assert result.exit_code == 0, result.output
        assert "Added default shortcuts" in result.output
        data = _parse_toml(config_file.read_text())
        assert data["transport"]["region"] == "cn-shanghai"
        assert data["shortcuts"] == dict(_DEFAULT_SHORTCUTS)

    def test_reset_shortcuts_restores_defaults_keeps_transport(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """``--reset-shortcuts`` restores defaults and preserves ``[transport]``."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[transport]\nregion = "cn-hangzhou"\n\n[shortcuts]\nps = "sandbox process list"\n'
        )
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "init", "--reset-shortcuts"])

        assert result.exit_code == 0, result.output
        assert "Reset [shortcuts]" in result.output
        data = _parse_toml(config_file.read_text())
        assert data["transport"]["region"] == "cn-hangzhou"
        assert data["shortcuts"] == dict(_DEFAULT_SHORTCUTS)
        assert "ps" not in data["shortcuts"]


# ---------------------------------------------------------------------------
# Part 1d — config get / list / set surface
# ---------------------------------------------------------------------------


class TestConfigShortcutsQueries:
    """``ebx config get/list/set`` surface the configured shortcuts."""

    @staticmethod
    def _write_config(tmp_path: Path) -> Path:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[transport]\n\n[shortcuts]\ncreate = "sandbox create"\nps = "sandbox process list"\n'
        )
        return config_file

    def test_config_list_shows_shortcuts_with_sources(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Each alias is listed, annotated as default or user-defined."""
        config_file = self._write_config(tmp_path)
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "list"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        create_line = next(ln for ln in lines if ln.startswith("shortcuts.create"))
        assert "sandbox create" in create_line
        assert "(default)" in create_line
        ps_line = next(ln for ln in lines if ln.startswith("shortcuts.ps"))
        assert "sandbox process list" in ps_line
        assert "(user)" in ps_line

    def test_config_get_shortcuts_shows_all_aliases(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = self._write_config(tmp_path)
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "get", "shortcuts"])

        assert result.exit_code == 0
        assert "create" in result.output
        assert "sandbox create" in result.output
        assert "ps" in result.output
        assert "sandbox process list" in result.output

    def test_config_get_single_shortcut_shows_target(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        config_file = self._write_config(tmp_path)
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "get", "shortcuts.create"])

        assert result.exit_code == 0
        assert "sandbox create" in result.output

    def test_config_set_empty_value_removes_shortcut(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """``config set shortcuts.create ""`` deletes the alias, keeps the rest."""
        config_file = self._write_config(tmp_path)
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(cli, ["config", "set", "shortcuts.create", ""])

        assert result.exit_code == 0, result.output
        assert "Removed shortcut 'create'" in result.output
        data = _parse_toml(config_file.read_text())
        assert "create" not in data["shortcuts"]
        assert data["shortcuts"]["ps"] == "sandbox process list"

    def test_set_shortcut_with_ebx_prefix_names_the_fix(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """``ebx template init`` is rejected with the command to retry.

        First-time users type the invocation they already know. The error
        must say to drop ``ebx`` and show the corrected command, instead of
        a flat list of every target.
        """
        config_file = self._write_config(tmp_path)
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(
                cli,
                ["config", "set", "shortcuts.aaaaa", "ebx template init"],
            )

        shown = result.output + (getattr(result, "stderr", None) or "")
        assert result.exit_code == 2, shown
        assert "Invalid shortcut target: 'ebx template init'" in shown
        assert 'Drop the leading "ebx"' in shown
        assert 'for example "template init"' in shown
        assert 'Try: ebx config set shortcuts.aaaaa "template init"' in shown
        assert "Available targets:" not in shown
        data = _parse_toml(config_file.read_text())
        assert "aaaaa" not in data["shortcuts"]

    def test_set_shortcut_unknown_target_explains_the_path_rule(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """An unknown path states the rule and groups the legal targets."""
        config_file = self._write_config(tmp_path)
        with (
            patch(f"{_CFG}._CONFIG_FILE", config_file),
            patch(f"{_CFG}._EBX_DIR", tmp_path),
        ):
            result = runner.invoke(
                cli,
                ["config", "set", "shortcuts.aaaaa", "not-a-command"],
            )

        shown = result.output + (getattr(result, "stderr", None) or "")
        assert result.exit_code == 2, shown
        assert 'without the "ebx" prefix' in shown
        assert 'for example "template init"' in shown
        assert "Available targets:" in shown
        assert "template: build, init, install, search" in shown
        assert "sandbox: connect, create, download, exec, files list" in shown
