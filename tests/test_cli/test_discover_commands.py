"""Tests for ``_discover_registered_commands`` security hardening.

Validates the opt-in gate (env var / .ebx marker) and safe-filename filter.
"""

from __future__ import annotations

import pytest

from easy_sandbox.cli.commands.sandbox import _discover_registered_commands

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REGISTER_SCRIPT = """\
from easy_sandbox.declarative.decorator import sandbox

@sandbox.register
def discovered_cmd(x: int) -> int:
    return x * 2
"""


@pytest.fixture()
def project_dir(tmp_path, monkeypatch):
    """Create a fake project directory with a register script."""
    script = tmp_path / "my_commands.py"
    script.write_text(_REGISTER_SCRIPT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # Ensure env var is unset by default
    monkeypatch.delenv("EBX_DISCOVER_COMMANDS", raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# Opt-in gate
# ---------------------------------------------------------------------------


class TestOptInGate:
    """Discovery requires explicit opt-in."""

    def test_no_opt_in_does_not_scan(self, project_dir):
        """Without env var or .ebx marker, nothing is imported."""
        from easy_sandbox.declarative.decorator import sandbox as _sb

        before = set(_sb._registry)
        _discover_registered_commands()
        after = set(_sb._registry)
        assert before == after, "Should not have discovered anything"

    def test_env_var_enables_discovery(self, project_dir, monkeypatch):
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "1")
        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "discovered_cmd" in _sb._registry

    def test_env_var_true_string(self, project_dir, monkeypatch):
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "true")
        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "discovered_cmd" in _sb._registry

    def test_env_var_yes_string(self, project_dir, monkeypatch):
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "yes")
        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "discovered_cmd" in _sb._registry

    def test_ebx_marker_file_enables_discovery(self, project_dir):
        (project_dir / ".ebx").write_text("", encoding="utf-8")
        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "discovered_cmd" in _sb._registry

    def test_ebx_marker_dir_enables_discovery(self, project_dir):
        (project_dir / ".ebx").mkdir()
        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "discovered_cmd" in _sb._registry

    def test_env_var_zero_does_not_enable(self, project_dir, monkeypatch):
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "0")
        from easy_sandbox.declarative.decorator import sandbox as _sb

        before = set(_sb._registry)
        _discover_registered_commands()
        after = set(_sb._registry)
        assert before == after


# ---------------------------------------------------------------------------
# Filename safety
# ---------------------------------------------------------------------------


class TestFilenameSafety:
    """Only valid Python identifiers are imported."""

    def test_dotted_filename_skipped(self, project_dir, monkeypatch):
        """A file like ``foo.bar.py`` (invalid identifier stem) is skipped."""
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "1")
        bad = project_dir / "foo.bar.py"
        bad.write_text(_REGISTER_SCRIPT.replace("discovered_cmd", "dotted_cmd"), encoding="utf-8")

        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "dotted_cmd" not in _sb._registry

    def test_hyphenated_filename_skipped(self, project_dir, monkeypatch):
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "1")
        bad = project_dir / "my-commands.py"
        bad.write_text(_REGISTER_SCRIPT.replace("discovered_cmd", "hyph_cmd"), encoding="utf-8")

        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "hyph_cmd" not in _sb._registry

    def test_numeric_start_filename_skipped(self, project_dir, monkeypatch):
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "1")
        bad = project_dir / "1evil.py"
        bad.write_text(_REGISTER_SCRIPT.replace("discovered_cmd", "num_cmd"), encoding="utf-8")

        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "num_cmd" not in _sb._registry

    def test_underscore_filename_allowed(self, project_dir, monkeypatch):
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "1")
        ok = project_dir / "_private_cmds.py"
        ok.write_text(_REGISTER_SCRIPT.replace("discovered_cmd", "priv_cmd"), encoding="utf-8")

        from easy_sandbox.declarative.decorator import sandbox as _sb

        _discover_registered_commands()
        assert "priv_cmd" in _sb._registry


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestDiscoverEdgeCases:
    """Misc edge cases."""

    def test_file_without_register_ignored(self, project_dir, monkeypatch):
        """Files not containing 'sandbox.register' are not imported."""
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "1")
        inert = project_dir / "utils.py"
        inert.write_text("x = 42\n", encoding="utf-8")

        from easy_sandbox.declarative.decorator import sandbox as _sb

        before = set(_sb._registry)
        _discover_registered_commands()
        # Only the register script should be imported
        assert "discovered_cmd" in _sb._registry
        # utils.py should NOT have triggered any registration
        new_cmds = set(_sb._registry) - before
        assert "x" not in new_cmds

    def test_broken_file_silently_skipped(self, project_dir, monkeypatch):
        """A file with syntax errors should not crash discovery."""
        monkeypatch.setenv("EBX_DISCOVER_COMMANDS", "1")
        broken = project_dir / "broken_cmds.py"
        broken.write_text("sandbox.register\ndef bad(:\n", encoding="utf-8")

        # Should not raise
        _discover_registered_commands()
