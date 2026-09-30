"""Offline end-to-end: long CLI steps use one moving header.

Docker, ACR, and the sandbox filesystem are mocked. A fake terminal captures
the activity block (Rich is not used: CliRunner's stdout is not a TTY, so the
CLI draws the ``--no-color`` transient block). Quiet and non-TTY runs must
not dump per-line logs or file bytes.

Runs in CI (no ``@pytest.mark.integration``). A live Docker run is still manual.
"""

from __future__ import annotations

import asyncio
import io
import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from easy_sandbox.cli import output as output_mod
from easy_sandbox.cli.main import cli
from easy_sandbox.models.sandbox import SandboxInfo

if TYPE_CHECKING:
    from pathlib import Path

_SECRET = "super-secret-file-bytes"
_TOKEN = "acr-placeholder-token"


class _TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class _FakeSys:
    def __init__(self, stderr: io.StringIO) -> None:
        self.stderr = stderr

    def __getattr__(self, name: str) -> object:
        return getattr(sys, name)


def _combined(result: Any) -> str:
    stderr = getattr(result, "stderr", None) or ""
    return f"{result.output}{stderr}"


def _prepare_template(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")
    (tmp_path / "template.yaml").write_text(
        "name: my-template\nresources:\n  cpu: 2\n  memory: 2048\n"
    )


def _fake_config() -> MagicMock:
    config = MagicMock()
    config.access_key_id = "platform-ak"
    config.access_key_secret = "platform-placeholder"
    config.region = "cn-hangzhou"
    config.api_key = ""
    config.api_url = ""
    return config


def _builder() -> tuple[MagicMock, Any]:
    builder = MagicMock()
    builder.check_docker.return_value = True
    builder.inject_sdk_wheel.return_value = []

    def _build(*_args: Any, **kwargs: Any) -> str:
        emit = kwargs.get("on_output")
        if emit is not None:
            emit("#5 [1/2] FROM ubuntu:22.04")
            emit("   ")
            emit("#5 DONE 0.1s")
        return "my-template:latest"

    def _push(*_args: Any, **kwargs: Any) -> None:
        emit = kwargs.get("on_output")
        if emit is not None:
            emit("Pushed my-template:latest")

    def _wait(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        on_poll = kwargs.get("on_poll")
        if on_poll is not None:
            on_poll("Creating", 0)
            on_poll("Ready", 2)
        return {"status": {"state": "ready"}}

    builder.build.side_effect = _build
    builder.push.side_effect = _push
    builder.login_acr_with_aksk.return_value = {
        "tempUserName": "temp-user",
        "authorizationToken": _TOKEN,
    }
    builder.tag.return_value = None
    return builder, _wait


@pytest.fixture
def tty_stderr(monkeypatch: pytest.MonkeyPatch) -> _TTYBuffer:
    buf = _TTYBuffer()
    monkeypatch.setattr(output_mod, "sys", _FakeSys(buf))
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(output_mod, "_ACTIVITY_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(output_mod, "is_ci_env", lambda: False)
    return buf


def _invoke_build(tmp_path: Path, *, prefix: list[str] | None = None) -> Any:
    builder, wait = _builder()
    with (
        patch("easy_sandbox.transport.config.load_config", return_value=_fake_config()),
        patch("easy_sandbox.api.docker_builder.DockerBuilder", return_value=builder),
        patch(
            "easy_sandbox.api.fc_template.create_official_template",
            return_value={"templateID": "tpl-progress", "statusCode": 200},
        ),
        patch("easy_sandbox.api.fc_template.wait_for_template_ready", side_effect=wait),
    ):
        return CliRunner().invoke(
            cli,
            [
                *(prefix or []),
                "template",
                "build",
                str(tmp_path),
                "--acr-namespace",
                "test-ns",
                "--yes",
            ],
        )


def _sandbox(sandbox_id: str = "sbx-cli-test-001") -> MagicMock:
    info = SandboxInfo.model_validate(
        {
            "sandboxID": sandbox_id,
            "templateID": "python-base",
            "status": "running",
            "region": "cn-hangzhou",
            "timeout": 300,
            "envdUrl": f"https://{sandbox_id}.example.invalid",
            "envdAccessToken": "envd-access-token-secret",
        }
    )
    sandbox = MagicMock()
    sandbox.id = info.sandbox_id
    sandbox.status = info.status
    sandbox.url = info.envd_url
    sandbox.info = info
    sandbox.kill = AsyncMock()
    sandbox.files = MagicMock()
    return sandbox


def test_deploy_streams_build_lines_under_the_header(
    tmp_path: Path, tty_stderr: _TTYBuffer
) -> None:
    _prepare_template(tmp_path)
    result = _invoke_build(tmp_path)
    assert result.exit_code == 0, result.output
    shown = tty_stderr.getvalue()
    assert "Building Docker image locally" in shown
    assert "... 0s" in shown
    assert "#5 [1/2] FROM ubuntu:22.04" in shown
    assert "#5 DONE 0.1s" in shown
    assert "Pushed my-template:latest" in shown
    assert "Ready 2s" in shown
    assert _TOKEN not in shown
    assert _SECRET not in shown
    stdout = getattr(result, "stdout", None) or ""
    assert "#5 [1/2] FROM ubuntu:22.04" not in stdout
    assert _TOKEN not in stdout


def test_non_tty_deploy_does_not_dump_build_lines(tmp_path: Path) -> None:
    _prepare_template(tmp_path)
    result = _invoke_build(tmp_path)
    assert result.exit_code == 0, result.output
    combined = _combined(result)
    assert "Building Docker image locally" in combined
    assert "#5 [1/2] FROM ubuntu:22.04" not in combined
    assert "Pushed my-template:latest" not in combined
    assert _TOKEN not in combined


def test_upload_lists_paths_and_not_file_bytes(tmp_path: Path, tty_stderr: _TTYBuffer) -> None:
    src = tmp_path / "payload"
    src.mkdir()
    (src / "notes.txt").write_text(_SECRET)
    (src / "keep.py").write_text("print(1)\n")
    seen: list[tuple[str, bytes]] = []

    class _Files:
        async def write(self, dest: str, data: bytes) -> None:
            seen.append((dest, data))

    class _Sandbox:
        files = _Files()

    async def _connect(_sid: str) -> _Sandbox:
        return _Sandbox()

    with patch("easy_sandbox.api.sandbox.Sandbox.connect", side_effect=_connect):
        result = CliRunner().invoke(
            cli,
            ["sandbox", "upload", "sb-1", str(src), "/app/data"],
        )

    assert result.exit_code == 0, result.output
    assert any(payload == _SECRET.encode() for _dest, payload in seen)
    shown = tty_stderr.getvalue()
    assert "Uploading" in shown
    assert "notes.txt" in shown
    assert "keep.py" in shown
    assert _SECRET not in shown
    assert _SECRET not in _combined(result)


def test_quiet_upload_does_not_list_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "one.txt"
    src.write_text(_SECRET)

    class _Files:
        async def write(self, dest: str, data: bytes) -> None:
            return None

    class _Sandbox:
        files = _Files()

    async def _connect(_sid: str) -> _Sandbox:
        return _Sandbox()

    monkeypatch.setattr(output_mod, "is_ci_env", lambda: False)
    with patch("easy_sandbox.api.sandbox.Sandbox.connect", side_effect=_connect):
        result = CliRunner().invoke(
            cli,
            ["--quiet", "sandbox", "upload", "sb-1", str(src), "/app/one.txt"],
        )
    assert result.exit_code == 0, result.output
    combined = _combined(result)
    assert "notes.txt" not in combined
    assert _SECRET not in combined
    assert "Uploading" not in combined


def test_json_deploy_does_not_dump_build_lines(tmp_path: Path) -> None:
    _prepare_template(tmp_path)
    result = _invoke_build(tmp_path, prefix=["--json"])
    assert result.exit_code == 0, result.output
    combined = _combined(result)
    assert "tpl-progress" in combined
    assert "#5 [1/2] FROM ubuntu:22.04" not in combined
    assert _TOKEN not in combined


def test_create_shows_an_elapsed_header(tty_stderr: _TTYBuffer) -> None:
    sandbox = _sandbox()

    def _finish(coro: Any) -> MagicMock:
        coro.close()
        return sandbox

    with patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_finish):
        result = CliRunner().invoke(
            cli,
            ["create", "--template", "python-base", "--request-timeout", "45"],
        )
    assert result.exit_code == 0, result.output
    shown = tty_stderr.getvalue()
    assert "Creating sandbox... 0s" in shown
    assert "envd-access-token-secret" not in shown
    stdout = getattr(result, "stdout", None) or ""
    assert "sbx-cli-test-001" in stdout
    assert "envd-access-token-secret" not in stdout


def test_download_shows_a_header_and_hides_bytes(tmp_path: Path, tty_stderr: _TTYBuffer) -> None:
    sandbox = _sandbox()
    sandbox.files.read_bytes = AsyncMock(return_value=_SECRET.encode())
    dest = tmp_path / "out.bin"
    with patch(
        "easy_sandbox.api.sandbox.Sandbox.connect",
        new_callable=AsyncMock,
        return_value=sandbox,
    ):
        result = CliRunner().invoke(
            cli,
            ["download", "sb-1", "/app/secret.bin", str(dest)],
        )
    assert result.exit_code == 0, result.output
    assert dest.read_bytes() == _SECRET.encode()
    shown = tty_stderr.getvalue()
    assert "Downloading /app/secret.bin... 0s" in shown
    assert _SECRET not in shown
    assert _SECRET not in _combined(result)


def test_kill_all_lists_ids_under_the_header(tty_stderr: _TTYBuffer) -> None:
    infos = [
        SandboxInfo.model_validate(
            {
                "sandboxID": sandbox_id,
                "templateID": "base",
                "status": "running",
                "region": "cn-hangzhou",
                "timeout": 300,
            }
        )
        for sandbox_id in ("sbx-a", "sbx-b")
    ]
    calls = {"n": 0}

    def _run(coro: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return infos
        return asyncio.run(coro)

    with (
        patch("easy_sandbox.transport.config.load_config"),
        patch("easy_sandbox.transport.auth.create_auth_provider"),
        patch("easy_sandbox.transport.http.HttpClient"),
        patch("easy_sandbox.protocol.sandbox.SandboxProtocol"),
        patch(
            "easy_sandbox.api.sandbox.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=_sandbox(),
        ),
        patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run),
    ):
        result = CliRunner().invoke(cli, ["kill", "--all", "--yes"])

    assert result.exit_code == 0, result.output
    shown = tty_stderr.getvalue()
    assert "Killing 2 sandbox(es)" in shown
    assert "1/2 sbx-a" in shown
    assert "2/2 sbx-b" in shown
    assert "Killed 2/2" in result.output


def test_template_search_shows_a_fetch_header(tty_stderr: _TTYBuffer) -> None:
    index = MagicMock()
    index.notice = ""
    index.filter.return_value = []

    async def _fetch(*_args: Any, **_kwargs: Any) -> MagicMock:
        return index

    with patch("easy_sandbox.utils.template_index.fetch_index", _fetch):
        result = CliRunner().invoke(cli, ["template", "search", "python"])

    assert result.exit_code == 0, result.output
    assert "Fetching the template index... 0s" in tty_stderr.getvalue()
    assert "No templates matching" in result.output


def test_template_create_shows_a_header_and_hides_the_password(tty_stderr: _TTYBuffer) -> None:
    password = "registry-password-placeholder"
    with (
        patch("easy_sandbox.transport.config.load_config", return_value=_fake_config()),
        patch(
            "easy_sandbox.api.fc_template.create_official_template",
            return_value={"templateID": "tpl-from-image", "statusCode": 200},
        ) as create,
    ):
        result = CliRunner().invoke(
            cli,
            [
                "template",
                "create",
                "registry.example/ns/app:latest",
                "--name",
                "from-image",
                "--registry-password",
                password,
            ],
        )
    assert result.exit_code == 0, result.output
    shown = tty_stderr.getvalue()
    assert "Creating template from-image... 0s" in shown
    assert password not in shown
    assert password not in _combined(result)
    assert create.call_args.kwargs["registry_password"] == password


def test_install_milestones_show_under_the_header(tty_stderr: _TTYBuffer) -> None:
    from pathlib import Path

    class _Backend:
        display_name = "Qwen Code"
        not_installed_error = RuntimeError

        def find_binary(self) -> None:
            return None

        def quick_setup_lines(self, *, reason: str) -> list[str]:
            return ["Install the official standalone build."]

        def install(self, *, on_progress: Any = None) -> Path:
            if on_progress is not None:
                on_progress("Downloading qwen-code from github mirror...")
                on_progress("Verifying SHA256 checksum...")
                on_progress("Extracting archive...")
            return Path("/tmp/qwen-ebx-test")

    import click

    with (
        patch(
            "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_backend",
            return_value=_Backend(),
        ),
        patch(
            "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_credentials",
            side_effect=click.ClickException("stop-after-install"),
        ),
    ):
        result = CliRunner().invoke(cli, ["create", "a small http server", "--yes"])

    assert result.exit_code != 0
    assert "stop-after-install" in result.output
    shown = tty_stderr.getvalue()
    assert "Installing Qwen Code... 0s" in shown
    assert "Downloading qwen-code from github mirror..." in shown
    assert "Verifying SHA256 checksum..." in shown
    assert "Extracting archive..." in shown
    assert "sk-" not in shown
