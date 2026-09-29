"""Task 210 targeted tests: explicit-route guard on ``ebx create`` and the
root LazyGroup unknown-command hint.

Contracts asserted here:
* ``ebx create`` with neither DESCRIPTION nor --template → Click UsageError,
  exit code 2, message on stderr listing all three explicit routes.
* Unknown top-level command with a close spelling candidate → exit 2 and a
  "Did you mean" suggestion only (no custom-command hint).
* Unknown top-level command with no plausible candidate → exit 2 and the
  template.yaml ``custom_commands`` / ``ebx run COMMAND`` hint.
* JSON / quiet / CI flags do not change exit code 2 semantics.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli

THREE_ROUTES = [
    "ebx create --template base",
    "--template <NAME>",
    "DESCRIPTION",
]


# ---------------------------------------------------------------------------
# 1. ebx create without description / template
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestCreateRequiresExplicitRoute:
    def test_bare_create_is_a_usage_error(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["create"])
        assert result.exit_code == 2
        assert "No DESCRIPTION or --template given" in result.output

    def test_error_lists_all_three_routes(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["create"])
        for fragment in THREE_ROUTES:
            assert fragment in result.output

    def test_explicit_base_still_routes_to_base(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The explicit base route keeps working (no AI, no clarification)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_sb = MagicMock()
        mock_sb.commands = MagicMock()
        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=mock_sb),
        ):
            result = runner.invoke(cli, ["create", "--template", "base"])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# 2. unknown top-level command hints
# ---------------------------------------------------------------------------


class TestUnknownCommandHints:
    def test_close_candidate_gets_correction_only(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["creat"])
        assert result.exit_code == 2
        assert "No such command 'creat'" in result.output
        assert "Did you mean" in result.output
        assert "'create'" in result.output
        # High-confidence candidates must NOT show the custom-command hint.
        assert "custom_commands" not in result.output

    def test_plausible_candidate_gets_correction_only(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["lis"])
        assert result.exit_code == 2
        assert "Did you mean" in result.output
        assert "custom_commands" not in result.output

    def test_no_candidate_gets_custom_command_hint(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["frobnicate"])
        assert result.exit_code == 2
        assert "No such command 'frobnicate'" in result.output
        assert "template.yaml" in result.output
        assert "custom_commands" in result.output
        assert "ebx run COMMAND" in result.output

    def test_init_typo_gets_init_correction(self, runner: CliRunner) -> None:
        """'ebx ini' now suggests the restored top-level ``init`` shortcut.

        difflib at cutoff 0.6 matches 'ini' against 'init' (restored by task
        211), so only the correction shows - no custom_commands hint.
        """
        result = runner.invoke(cli, ["ini"])
        assert result.exit_code == 2
        assert "No such command 'ini'" in result.output
        assert "Did you mean" in result.output
        assert "'init'" in result.output
        assert "custom_commands" not in result.output

    @pytest.mark.parametrize("flags", [["--json"], ["--quiet"], ["--ci"]])
    def test_exit_code_2_regardless_of_output_mode(
        self, runner: CliRunner, flags: list[str]
    ) -> None:
        result = runner.invoke(cli, [*flags, "frobnicate"])
        assert result.exit_code == 2
        assert "No such command 'frobnicate'" in result.output
