"""Tests for the live agent-activity line (``OutputManager.activity``)."""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

import pytest

from easy_sandbox.cli import output as output_mod
from easy_sandbox.cli.output import OutputManager

if TYPE_CHECKING:
    from collections.abc import Iterator


class _TTYBuffer(io.StringIO):
    """A ``stderr`` stand-in that claims to be an interactive terminal."""

    def isatty(self) -> bool:
        return True


class _FakeSys:
    """``sys`` shim: only ``stderr`` differs from the real module.

    pytest's output capture re-installs its own ``sys.stderr`` for the
    duration of each test, so the stream is injected at module-reference
    level instead of patching ``sys.stderr`` itself.
    """

    def __init__(self, stderr: io.StringIO) -> None:
        self.stderr = stderr

    def __getattr__(self, name: str) -> object:
        return getattr(sys, name)


@pytest.fixture
def tty_stderr(monkeypatch: pytest.MonkeyPatch) -> Iterator[_TTYBuffer]:
    buf = _TTYBuffer()
    monkeypatch.setattr(output_mod, "sys", _FakeSys(buf))
    monkeypatch.setenv("TERM", "xterm-256color")
    # Deterministic: never throttle away the updates under test.
    monkeypatch.setattr(output_mod, "_ACTIVITY_MIN_INTERVAL", 0.0)
    yield buf


