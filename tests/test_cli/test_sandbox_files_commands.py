"""Tests for sandbox files CLI commands: list, stat, mkdir, rm, mv, search."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from easy_sandbox.cli.main import cli
from easy_sandbox.models.filesystem import FileInfo, FileType
from easy_sandbox.models.process import ProcessResult

if TYPE_CHECKING:
    from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sandbox() -> MagicMock:
    """Build a lightweight mock Sandbox for file-command tests."""
    sb = MagicMock()
    sb.id = "sbx-test-001"
    sb.capabilities = {"shell", "files", "code"}

    sb.files = MagicMock()
    sb.files.list = AsyncMock(return_value=[])
    sb.files.get_info = AsyncMock()
    sb.files.make_dir = AsyncMock()
    sb.files.remove = AsyncMock()
    sb.files.move = AsyncMock()

    sb.commands = MagicMock()
    sb.commands.run = AsyncMock()

    sb.kill = AsyncMock()
    return sb


def _patch_connect(sb: MagicMock):
    return patch(
        "easy_sandbox.api.sandbox.Sandbox.connect",
        new_callable=AsyncMock,
        return_value=sb,
    )


# ===================================================================
# sandbox files list
# ===================================================================


class TestFilesList:
    def test_list_non_recursive_happy(self, runner: CliRunner) -> None:
        """Non-recursive list returns two entries."""
        sb = _make_sandbox()
        sb.files.list = AsyncMock(
            return_value=[
                FileInfo(name="app.py", path="/home/user/app.py", type=FileType.FILE, size=1024),
                FileInfo(name="data", path="/home/user/data", type=FileType.DIRECTORY, size=0),
            ]
        )
        with _patch_connect(sb):
            result = runner.invoke(cli, ["sandbox", "files", "list", "sbx-test-001"])
        assert result.exit_code == 0
        assert "app.py" in result.output
        assert "data" in result.output

    def test_list_recursive(self, runner: CliRunner) -> None:
        """Recursive list uses 'find' via commands.run."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="/home/user\n/home/user/app.py\n/home/user/data\n",
                stderr="",
                exit_code=0,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "list", "sbx-test-001", "--recursive"],
            )
        assert result.exit_code == 0
        assert "/home/user/app.py" in result.output

    def test_list_empty_directory(self, runner: CliRunner) -> None:
        """Empty directory shows 'empty' message."""
        sb = _make_sandbox()
        sb.files.list = AsyncMock(return_value=[])
        with _patch_connect(sb):
            result = runner.invoke(cli, ["sandbox", "files", "list", "sbx-test-001"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_list_json(self, runner: CliRunner) -> None:
        """Non-recursive list with --json outputs a JSON array."""
        sb = _make_sandbox()
        sb.files.list = AsyncMock(
            return_value=[
                FileInfo(name="test.py", path="/home/user/test.py", type=FileType.FILE, size=512),
            ]
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "files", "list", "sbx-test-001"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["name"] == "test.py"

    def test_list_recursive_json(self, runner: CliRunner) -> None:
        """Recursive list with --json outputs entries key."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="/home/user/a.py\n/home/user/b.py\n",
                stderr="",
                exit_code=0,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "files", "list", "sbx-test-001", "-r"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "entries" in data
        assert len(data["entries"]) == 2

    def test_list_missing_sandbox_id(self, runner: CliRunner) -> None:
        """Missing SANDBOX_ID argument → exit 2."""
        result = runner.invoke(cli, ["sandbox", "files", "list"])
        assert result.exit_code == 2

    def test_list_api_error(self, runner: CliRunner) -> None:
        """Backend FileOperationError → exit 1 (general SDK error)."""
        from easy_sandbox.models.errors import FileOperationError

        sb = _make_sandbox()
        sb.files.list = AsyncMock(side_effect=FileOperationError("disk error"))
        with _patch_connect(sb):
            result = runner.invoke(cli, ["sandbox", "files", "list", "sbx-test-001"])
        assert result.exit_code == 1


# ===================================================================
# sandbox files stat
# ===================================================================


class TestFilesStat:
    def test_stat_happy(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.files.get_info = AsyncMock(
            return_value=FileInfo(
                name="app.py",
                path="/home/user/app.py",
                type=FileType.FILE,
                size=2048,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "stat", "sbx-test-001", "--path", "/home/user/app.py"],
            )
        assert result.exit_code == 0
        assert "app.py" in result.output
        assert "file" in result.output

    def test_stat_json(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.files.get_info = AsyncMock(
            return_value=FileInfo(
                name="data",
                path="/app/data",
                type=FileType.DIRECTORY,
                size=0,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["--json", "sandbox", "files", "stat", "sbx-test-001", "-p", "/app/data"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["Name"] == "data"
        assert data["Type"] == "directory"

    def test_stat_missing_path(self, runner: CliRunner) -> None:
        """--path is required → exit 2."""
        result = runner.invoke(cli, ["sandbox", "files", "stat", "sbx-test-001"])
        assert result.exit_code == 2

    def test_stat_not_found(self, runner: CliRunner) -> None:
        from easy_sandbox.models.errors import FileNotFoundError_

        sb = _make_sandbox()
        sb.files.get_info = AsyncMock(side_effect=FileNotFoundError_("not found"))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "stat", "sbx-test-001", "-p", "/no/such"],
            )
        assert result.exit_code == 4


# ===================================================================
# sandbox files mkdir
# ===================================================================


class TestFilesMkdir:
    def test_mkdir_happy(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "mkdir", "sbx-test-001", "-p", "/home/user/new_dir"],
            )
        assert result.exit_code == 0
        sb.files.make_dir.assert_called_once_with("/home/user/new_dir")

    def test_mkdir_missing_path(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["sandbox", "files", "mkdir", "sbx-test-001"])
        assert result.exit_code == 2

    def test_mkdir_already_exists(self, runner: CliRunner) -> None:
        from easy_sandbox.models.errors import FileOperationError

        sb = _make_sandbox()
        sb.files.make_dir = AsyncMock(side_effect=FileOperationError("already exists"))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "mkdir", "sbx-test-001", "-p", "/existing"],
            )
        assert result.exit_code == 1


# ===================================================================
# sandbox files rm
# ===================================================================


class TestFilesRm:
    def test_rm_yes_flag(self, runner: CliRunner) -> None:
        """--yes skips confirmation; remove is called."""
        sb = _make_sandbox()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "rm", "sbx-test-001", "-p", "/tmp/old.txt", "-y"],
            )
        assert result.exit_code == 0
        sb.files.remove.assert_called_once_with("/tmp/old.txt")

    def test_rm_abort(self, runner: CliRunner) -> None:
        """User answers 'n' to confirmation prompt → abort."""
        sb = _make_sandbox()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "rm", "sbx-test-001", "-p", "/tmp/old.txt"],
                input="n\n",
            )
        assert result.exit_code != 0
        sb.files.remove.assert_not_called()

    def test_rm_confirm_yes(self, runner: CliRunner) -> None:
        """User answers 'y' to confirmation prompt → proceed."""
        sb = _make_sandbox()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "rm", "sbx-test-001", "-p", "/tmp/old.txt"],
                input="y\n",
            )
        assert result.exit_code == 0
        sb.files.remove.assert_called_once_with("/tmp/old.txt")

    def test_rm_missing_path(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["sandbox", "files", "rm", "sbx-test-001"])
        assert result.exit_code == 2

    def test_rm_not_found(self, runner: CliRunner) -> None:
        from easy_sandbox.models.errors import FileNotFoundError_

        sb = _make_sandbox()
        sb.files.remove = AsyncMock(side_effect=FileNotFoundError_("not found"))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "rm", "sbx-test-001", "-p", "/gone", "-y"],
            )
        assert result.exit_code == 4


# ===================================================================
# sandbox files mv
# ===================================================================


class TestFilesMv:
    def test_mv_happy(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                [
                    "sandbox",
                    "files",
                    "mv",
                    "sbx-test-001",
                    "--source",
                    "/home/user/old.py",
                    "--dest",
                    "/home/user/new.py",
                ],
            )
        assert result.exit_code == 0
        sb.files.move.assert_called_once_with("/home/user/old.py", "/home/user/new.py")

    def test_mv_missing_source(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["sandbox", "files", "mv", "sbx-test-001", "--dest", "/home/user/new.py"],
        )
        assert result.exit_code == 2

    def test_mv_missing_dest(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["sandbox", "files", "mv", "sbx-test-001", "--source", "/home/user/old.py"],
        )
        assert result.exit_code == 2

    def test_mv_source_not_found(self, runner: CliRunner) -> None:
        from easy_sandbox.models.errors import FileNotFoundError_

        sb = _make_sandbox()
        sb.files.move = AsyncMock(side_effect=FileNotFoundError_("source not found"))
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                [
                    "sandbox",
                    "files",
                    "mv",
                    "sbx-test-001",
                    "-s",
                    "/no/such",
                    "-d",
                    "/home/user/dest",
                ],
            )
        assert result.exit_code == 4


# ===================================================================
# sandbox files search
# ===================================================================


class TestFilesSearch:
    def test_search_happy(self, runner: CliRunner) -> None:
        """Three hits displayed."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="/app/a.py\n/app/b.py\n/app/c.py\n",
                stderr="",
                exit_code=0,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                [
                    "sandbox",
                    "files",
                    "search",
                    "sbx-test-001",
                    "--path",
                    "/app",
                    "--pattern",
                    "*.py",
                ],
            )
        assert result.exit_code == 0
        assert "Found 3 file(s)" in result.output

    def test_search_no_match(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="",
                stderr="",
                exit_code=0,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                ["sandbox", "files", "search", "sbx-test-001", "-p", "/app", "--pattern", "*.rs"],
            )
        assert result.exit_code == 0
        assert "No files found" in result.output

    def test_search_json(self, runner: CliRunner) -> None:
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="/app/x.log\n",
                stderr="",
                exit_code=0,
            )
        )
        with _patch_connect(sb):
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "sandbox",
                    "files",
                    "search",
                    "sbx-test-001",
                    "-p",
                    "/app",
                    "--pattern",
                    "*.log",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "results" in data
        assert len(data["results"]) == 1

    def test_search_max_depth(self, runner: CliRunner) -> None:
        """--max-depth 3 is forwarded to find -maxdepth 3."""
        sb = _make_sandbox()
        sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="",
                stderr="",
                exit_code=0,
            )
        )
        with _patch_connect(sb):
            runner.invoke(
                cli,
                [
                    "sandbox",
                    "files",
                    "search",
                    "sbx-test-001",
                    "-p",
                    "/app",
                    "--pattern",
                    "*.py",
                    "--max-depth",
                    "3",
                ],
            )
        call_args = sb.commands.run.call_args
        assert "-maxdepth 3" in call_args[0][0]

    def test_search_missing_pattern(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["sandbox", "files", "search", "sbx-test-001", "--path", "/app"],
        )
        assert result.exit_code == 2

    def test_search_missing_path(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["sandbox", "files", "search", "sbx-test-001", "--pattern", "*.py"],
        )
        assert result.exit_code == 2
