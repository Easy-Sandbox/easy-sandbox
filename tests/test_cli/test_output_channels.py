"""Channel-separation tests for the CLI output manager (task 167).

The contract under test:

* **stdout** carries only what a user or a script consumes as the result
  (``data`` / ``table`` / ``success``),
* **stderr** carries progress state, diagnostics and every stdlib ``logging``
  record,
* a library warning is rendered exactly once (no duplicate handler), and
* output written while a Rich spinner is live pauses/restores that spinner
  instead of interleaving with it.

Everything here runs through ``CliRunner`` so ``result.stdout`` /
``result.stderr`` are inspected separately — ``result.output`` is the mixed
stream and would hide exactly the pollution these tests guard against.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import click
import pytest

import easy_sandbox.utils.logging as log_module
from easy_sandbox.cli.main import cli
from easy_sandbox.cli.output import OutputManager, get_output
from easy_sandbox.models.sandbox import SandboxInfo
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pristine_logging() -> Iterator[None]:
    """Give every test a pristine global logging state.

    ``OutputManager`` and ``easy_sandbox.utils.logging`` both mutate global
    logger state (handlers, levels); without this isolation a leftover handler
    from a previous test would make the "rendered once" assertions flaky and
    would leak the CLI bridge into unrelated suites.
    """
    root_logger = logging.getLogger()
    package_logger = logging.getLogger("easy_sandbox")
    saved_root_handlers = list(root_logger.handlers)
    saved_package_handlers = list(package_logger.handlers)
    saved_package_level = package_logger.level
    saved_configured = log_module._CONFIGURED

    log_module._CONFIGURED = False
    root_logger.handlers.clear()
    package_logger.handlers.clear()
    package_logger.setLevel(logging.NOTSET)
    try:
        yield
    finally:
        root_logger.handlers.clear()
        package_logger.handlers.clear()
        package_logger.setLevel(saved_package_level)
        package_logger.handlers.extend(saved_package_handlers)
        root_logger.handlers.extend(saved_root_handlers)
        log_module._CONFIGURED = saved_configured


def _make_ctx_cmd(body: Callable[[OutputManager], None]) -> click.Command:
    """Build a click command that runs *body* with a context-bound manager.

    The manager is stored in ``ctx.meta["ebx.output"]`` exactly like the real
    CLI root group does, so ``get_output(ctx)`` returns it.
    """

    @click.command("emit")
    @click.option("--quiet", is_flag=True)
    @click.option("--json", "json_flag", is_flag=True)
    @click.option("--verbose", "verbose_flag", is_flag=True)
    @click.pass_context
    def cmd(ctx: click.Context, quiet: bool, json_flag: bool, verbose_flag: bool) -> None:
        ctx.meta["ebx.output"] = OutputManager(
            quiet=quiet,
            json_mode=json_flag,
            verbose=verbose_flag,
            no_color=True,
        )
        body(get_output(ctx))

    return cmd


class _FakeStatus:
    """Minimal stand-in for a Rich ``Status`` object."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def stop(self) -> None:
        self._events.append("stop")

    def start(self) -> None:
        self._events.append("start")


def _mock_sandbox(sandbox_id: str = "sbx-chan-001", template: str = "base") -> MagicMock:
    """Build a mock Sandbox object (mirrors ``test_create_nl._make_sandbox``)."""
    info = SandboxInfo.model_validate(
        {
            "sandboxID": sandbox_id,
            "templateID": template,
            "status": "running",
            "region": "cn-hangzhou",
            "timeout": 300,
            "envdUrl": f"https://{sandbox_id}.cn-hangzhou.e2b.fc.aliyuncs.com",
            "envdAccessToken": "tok",
        }
    )
    mock_sb = MagicMock()
    mock_sb.id = info.sandbox_id
    mock_sb.status = info.status
    mock_sb.url = info.envd_url
    mock_sb.info = info
    mock_sb.files = MagicMock()
    return mock_sb


def _run_coro(coro: Any) -> Any:
    """Side effect for patched ``run_sync`` that really awaits the coroutine."""
    import asyncio

    return asyncio.run(coro)


def _invoke_create(
    runner: CliRunner,
    args: list[str],
    *,
    template: str = "base",
) -> Any:
    """Invoke ``ebx create`` with a mocked SDK that logs a fallback warning.

    The warning emulates ``api.capability``'s capability-resolver fallback —
    the record that used to be printed twice and used to leak into stdout in
    ``--json`` mode.
    """
    mock_sb = _mock_sandbox(template=template)

    async def _create(*_args: Any, **_kwargs: Any) -> Any:
        get_logger("api.capability").warning(
            "Could not resolve capabilities for template %r; falling back to DEFAULT_CAPABILITIES",
            template,
        )
        return mock_sb

    with (
        patch("easy_sandbox.api.sandbox.Sandbox.create", MagicMock(side_effect=_create)),
        patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
    ):
        return runner.invoke(cli, args)


# ---------------------------------------------------------------------------
# OutputManager channel policy
# ---------------------------------------------------------------------------


