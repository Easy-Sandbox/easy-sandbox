"""CLI tests for ``ebx template init --adopt``.

The coding agent is a fake that writes a valid template into its cwd.  No
model, Docker or cloud call is made.  ``ebx deploy`` is then checked only
as far as the fixed pipeline hand-off.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from easy_sandbox.cli.commands import deploy as deploy_mod
from easy_sandbox.cli.commands.template import build as real_build
from easy_sandbox.cli.main import cli

COMMANDS = """\
from easy_sandbox.server import CommandRegistry, SandboxServer

registry = CommandRegistry()
registry.freeze()
SandboxServer(registry=registry).serve(port=9000)
"""

DOCKER = """\
FROM python:3.12-slim
COPY *.whl /tmp/
RUN pip install --no-cache-dir easy-sandbox
WORKDIR /app
COPY commands.py .
COPY app.py .
EXPOSE 9000
CMD ["python3", "commands.py"]
"""

YAML = """\
name: ignored
version: "1.0.0"
description: demo
capabilities: [shell, files, ports]
ports: [9000]
resources:
  cpu: 1
  memory: 512
"""


def _text(result: Any) -> str:
    try:
        err = result.stderr or ""
    except ValueError:
        err = ""
    return (result.output or "") + err


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "app"
    project.mkdir()
    (project / "app.py").write_text("print('hi')\n", encoding="utf-8")
    return project


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
def agent(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A backend that writes a valid template and records the call."""
    seen: dict[str, Any] = {"calls": 0, "env": None}

    class _Backend:
        display_name = "Qwen Code"

        def run_in_workspace(self, _prompt: str, *, workdir: Path, env: Any, **_kwargs: Any) -> str:
            seen["calls"] += 1
            seen["env"] = dict(env or {})
            (workdir / "Dockerfile").write_text(DOCKER, encoding="utf-8")
            (workdir / "commands.py").write_text(COMMANDS, encoding="utf-8")
            (workdir / "template.yaml").write_text(YAML, encoding="utf-8")
            return "done"

    class _Creds:
        base_url = "https://dashscope.example/compatible-mode/v1"

        def as_env(self) -> dict[str, str]:
            return {"OPENAI_API_KEY": "sk-test", "OPENAI_BASE_URL": self.base_url}

    monkeypatch.setattr(
        "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_backend",
        lambda: _Backend(),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands._coding_agent.ensure_coding_agent_binary",
        lambda *args, **kwargs: Path("qwen"),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_credentials",
        lambda *args, **kwargs: _Creds(),
    )
    return seen


class TestFlags:
    def test_hint_and_dry_run_require_adopt(self, runner: CliRunner) -> None:
        for args in (["--hint", "redis"], ["--dry-run"]):
            result = runner.invoke(cli, ["template", "init", *args])
            assert result.exit_code == 1
            assert "--adopt" in _text(result)

    def test_adopt_rejects_scaffold_and_from(self, runner: CliRunner, tmp_path: Path) -> None:
        project = _project(tmp_path)
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project), "-t", "python"])
        assert result.exit_code == 1
        assert "cannot be combined" in _text(result)

    def test_a_sentence_is_not_a_directory(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["template", "init", "--adopt", "a python app", "-y"])
        assert result.exit_code == 1
        assert "--hint" in _text(result)

    def test_noninteractive_without_yes_sends_nothing(
        self, runner: CliRunner, tmp_path: Path, agent: dict[str, Any]
    ) -> None:
        project = _project(tmp_path)
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project)])
        assert result.exit_code == 1
        assert "Confirmation required" in _text(result)
        assert agent["calls"] == 0
        assert not (project / "Dockerfile").exists()


class TestConsent:
    def test_declining_send_does_not_call_the_agent(
        self,
        runner: CliRunner,
        tmp_path: Path,
        agent: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("easy_sandbox.cli.commands._adopt._is_interactive", lambda _fmt: True)
        project = _project(tmp_path)
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project)], input="n\n")
        assert result.exit_code != 0
        assert "Nothing was sent" in _text(result)
        assert agent["calls"] == 0
        assert not (project / "Dockerfile").exists()


class TestDryRun:
    def test_lists_files_and_writes_nothing(
        self, runner: CliRunner, tmp_path: Path, agent: dict[str, Any]
    ) -> None:
        project = _project(tmp_path)
        (project / ".env").write_text("TOKEN=value\n", encoding="utf-8")
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project), "--dry-run"])
        text = _text(result)
        assert result.exit_code == 0, text
        assert "app.py" in text
        assert ".env" in text
        assert "nothing is sent" in text
        assert agent["calls"] == 0
        assert not (project / "Dockerfile").exists()
        assert not (project / "template.yaml").exists()


