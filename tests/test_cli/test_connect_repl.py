"""Focused tests for the ``ebx connect`` REPL (task 185).

Two layers are covered:

* :mod:`easy_sandbox.cli.repl` — failure mapping (missing-command extraction
  from ``EnvdRpcError.envd_error``, timeouts, sanitised remote errors),
  spelling hints limited to session-verified commands, and the readline gate.
* the ``ebx connect`` command itself — one friendly notice per failure with no
  sandbox URL / MDN link / duplicate WARNING, every exit path (``exit``,
  ``quit``, Ctrl+D and Ctrl+C) and the "state does not persist" banner.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import easy_sandbox.utils.logging as log_module
from easy_sandbox.cli.main import cli
from easy_sandbox.cli.repl import (
    REPL_TIMEOUT,
    describe_command_failure,
    enable_line_editing,
    program_name,
    sanitize_text,
)
from easy_sandbox.models.errors import CommandTimeoutError, ConnectionError_, EnvdRpcError
from easy_sandbox.models.process import ProcessResult
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from click.testing import CliRunner, Result

_SANDBOX_ID = "sbx-cli-test-001"
_ENVD_MESSAGE = "envd rejected process.Process/Start with HTTP 500"
_STATUS_HINT = "Check the sandbox status with 'ebx info <SANDBOX_ID>' and retry."


@pytest.fixture(autouse=True)
def _pristine_logging() -> Iterator[None]:
    """Isolate global logging state (mirrors ``test_output_channels``).

    Without this, a handler left behind by an earlier suite could make the
    "rendered once" assertions flaky.
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


def _not_found(name: str) -> EnvdRpcError:
    """Structured envd 500 for an unknown executable (Go ``exec`` style body)."""
    return EnvdRpcError(
        _ENVD_MESSAGE,
        status_code=500,
        rpc_path="/process.Process/Start",
        envd_error={
            "error": {"code": 500, "message": f'exec: "{name}": executable file not found in $PATH'}
        },
    )


def _mock_sandbox(run: AsyncMock) -> MagicMock:
    sandbox = MagicMock()
    sandbox.id = _SANDBOX_ID
    sandbox.commands = MagicMock()
    sandbox.commands.run = run
    return sandbox