class TestOutputChannels:
    """Results on stdout, status + diagnostics on stderr."""

    def test_result_helpers_write_to_stdout(self, runner: CliRunner) -> None:
        def body(out: OutputManager) -> None:
            out.data({"ID": "sbx-1"})
            out.success("done")

        result = runner.invoke(_make_ctx_cmd(body), [])

        assert result.exit_code == 0
        assert result.stdout.splitlines() == ["ID  sbx-1", "done"]
        assert result.stderr == ""

    def test_diagnostic_helpers_write_to_stderr(self, runner: CliRunner) -> None:
        def body(out: OutputManager) -> None:
            out.info("starting")
            out.progress("step 1")
            out.warning("careful")
            out.error("boom", code="E1001", suggestion="retry")

        result = runner.invoke(_make_ctx_cmd(body), [])

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr.splitlines() == [
            "starting",
            "... step 1",
            "Warning: careful",
            "[E1001] boom",
            "  Suggestion: retry",
        ]

    def test_quiet_keeps_only_result_values(self, runner: CliRunner) -> None:
        def body(out: OutputManager) -> None:
            out.info("hidden")
            out.progress("hidden")
            out.warning("hidden")
            out.data({"ID": "sbx-1", "Status": "running"})

        result = runner.invoke(_make_ctx_cmd(body), ["--quiet"])

        assert result.stdout.splitlines() == ["sbx-1", "running"]
        assert result.stderr == ""

    def test_json_mode_keeps_stdout_a_single_document(self, runner: CliRunner) -> None:
        def body(out: OutputManager) -> None:
            out.info("starting")
            out.warning("careful")
            out.data({"ID": "sbx-1"})

        result = runner.invoke(_make_ctx_cmd(body), ["--json"])

        # The whole stdout stream must decode as one JSON document.
        assert json.loads(result.stdout) == {"ID": "sbx-1"}
        assert "starting" in result.stderr
        assert "careful" in result.stderr
        assert "starting" not in result.stdout

    def test_debug_requires_verbose_and_stays_on_stderr(self, runner: CliRunner) -> None:
        def body(out: OutputManager) -> None:
            out.debug("detail")

        silent = runner.invoke(_make_ctx_cmd(body), [])
        assert "detail" not in silent.stderr

        verbose = runner.invoke(_make_ctx_cmd(body), ["--verbose"])
        assert "DEBUG: detail" in verbose.stderr
        assert verbose.stdout == ""


# ---------------------------------------------------------------------------
# stdlib logging bridge
# ---------------------------------------------------------------------------


class TestLoggingBridge:
    """One handler, one line, always on stderr."""

    def test_manager_owns_a_single_root_handler(self, runner: CliRunner) -> None:
        def body(_out: OutputManager) -> None:
            pass

        runner.invoke(_make_ctx_cmd(body), [])

        assert len(logging.getLogger().handlers) == 1
        assert logging.getLogger("easy_sandbox").handlers == []

    def test_library_warning_is_rendered_once_on_stderr(self, runner: CliRunner) -> None:
        def body(_out: OutputManager) -> None:
            get_logger("api.capability").warning("fallback %s", "base")

        result = runner.invoke(_make_ctx_cmd(body), [])

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr.splitlines() == ["WARNING: fallback base"]

    def test_sdk_configured_before_manager_still_renders_once(self, runner: CliRunner) -> None:
        # A module-scope ``get_logger`` installs the SDK's standalone handler;
        # the manager must take that handler over instead of stacking on it.
        get_logger("api.capability")

        def body(_out: OutputManager) -> None:
            get_logger("api.capability").warning("fallback")

        result = runner.invoke(_make_ctx_cmd(body), [])

        assert result.stderr.splitlines() == ["WARNING: fallback"]

    def test_quiet_suppresses_library_warnings(self, runner: CliRunner) -> None:
        def body(_out: OutputManager) -> None:
            get_logger("api.capability").warning("fallback")

        result = runner.invoke(_make_ctx_cmd(body), ["--quiet"])

        assert result.stdout == ""
        assert result.stderr == ""


# ---------------------------------------------------------------------------
# Spinner guard
# ---------------------------------------------------------------------------


class TestSpinnerGuard:
    """Writes pause a live spinner and resume it afterwards."""

    def test_writes_pause_and_resume_the_live_spinner(self, runner: CliRunner) -> None:
        events: list[str] = []

        def body(out: OutputManager) -> None:
            # White-box: a live Rich status would be registered by
            # ``OutputManager.spinner``; a fake keeps the test TTY-independent.
            out._spinner_stack.append(_FakeStatus(events))
            out.warning("careful")
            out.data({"ID": "sbx-1"})
            events.append("end")

        result = runner.invoke(_make_ctx_cmd(body), [])

        assert events == ["stop", "start", "stop", "start", "end"]
        assert "careful" in result.stderr
        assert "sbx-1" in result.stdout

    def test_no_spinner_means_no_lifecycle_calls(self, runner: CliRunner) -> None:
        def body(out: OutputManager) -> None:
            out.warning("careful")

        result = runner.invoke(_make_ctx_cmd(body), [])

        assert result.stderr.splitlines() == ["Warning: careful"]


