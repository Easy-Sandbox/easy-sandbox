"""Output formatters for CLI commands.

Supports three modes: table (rich), JSON, and quiet.
"""
from __future__ import annotations

import json as json_module
from typing import Any

import click


class OutputFormatter:
    """Base formatter that dispatches to the right format."""

    def __init__(
        self,
        *,
        use_json: bool = False,
        quiet: bool = False,
        no_color: bool = False,
    ) -> None:
        self.use_json = use_json
        self.quiet = quiet
        self.no_color = no_color

    def print_success(self, message: str) -> None:
        """Print a success message."""
        if self.quiet:
            return
        if self.use_json:
            self._print_json({"status": "success", "message": message})
        else:
            _click_echo_green(message, no_color=self.no_color)

    def print_error(
        self,
        message: str,
        *,
        suggestion: str = "",
        code: str = "",
    ) -> None:
        """Print an error message with optional code and suggestion."""
        if self.use_json:
            data: dict[str, Any] = {"status": "error", "message": message}
            if code:
                data["code"] = code
            if suggestion:
                data["suggestion"] = suggestion
            self._print_json(data)
        else:
            parts: list[str] = []
            if code:
                parts.append(f"[{code}] ")
            parts.append(message)
            _click_echo_red("".join(parts), no_color=self.no_color)
            if suggestion and not self.quiet:
                click.echo(f"  Suggestion: {suggestion}", err=True)

    def print_table(self, headers: list[str], rows: list[list[str]]) -> None:
        """Print data as a table (rich), JSON, or quiet tab-separated."""
        if self.use_json:
            items = [dict(zip(headers, row)) for row in rows]
            self._print_json(items)
            return
        if self.quiet:
            for row in rows:
                click.echo("\t".join(row))
            return
        # Try rich table, fallback to simple
        try:
            from rich.console import Console
            from rich.table import Table

            console = Console(no_color=self.no_color)
            table = Table()
            for h in headers:
                table.add_column(h, style="bold")
            for row in rows:
                table.add_row(*row)
            console.print(table)
        except ImportError:
            # Fallback to simple format
            header_line = "\t".join(headers)
            click.echo(header_line)
            click.echo("-" * len(header_line))
            for row in rows:
                click.echo("\t".join(row))

    def print_dict(self, data: dict[str, Any]) -> None:
        """Print a dict as key-value pairs, JSON, or quiet values."""
        if self.use_json:
            self._print_json(data)
            return
        if self.quiet:
            for v in data.values():
                click.echo(str(v))
            return
        max_key_len = max((len(str(k)) for k in data), default=0)
        for k, v in data.items():
            click.echo(f"{str(k).ljust(max_key_len)}  {v}")

    def print_data(self, data: Any) -> None:
        """Print raw data (for JSON mode mostly)."""
        if self.use_json:
            self._print_json(data)
        else:
            click.echo(str(data))

    def _print_json(self, data: Any) -> None:
        """Print data as JSON (prefer orjson if available)."""
        try:
            import orjson

            click.echo(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
        except ImportError:
            click.echo(json_module.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _click_echo_green(msg: str, no_color: bool = False) -> None:
    if no_color:
        click.echo(msg)
    else:
        click.echo(click.style(msg, fg="green"))


def _click_echo_red(msg: str, no_color: bool = False) -> None:
    if no_color:
        click.echo(msg, err=True)
    else:
        click.echo(click.style(msg, fg="red"), err=True)


def get_formatter(ctx: click.Context) -> OutputFormatter:
    """Get an OutputFormatter from the Click context.

    When the new :class:`~easy_sandbox.cli.output.OutputManager` is
    available in *ctx.meta*, we return the legacy formatter configured from
    it.  Otherwise we fall back to the manual ctx.obj dict approach.
    """
    # Prefer the OutputManager stored by the CLI root
    mgr = ctx.meta.get("ebx.output") if ctx else None
    if mgr is not None:
        return OutputFormatter(
            use_json=mgr.json_mode,
            quiet=mgr.quiet,
            no_color=mgr.no_color,
        )
    obj = ctx.obj or {} if ctx else {}
    return OutputFormatter(
        use_json=obj.get("json", False),
        quiet=obj.get("quiet", False),
        no_color=obj.get("no_color", False),
    )
