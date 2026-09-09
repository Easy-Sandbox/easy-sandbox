"""Tests for CLI output formatters."""
from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from serverless_sandbox.cli.formatters import OutputFormatter, get_formatter


class TestOutputFormatterSuccess:
    """Test print_success in all modes."""

    def test_normal_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(no_color=True)
        with runner.isolated_filesystem():
            result = runner.invoke(_make_cmd(lambda: fmt.print_success("All good")))
            assert result.exit_code == 0
            assert "All good" in result.output

    def test_json_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(use_json=True)
        result = runner.invoke(_make_cmd(lambda: fmt.print_success("All good")))
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["message"] == "All good"

    def test_quiet_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(quiet=True)
        result = runner.invoke(_make_cmd(lambda: fmt.print_success("All good")))
        assert result.exit_code == 0
        assert result.output.strip() == ""


class TestOutputFormatterError:
    """Test print_error in all modes."""

    def test_normal_with_code_and_suggestion(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(no_color=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_error("Oops", code="E1001", suggestion="Try again"))
        )
        # Click 8.5 separates stderr by default; Click <8.5 mixes into output
        try:
            err = result.stderr
        except ValueError:
            err = result.output
        assert "[E1001]" in err
        assert "Oops" in err
        assert "Try again" in err

    def test_json_mode_error(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(use_json=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_error("Bad", code="E2002", suggestion="Fix it"))
        )
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "E2002"
        assert data["suggestion"] == "Fix it"

    def test_error_no_suggestion_when_quiet(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(quiet=True, no_color=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_error("Error", suggestion="Hint"))
        )
        # Click 8.5 separates stderr by default; Click <8.5 mixes into output
        try:
            err = result.stderr
        except ValueError:
            err = result.output
        assert "Suggestion" not in err


class TestOutputFormatterTable:
    """Test print_table in all modes."""

    def test_json_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(use_json=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_table(["Name", "Age"], [["Alice", "30"], ["Bob", "25"]]))
        )
        data = json.loads(result.output)
        assert len(data) == 2
        assert data[0] == {"Name": "Alice", "Age": "30"}

    def test_quiet_mode_tab_separated(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(quiet=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_table(["A", "B"], [["1", "2"], ["3", "4"]]))
        )
        lines = result.output.strip().split("\n")
        assert lines[0] == "1\t2"
        assert lines[1] == "3\t4"

    def test_normal_mode_has_content(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(no_color=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_table(["ID", "Status"], [["sbx-1", "running"]]))
        )
        assert "sbx-1" in result.output
        assert "running" in result.output


class TestOutputFormatterDict:
    """Test print_dict in all modes."""

    def test_json_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(use_json=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_dict({"key": "value", "num": 42}))
        )
        data = json.loads(result.output)
        assert data["key"] == "value"
        assert data["num"] == 42

    def test_quiet_mode_values_only(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(quiet=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_dict({"key": "value", "num": 42}))
        )
        lines = result.output.strip().split("\n")
        assert "value" in lines[0]
        assert "42" in lines[1]

    def test_normal_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(no_color=True)
        result = runner.invoke(
            _make_cmd(lambda: fmt.print_dict({"name": "test"}))
        )
        assert "name" in result.output
        assert "test" in result.output


class TestGetFormatter:
    """Test get_formatter extracts context correctly."""

    def test_from_context(self) -> None:
        @click.command()
        @click.pass_context
        def cmd(ctx: click.Context) -> None:
            ctx.ensure_object(dict)
            ctx.obj["json"] = True
            ctx.obj["quiet"] = False
            ctx.obj["no_color"] = True
            fmt = get_formatter(ctx)
            assert fmt.use_json is True
            assert fmt.quiet is False
            assert fmt.no_color is True

        runner = CliRunner()
        result = runner.invoke(cmd)
        assert result.exit_code == 0

    def test_from_empty_context(self) -> None:
        @click.command()
        @click.pass_context
        def cmd(ctx: click.Context) -> None:
            ctx.obj = None
            fmt = get_formatter(ctx)
            assert fmt.use_json is False

        runner = CliRunner()
        result = runner.invoke(cmd)
        assert result.exit_code == 0


class TestPrintData:
    """Test print_data."""

    def test_json_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter(use_json=True)
        result = runner.invoke(_make_cmd(lambda: fmt.print_data({"a": 1})))
        data = json.loads(result.output)
        assert data == {"a": 1}

    def test_normal_mode(self) -> None:
        runner = CliRunner()
        fmt = OutputFormatter()
        result = runner.invoke(_make_cmd(lambda: fmt.print_data("hello")))
        assert "hello" in result.output


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_cmd(fn):
    """Wrap a callable as a Click command for CliRunner."""
    @click.command()
    def cmd():
        fn()
    return cmd
