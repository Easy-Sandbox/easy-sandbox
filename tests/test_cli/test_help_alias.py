"""Task 191 — ``-h`` alias for every reachable command path.

The alias is configured exactly once, on the root group in
:mod:`easy_sandbox.cli.main`
(``context_settings={"help_option_names": ["-h", "--help"]}``).  Click
propagates ``help_option_names`` from the parent Context down the entire
command tree — including lazily loaded groups (``LazyGroup``) and nested
sub-groups (``sandbox files`` / ``sandbox process`` / ``sandbox system``) —
so no per-command wiring is required.

These tests lock the behaviour in:

* walking every reachable path (the root plus all subcommands, including
  lazily registered ones) and asserting ``-h`` / ``--help`` both exit 0 with
  identical output;
* asserting the target command's callback never runs on a help path, so no
  command side effects (filesystem, network) are triggered;
* guarding against a future command defining a ``-h`` parameter of its own —
  Click would then silently drop the alias for that command, so the guard
  makes the conflict explicit and deliberate;
* covering the ``ebx run`` passthrough command: before this task,
  ``ebx run <id> <cmd> -h`` failed with "Unexpected positional argument"
  (``-h`` was never a passthrough token there); it now shows help without
  dialling the sandbox, and the ``--key value`` extra-arg contract is
  unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest

from easy_sandbox.cli.main import cli

if TYPE_CHECKING:
    from click.testing import CliRunner


def _iter_commands(cmd: click.Command, path: tuple[str, ...] = ()) -> Any:
    """Yield ``(path, command)`` for every command reachable from *cmd*.

    Resolution goes through ``Group.get_command`` — the same entry point
    argument parsing uses — so lazily registered subcommands are loaded and
    included exactly as they are at runtime.
    """
    ctx = click.Context(cmd)
    for name in cmd.list_commands(ctx):
        sub = cmd.get_command(ctx, name)
        if sub is None:  # pragma: no cover — defensive (broken lazy import)
            continue
        subpath = (*path, name)
        yield subpath, sub
        if isinstance(sub, click.Group):
            yield from _iter_commands(sub, subpath)


#: Root plus every reachable command, keyed by its path.
_COMMANDS: dict[tuple[str, ...], click.Command] = {
    (): cli,
    **dict(_iter_commands(cli)),
}
_PATHS: list[tuple[str, ...]] = sorted(_COMMANDS)
_CASE_IDS = [" ".join(p) or "<root>" for p in _PATHS]


def _invoke_pair(runner: CliRunner, path: tuple[str, ...]) -> tuple[Any, Any]:
    """Invoke ``<path> -h`` and ``<path> --help`` and return both results."""
    short = runner.invoke(cli, [*path, "-h"])
    long = runner.invoke(cli, [*path, "--help"])
    return short, long


@pytest.mark.parametrize("path", _PATHS, ids=_CASE_IDS)
def test_dash_h_matches_double_dash_help(runner: CliRunner, path: tuple[str, ...]) -> None:
    """Both spellings exit 0 and print identical help for every command."""
    short, long = _invoke_pair(runner, path)

    assert short.exit_code == 0, (
        f"`ebx {' '.join(path)} -h` exited {short.exit_code}: {short.output!r}"
    )
    assert long.exit_code == 0, (
        f"`ebx {' '.join(path)} --help` exited {long.exit_code}: {long.output!r}"
    )
    assert short.output == long.output
    assert short.output.startswith("Usage:")


@pytest.mark.parametrize("path", _PATHS, ids=_CASE_IDS)
def test_help_never_runs_the_target_callback(runner: CliRunner, path: tuple[str, ...]) -> None:
    """Showing help must not execute the target command (no side effects).

    Ancestor group callbacks may run — that is Click's standard resolution
    flow and they are side-effect-free context initialisers.  The *target*
    command itself must never be invoked.
    """
    target = _COMMANDS[path]
    calls: list[tuple[str, ...]] = []
    original = target.callback

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(path)
        if original is not None:  # pragma: no cover — ebx commands all define one
            return original(*args, **kwargs)
        return None

    target.callback = spy
    try:
        short, long = _invoke_pair(runner, path)
    finally:
        target.callback = original

    assert short.exit_code == 0
    assert long.exit_code == 0
    assert calls == [], f"help executed the callback of `ebx {' '.join(path)}`"


def test_no_command_reserves_dash_h_for_itself() -> None:
    """Guard: a user-facing ``-h`` parameter would drop the alias.

    Click protects the user parameter (help keeps only ``--help`` for that
    command), which is safe but subtle — this test makes the conflict loud
    so the decision is explicit rather than silent.
    """
    offenders = []
    for path, cmd in sorted(_COMMANDS.items()):
        for param in cmd.params:
            names = (*param.opts, *param.secondary_opts)
            if "-h" in names:
                offenders.append(f"`ebx {' '.join(path) or '<root>'}` parameter {param.name!r}")
    assert not offenders, (
        "Commands reserving '-h' (the help alias would be dropped there): " + ", ".join(offenders)
    )


def test_every_lazy_subcommand_is_covered() -> None:
    """Every lazily registered top-level name resolves and is tested above."""
    lazy = getattr(cli, "_lazy_subcommands", {})
    top_level = {p[0] for p in _PATHS if len(p) == 1}
    assert set(lazy) <= top_level


class TestRunPassthroughCompatibility:
    """``ebx run`` keeps its extra-arg contract while gaining ``-h``.

    Before task 191, ``ebx run <id> <cmd> -h`` was rejected with "Unexpected
    positional argument" — ``-h`` was never forwarded to the remote command.
    It now shows help, and the sandbox is not dialled on the help path.
    """

    def test_dash_h_shows_help_without_connecting(self, runner: CliRunner) -> None:
        connect = AsyncMock()
        with patch("easy_sandbox.api.sandbox.Sandbox.connect", new=connect):
            result = runner.invoke(cli, ["run", "sbx-1", "build", "-h"])

        assert result.exit_code == 0
        assert result.output.startswith("Usage: cli run")
        connect.assert_not_called()

    def test_double_dash_help_also_skips_connect(self, runner: CliRunner) -> None:
        connect = AsyncMock()
        with patch("easy_sandbox.api.sandbox.Sandbox.connect", new=connect):
            result = runner.invoke(cli, ["run", "sbx-1", "build", "--help"])

        assert result.exit_code == 0
        assert result.output.startswith("Usage: cli run")
        connect.assert_not_called()

    def test_extra_args_still_forwarded(self, runner: CliRunner) -> None:
        """``--key value`` extra args keep working after the alias change."""
        from easy_sandbox.models.process import CommandResult

        mock_result = CommandResult(
            value="deployed",
            stdout="deployed\n",
            stderr="",
            exit_code=0,
            execution_time=1.0,
            source="template",
        )
        mock_sandbox = MagicMock()
        mock_sandbox.custom = AsyncMock(return_value=mock_result)

        with patch(
            "easy_sandbox.api.sandbox.Sandbox.connect",
            new=AsyncMock(return_value=mock_sandbox),
        ):
            result = runner.invoke(cli, ["run", "sbx-1", "deploy", "--target", "staging"])

        assert result.exit_code == 0
        assert "deployed" in result.output
        mock_sandbox.custom.assert_awaited_once()
        call = mock_sandbox.custom.call_args
        assert call.args[0] == "deploy"
        assert call.kwargs.get("target") == "staging"