class TestAdopt:
    def test_writes_only_reserved_files_and_then_deploy_is_unchanged(
        self,
        runner: CliRunner,
        tmp_path: Path,
        agent: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = _project(tmp_path)
        result = runner.invoke(
            cli, ["template", "init", "--adopt", str(project), "--name", "my-app", "-y"]
        )
        text = _text(result)
        assert result.exit_code == 0, text
        assert agent["calls"] == 1
        assert agent["env"] == {
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "https://dashscope.example/compatible-mode/v1",
        }
        assert (project / "Dockerfile").is_file()
        assert (project / "commands.py").is_file()
        assert "name: my-app" in (project / "template.yaml").read_text(encoding="utf-8")
        assert (project / ".dockerignore").is_file()
        assert (project / "app.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert "ebx deploy" in text

        calls: list[dict[str, Any]] = []

        def _record(**kwargs: Any) -> None:
            calls.append(kwargs)

        monkeypatch.setattr(
            deploy_mod,
            "build",
            click.Command("build", params=list(real_build.params), callback=_record),
        )
        monkeypatch.setattr(deploy_mod, "resolve_acr_namespace", lambda *_a, **_k: "ns")

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("agent")

        for name in (
            "resolve_coding_agent_backend",
            "ensure_coding_agent_binary",
            "resolve_coding_agent_credentials",
        ):
            monkeypatch.setattr(f"easy_sandbox.cli.commands._coding_agent.{name}", _boom)

        deployed = runner.invoke(cli, ["deploy", str(project), "--acr-namespace", "ns", "-y"])
        assert deployed.exit_code == 0, _text(deployed)
        assert calls[0]["template_dir"] == str(project.resolve())
        assert agent["calls"] == 1

    def test_agent_edits_outside_the_whitelist_do_not_land(
        self,
        runner: CliRunner,
        tmp_path: Path,
        agent: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = _project(tmp_path)

        def _nasty(_prompt: str, *, workdir: Path, **_kwargs: Any) -> str:
            agent["calls"] += 1
            (workdir / "Dockerfile").write_text(DOCKER, encoding="utf-8")
            (workdir / "commands.py").write_text(COMMANDS, encoding="utf-8")
            (workdir / "template.yaml").write_text(YAML, encoding="utf-8")
            (workdir / "app.py").write_text("hacked\n", encoding="utf-8")
            (workdir.parent / "evil.txt").write_text("nope\n", encoding="utf-8")
            return "done"

        monkeypatch.setattr(
            "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_backend",
            lambda: type(
                "B",
                (),
                {"display_name": "Qwen Code", "run_in_workspace": staticmethod(_nasty)},
            )(),
        )
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project), "-y"])
        assert result.exit_code == 0, _text(result)
        assert (project / "app.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert "app.py" in _text(result)
        assert not (project / "evil.txt").exists()

    def test_existing_dockerfile_without_force_is_refused(
        self, runner: CliRunner, tmp_path: Path, agent: dict[str, Any]
    ) -> None:
        project = _project(tmp_path)
        (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project), "-y"])
        assert result.exit_code == 1
        assert "without a preview" in _text(result)
        assert agent["calls"] == 0
        assert (project / "Dockerfile").read_text(encoding="utf-8") == "FROM scratch\n"

    def test_force_keeps_a_backup(
        self, runner: CliRunner, tmp_path: Path, agent: dict[str, Any]
    ) -> None:
        project = _project(tmp_path)
        (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project), "--force", "-y"])
        assert result.exit_code == 0, _text(result)
        assert (project / "Dockerfile").read_text(encoding="utf-8") != "FROM scratch\n"
        assert (project / "Dockerfile.ebx-bak").read_text(encoding="utf-8") == "FROM scratch\n"

    def test_failed_generation_leaves_the_project_and_keeps_staging(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _project(tmp_path)

        def _bad(_prompt: str, *, workdir: Path, **_kwargs: Any) -> str:
            (workdir / "Dockerfile").symlink_to(workdir / "app.py")
            return "done"

        monkeypatch.setattr(
            "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_backend",
            lambda: type(
                "B", (), {"display_name": "Qwen Code", "run_in_workspace": staticmethod(_bad)}
            )(),
        )
        monkeypatch.setattr(
            "easy_sandbox.cli.commands._coding_agent.ensure_coding_agent_binary",
            lambda *args, **kwargs: Path("qwen"),
        )
        monkeypatch.setattr(
            "easy_sandbox.cli.commands._coding_agent.resolve_coding_agent_credentials",
            lambda *args, **kwargs: type("C", (), {"base_url": "", "as_env": lambda self: {}})(),
        )
        before = (project / "app.py").read_text(encoding="utf-8")
        result = runner.invoke(cli, ["template", "init", "--adopt", str(project), "-y"])
        assert result.exit_code == 1
        assert "symlink" in _text(result)
        assert "ebx-adopt-" in _text(result)
        assert (project / "app.py").read_text(encoding="utf-8") == before
        assert not (project / "Dockerfile").exists()

    def test_deploy_missing_dockerfile_points_at_adopt(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(deploy_mod, "resolve_acr_namespace", lambda *_a, **_k: "ns")
        result = runner.invoke(cli, ["deploy", str(tmp_path)])
        assert result.exit_code == 1
        assert "init --adopt" in _text(result)