# ---------------------------------------------------------------------------
# `ebx create` end-to-end
# ---------------------------------------------------------------------------


class TestCreateChannelSeparation:
    """``ebx create`` never mixes diagnostics into the result stream."""

    def test_plain_mode_splits_result_and_warning(self, runner: CliRunner) -> None:
        result = _invoke_create(runner, ["create", "--template", "base"])

        assert result.exit_code == 0, result.output
        assert "sbx-chan-001" in result.stdout
        assert "created successfully" in result.stdout
        assert "falling back to DEFAULT_CAPABILITIES" not in result.stdout
        # Exactly one rendered warning line — the duplicate-handler regression.
        assert (
            result.stderr.splitlines().count(
                "WARNING: Could not resolve capabilities for template 'base'; "
                "falling back to DEFAULT_CAPABILITIES"
            )
            == 1
        )
        assert "sbx-chan-001" not in result.stderr

    def test_json_mode_stdout_is_a_single_document(self, runner: CliRunner) -> None:
        result = _invoke_create(runner, ["--json", "create", "--template", "base"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["ID"] == "sbx-chan-001"
        assert payload["Status"] == "running"
        assert "falling back" in result.stderr

    def test_quiet_mode_prints_values_only(self, runner: CliRunner) -> None:
        result = _invoke_create(runner, ["--quiet", "create", "--template", "base"])

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            "sbx-chan-001",
            "running",
            "base",
            "https://sbx-chan-001.cn-hangzhou.e2b.fc.aliyuncs.com",
        ]
        assert result.stderr == ""

    def test_ci_mode_is_json_and_silent(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CI", "1")

        result = _invoke_create(runner, ["create", "--template", "base"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["ID"] == "sbx-chan-001"
        assert result.stderr == ""

    def test_description_template_conflict_reports_on_stderr_only(self, runner: CliRunner) -> None:
        """Task 160 invariant: rejected before any AI or network call."""
        gen_mock = MagicMock()
        create_mock = MagicMock()

        with (
            patch("easy_sandbox.agent.codegen.generate_template_files", gen_mock),
            patch("easy_sandbox.api.sandbox.Sandbox.create", create_mock),
        ):
            result = runner.invoke(cli, ["create", "python", "--template", "base"])

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "cannot be combined" in result.stderr
        gen_mock.assert_not_called()
        create_mock.assert_not_called()


# ---------------------------------------------------------------------------
# deploy diagnostics
# ---------------------------------------------------------------------------


class TestDeployDiagnosticsChannel:
    """``_do_deploy`` warnings follow the same channel rules."""

    @staticmethod
    def _deploy_cmd(tmp_path: Path) -> click.Command:
        from easy_sandbox.cli.commands.template import _do_deploy

        @click.command("deploy")
        @click.option("--quiet", is_flag=True)
        @click.option("--json", "json_flag", is_flag=True)
        @click.pass_context
        def cmd(ctx: click.Context, quiet: bool, json_flag: bool) -> None:
            ctx.meta["ebx.output"] = OutputManager(quiet=quiet, json_mode=json_flag, no_color=True)
            out = get_output(ctx)
            data = _do_deploy(
                str(tmp_path),
                acr_namespace="test-ns",
                start_cmd="echo hi",
                ctx=ctx,
                verbose=False,
            )
            out.data(data)

        return cmd

    @pytest.fixture
    def _patch_pipeline(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        config = MagicMock()
        config.access_key_id = "ak"
        config.access_key_secret = "sk"
        config.region = "cn-hangzhou"
        monkeypatch.setattr(
            "easy_sandbox.transport.config.load_config",
            MagicMock(return_value=config),
        )
        monkeypatch.setattr(
            "easy_sandbox.cli.commands.template._build_image",
            MagicMock(return_value="img:latest"),
        )
        monkeypatch.setattr(
            "easy_sandbox.cli.commands.template._push_image",
            MagicMock(return_value=("acr/img:latest", {})),
        )
        monkeypatch.setattr(
            "easy_sandbox.api.fc_template.create_official_template",
            MagicMock(return_value={"templateID": "tmpl-1"}),
        )
        monkeypatch.setattr(
            "easy_sandbox.api.fc_template.wait_for_template_ready",
            MagicMock(return_value={"status": {"state": "ready"}}),
        )

    def test_start_cmd_warning_is_one_stderr_line(
        self, runner: CliRunner, tmp_path: Path, _patch_pipeline: None
    ) -> None:
        result = runner.invoke(self._deploy_cmd(tmp_path), [])

        assert result.exit_code == 0, result.output
        assert "TemplateID" in result.stdout
        assert (
            result.stderr.splitlines().count(
                "Warning: --start-cmd / --ready-cmd only take effect with --generation 2 (MicroVM)."
            )
            == 1
        )
        assert "only take effect" not in result.stdout

    def test_start_cmd_warning_suppressed_in_quiet_mode(
        self, runner: CliRunner, tmp_path: Path, _patch_pipeline: None
    ) -> None:
        result = runner.invoke(self._deploy_cmd(tmp_path), ["--quiet"])

        assert result.exit_code == 0, result.output
        assert "only take effect" not in result.stderr
        assert result.stderr == ""
