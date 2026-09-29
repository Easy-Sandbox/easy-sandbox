"""Tests for the E2B compatibility layer public exports.

Guards the import surface documented in ``docs/*/guide/migrate-from-e2b.md``:
``from easy_sandbox.compat import E2BSandbox`` must keep working, and
``easy_sandbox.compat.__all__`` must list both public names.
"""

from __future__ import annotations

import easy_sandbox.compat as compat


class TestCompatPackageExports:
    """Test the ``easy_sandbox.compat`` package re-exports."""

    def test_import_sandbox_from_package(self) -> None:
        from easy_sandbox.compat import Sandbox

        assert Sandbox is not None

    def test_import_e2b_sandbox_from_package(self) -> None:
        from easy_sandbox.compat import E2BSandbox

        assert E2BSandbox is not None

    def test_import_e2b_sandbox_from_submodule(self) -> None:
        from easy_sandbox.compat.sandbox import E2BSandbox, Sandbox

        assert E2BSandbox is Sandbox

    def test_e2b_sandbox_is_alias_of_sandbox(self) -> None:
        from easy_sandbox.compat import E2BSandbox, Sandbox

        # ``compat/sandbox.py`` defines ``E2BSandbox = Sandbox`` (an alias,
        # not a subclass), so both names resolve to the same class object.
        assert E2BSandbox is Sandbox
        assert issubclass(E2BSandbox, Sandbox)

    def test_all_contains_both_exports(self) -> None:
        assert "Sandbox" in compat.__all__
        assert "E2BSandbox" in compat.__all__

    def test_all_entries_are_resolvable(self) -> None:
        for name in compat.__all__:
            assert getattr(compat, name) is not None
