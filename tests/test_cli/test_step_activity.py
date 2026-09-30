"""Build and push steps show their log under the phase header."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from easy_sandbox.cli.commands.template import _StepReporter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest import MonkeyPatch


class _Out:
    """Stand-in for :class:`OutputManager`."""

    def __init__(self, *, activity: bool) -> None:
        self.use_activity_line = activity
        self.progress_lines: list[str] = []
        self.info_lines: list[str] = []
        self.updates: list[str] = []
        self.closed = 0

    def progress(self, message: str) -> None:
        self.progress_lines.append(message)

    def info(self, message: str) -> None:
        self.info_lines.append(message)

    @contextmanager
    def activity(self, message: str) -> Iterator[Any]:
        out = self

        def update(summary: str = "") -> None:
            out.updates.append(summary)

        try:
            yield update
        finally:
            out.closed += 1


class TestStepReporter:
    def test_docker_lines_scroll_under_the_phase(self) -> None:
        out = _Out(activity=True)
        reporter = _StepReporter(out, verbose=False)
        try:
            reporter.phase("[3/3] Building Docker image locally: app:latest")
            reporter.log("  #1 [internal] load build definition")
            reporter.log("")
            reporter.log("#2 [1/4] FROM python:3.12-slim")
            reporter.log("#3 [2/4] RUN pip install easy-sandbox")
        finally:
            reporter.close()

        assert out.updates[0].splitlines() == ["#1 [internal] load build definition"]
        assert out.updates[-1].splitlines() == [
            "#1 [internal] load build definition",
            "#2 [1/4] FROM python:3.12-slim",
            "#3 [2/4] RUN pip install easy-sandbox",
        ]
        assert out.info_lines == []
        assert out.closed == 1

    def test_verbose_prints_every_line_and_skips_the_feed(self) -> None:
        out = _Out(activity=True)
        reporter = _StepReporter(out, verbose=True)
        try:
            reporter.phase("Building")
            reporter.log("Step 1/2 : FROM python")
        finally:
            reporter.close()

        assert out.progress_lines == ["Building"]
        assert out.info_lines == ["Step 1/2 : FROM python"]
        assert out.updates == []
        assert out.closed == 0

    def test_without_a_tty_one_progress_line_and_no_log_spam(self) -> None:
        out = _Out(activity=False)
        reporter = _StepReporter(out, verbose=False)
        try:
            reporter.phase("Pushing to ACR: example:latest")
            reporter.log("layer abc: Pushed")
            reporter.done("Image pushed to ACR: example:latest")
        finally:
            reporter.close()

        assert out.progress_lines == [
            "Pushing to ACR: example:latest",
            "Image pushed to ACR: example:latest",
        ]
        assert out.info_lines == []
        assert out.updates == []

    def test_silent_phase_keeps_refreshing(self, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr(
            "easy_sandbox.cli.commands.template._STEP_TICK_SECONDS",
            0.05,
        )
        out = _Out(activity=True)
        seen = threading.Event()
        original = out.activity

        @contextmanager
        def activity(message: str) -> Any:
            with original(message) as update:

                def watching(summary: str = "") -> None:
                    update(summary)
                    seen.set()

                yield watching

        out.activity = activity  # type: ignore[method-assign]
        reporter = _StepReporter(out, verbose=False)
        try:
            reporter.phase("Injecting SDK wheel")
            assert seen.wait(1.0)
        finally:
            reporter.close()

        assert out.updates
        assert out.closed == 1
