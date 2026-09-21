"""Unified CLI output manager with TTY/CI detection and multi-mode support.

Provides a single ``OutputManager`` that every CLI command should use instead
of bare ``click.echo`` calls.  Supports normal, verbose, quiet, JSON, and
CI output modes.
"""
from __future__ import annotations

import json as json_module
import logging
import os
import sys
from typing import Any

import click

__all__ = [
    "OutputManager",
    "get_output",
    "is_tty",
    "is_ci_env",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

_CI_ENV_VARS: tuple[str, ...] = (
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


def is_tty() -> bool:
    """Return ``True`` when *stdout* is connected to a terminal."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def is_ci_env() -> bool:
    """Return ``True`` when running inside a known CI environment."""
    return any(os.environ.get(v) for v in _CI_ENV_VARS)


# ---------------------------------------------------------------------------
# OutputManager
# ---------------------------------------------------------------------------


class OutputManager:
    """Unified output manager for the CLI.

    Central place that decides *what* gets printed and *how*, depending on
    the combination of ``--verbose``, ``--quiet``, ``--json``, ``--no-color``,
    ``--ci``, and ``--log-level`` flags.

    Parameters
    ----------
    verbose:
        Emit DEBUG-level messages.
    quiet:
        Suppress informational messages; only errors and final results.
    json_mode:
        All output as JSON lines (machine-parseable).
    no_color:
        Disable ANSI colours / Rich markup.
    ci:
        CI/CD mode — implies *quiet + no_color + json_mode*.
    log_level:
        Explicit log level string (``DEBUG`` / ``INFO`` / ``WARNING`` /
        ``ERROR``).  Takes precedence over *verbose* / *quiet*.
    """

    def __init__(
        self,
        *,
        verbose: bool = False,
        quiet: bool = False,
        json_mode: bool = False,
        no_color: bool = False,
        ci: bool = False,
        log_level: str | None = None,
    ) -> None:
        # CI mode overrides
        if ci:
            quiet = True
            json_mode = True
            no_color = True

        self.verbose = verbose
        self.quiet = quiet
        self.json_mode = json_mode
        self.no_color = no_color or not is_tty()
        self.ci = ci

        # Resolve effective log level
        if log_level is not None:
            self._level = getattr(logging, log_level.upper(), logging.INFO)
        elif verbose:
            self._level = logging.DEBUG
        elif quiet:
            self._level = logging.ERROR
        else:
            self._level = logging.INFO

        # Configure the root logger once so that library-level logging
        # respects the chosen verbosity.
        logging.basicConfig(
            level=self._level,
            format="%(levelname)s: %(message)s",
            force=True,
        )

    # -- public helpers for the existing OutputFormatter context keys --------

    @property
    def use_json(self) -> bool:  # noqa: D401
        """Alias kept for backward compatibility with ``OutputFormatter``."""
        return self.json_mode

    # -- output methods -----------------------------------------------------

    def info(self, message: str, **kwargs: Any) -> None:
        """Print an informational message (suppressed in *quiet* mode)."""
        if self.quiet:
            return
        if self.json_mode:
            self._json({"level": "info", "message": message, **kwargs})
        else:
            click.echo(message)

    def success(self, message: str, **kwargs: Any) -> None:
        """Print a success message (suppressed in *quiet* mode)."""
        if self.quiet:
            return
        if self.json_mode:
            self._json({"status": "success", "message": message, **kwargs})
        else:
            if self.no_color:
                click.echo(message)
            else:
                click.echo(click.style(message, fg="green"))

    def warning(self, message: str, **kwargs: Any) -> None:
        """Print a warning message (always shown unless *quiet*)."""
        if self.quiet:
            return
        if self.json_mode:
            self._json({"level": "warning", "message": message, **kwargs})
        else:
            if self.no_color:
                click.echo(f"Warning: {message}", err=True)
            else:
                click.echo(click.style(f"Warning: {message}", fg="yellow"), err=True)

    def error(self, message: str, *, code: str = "", suggestion: str = "", **kwargs: Any) -> None:
        """Print an error message (**always** shown, even in *quiet* mode)."""
        if self.json_mode:
            payload: dict[str, Any] = {"status": "error", "message": message}
            if code:
                payload["code"] = code
            if suggestion:
                payload["suggestion"] = suggestion
            payload.update(kwargs)
            self._json(payload)
        else:
            parts: list[str] = []
            if code:
                parts.append(f"[{code}] ")
            parts.append(message)
            text = "".join(parts)
            if self.no_color:
                click.echo(text, err=True)
            else:
                click.echo(click.style(text, fg="red"), err=True)
            if suggestion and not self.quiet:
                click.echo(f"  Suggestion: {suggestion}", err=True)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Print a debug message (only in *verbose* mode)."""
        if not self.verbose:
            return
        if self.json_mode:
            self._json({"level": "debug", "message": message, **kwargs})
        else:
            if self.no_color:
                click.echo(f"DEBUG: {message}", err=True)
            else:
                click.echo(click.style(f"DEBUG: {message}", fg="cyan"), err=True)

    def data(self, data: dict[str, Any] | list[Any] | Any, **kwargs: Any) -> None:
        """Print structured data.

        In JSON mode the data is emitted as a JSON object.  Otherwise it is
        formatted as a key-value list (for dicts), a table (for lists of
        dicts), or plain ``str()`` for anything else.
        """
        if self.json_mode:
            self._json(data)
            return

        if isinstance(data, dict):
            if not data:
                return
            max_key = max(len(str(k)) for k in data)
            for k, v in data.items():
                click.echo(f"{str(k).ljust(max_key)}  {v}")
        elif isinstance(data, list):
            for item in data:
                click.echo(str(item))
        else:
            click.echo(str(data))

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        """Print tabular data.

        JSON mode emits a list of dicts; quiet mode emits tab-separated
        values; normal mode attempts a Rich table with a plain-text fallback.
        """
        if self.json_mode:
            items = [dict(zip(headers, row, strict=False)) for row in rows]
            self._json(items)
            return
        if self.quiet:
            for row in rows:
                click.echo("\t".join(row))
            return
        # Rich table with fallback
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
            header_line = "\t".join(headers)
            click.echo(header_line)
            click.echo("-" * len(header_line))
            for row in rows:
                click.echo("\t".join(row))

    def progress(self, message: str) -> None:
        """Print a progress / status message.

        In CI mode this is a simple one-liner; in interactive mode it could
        use a spinner (future enhancement).
        """
        if self.quiet:
            return
        if self.json_mode:
            self._json({"level": "progress", "message": message})
        else:
            if self.no_color:
                click.echo(f"... {message}")
            else:
                click.echo(click.style(f"... {message}", fg="blue"))

    # -- private helpers ----------------------------------------------------

    def _json(self, data: Any) -> None:
        """Emit a single JSON value to stdout."""
        try:
            import orjson

            click.echo(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
        except ImportError:
            click.echo(json_module.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Context helper
# ---------------------------------------------------------------------------


def get_output(ctx: click.Context | None = None) -> OutputManager:
    """Retrieve the ``OutputManager`` from the Click context.

    The manager is stored in ``ctx.meta["sbox.output"]`` so that
    ``ctx.obj`` remains JSON-serializable.

    Falls back to a default instance when no context is available (e.g.
    during early startup / error handling).
    """
    if ctx is None:
        ctx = click.get_current_context(silent=True)

    if ctx is not None:
        mgr = ctx.meta.get("sbox.output")
        if isinstance(mgr, OutputManager):
            return mgr

    # Fallback — create a minimal default manager
    return OutputManager()
