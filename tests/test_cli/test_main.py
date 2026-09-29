"""Tests for CLI main entry point and LazyGroup."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import click

from easy_sandbox.cli.main import LazyGroup, cli

if TYPE_CHECKING:
    from click.testing import CliRunner


class TestLazyGroup:
    """Test the LazyGroup lazy-loading mechanism."""

    def test_list_commands_includes_lazy(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # All lazy commands should appear in help
        for cmd in (
            "create",
            "list",
            "info",
            "kill",
            "exec",
            "connect",
            "config",
            "template",
            "mcp",
            "install",
        ):
            assert cmd in result.output

    def test_lazy_group_loads_on_demand(self) -> None:
        """LazyGroup should resolve import paths correctly."""
        group = LazyGroup(
            name="test",
            lazy_subcommands={
                "create": "easy_sandbox.cli.commands.sandbox:create",
            },
        )
        ctx = click.Context(group)
        cmd = group.get_command(ctx, "create")
        assert cmd is not None
        assert cmd.name == "create"

    def test_lazy_group_returns_none_for_unknown(self) -> None:
        group = LazyGroup(
            name="test",
            lazy_subcommands={},
        )
        ctx = click.Context(group)
        assert group.get_command(ctx, "nonexistent") is None

    def test_lazy_group_list_commands_sorted(self) -> None:
        group = LazyGroup(
            name="test",
            lazy_subcommands={
                "beta": "easy_sandbox.cli.commands.sandbox:create",
                "alpha": "easy_sandbox.cli.commands.sandbox:create",
            },
        )
        ctx = click.Context(group)
        cmds = group.list_commands(ctx)
        assert cmds == ["alpha", "beta"]


class TestCLIRoot:
    """Test the root CLI group."""

    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ebx" in result.output
        assert "Easy Sandbox CLI" in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        # Should contain version number
        assert "version" in result.output.lower() or "0." in result.output

    def test_context_options_stored(self, runner: CliRunner) -> None:
        """Global options should be passed through context."""

        @cli.command("_test_ctx")
        @click.pass_context
        def _test_ctx(ctx: click.Context) -> None:
            click.echo(json.dumps(ctx.obj))

        result = runner.invoke(
            cli, ["--json", "--quiet", "--no-color", "--timeout", "60", "_test_ctx"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["json"] is True
        assert data["quiet"] is True
        assert data["no_color"] is True
        assert data["timeout"] == 60

    def test_no_args_shows_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        # Should show usage/help when no command
        assert "Usage" in result.output or "ebx" in result.output


class TestTopLevelInitRestored:
    """The top-level ``ebx init`` scaffold shortcut is back (task 211).

    It shares the exact same ``click.Command`` object as ``ebx template init``
    (the scaffold logic is never duplicated), while ``ebx config init``
    (credentials) and ``ebx create`` (cloud sandbox) keep their single
    responsibilities.
    """

    def test_top_level_init_is_a_command(self) -> None:
        ctx = click.Context(cli)
        assert cli.get_command(ctx, "init") is not None

    def test_invoking_init_without_case_requires_explicit_choice(self, runner: CliRunner) -> None:
        """Non-TTY (CliRunner) never blocks: an explicit case or --from is required."""
        result = runner.invoke(cli, ["init"])
        # ``handle_errors`` re-wraps a callback-raised click.UsageError into
        # the general error exit (1); the message keeps the usage contract.
        assert result.exit_code == 1
        assert "No scaffold case specified" in result.output
        assert "Use -t/--template <case> or --from <ref>" in result.output

    def test_init_help_shows_scaffold_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0
        assert "Scaffold a new sandbox template project" in result.output

    def test_root_help_lists_init_command(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        commands_block = result.output.split("Commands:", 1)[1]
        listed = [line.strip().split()[0] for line in commands_block.splitlines() if line.strip()]
        assert "init" in listed
        # The real entry points survive.
        assert {"create", "config", "template"}.issubset(set(listed))

    def test_root_help_names_the_three_entry_points(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Setup, create, or scaffold:" in result.output
        assert "ebx config init" in result.output
        assert "ebx create [DESCRIPTION]" in result.output
        assert "ebx template init [DIR]" in result.output

    def test_config_init_still_exists_with_guided_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "init", "--help"])
        assert result.exit_code == 0
        assert "Guided setup" in result.output

    def test_template_init_still_exists_with_scaffold_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "init", "--help"])
        assert result.exit_code == 0
        assert "Scaffold a new sandbox template project" in result.output


class TestVerboseSubcommandFlag:
    """The local ``-v/--verbose`` flag on subcommands flips the shared manager."""

    def test_enable_verbose_sets_context_and_manager(self) -> None:
        from easy_sandbox.cli.output import OutputManager, enable_verbose, get_output

        ctx = click.Context(click.Command("x"))
        ctx.meta["ebx.output"] = OutputManager()
        ctx.obj = {}

        assert get_output(ctx).verbose is False
        enable_verbose(ctx)

        assert ctx.obj["verbose"] is True
        assert get_output(ctx).verbose is True

    def test_enable_verbose_creates_obj_when_missing(self) -> None:
        from easy_sandbox.cli.output import OutputManager, enable_verbose

        ctx = click.Context(click.Command("x"))
        ctx.meta["ebx.output"] = OutputManager()
        ctx.obj = None  # type: ignore[assignment]

        enable_verbose(ctx)
        assert ctx.obj == {"verbose": True}

    def test_set_verbose_enables_debug_output(self, capsys) -> None:
        from easy_sandbox.cli.output import OutputManager

        out = OutputManager(no_color=True)
        out.debug("hidden")
        assert "hidden" not in capsys.readouterr().err

        out.set_verbose(True)
        out.debug("shown")
        assert "shown" in capsys.readouterr().err