class TestAvailability:
    def test_none_when_stderr_is_not_a_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(output_mod, "sys", _FakeSys(io.StringIO()))
        with OutputManager(verbose=True).activity("Working") as update:
            assert update is None

    @pytest.mark.parametrize("mode", [{"json_mode": True}, {"quiet": True}, {"ci": True}])
    def test_none_in_machine_or_silent_modes(
        self, tty_stderr: _TTYBuffer, mode: dict[str, bool]
    ) -> None:
        with OutputManager(**mode).activity("Working") as update:
            assert update is None
        assert tty_stderr.getvalue() == ""

    def test_none_on_a_dumb_terminal(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TERM", "dumb")
        with OutputManager(verbose=True).activity("Working") as update:
            assert update is None
        assert tty_stderr.getvalue() == ""

    def test_available_under_verbose_where_the_spinner_is_not(self, tty_stderr: _TTYBuffer) -> None:
        out = OutputManager(verbose=True)
        assert out.use_rich_spinner is False
        assert out.use_activity_line is True


ERASE = "\x1b[J"


class TestTransientLine:
    """``--verbose`` / ``--no-color``: a self-erasing block, redrawn in place."""

    def test_header_first_then_grey_lines_below(self, tty_stderr: _TTYBuffer) -> None:
        out = OutputManager(verbose=True)

        with out.activity("Assessing description") as update:
            assert update is not None
            update("checking docs\nwriting the Dockerfile")
            drawn = tty_stderr.getvalue()
            last_block = drawn[drawn.rindex("Assessing description") :]
            rows = [row.strip() for row in last_block.split("\n")]
            assert rows[0].startswith("Assessing description... 0s")
            assert rows[1] == "checking docs"
            assert rows[2] == "writing the Dockerfile"

        # After the block the whole block is cleared: move up, clear to end.
        assert tty_stderr.getvalue().endswith("\x1b[2A\r" + ERASE)

    def test_four_lines_are_shown_by_default_and_they_scroll(self, tty_stderr: _TTYBuffer) -> None:
        out = OutputManager(verbose=True)

        with out.activity("Working") as update:
            assert update is not None
            update("one\ntwo\nthree\nfour\nfive")
            first = tty_stderr.getvalue()
            assert "one" not in first
            assert all(x in first for x in ("two", "three", "four", "five"))
            update("one\ntwo\nthree\nfour\nfive\nsix")
            latest = tty_stderr.getvalue()[len(first) :]
            assert "two" not in latest  # scrolled out
            assert all(x in latest for x in ("three", "four", "five", "six"))
            assert latest.startswith("\x1b[4A\r")  # rewound over header + 4 rows

    def test_redraw_moves_up_over_the_previous_block(self, tty_stderr: _TTYBuffer) -> None:
        out = OutputManager(verbose=True)

        with out.activity("Working") as update:
            assert update is not None
            update("a\nb")
            before = len(tty_stderr.getvalue())
            update("b\nc")
            assert tty_stderr.getvalue()[before:].startswith("\x1b[2A\r")

    def test_line_count_is_configurable(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EBX_ACTIVITY_LINES", "3")
        with OutputManager(verbose=True).activity("Working") as update:
            assert update is not None
            update("a\nb\nc\nd")
            block = tty_stderr.getvalue()
            assert "a" not in block.split("Working... 0s")[-1].replace("Working", "")
            assert all(x in block for x in ("b", "c", "d"))

    @pytest.mark.parametrize(
        ("raw", "expected"), [("", 4), ("nope", 4), ("0", 1), ("5", 5), ("99", 10)]
    )
    def test_line_count_parsing(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
    ) -> None:
        monkeypatch.setenv("EBX_ACTIVITY_LINES", raw)
        assert output_mod._activity_line_count() == expected

    def test_log_lines_do_not_interleave_with_the_block(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Route ``click.echo`` into the same buffer so the relative order of
        # erase / log line / redraw is observable.
        monkeypatch.setattr(
            output_mod.click, "echo", lambda text="", err=False, **_: tty_stderr.write(f"{text}\n")
        )
        out = OutputManager(verbose=True)

        with out.activity("Working") as update:
            assert update is not None
            update("thinking")
            tty_stderr.truncate(0)
            tty_stderr.seek(0)
            out.info("a log line")
            written = tty_stderr.getvalue()

        before, _, after = written.partition("a log line")
        assert before.endswith(ERASE)  # block erased before the log write
        assert after.startswith("\n")  # the log line is a clean, whole line
        assert "Working" in after  # and the block redrawn right after it

    def test_control_characters_and_markup_are_rendered_literally(
        self, tty_stderr: _TTYBuffer
    ) -> None:
        out = OutputManager(verbose=True)

        with out.activity("Working") as update:
            assert update is not None
            update("a\x1b[31mred\x1b[0m\x07 [bold red]x[/bold red]\nnext")

        text = tty_stderr.getvalue()
        assert "\x1b[31m" not in text
        assert "\x07" not in text
        assert "[bold red]x[/bold red]" in text

    def test_updates_are_throttled(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(output_mod, "_ACTIVITY_MIN_INTERVAL", 3600.0)
        out = OutputManager(verbose=True)

        with out.activity("Working") as update:
            assert update is not None
            update("first")
            update("second")

        text = tty_stderr.getvalue()
        assert "first" in text
        assert "second" not in text

    def test_erased_even_when_the_block_raises(self, tty_stderr: _TTYBuffer) -> None:
        out = OutputManager(verbose=True)

        with pytest.raises(RuntimeError), out.activity("Working"):
            raise RuntimeError("boom")

        assert tty_stderr.getvalue().endswith(ERASE)
        assert out._spinner_stack == []

    def test_nothing_goes_to_stdout(
        self, tty_stderr: _TTYBuffer, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with OutputManager(verbose=True).activity("Working") as update:
            assert update is not None
            update("hello")

        assert capsys.readouterr().out == ""

    def test_spinner_is_an_elapsed_header(self, tty_stderr: _TTYBuffer) -> None:
        out = OutputManager(verbose=True)
        with out.spinner("Creating sandbox"):
            text = tty_stderr.getvalue()
        assert "Creating sandbox... 0s" in text

    def test_spinner_tick_advances_the_elapsed_time(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time

        monkeypatch.setattr(output_mod, "_ACTIVITY_TICK_SECONDS", 0.05)
        with OutputManager(verbose=True).spinner("Creating sandbox"):
            time.sleep(1.15)
        text = tty_stderr.getvalue()
        assert "Creating sandbox... 0s" in text
        assert "Creating sandbox... 1s" in text or "Creating sandbox... 2s" in text

    def test_quiet_spinner_writes_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        with OutputManager(quiet=True).spinner("Creating sandbox"):
            pass
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestRichStatus:
    """Normal colour TTY: a Rich status, refreshed in place."""

    def _out(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch, width: int = 100
    ) -> OutputManager:
        import rich.console

        real_console = rich.console.Console
        monkeypatch.setattr(output_mod, "is_tty", lambda: True)
        monkeypatch.setattr(
            rich.console,
            "Console",
            lambda **_: real_console(file=tty_stderr, force_terminal=True, width=width),
        )
        out = OutputManager()
        assert out.use_rich_spinner is True
        return out

    def test_status_shows_header_and_the_latest_lines(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = self._out(tty_stderr, monkeypatch)

        with out.activity("Researching public facts") as update:
            assert update is not None
            update("gone-first\nsecond\nthird\ntool: web_fetch\nwriting notes")
            assert out._spinner_stack  # registered so log writes can pause it

        text = tty_stderr.getvalue()
        assert "Researching public facts" in text
        assert "tool: web_fetch" in text and "writing notes" in text
        assert "gone-first" not in text  # scrolled out
        assert out._spinner_stack == []

    def test_lines_sit_below_the_header_not_beside_it(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import re

        out = self._out(tty_stderr, monkeypatch)
        with out.activity("Working") as update:
            assert update is not None
            update("alpha\nbeta")
        plain = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", tty_stderr.getvalue())
        rows = [r for r in plain.replace("\r", "\n").split("\n") if "alpha" in r or "Working" in r]
        header_rows = [r for r in rows if "Working" in r]
        assert header_rows and all("alpha" not in r for r in header_rows)

    def test_long_lines_are_cut_not_wrapped(
        self, tty_stderr: _TTYBuffer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = self._out(tty_stderr, monkeypatch, width=30)
        with out.activity("Working") as update:
            assert update is not None
            update("y" * 200 + "\n" + "z" * 200)
        shown = tty_stderr.getvalue().split("\x1b[?25h")[0]
        assert shown.strip().count("\n") == 2  # header + two rows, nothing wrapped
        assert shown.count("…") == 2


class TestHelpers:
    def test_fit_cells_is_cjk_aware(self) -> None:
        fitted = output_mod._fit_cells("你好世界你好世界", 7)
        assert fitted.endswith("…")
        assert output_mod._cell_len(fitted) <= 7

    def test_fit_cells_leaves_short_text_alone(self) -> None:
        assert output_mod._fit_cells("abc", 10) == "abc"
        assert output_mod._fit_cells("abc", 0) == ""

    def test_activity_head(self) -> None:
        assert output_mod._activity_head("Working", 3) == "Working... 3s"
        assert output_mod._activity_head("Checking Docker daemon...", 3) == (
            "Checking Docker daemon... 3s"
        )

    def test_activity_lines_keep_the_last_n_clean_lines(self) -> None:
        assert output_mod._activity_lines("", 2) == []
        assert output_mod._activity_lines("a\tb", 2) == ["a b"]
        assert output_mod._activity_lines("1\n\n2\n3", 2) == ["2", "3"]
        assert output_mod._activity_lines("x\x1b[31m\ny", 5) == ["x", "y"]