class _FakeStdin:
    """Stdin stub exposing only what :func:`enable_line_editing` inspects."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# ---------------------------------------------------------------------------
# Failure mapping
# ---------------------------------------------------------------------------


class TestDescribeCommandFailure:
    def test_missing_command_read_from_structured_envd_error(self) -> None:
        failure = describe_command_failure(
            _not_found("sl"), command="sl -la", known_commands={"ls", "cat"}
        )

        assert failure.message == "Command not found: sl"
        assert failure.code == "E3006"
        assert "Did you mean 'ls'?" in failure.suggestion

    def test_missing_command_falls_back_to_typed_program(self) -> None:
        # envd reports "exec not found" without naming the executable.
        exc = EnvdRpcError(
            _ENVD_MESSAGE,
            status_code=500,
            rpc_path="/process.Process/Start",
            envd_error={"error": {"message": "exec not found"}},
        )

        failure = describe_command_failure(exc, command="sl -la")

        assert failure.message == "Command not found: sl"
        assert "Did you mean" not in failure.suggestion

    @pytest.mark.parametrize(
        "detail",
        [
            "bash: sl: command not found",
            "bash: line 1: git: command not found",
            "sl: executable file not found",
            "not found: jq",
        ],
    )
    def test_command_name_shapes_are_recognised(self, detail: str) -> None:
        exc = EnvdRpcError(
            _ENVD_MESSAGE,
            status_code=500,
            rpc_path="/process.Process/Start",
            envd_error={"error": {"message": detail}},
        )

        failure = describe_command_failure(exc, command="whatever")

        expected = {
            "bash: sl: command not found": "sl",
            "bash: line 1: git: command not found": "git",
            "sl: executable file not found": "sl",
            "not found: jq": "jq",
        }[detail]
        assert failure.message == f"Command not found: {expected}"

    def test_cd_is_explained_as_a_shell_builtin(self) -> None:
        failure = describe_command_failure(_not_found("cd"), command="cd /app")

        assert failure.message == "Command not found: cd"
        assert "cd /path && <cmd>" in failure.suggestion

    def test_other_shell_builtin_gets_a_state_warning(self) -> None:
        failure = describe_command_failure(_not_found("export"), command="export FOO=1")

        assert "shell state" in failure.suggestion

    def test_spelling_hint_requires_a_close_session_command(self) -> None:
        failure = describe_command_failure(
            _not_found("figma"), command="figma", known_commands={"ls", "cat"}
        )

        assert "Did you mean" not in failure.suggestion
        assert "'figma'" in failure.suggestion

    def test_remote_4xx_detail_is_shown_with_status(self) -> None:
        exc = EnvdRpcError(
            _ENVD_MESSAGE,
            status_code=400,
            rpc_path="/process.Process/Start",
            envd_error={"error": {"message": "invalid argument: bad pid"}},
        )

        failure = describe_command_failure(exc, command="kill -9 1")

        assert failure.message == (
            "Sandbox envd rejected the command (HTTP 400): invalid argument: bad pid"
        )
        assert "https://" not in failure.message

    def test_remote_5xx_detail_is_clipped_and_sanitised(self) -> None:
        blob = (
            "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500"
            + " upstream exploded" * 40
        )
        exc = EnvdRpcError(
            _ENVD_MESSAGE,
            status_code=502,
            rpc_path="/process.Process/Start",
            body_text=blob,
        )

        failure = describe_command_failure(exc, command="ls")

        assert "(HTTP 502)" in failure.message
        assert "mozilla.org" not in failure.message
        assert "https://" not in failure.message
        assert failure.message.endswith("...")

    def test_envd_error_without_status_has_no_http_fragment(self) -> None:
        exc = EnvdRpcError(
            "envd rejected the request",
            envd_error={"error": {"message": "stream closed"}},
        )

        failure = describe_command_failure(exc, command="ls")

        assert failure.message == "Sandbox envd rejected the command: stream closed"

    @pytest.mark.parametrize(
        "exc",
        [CommandTimeoutError("boom"), httpx.ReadTimeout("slow")],
        ids=["sdk-timeout", "httpx-timeout"],
    )
    def test_timeouts_map_to_one_short_message(self, exc: BaseException) -> None:
        failure = describe_command_failure(exc, command="sleep 60")

        assert failure.message == f"Command timed out after {REPL_TIMEOUT}s."
        assert failure.code == "E3001"
        assert "ebx exec" in failure.suggestion

    def test_sandbox_error_url_is_scrubbed(self) -> None:
        exc = ConnectionError_(
            "connection to https://sbx-1.cn-hangzhou.e2b.fc.aliyuncs.com refused"
        )

        failure = describe_command_failure(exc, command="ls")

        assert "https://" not in failure.message
        assert "https://" not in failure.suggestion
        assert failure.code == "E5001"

    def test_http_status_error_suggests_status_check(self) -> None:
        request = httpx.Request("POST", "https://sbx-1.e2b.fc.aliyuncs.com/process.Process/Start")
        response = httpx.Response(503, request=request)
        exc = httpx.HTTPStatusError("Server error", request=request, response=response)

        failure = describe_command_failure(exc, command="ls")

        assert failure.message == "Remote request failed (HTTP 503)."
        assert failure.suggestion == _STATUS_HINT

    def test_protocol_error_mentions_interruption(self) -> None:
        failure = describe_command_failure(
            httpx.RemoteProtocolError("peer closed connection"), command="ls"
        )

        assert "interrupted" in failure.message
        assert failure.code == "E5003"

    def test_unknown_exception_falls_back_to_debug_hint(self) -> None:
        failure = describe_command_failure(ValueError("boom"), command="ls")

        assert failure.message == "Unexpected error while running this line: boom"
        assert "-v connect" in failure.suggestion
        assert failure.code == ""


class TestReplHelpers:
    def test_program_name_handles_quotes_and_fallbacks(self) -> None:
        assert program_name('"/usr/bin/ls" -la') == "/usr/bin/ls"
        assert program_name("echo hello") == "echo"
        assert program_name("") == ""
        # Unbalanced quotes fall back to a plain split instead of raising.
        assert program_name('echo "unclosed') == "echo"

    def test_sanitize_text_removes_urls_and_mdn_links(self) -> None:
        text = (
            "Client error '500' for url 'https://sbx-1.example/envd' "
            "For more information check: "
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500"
        )

        assert sanitize_text(text) == "Client error '500' for url"

    def test_sanitize_text_collapses_whitespace(self) -> None:
        assert sanitize_text("a\n   b\t c") == "a b c"

    def test_sanitize_text_keeps_plain_prose(self) -> None:
        # Only the httpx "check: https://…" clause is dropped, not general text.
        text = "For more information check the logs"

        assert sanitize_text(text) == text


class TestEnableLineEditing:
    def test_no_tty_keeps_plain_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", _FakeStdin(False))

        assert enable_line_editing() is False

    def test_missing_stdin_degrades_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", None)

        assert enable_line_editing() is False

    def test_interactive_tty_enables_readline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("readline")
        monkeypatch.setattr("sys.stdin", _FakeStdin(True))

        assert enable_line_editing() is True


# ---------------------------------------------------------------------------
# `ebx connect` session
# ---------------------------------------------------------------------------


class TestConnectSession:
    """End-to-end session behaviour through ``CliRunner`` (non-TTY stdin)."""

    @staticmethod
    def _invoke(runner: CliRunner, inputs: Any, run: AsyncMock) -> Result:
        sandbox = _mock_sandbox(run)
        with (
            patch(
                "easy_sandbox.api.sandbox.Sandbox.connect",
                new_callable=AsyncMock,
                return_value=sandbox,
            ),
            patch("builtins.input", side_effect=inputs),
        ):
            return runner.invoke(cli, ["connect", _SANDBOX_ID])

    def test_session_banner_states_no_state_persists(self, runner: CliRunner) -> None:
        run = AsyncMock()

        result = self._invoke(runner, ["exit"], run)

        assert result.exit_code == 0
        assert "Connected to sandbox sbx-cli-test-001" in result.stdout
        assert "each line runs in an independent process" in result.stderr
        assert "do not persist" in result.stderr

    def test_missing_command_is_one_friendly_notice(self, runner: CliRunner) -> None:
        run = AsyncMock(side_effect=_not_found("sl"))

        result = self._invoke(runner, ["sl -la", "exit"], run)

        assert result.exit_code == 0
        assert "Command not found" not in result.stdout
        assert result.stderr.count("Command not found: sl") == 1
        assert result.stderr.count("[E3006]") == 1
        combined = result.stdout + result.stderr
        assert "WARNING" not in combined
        assert "https://" not in combined
        assert "developer.mozilla.org" not in combined

    def test_spelling_hint_uses_commands_that_ran_in_session(self, runner: CliRunner) -> None:
        ls_result = ProcessResult(stdout="app.py\n", stderr="", exit_code=0, execution_time=0.1)
        run = AsyncMock(side_effect=[ls_result, _not_found("sl")])

        result = self._invoke(runner, ["ls /app", "sl", "exit"], run)

        assert result.exit_code == 0
        assert "app.py" in result.stdout
        assert "Did you mean 'ls'? It ran earlier in this session." in result.stderr

    def test_remote_rejection_shows_status_without_url(self, runner: CliRunner) -> None:
        exc = EnvdRpcError(
            _ENVD_MESSAGE,
            status_code=503,
            rpc_path="/process.Process/Start",
            envd_error={"error": {"message": "sandbox is not running"}},
        )
        run = AsyncMock(side_effect=exc)

        result = self._invoke(runner, ["ls", "quit"], run)

        assert result.exit_code == 0
        assert (
            "Sandbox envd rejected the command (HTTP 503): sandbox is not running" in result.stderr
        )
        assert "https://" not in result.stdout + result.stderr

    def test_timeout_keeps_the_session_alive(self, runner: CliRunner) -> None:
        run = AsyncMock(side_effect=httpx.ReadTimeout("read timed out"))

        result = self._invoke(runner, ["sleep 60", "exit"], run)

        assert result.exit_code == 0
        assert f"Command timed out after {REPL_TIMEOUT}s." in result.stderr
        assert "Disconnected." in result.stderr

    def test_library_warning_renders_once_beside_the_error(self, runner: CliRunner) -> None:
        """A log record from the failing call must not duplicate the notice."""

        async def _failing(cmd: str, *, timeout: int) -> ProcessResult:
            get_logger("transport.http").warning("envd rejected Process/Start (HTTP 500)")
            raise _not_found("sl")

        run = AsyncMock(side_effect=_failing)

        result = self._invoke(runner, ["sl", "exit"], run)

        assert result.stderr.count("WARNING: envd rejected Process/Start (HTTP 500)") == 1
        assert result.stderr.count("Command not found: sl") == 1

    def test_quit_disconnects_without_running_anything(self, runner: CliRunner) -> None:
        run = AsyncMock()

        result = self._invoke(runner, ["quit"], run)

        assert result.exit_code == 0
        assert "Disconnected." in result.stderr
        run.assert_not_called()

    def test_blank_lines_are_ignored(self, runner: CliRunner) -> None:
        run = AsyncMock()

        result = self._invoke(runner, ["", "   ", "exit"], run)

        assert result.exit_code == 0
        run.assert_not_called()

    def test_ctrl_d_at_prompt_disconnects_cleanly(self, runner: CliRunner) -> None:
        run = AsyncMock()

        result = self._invoke(runner, EOFError(), run)

        assert result.exit_code == 0
        assert "Disconnected." in result.stderr
        run.assert_not_called()

    def test_ctrl_c_at_prompt_disconnects_cleanly(self, runner: CliRunner) -> None:
        run = AsyncMock()

        result = self._invoke(runner, KeyboardInterrupt(), run)

        assert result.exit_code == 0
        assert "Disconnected." in result.stderr
        run.assert_not_called()
