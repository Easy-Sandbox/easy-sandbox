"""Tests for sandbox CLI commands: create, list, info, kill, exec, upload, download."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from serverless_sandbox.cli.main import cli
from serverless_sandbox.models.sandbox import SandboxInfo, SandboxStatus
from serverless_sandbox.models.process import ProcessResult


def _make_sandbox(
    sandbox_id: str = "sbx-cli-test-001",
    template: str = "python-base",
    status: str = "running",
) -> MagicMock:
    """Build a mock Sandbox object with an .info attribute."""
    sb_info = SandboxInfo.model_validate({
        "sandboxID": sandbox_id,
        "templateID": template,
        "status": status,
        "region": "cn-hangzhou",
        "timeout": 300,
        "envdUrl": f"https://{sandbox_id}.cn-hangzhou.e2b.fc.aliyuncs.com",
        "envdAccessToken": "tok",
    })
    mock_sb = MagicMock()
    mock_sb.id = sb_info.sandbox_id
    mock_sb.status = sb_info.status
    mock_sb.url = sb_info.envd_url
    mock_sb.info = sb_info
    mock_sb.kill = AsyncMock()
    mock_sb.commands = MagicMock()
    mock_sb.commands.run = AsyncMock()
    mock_sb.files = MagicMock()
    mock_sb.files.write = AsyncMock()
    mock_sb.files.read_bytes = AsyncMock(return_value=b"file-content")
    return mock_sb


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_create_basic(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.create", new_callable=AsyncMock
        ) as mock_create, patch(
            "serverless_sandbox.utils.async_bridge.run_sync", return_value=mock_sb
        ):
            result = runner.invoke(cli, ["create", "--template", "python-base"])

        assert result.exit_code == 0
        assert "sbx-cli-test-001" in result.output

    def test_create_json(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync", return_value=mock_sb
        ):
            result = runner.invoke(cli, ["--json", "create", "--template", "python-base"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ID"] == "sbx-cli-test-001"

    def test_create_with_envs(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync", return_value=mock_sb
        ):
            result = runner.invoke(
                cli, ["create", "-e", "FOO=bar", "-e", "BAZ=qux"]
            )

        assert result.exit_code == 0
        assert "sbx-cli-test-001" in result.output

    def test_create_invalid_env_format(self, runner: CliRunner) -> None:
        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync",
            side_effect=Exception("should not be called"),
        ):
            result = runner.invoke(cli, ["create", "-e", "INVALID"])

        assert result.exit_code == 2

    def test_create_with_metadata(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync", return_value=mock_sb
        ):
            result = runner.invoke(
                cli, ["create", "-m", "owner=test", "-m", "env=dev"]
            )

        assert result.exit_code == 0


class TestConnect:
    def test_connect_interactive_exit(self, runner: CliRunner) -> None:
        """Connect should start interactive session; 'exit' disconnects."""
        mock_sb = MagicMock()
        mock_sb.id = "sbx-cli-test-001"
        mock_sb.commands = MagicMock()

        async def fake_connect(sid):
            return mock_sb

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ), patch(
            "builtins.input",
            side_effect=["exit"],
        ):
            result = runner.invoke(cli, ["connect", "sbx-cli-test-001"])

        assert result.exit_code == 0
        assert "Connected" in result.output or "Disconnected" in result.output

    def test_connect_eof(self, runner: CliRunner) -> None:
        """Ctrl+D (EOF) should disconnect."""
        mock_sb = MagicMock()
        mock_sb.id = "sbx-cli-test-001"
        mock_sb.commands = MagicMock()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ), patch(
            "builtins.input",
            side_effect=EOFError,
        ):
            result = runner.invoke(cli, ["connect", "sbx-cli-test-001"])

        assert result.exit_code == 0
        assert "Disconnected" in result.output

    def test_connect_runs_command(self, runner: CliRunner) -> None:
        """Connect should execute commands and print output."""
        mock_result = MagicMock()
        mock_result.stdout = "hello world\n"
        mock_result.stderr = ""

        mock_sb = MagicMock()
        mock_sb.id = "sbx-cli-test-001"
        mock_sb.commands = MagicMock()
        mock_sb.commands.run = AsyncMock(return_value=mock_result)

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ), patch(
            "builtins.input",
            side_effect=["echo hello", "exit"],
        ):
            result = runner.invoke(cli, ["connect", "sbx-cli-test-001"])

        assert result.exit_code == 0
        assert "hello world" in result.output


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestList:
    def _patch_list_deps(self, mock_return):
        """Common patches for list command's lazy imports."""
        return [
            patch("serverless_sandbox.transport.config.load_config"),
            patch("serverless_sandbox.transport.auth.create_auth_provider"),
            patch("serverless_sandbox.transport.http.HttpClient"),
            patch("serverless_sandbox.protocol.sandbox.SandboxProtocol"),
            patch("serverless_sandbox.utils.async_bridge.run_sync", return_value=mock_return),
        ]

    def test_list_basic(self, runner: CliRunner) -> None:
        mock_sandboxes = [
            SandboxInfo.model_validate({
                "sandboxID": "sbx-1",
                "templateID": "base",
                "status": "running",
                "region": "cn-hangzhou",
                "timeout": 300,
            }),
        ]

        patches = self._patch_list_deps(mock_sandboxes)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        assert "sbx-1" in result.output

    def test_list_json(self, runner: CliRunner) -> None:
        mock_sandboxes = [
            SandboxInfo.model_validate({
                "sandboxID": "sbx-1",
                "templateID": "base",
                "status": "running",
                "region": "cn-hangzhou",
                "timeout": 300,
            }),
        ]

        patches = self._patch_list_deps(mock_sandboxes)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = runner.invoke(cli, ["--json", "list"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["ID"] == "sbx-1"

    def test_list_empty(self, runner: CliRunner) -> None:
        patches = self._patch_list_deps([])
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        assert "No sandboxes" in result.output


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

class TestInfo:
    def test_info_basic(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync", return_value=mock_sb
        ):
            result = runner.invoke(cli, ["info", "sbx-cli-test-001"])

        assert result.exit_code == 0
        assert "sbx-cli-test-001" in result.output
        assert "running" in result.output


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------

class TestKill:
    def test_kill_with_yes(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(cli, ["kill", "sbx-cli-test-001", "--yes"])

        assert result.exit_code == 0
        assert "killed" in result.output.lower()

    def test_kill_abort(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["kill", "sbx-cli-test-001"], input="n\n")
        assert result.exit_code != 0  # Aborted

    def test_kill_no_id_no_all(self, runner: CliRunner) -> None:
        """Should error when neither sandbox_id nor --all is given."""
        result = runner.invoke(cli, ["kill", "--yes"])
        assert result.exit_code == 2

    def test_kill_all_empty(self, runner: CliRunner) -> None:
        """--all with no running sandboxes."""
        with patch(
            "serverless_sandbox.transport.config.load_config",
        ), patch(
            "serverless_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "serverless_sandbox.transport.http.HttpClient",
        ), patch(
            "serverless_sandbox.protocol.sandbox.SandboxProtocol",
        ), patch(
            "serverless_sandbox.utils.async_bridge.run_sync",
            return_value=[],
        ):
            result = runner.invoke(cli, ["kill", "--all", "--yes"])

        assert result.exit_code == 0
        assert "No running" in result.output

    def test_kill_all_with_sandboxes(self, runner: CliRunner) -> None:
        """--all should kill listed sandboxes."""
        mock_sb = _make_sandbox()
        sb_info = SandboxInfo.model_validate({
            "sandboxID": "sbx-1",
            "templateID": "base",
            "status": "running",
            "region": "cn-hangzhou",
            "timeout": 300,
        })
        call_count = [0]

        def side_effect(coro):
            import asyncio as _aio
            call_count[0] += 1
            if call_count[0] == 1:
                return [sb_info]
            # _connect_and_kill: run the merged coroutine
            return _aio.run(coro)

        with patch(
            "serverless_sandbox.transport.config.load_config",
        ), patch(
            "serverless_sandbox.transport.auth.create_auth_provider",
        ), patch(
            "serverless_sandbox.transport.http.HttpClient",
        ), patch(
            "serverless_sandbox.protocol.sandbox.SandboxProtocol",
        ), patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ), patch(
            "serverless_sandbox.utils.async_bridge.run_sync",
            side_effect=side_effect,
        ):
            result = runner.invoke(cli, ["kill", "--all", "--yes"])

        assert result.exit_code == 0
        assert "Killed" in result.output


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------

class TestExec:
    def test_exec_basic(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()
        mock_result = ProcessResult(stdout="hello\n", stderr="", exit_code=0, execution_time=0.1)
        mock_sb.commands.run = AsyncMock(return_value=mock_result)

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(cli, ["exec", "sbx-cli-test-001", "echo hello"])

        assert result.exit_code == 0
        assert "hello" in result.output

    def test_exec_json(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()
        mock_result = ProcessResult(stdout="hi\n", stderr="", exit_code=0, execution_time=0.05)
        mock_sb.commands.run = AsyncMock(return_value=mock_result)

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(cli, ["--json", "exec", "sbx-cli-test-001", "echo hi"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stdout"] == "hi\n"
        assert data["exit_code"] == 0

    def test_exec_nonzero_exit(self, runner: CliRunner) -> None:
        mock_sb = _make_sandbox()
        mock_result = ProcessResult(stdout="", stderr="error\n", exit_code=1, execution_time=0.05)
        mock_sb.commands.run = AsyncMock(return_value=mock_result)

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(cli, ["exec", "sbx-cli-test-001", "false"])

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_auth_error_exit_code_3(self, runner: CliRunner) -> None:
        from serverless_sandbox.models.errors import AuthenticationError

        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync",
            side_effect=AuthenticationError("bad key"),
        ):
            result = runner.invoke(cli, ["create"])

        assert result.exit_code == 3

    def test_template_not_found_exit_code_4(self, runner: CliRunner) -> None:
        from serverless_sandbox.models.errors import TemplateNotFoundError

        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync",
            side_effect=TemplateNotFoundError("no such template"),
        ):
            result = runner.invoke(cli, ["create"])

        assert result.exit_code == 4

    def test_timeout_error_exit_code_5(self, runner: CliRunner) -> None:
        from serverless_sandbox.models.errors import CommandTimeoutError

        mock_sb = _make_sandbox()
        mock_sb.commands.run = AsyncMock(side_effect=CommandTimeoutError("timed out"))

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(cli, ["exec", "sbx-1", "sleep 999"])

        assert result.exit_code == 5

    def test_quota_error_exit_code_6(self, runner: CliRunner) -> None:
        from serverless_sandbox.models.errors import QuotaExceededError

        with patch(
            "serverless_sandbox.utils.async_bridge.run_sync",
            side_effect=QuotaExceededError("quota exceeded"),
        ):
            result = runner.invoke(cli, ["create"])

        assert result.exit_code == 6


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

class TestUpload:
    def test_upload_file(self, runner: CliRunner, tmp_path) -> None:
        """Upload a single file."""
        local_file = tmp_path / "script.py"
        local_file.write_text("print('hello')")

        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(
                cli, ["upload", "sbx-cli-test-001", str(local_file), "/app/script.py"]
            )

        assert result.exit_code == 0
        assert "Uploaded" in result.output
        assert "/app/script.py" in result.output

    def test_upload_file_not_exists(self, runner: CliRunner) -> None:
        """click.Path(exists=True) should reject missing files."""
        result = runner.invoke(
            cli, ["upload", "sbx-1", "/nonexistent/file.py", "/app/file.py"]
        )
        assert result.exit_code != 0

    def test_upload_directory(self, runner: CliRunner, tmp_path) -> None:
        """Upload a directory recursively."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "sub" / "b.txt").write_text("bbb")

        mock_sb = _make_sandbox()

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(
                cli, ["upload", "sbx-cli-test-001", str(tmp_path), "/app/data"]
            )

        assert result.exit_code == 0
        assert "Uploaded 2 files" in result.output


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

class TestDownload:
    def test_download_file(self, runner: CliRunner, tmp_path) -> None:
        """Download a file to a specific path."""
        mock_sb = _make_sandbox()
        mock_sb.files.read_bytes = AsyncMock(return_value=b"csv-data")
        dest = tmp_path / "result.csv"

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(
                cli, ["download", "sbx-cli-test-001", "/app/result.csv", str(dest)]
            )

        assert result.exit_code == 0
        assert "Downloaded" in result.output
        assert dest.read_bytes() == b"csv-data"

    def test_download_to_directory(self, runner: CliRunner, tmp_path) -> None:
        """Download to an existing directory — use remote filename."""
        mock_sb = _make_sandbox()
        mock_sb.files.read_bytes = AsyncMock(return_value=b"log-data")

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(
                cli, ["download", "sbx-cli-test-001", "/app/output.log", str(tmp_path)]
            )

        assert result.exit_code == 0
        assert (tmp_path / "output.log").read_bytes() == b"log-data"

    def test_download_creates_parent_dirs(self, runner: CliRunner, tmp_path) -> None:
        """Intermediate directories should be created automatically."""
        mock_sb = _make_sandbox()
        mock_sb.files.read_bytes = AsyncMock(return_value=b"binary")
        dest = tmp_path / "deep" / "nested" / "file.bin"

        with patch(
            "serverless_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = runner.invoke(
                cli, ["download", "sbx-cli-test-001", "/app/file.bin", str(dest)]
            )

        assert result.exit_code == 0
        assert dest.read_bytes() == b"binary"
