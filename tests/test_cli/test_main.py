"""Tests for CLI main entry point and LazyGroup."""
from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from serverless_sandbox.cli.main import LazyGroup, cli


class TestLazyGroup:
    """Test the LazyGroup lazy-loading mechanism."""

    def test_list_commands_includes_lazy(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # All lazy commands should appear in help
        for cmd in ("create", "list", "info", "kill", "exec", "connect", "config", "template", "mcp", "install"):
            assert cmd in result.output

    def test_lazy_group_loads_on_demand(self) -> None:
        """LazyGroup should resolve import paths correctly."""
        group = LazyGroup(
            name="test",
            lazy_subcommands={
                "create": "serverless_sandbox.cli.commands.sandbox:create",
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
                "beta": "serverless_sandbox.cli.commands.sandbox:create",
                "alpha": "serverless_sandbox.cli.commands.sandbox:create",
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
        assert "sbox" in result.output
        assert "Serverless Sandbox CLI" in result.output

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

        result = runner.invoke(cli, ["--json", "--quiet", "--no-color", "--timeout", "60", "_test_ctx"])
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
        assert "Usage" in result.output or "sbox" in result.output
