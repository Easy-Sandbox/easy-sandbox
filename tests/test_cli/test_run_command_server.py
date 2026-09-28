"""Tests for ``ebx run`` dispatching to Sandbox.custom (server call)."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import click.testing

from easy_sandbox.cli.main import cli
from easy_sandbox.models.errors import CommandNotFoundError
from easy_sandbox.models.process import CommandResult


@dataclass
class _FakeRegisteredCommand:
    """Minimal stand-in for ``_RegisteredCommand``."""

    name: str
    source: str = ""
    args: list[object] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_sandbox(*, run_command_result: object = "ok") -> MagicMock:
    """Return a MagicMock that quacks like a connected Sandbox.

    ``sandbox.custom(name, ...)`` is an AsyncMock returning a
    server-sourced :class:`CommandResult` whose ``value`` is
    *run_command_result* (mechanism B).
    """
    sb = MagicMock()
    sb.custom = AsyncMock(
        return_value=CommandResult(
            value=run_command_result,
            exit_code=0,
            source="server",
        )
    )
    return sb


def _fake_run_sync(coro: object) -> object:
    """Transparent run_sync replacement that resolves awaitables."""
    import asyncio
    import inspect

    if inspect.isawaitable(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    return coro  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunCommandServer:
    """``ebx run <id> <cmd> --key value`` dispatches via Sandbox.custom."""

    def test_run_command_success(self) -> None:
        """Happy path: custom() hits the server -> result printed."""
        runner = click.testing.CliRunner()
        mock_sb = _make_mock_sandbox(run_command_result=42)

        fake_registry: dict[str, _FakeRegisteredCommand] = {
            "mytool": _FakeRegisteredCommand(name="mytool"),
        }

        with (
            patch(
                "easy_sandbox.api.sandbox.Sandbox.connect",
                new_callable=AsyncMock,
                return_value=mock_sb,
            ),
            patch(
                "easy_sandbox.utils.async_bridge.run_sync",
                side_effect=_fake_run_sync,
            ),
            patch(
                "easy_sandbox.declarative.decorator.sandbox._registry",
                fake_registry,
            ),
        ):
            result = runner.invoke(
                cli,
                ["run", "sbx-123", "mytool", "--x", "1", "--y", "hi"],
            )

        assert result.exit_code == 0, f"exit_code={result.exit_code}\noutput:\n{result.output}"
        mock_sb.custom.assert_called_once_with("mytool", server_port=9000, x="1", y="hi")
        assert "42" in result.output

    def test_run_command_json_output(self) -> None:
        """With ``--json``, the result is printed as JSON data."""
        runner = click.testing.CliRunner()
        mock_sb = _make_mock_sandbox(run_command_result={"sum": 3})

        fake_registry: dict[str, _FakeRegisteredCommand] = {
            "mytool": _FakeRegisteredCommand(name="mytool"),
        }

        with (
            patch(
                "easy_sandbox.api.sandbox.Sandbox.connect",
                new_callable=AsyncMock,
                return_value=mock_sb,
            ),
            patch(
                "easy_sandbox.utils.async_bridge.run_sync",
                side_effect=_fake_run_sync,
            ),
            patch(
                "easy_sandbox.declarative.decorator.sandbox._registry",
                fake_registry,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--json", "run", "sbx-123", "mytool", "--x", "1"],
            )

        assert result.exit_code == 0, f"exit_code={result.exit_code}\noutput:\n{result.output}"
        assert "result" in result.output

    def test_run_command_runtime_error(self) -> None:
        """CommandNotFoundError from custom() surfaces in CLI output."""
        runner = click.testing.CliRunner()
        mock_sb = MagicMock()
        mock_sb.custom = AsyncMock(
            side_effect=CommandNotFoundError(
                "bad",
                checked=["template custom_commands", "sandbox server"],
                server_status="reachable but command not found (HTTP 404)",
            ),
        )

        fake_registry: dict[str, _FakeRegisteredCommand] = {
            "bad": _FakeRegisteredCommand(name="bad"),
        }

        with (
            patch(
                "easy_sandbox.api.sandbox.Sandbox.connect",
                new_callable=AsyncMock,
                return_value=mock_sb,
            ),
            patch(
                "easy_sandbox.utils.async_bridge.run_sync",
                side_effect=_fake_run_sync,
            ),
            patch(
                "easy_sandbox.declarative.decorator.sandbox._registry",
                fake_registry,
            ),
        ):
            result = runner.invoke(
                cli,
                ["run", "sbx-123", "bad"],
            )

        # CommandNotFoundError should surface (non-zero exit or error output)
        assert result.exit_code != 0 or "not found" in result.output
