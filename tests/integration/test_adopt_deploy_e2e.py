"""Offline end-to-end: ``ebx template init --adopt`` then ``ebx deploy``.

The coding agent is the real ``QwenCodeBackend``, with only the ``qwen``
subprocess replaced. Docker, ACR and ``CreateTemplate`` are mocked. The
assertions are the ones a real publish depends on: the registered payload
matches the ``template.yaml`` that ``--adopt`` wrote, the user's source and
secrets are unchanged, and deploy makes no second model call.

Runs in CI (no ``@pytest.mark.integration``). A live Qwen Code + Docker run
is still manual.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from easy_sandbox.agent.coding_agent import QwenCodeBackend
from easy_sandbox.agent.qwen_code import QwenCodeCredentials, QwenCodeRunResult, scrubbed_environ
from easy_sandbox.cli.main import cli
from easy_sandbox.utils.dockerignore import DockerIgnore

_CREDS = QwenCodeCredentials(
    source="qwen-stored",
    api_key="sk-test",
    base_url="https://dashscope.example/compatible-mode/v1",
    model="qwen3-coder-plus",
)

_COMMANDS = """\
from easy_sandbox.server import CommandRegistry, SandboxServer

registry = CommandRegistry()
registry.freeze()
SandboxServer(registry=registry).serve(port=9000)
"""

_LEAKS = {
    "ALICLOUD_ACCESS_KEY_ID": "LTAI-leak",
    "E2B_API_KEY": "e2b-leak",
    "ACR_PASSWORD": "acr-leak",
    "AWS_SECRET_ACCESS_KEY": "aws-leak",
    "GITHUB_TOKEN": "gh-leak",
}

_SAMPLES: dict[str, dict[str, Any]] = {
    "flask": {
        "name": "flask-api",
        "hint": "the API listens on 8080",
        "files": {
            "app.py": "print('hello from flask')\n",
            "requirements.txt": "flask==3.0.0\n",
            ".env": "APP_TOKEN=placeholder-not-real\n",
        },
        "copy": ("app.py", "requirements.txt"),
        "cpu": 4,
        "memory": 4096,
        "generation": 2,
    },
    "express": {
        "name": "express-api",
        "hint": "the server listens on 3000",
        "files": {
            "index.js": "console.log('hello from express')\n",
            "package.json": '{"name":"web","version":"1.0.0"}\n',
            ".env": "APP_TOKEN=placeholder-not-real\n",
        },
        "copy": ("index.js", "package.json"),
        "cpu": 2,
        "memory": 2048,
        "generation": 1,
    },
}


def _text(result: Any) -> str:
    try:
        err = result.stderr or ""
    except ValueError:
        err = ""
    return (result.output or "") + err


def _dockerfile(sources: tuple[str, ...]) -> str:
    copies = "\n".join(f"COPY {name} ." for name in sources)
    return (
        "FROM python:3.12-slim\n"
        "COPY *.whl /tmp/\n"
        "RUN pip install --no-cache-dir easy-sandbox\n"
        "WORKDIR /app\n"
        "COPY commands.py .\n"
        f"{copies}\n"
        "EXPOSE 9000\n"
        'CMD ["python3", "commands.py"]\n'
    )


def _template_yaml(sample: dict[str, Any]) -> str:
    return (
        "name: ignored-by-cli\n"
        'version: "1.0.0"\n'
        f"description: {sample['name']} demo\n"
        "capabilities: [shell, files, ports]\n"
        "ports: [9000]\n"
        f"generation: {sample['generation']}\n"
        "resources:\n"
        f"  cpu: {sample['cpu']}\n"
        f"  memory: {sample['memory']}\n"
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _no_staging_left_behind() -> Any:
    yield
    root = Path(tempfile.gettempdir())
    for path in root.glob("ebx-adopt-*"):
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def leaked_cloud_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _LEAKS.items():
        monkeypatch.setenv(key, value)


def _agent(monkeypatch: pytest.MonkeyPatch, sample: dict[str, Any]) -> dict[str, Any]:
    """Real backend; the qwen subprocess writes a valid template into cwd."""
    seen: dict[str, Any] = {"calls": 0}

    def _headless(
        prompt: str,
        *,
        cwd: Path | str,
        env: Any = None,
        clean_env: bool = False,
        **kwargs: Any,
    ) -> QwenCodeRunResult:
        seen["calls"] += 1
        seen["prompt"] = prompt
        seen["clean_env"] = clean_env
        seen["max_session_turns"] = kwargs.get("max_session_turns")
        seen["cwd"] = Path(cwd)
        child = {**scrubbed_environ(), **dict(env or {})} if clean_env else {**dict(env or {})}
        seen["child_env"] = child
        seen["staged_files"] = sorted(
            path.relative_to(cwd).as_posix() for path in Path(cwd).rglob("*") if path.is_file()
        )
        workdir = Path(cwd)
        (workdir / "Dockerfile").write_text(_dockerfile(sample["copy"]), encoding="utf-8")
        (workdir / "commands.py").write_text(_COMMANDS, encoding="utf-8")
        (workdir / "template.yaml").write_text(_template_yaml(sample), encoding="utf-8")
        (workdir / "README.md").write_text("written by the agent\n", encoding="utf-8")
        return QwenCodeRunResult(text="done", is_error=False, exit_code=0)

    monkeypatch.setattr("easy_sandbox.agent.qwen_code.run_qwen_code_headless", _headless)
    monkeypatch.setattr(
        "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_backend",
        lambda: QwenCodeBackend(),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands._coding_agent.ensure_coding_agent_binary",
        lambda *args, **kwargs: Path("qwen"),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_credentials",
        lambda *args, **kwargs: _CREDS,
    )
    return seen


def _project(tmp_path: Path, kind: str, sample: dict[str, Any]) -> Path:
    project = tmp_path / kind
    project.mkdir()
    for name, text in sample["files"].items():
        (project / name).write_text(text, encoding="utf-8")
    return project


@pytest.mark.parametrize("kind", sorted(_SAMPLES))
def test_adopt_then_deploy_registers_the_written_template(
    kind: str,
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    leaked_cloud_env: None,
) -> None:
    sample = _SAMPLES[kind]
    project = _project(tmp_path, kind, sample)
    before = {name: (project / name).read_text(encoding="utf-8") for name in sample["files"]}
    seen = _agent(monkeypatch, sample)

    adopted = runner.invoke(
        cli,
        [
            "template",
            "init",
            "--adopt",
            str(project),
            "--name",
            sample["name"],
            "--hint",
            sample["hint"],
            "-y",
        ],
    )
    assert adopted.exit_code == 0, _text(adopted)
    assert seen["calls"] == 1
    assert seen["clean_env"] is True
    assert seen["max_session_turns"] == 40
    assert seen["cwd"] != project
    assert seen["cwd"].name.startswith("ebx-adopt-")
    assert sample["hint"] in seen["prompt"]
    assert ".env" not in seen["prompt"]
    assert ".env" not in seen["staged_files"]
    for source in sample["copy"]:
        assert source in seen["staged_files"]
    for key, value in _LEAKS.items():
        assert key not in seen["child_env"]
        assert value not in seen["child_env"].values()
    assert seen["child_env"]["OPENAI_API_KEY"] == "sk-test"

    for name, text in before.items():
        assert (project / name).read_text(encoding="utf-8") == text
    assert not (project / "README.md").exists()
    manifest = yaml.safe_load((project / "template.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == sample["name"]
    assert manifest["resources"]["cpu"] == sample["cpu"]
    assert manifest["resources"]["memory"] == sample["memory"]
    assert manifest["generation"] == sample["generation"]
    assert manifest["description"] == f"{sample['name']} demo"
    ignore = DockerIgnore.from_text((project / ".dockerignore").read_text(encoding="utf-8"))
    assert ignore.excludes(".env") is True
    assert ignore.excludes("easy_sandbox-0.0.0-py3-none-any.whl") is False

    fake_config = MagicMock()
    fake_config.access_key_id = "platform-ak"
    fake_config.access_key_secret = "platform-sk"
    fake_config.region = "cn-hangzhou"
    fake_config.api_key = ""
    fake_config.api_url = ""

    with (
        patch("easy_sandbox.transport.config.load_config", return_value=fake_config),
        patch("easy_sandbox.api.docker_builder.DockerBuilder") as mock_builder_cls,
        patch("easy_sandbox.api.fc_template.create_official_template") as mock_create,
        patch(
            "easy_sandbox.api.fc_template.wait_for_template_ready",
            return_value={"status": {"state": "ready"}},
        ),
    ):
        builder = mock_builder_cls.return_value
        builder.check_docker.return_value = True
        builder.inject_sdk_wheel.return_value = []
        builder.build.return_value = f"{sample['name']}:latest"
        builder.login_acr_with_aksk.return_value = {
            "tempUserName": "u",
            "authorizationToken": "t",
        }
        builder.tag.return_value = None
        builder.push.return_value = None
        mock_create.return_value = {"templateID": f"tpl-{kind}", "statusCode": 200}
        deployed = runner.invoke(
            cli,
            ["deploy", str(project), "--acr-namespace", "test-ns", "-y"],
        )

    assert deployed.exit_code == 0, _text(deployed)
    assert f"tpl-{kind}" in _text(deployed)
    assert seen["calls"] == 1
    assert builder.build.call_args.kwargs["context_dir"] == project.resolve()
    registered = mock_create.call_args.kwargs
    assert registered["name"] == manifest["name"]
    assert registered["cpu"] == manifest["resources"]["cpu"]
    assert registered["memory_size"] == manifest["resources"]["memory"]
    assert registered["generation"] == manifest["generation"]
    assert "description" not in registered
    assert sample["name"] in registered["image"]
    assert "test-ns" in registered["image"]
    for name, text in before.items():
        assert (project / name).read_text(encoding="utf-8") == text
