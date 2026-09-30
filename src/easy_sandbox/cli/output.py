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
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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
# Live activity line
# ---------------------------------------------------------------------------

_ACTIVITY_STRIP_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|[\x00-\x1f\x7f]")

#: Minimum seconds between two redraws of the activity line.
_ACTIVITY_MIN_INTERVAL = 0.1

#: How often a ticked activity block redraws so the elapsed time keeps moving
#: while the step is silent.
_ACTIVITY_TICK_SECONDS = 1.0


#: Environment variable overriding how many grey activity lines are shown.
_ACTIVITY_LINES_ENV = "EBX_ACTIVITY_LINES"

#: Grey activity lines shown under the header by default.
_ACTIVITY_LINES_DEFAULT = 4

#: Upper bound for :data:`_ACTIVITY_LINES_ENV` (keeps the block small).
_ACTIVITY_LINES_MAX = 10


def _activity_line_count() -> int:
    """How many activity lines to show: ``EBX_ACTIVITY_LINES`` (1-10), default 4."""
    raw = os.environ.get(_ACTIVITY_LINES_ENV, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return _ACTIVITY_LINES_DEFAULT
    return min(max(value, 1), _ACTIVITY_LINES_MAX)


def _activity_head(message: str, elapsed: int) -> str:
    """The header line: ``message... 12s``.

    Phase strings that already end in an ellipsis (``Checking Docker
    daemon...``) are not given a second one.
    """
    text = message.rstrip()
    if text.endswith("..."):
        return f"{text} {elapsed}s"
    return f"{text}... {elapsed}s"


def _activity_lines(summary: str, limit: int) -> list[str]:
    """Split *summary* into its last *limit* non-empty lines, controls removed.

    The agent side hands over a newline-separated feed (oldest first); each
    line is sanitised on its own so an escape sequence can never survive or
    span lines.
    """
    lines = [" ".join(_ACTIVITY_STRIP_RE.sub(" ", raw).split()) for raw in summary.splitlines()]
    return [line for line in lines if line][-limit:]


def _cell_len(text: str) -> int:
    try:
        from rich.cells import cell_len

        return int(cell_len(text))
    except ImportError:  # pragma: no cover - rich is a CLI dependency
        return len(text)


def _fit_cells(text: str, width: int) -> str:
    """Truncate *text* to at most *width* terminal cells (CJK-aware)."""
    if width <= 0:
        return ""
    if _cell_len(text) <= width:
        return text
    out: list[str] = []
    used = 0
    for char in text:
        size = _cell_len(char)
        if used + size > width - 1:
            break
        out.append(char)
        used += size
    return "".join(out) + "…"


class _TransientLine:
    """A self-erasing block on *stderr*: a header plus grey activity lines.

    Used for ``--verbose`` / ``--no-color`` sessions where Rich's live
    status is not (or cannot be) used.  Duck-types the two methods
    :meth:`OutputManager._spinner_guard` calls on a live status (``stop`` /
    ``start``), so every ordinary log, info or warning write first clears the
    block and redraws it afterwards — log lines never interleave with it.

    The block is redrawn in place: the cursor stays at the end of its last
    row (no trailing newline), and each redraw moves up over the rows drawn
    before (``ESC [ n A``), then clears to the end of the screen.
    """

    def __init__(self, *, color: bool) -> None:
        self._color = color
        self._head = ""
        self._details: list[str] = []
        self._active = False
        self._rows = 0  # rows currently on screen

    def _width(self) -> int:
        return max(shutil.get_terminal_size(fallback=(80, 24)).columns - 1, 10)

    def _rewind(self) -> None:
        if self._rows > 1:
            sys.stderr.write(f"\x1b[{self._rows - 1}A")
        sys.stderr.write("\r")

    def _draw(self) -> None:
        width = self._width()
        previous = self._rows
        self._rewind()
        rows = [(self._head, False), *[(d, True) for d in self._details]]
        out: list[str] = []
        for text, grey in rows:
            fitted = _fit_cells(text, width)
            padded = fitted + " " * max(width - _cell_len(fitted), 0)
            out.append(click.style(padded, fg="bright_black") if grey and self._color else padded)
        sys.stderr.write("\n".join(out))
        if previous > len(rows):
            sys.stderr.write("\x1b[J")  # leftover rows from a taller block
        sys.stderr.flush()
        self._rows = len(rows)

    def _erase(self) -> None:
        if self._rows:
            self._rewind()
            sys.stderr.write("\x1b[J")
            sys.stderr.flush()
            self._rows = 0

    def start(self) -> None:
        self._active = True
        if self._head:
            self._draw()

    def stop(self) -> None:
        self._active = False
        self._erase()

    def update(self, head: str, details: list[str]) -> None:
        self._head = head
        self._details = details
        if self._active:
            self._draw()


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
        """Context manager for a long step that has no line-by-line log.

        On an interactive terminal this is the activity header
        (``message... 12s``), redrawn once a second so the elapsed time does
        not freeze. Grey detail lines stay empty until a caller uses
        :meth:`activity` and feeds them. Quiet, JSON, CI, and non-TTY
        sessions stay silent — callers that need a machine-readable line
        already emit :meth:`progress` themselves.

        If the wrapped block raises, the display stops and the exception
        propagates untouched.
        """
        if self.use_activity_line:
            with self.activity(message, tick=True):
                yield
            return
        yield

    @contextmanager
    def live_spinner(self, message: str) -> Iterator[Any]:
        """Like :meth:`spinner`, but yields ``update(text)`` for one detail line.

        On an interactive terminal *text* is the grey line under the
        ``message... 12s`` header. ``--verbose`` without a live display
        prints each change on stderr. Quiet, JSON, CI, and non-TTY yield a
        no-op.
        """
        if self.use_activity_line:
            with self.activity(message, tick=True) as update:
                yield update or (lambda _text: None)
            return
        if self.verbose and not self.quiet and not self.json_mode:
            yield lambda text: self._write_stderr(f"... {text}")
            return
        yield lambda _text: None

    @property
    def use_activity_line(self) -> bool:
        """Whether a live (grey) activity line can be drawn on *stderr*.

        Needs an interactive stderr, a real terminal type, and no
        ``--json`` / ``--quiet`` / CI mode.  Unlike :attr:`use_rich_spinner`
        it stays available under ``--verbose`` and ``--no-color``: there
        the line is a self-erasing ``\\r`` line that the log writers
        already pause around.
        """
        return not (
            self.quiet
            or self.json_mode
            or self.ci
            or os.environ.get("TERM", "").lower() == "dumb"
            or not (hasattr(sys.stderr, "isatty") and sys.stderr.isatty())
        )

    @contextmanager
    def activity(
        self, message: str, *, tick: bool = False
    ) -> Iterator[Callable[[str], None] | None]:
        """Show *message* with elapsed time and a rolling activity feed.

        Yields an ``update(summary)`` callable, or ``None`` when no live
        display can be drawn (non-TTY, ``--json``, ``--quiet``, CI, dumb
        terminal); callers then simply skip reporting.  *summary* is recent
        activity, **one line per entry, oldest first**: the display keeps
        the last ``EBX_ACTIVITY_LINES`` (default 4) of them in grey *below*
        the ``message... 12s`` header, so the block scrolls by line.  An
        update that arrives inside the throttle window is remembered and
        drawn on the next update that is allowed through — a later call is
        still required, so a throttled line never appears on its own.

        When *tick* is true a daemon redraws the same summary once a second
        so the elapsed time keeps moving during a silent step (create,
        upload, install, fetch). Agent runs leave it off; they already
        heartbeat. Everything is written to **stderr**, never stdout, and
        each line is stripped of control characters and rendered literally
        (never as Rich markup).

        * normal TTY — a Rich status whose text is refreshed in place;
        * ``--verbose`` / ``--no-color`` on a TTY — a transient block
          redrawn in place and cleared around every log write.
        """
        if not self.use_activity_line:
            yield None
            return
        started = time.monotonic()
        last = [0.0]
        pending = [""]
        shown = _activity_line_count()
        lock = threading.Lock()

        def make_updater(render: Callable[[str, list[str]], None]) -> Callable[[str], None]:
            def update(summary: str = "") -> None:
                with lock:
                    pending[0] = summary
                    now = time.monotonic()
                    # ``last[0] == 0`` is the first draw; it always paints.
                    if last[0] and now - last[0] < _ACTIVITY_MIN_INTERVAL:
                        return
                    last[0] = now
                    text = pending[0]
                render(_activity_head(message, int(now - started)), _activity_lines(text, shown))

            return update

        def _arm(redraw: Callable[[], None]) -> tuple[threading.Event, threading.Thread] | None:
            if not tick:
                return None
            stop = threading.Event()

            def _run() -> None:
                while not stop.wait(_ACTIVITY_TICK_SECONDS):
                    with suppress(Exception):
                        redraw()

            thread = threading.Thread(target=_run, name="ebx-activity-tick", daemon=True)
            thread.start()
            return stop, thread

        def _disarm(armed: tuple[threading.Event, threading.Thread] | None) -> None:
            if armed is None:
                return
            stop, thread = armed
            stop.set()
            thread.join(timeout=1.0)

        if self.use_rich_spinner:
            try:
                from rich.console import Console
                from rich.text import Text
            except ImportError:
                yield None
                return

            console = Console(stderr=True)

            def styled(head: str, details: list[str]) -> Any:
                # Rich would wrap an over-long row inside the spinner table
                # (growing the block); cut each row to the room left after
                # the spinner glyph instead.
                room = max(console.width - 3, 10)
                parts: list[tuple[str, str]] = [(_fit_cells(head, room), "bold blue")]
                for detail in details:
                    parts.extend([("\n", ""), (_fit_cells(detail, room), "grey50")])
                return Text.assemble(*parts, no_wrap=True, overflow="ellipsis")

            with console.status(styled(_activity_head(message, 0), []), spinner="dots") as status:
                self._spinner_stack.append(status)
                updater = make_updater(lambda head, det: status.update(styled(head, det)))

                def _redraw() -> None:
                    with lock:
                        text = pending[0]
                        now = time.monotonic()
                        if last[0] and now - last[0] < _ACTIVITY_MIN_INTERVAL:
                            return
                        last[0] = now
                    render_head = _activity_head(message, int(now - started))
                    status.update(styled(render_head, _activity_lines(text, shown)))

                armed = _arm(_redraw)
                try:
                    yield updater
                finally:
                    _disarm(armed)
                    self._spinner_stack.pop()
            return

        line = _TransientLine(color=not self.no_color)
        self._spinner_stack.append(line)
        line.update(_activity_head(message, 0), [])
        line.start()
        updater = make_updater(line.update)

        def _redraw_plain() -> None:
            with lock:
                text = pending[0]
                now = time.monotonic()
                if last[0] and now - last[0] < _ACTIVITY_MIN_INTERVAL:
                    return
                last[0] = now
            line.update(_activity_head(message, int(now - started)), _activity_lines(text, shown))

        armed = _arm(_redraw_plain)
        try:
            yield updater
        finally:
            _disarm(armed)
            with suppress(ValueError):
                self._spinner_stack.remove(line)
            line.stop()

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
