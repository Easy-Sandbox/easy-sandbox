"""Unified CLI output manager with TTY/CI detection and multi-mode support.

Provides a single ``OutputManager`` that every CLI command should use instead
of bare ``click.echo`` calls.  Supports normal, verbose, quiet, JSON, and
CI output modes.

Channel policy (task 167):

* **stdout** carries only what a user or a script consumes as the final
  result: ``data``, ``table``, ``success``.
* **stderr** carries progress state and diagnostics: ``info``, ``progress``,
  ``warning``, ``error``, ``debug``, and every stdlib ``logging`` record
  (bridged through a single root handler).

Machine-readable output can therefore never be polluted by status lines or
log records, in any mode (plain / ``--quiet`` / ``--json`` / ``--ci``).
"""

from __future__ import annotations

import json as json_module
import logging
import os
import sys
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "OutputManager",
    "enable_verbose",
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
# logging bridge
# ---------------------------------------------------------------------------


class _LogBridgeHandler(logging.Handler):
    """Forward stdlib ``logging`` records into the CLI's stderr channel.

    A *single* instance of this handler is installed on the root logger by
    :class:`OutputManager`, replacing the handler that
    ``easy_sandbox.utils.logging`` installs for standalone SDK use.  That is
    what keeps a library warning (e.g. the capability-resolver fallback) from
    being rendered twice — once with the SDK's timestamped format on the
    package logger and once through the root handler.

    Records are formatted once (``LEVELNAME: message``) and handed to the
    manager so that live spinners are paused before anything is written.
    """

    def __init__(self, manager: OutputManager) -> None:
        super().__init__(level=manager._level)
        self._manager = manager
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Write the formatted record to the manager's diagnostic channel."""
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - defensive (bad %-args)
            self.handleError(record)
            return
        self._manager._emit_log(message)


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

    Channel policy
    --------------
    Results meant to be consumed (``data`` / ``table`` / ``success``) are
    written to **stdout**; progress state and diagnostics (``info`` /
    ``progress`` / ``warning`` / ``error`` / ``debug``) are written to
    **stderr**, together with every bridged stdlib log record.  In ``--json``
    mode the diagnostic messages stay JSON, but on stderr, so ``stdout``
    remains a single machine-parseable document.
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
            # NOTE-01: Default to WARNING to avoid noisy INFO logs in
            # normal usage; users can use --verbose for DEBUG output.
            self._level = logging.WARNING

        #: Status objects currently rendering on stderr.  Output written
        #: while any of them is live is wrapped in a pause/resume guard so
        #: that Rich's live display never garbles a warning or a result.
        self._spinner_stack: list[Any] = []
        self._log_bridge: _LogBridgeHandler | None = None

        # Configure logging once so that library-level logging respects the
        # chosen verbosity and lands on the diagnostic channel exactly once.
        self._configure_logging()

    # -- public helpers for the existing OutputFormatter context keys --------

    @property
    def use_json(self) -> bool:
        """Alias kept for backward compatibility with ``OutputFormatter``."""
        return self.json_mode

    def set_verbose(self, enabled: bool = True) -> None:
        """Enable (or disable) verbose mode after construction.

        Used when a subcommand-level ``-v/--verbose`` flag is parsed after
        the root group has already created this manager.
        """
        self.verbose = enabled
        self._level = logging.DEBUG if enabled else logging.WARNING
        self._apply_log_level()

    # -- output methods -----------------------------------------------------

    def info(self, message: str, **kwargs: Any) -> None:
        """Print an informational message to *stderr* (suppressed in *quiet*)."""
        if self.quiet:
            return
        if self.json_mode:
            self._json({"level": "info", "message": message, **kwargs}, err=True)
        else:
            self._write_stderr(message)

    def success(self, message: str, **kwargs: Any) -> None:
        """Print a success message to *stdout* (suppressed in *quiet* mode).

        A success notice belongs to the result channel: it is what a human
        reads after the command did its job.
        """
        if self.quiet:
            return
        if self.json_mode:
            self._json({"status": "success", "message": message, **kwargs})
        else:
            self._write_stdout(message, color="green")

    def warning(self, message: str, **kwargs: Any) -> None:
        """Print a warning to *stderr* (always shown unless *quiet*)."""
        if self.quiet:
            return
        if self.json_mode:
            self._json({"level": "warning", "message": message, **kwargs}, err=True)
        else:
            self._write_stderr(f"Warning: {message}", color="yellow")

    def error(self, message: str, *, code: str = "", suggestion: str = "", **kwargs: Any) -> None:
        """Print an error message to *stderr* (**always** shown, even in *quiet*)."""
        if self.json_mode:
            payload: dict[str, Any] = {"status": "error", "message": message}
            if code:
                payload["code"] = code
            if suggestion:
                payload["suggestion"] = suggestion
            payload.update(kwargs)
            self._json(payload, err=True)
        else:
            parts: list[str] = []
            if code:
                parts.append(f"[{code}] ")
            parts.append(message)
            text = "".join(parts)
            self._write_stderr(text, color="red")
            if suggestion and not self.quiet:
                self._write_stderr(f"  Suggestion: {suggestion}")

    def debug(self, message: str, **kwargs: Any) -> None:
        """Print a debug message to *stderr* (only in *verbose* mode)."""
        if not self.verbose:
            return
        if self.json_mode:
            self._json({"level": "debug", "message": message, **kwargs}, err=True)
        else:
            self._write_stderr(f"DEBUG: {message}", color="cyan")

    def data(self, data: dict[str, Any] | list[Any] | Any, **kwargs: Any) -> None:
        """Print structured data — the user-consumable result — to *stdout*.

        In JSON mode the data is emitted as a single JSON document on stdout.
        In quiet mode only the bare values are written (one per line) so that
        shell pipelines keep working.  Otherwise dicts become aligned
        key/value lines, lists one line per item, and anything else ``str()``.
        """
        if self.json_mode:
            self._json(data)
            return

        if self.quiet:
            if isinstance(data, dict):
                for value in data.values():
                    self._write_stdout(str(value))
            elif isinstance(data, list):
                for item in data:
                    self._write_stdout(str(item))
            else:
                self._write_stdout(str(data))
            return

        if isinstance(data, dict):
            if not data:
                return
            max_key = max(len(str(k)) for k in data)
            for k, v in data.items():
                self._write_stdout(f"{str(k).ljust(max_key)}  {v}")
        elif isinstance(data, list):
            for item in data:
                self._write_stdout(str(item))
        else:
            self._write_stdout(str(data))

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        """Print tabular data.

        JSON mode emits a list of dicts; quiet mode emits tab-separated
        values; normal mode attempts a Rich table with a plain-text fallback.
        """
        if self.json_mode:
            items = [dict(zip(headers, row)) for row in rows]  # noqa: B905
            self._json(items)
            return
        if self.quiet:
            for row in rows:
                self._write_stdout("\t".join(row))
            return
        # Rich table with fallback
        try:
            from rich.console import Console
            from rich.table import Table

            console = Console(no_color=self.no_color, file=sys.stdout)
            table = Table()
            for h in headers:
                table.add_column(h, style="bold")
            for row in rows:
                table.add_row(*row)
            with self._spinner_guard():
                console.print(table)
        except ImportError:
            header_line = "\t".join(headers)
            self._write_stdout(header_line)
            self._write_stdout("-" * len(header_line))
            for row in rows:
                self._write_stdout("\t".join(row))

    def progress(self, message: str) -> None:
        """Print a progress / status message to *stderr*.

        Status updates are diagnostics, never results: they stay on stderr in
        every mode so ``ebx ... | jq`` (or any other consumer of stdout) is
        unaffected.  In CI/quiet mode they are suppressed.
        """
        if self.quiet:
            return
        if self.json_mode:
            self._json({"level": "progress", "message": message}, err=True)
        else:
            self._write_stderr(f"... {message}", color="blue")

    @property
    def use_rich_spinner(self) -> bool:
        """Whether rich spinners are appropriate for the current session.

        Only enabled in interactive TTY mode: disabled by ``--verbose``,
        ``--quiet``, ``--json``, ``--no-color`` (which includes non-TTY
        stdout), or when stderr is not connected to a terminal.

        In verbose mode spinners are suppressed because DEBUG log lines
        written to stderr would interleave with the Rich live-display,
        producing garbled output like ``⠋ Waiting...DEBUG: https://...``.
        """
        return not (
            self.verbose
            or self.quiet
            or self.json_mode
            or self.no_color
            or not (hasattr(sys.stderr, "isatty") and sys.stderr.isatty())
        )

    @contextmanager
    def spinner(self, message: str) -> Iterator[None]:
        """Context manager showing an animated spinner for a blocking operation.

        In interactive TTY mode a Rich spinner is rendered on *stderr* (so it
        never mixes with JSON/text results on stdout).  In quiet, JSON, CI, or
        non-TTY sessions the spinner is silent — callers already emit their own
        progress messages where needed.

        If the wrapped block raises, the spinner stops cleanly and the
        exception propagates untouched so callers can still report errors.
        """
        if not self.use_rich_spinner:
            yield
            return
        try:
            from rich.console import Console
        except ImportError:
            yield
            return
        console = Console(stderr=True)
        with console.status(f"[bold blue]{message}...", spinner="dots") as status:
            self._spinner_stack.append(status)
            try:
                yield
            finally:
                self._spinner_stack.pop()

    @contextmanager
    def live_spinner(self, message: str) -> Iterator[Any]:
        """Like :meth:`spinner`, but yields an updater callable.

        The yielded ``update(text)`` callable refreshes the spinner text (used
        to show poll status / elapsed time).  In verbose mode the updater
        prints each status change as a plain line on stderr so that poll
        progress remains visible alongside DEBUG logs.  In other degraded
        modes (quiet / JSON / non-TTY) the updater is a no-op.
        """
        if not self.use_rich_spinner:
            if self.verbose:
                # Print poll updates as plain lines so progress is visible
                # alongside DEBUG logs without conflicting with a spinner.
                yield lambda text: self._write_stderr(f"... {text}")
            else:
                yield lambda _text: None  # no-op in non-TTY / quiet / json
            return
        try:
            from rich.console import Console
        except ImportError:
            yield lambda _text: None
            return
        console = Console(stderr=True)
        with console.status(f"[bold blue]{message}...", spinner="dots") as status:
            self._spinner_stack.append(status)
            try:
                yield lambda text: status.update(f"[bold blue]{text}...")
            finally:
                self._spinner_stack.pop()

    # -- private helpers ----------------------------------------------------

    def _configure_logging(self) -> None:
        """Install the single stdlib-logging bridge used by this manager.

        The bridge handler lives on the *root* logger and replaces whatever a
        previous ``logging.basicConfig`` (or the SDK's standalone fallback
        handler) installed, so a library warning is rendered exactly once, on
        stderr.  Its level follows the CLI's verbosity — that is what
        ``--quiet`` / ``--verbose`` / ``--log-level`` mean during a CLI run —
        while propagation stays enabled so that ``caplog``-style handlers
        keep working.
        """
        root_logger = logging.getLogger()
        root_logger.setLevel(self._level)
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        # The SDK's standalone handler would render every record a second
        # time; the bridge supersedes it.  The package logger's own level is
        # left untouched: the handler gate already implements the CLI level.
        package_logger = logging.getLogger("easy_sandbox")
        for handler in list(package_logger.handlers):
            package_logger.removeHandler(handler)
        self._log_bridge = _LogBridgeHandler(self)
        root_logger.addHandler(self._log_bridge)

    def _apply_log_level(self) -> None:
        """Re-align the root logger and the bridge after a level change."""
        logging.getLogger().setLevel(self._level)
        if self._log_bridge is not None:
            self._log_bridge.setLevel(self._level)

    def _emit_log(self, message: str) -> None:
        """Write a bridged stdlib log record to stderr."""
        self._write_stderr(message)

    def _pause_spinner(self) -> None:
        """Stop every live status display so raw output is not garbled."""
        for status in reversed(self._spinner_stack):
            with suppress(Exception):  # pragma: no cover - defensive
                status.stop()

    def _resume_spinner(self) -> None:
        """Restart the status displays paused by :meth:`_pause_spinner`."""
        for status in self._spinner_stack:
            with suppress(Exception):  # pragma: no cover - defensive
                status.start()

    @contextmanager
    def _spinner_guard(self) -> Iterator[None]:
        """Hide live spinners around a write, then restore them.

        Without this, a Rich live display and a plain ``click.echo`` line
        written at the same time interleave into unreadable output
        (``⠋ Waiting...Warning: ...``).
        """
        if not self._spinner_stack:
            yield
            return
        self._pause_spinner()
        try:
            yield
        finally:
            self._resume_spinner()

    def _write_stdout(self, message: str, *, color: str | None = None) -> None:
        """Write one result line to stdout, pausing any live spinner first."""
        self._write(message, err=False, color=color)

    def _write_stderr(self, message: str, *, color: str | None = None) -> None:
        """Write one status/diagnostic line to stderr, pausing any spinner."""
        self._write(message, err=True, color=color)

    def _write(self, message: str, *, err: bool, color: str | None) -> None:
        """Low-level writer shared by every channel helper."""
        text = message if (self.no_color or color is None) else click.style(message, fg=color)
        with self._spinner_guard():
            click.echo(text, err=err)

    def _json(self, data: Any, *, err: bool = False) -> None:
        """Emit a single JSON value to stdout (``err=True`` → stderr)."""
        try:
            import orjson

            text = orjson.dumps(data, option=orjson.OPT_INDENT_2).decode()
        except ImportError:
            text = json_module.dumps(data, indent=2, default=str)
        with self._spinner_guard():
            click.echo(text, err=err)


# ---------------------------------------------------------------------------
# Context helper
# ---------------------------------------------------------------------------


def get_output(ctx: click.Context | None = None) -> OutputManager:
    """Retrieve the ``OutputManager`` from the Click context.

    The manager is stored in ``ctx.meta["ebx.output"]`` so that
    ``ctx.obj`` remains JSON-serializable.

    Falls back to a default instance when no context is available (e.g.
    during early startup / error handling).
    """
    if ctx is None:
        ctx = click.get_current_context(silent=True)

    if ctx is not None:
        mgr = ctx.meta.get("ebx.output")
        if isinstance(mgr, OutputManager):
            return mgr

    # Fallback — create a minimal default manager
    return OutputManager()


def enable_verbose(ctx: click.Context) -> None:
    """Turn on verbose mode from a subcommand-level ``-v/--verbose`` flag.

    Some users type ``ebx create -v`` instead of ``ebx -v create``.  Key
    subcommands therefore accept a local ``-v/--verbose`` flag and call this
    helper, which flips the shared :class:`OutputManager` (stored in
    ``ctx.meta``) to verbose and re-applies DEBUG-level logging.
    """
    out = get_output(ctx)
    out.set_verbose(True)
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj["verbose"] = True
