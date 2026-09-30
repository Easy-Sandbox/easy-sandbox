"""End-to-end CLI flows for natural-language create versus template init.

Each test enters through the real ``ebx`` command tree (``template init``,
``init``, ``create``, ``sandbox create``). The coding agent, image build,
and sandbox API are stubbed so the run stays offline; the assertions are
on the files left on disk and on the calls that must not happen.

Run with: pytest tests/integration/test_nl_template_init_e2e.py -m integration -v
"""

from __future__ import annotations

import asyncio
import sys as _sys
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from easy_sandbox.agent import codegen as _codegen
from easy_sandbox.agent.clarify import ClarifyAssessment
from easy_sandbox.agent.codegen import CodegenResult
from easy_sandbox.agent.qwen_code import QwenCodeCredentials, QwenCodeRunResult
from easy_sandbox.cli.main import cli
from easy_sandbox.models.sandbox import SandboxInfo

if TYPE_CHECKING:
    from pathlib import Path

# Captured before any test patches it: the *real* generator, used by the
# "real codegen" tests below so the prompt, validation and file listing run.
_REAL_GENERATE = _codegen.generate_template_files

_CREDS = QwenCodeCredentials(
    source="qwen-stored",
    api_key="sk-test",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    model="qwen3-coder-plus",
)
_TEMPLATE_NAME = "ebx-nl-sandbox-abc123"
_DESCRIPTION = "a python data science env with pandas"


class _FakeTTYStdin:
    def isatty(self) -> bool:
        return True


class _FakeSys:
    """TTY stand-in. CliRunner replaces the real stdin while a command runs."""

    def __init__(self) -> None:
        self.stdin = _FakeTTYStdin()

    def __getattr__(self, name: str) -> Any:
        return getattr(_sys, name)


def _shown(result: Any) -> str:
    text = result.output or ""
    with suppress(ValueError):
        text += result.stderr or ""
    return text


def _run_coro(coro: Any) -> Any:
    return asyncio.run(coro)


def _codegen_result(tmp_path: Path) -> CodegenResult:
    workdir = tmp_path / "generated"
    workdir.mkdir(parents=True, exist_ok=True)
    dockerfile = workdir / "Dockerfile"
    dockerfile.write_text("FROM python:3.12-slim\n", encoding="utf-8")
    template_yaml = workdir / "template.yaml"
    template_yaml.write_text(f"name: {_TEMPLATE_NAME}\n", encoding="utf-8")
    commands_py = workdir / "commands.py"
    commands_py.write_text(
        "from easy_sandbox.server import CommandRegistry, SandboxServer\n"
        "registry = CommandRegistry()\n"
        "SandboxServer(registry=registry).serve(port=9000)\n",
        encoding="utf-8",
    )
    (workdir / "README.md").write_text("# generated\n", encoding="utf-8")
    return CodegenResult(
        workdir=workdir,
        template_name=_TEMPLATE_NAME,
        dockerfile=dockerfile,
        template_yaml=template_yaml,
        description=_DESCRIPTION,
        raw_output="generated",
        commands_py=commands_py,
        files=("Dockerfile", "README.md", "commands.py", "template.yaml"),
    )


def _sandbox() -> MagicMock:
    info = SandboxInfo.model_validate(
        {
            "sandboxID": "sbx-e2e-001",
            "templateID": "tmpl-ai-123",
            "status": "running",
            "region": "cn-hangzhou",
            "timeout": 300,
            "envdUrl": "https://sbx-e2e-001.cn-hangzhou.e2b.fc.aliyuncs.com",
            "envdAccessToken": "tok",
        }
    )
    sandbox = MagicMock()
    sandbox.id = info.sandbox_id
    sandbox.status = info.status
    sandbox.url = info.envd_url
    sandbox.info = info
    return sandbox


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def agent_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Hermetic coding-agent + deploy stubs. No network, no real Qwen Code."""
    binary = tmp_path / "qwen"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.find_qwen_code_binary",
        MagicMock(return_value=binary),
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials",
        MagicMock(return_value=_CREDS),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.config_cmd.load_config_dict",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.config_cmd.read_env_var",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.template.resolve_acr_namespace",
        MagicMock(return_value="test-acr-ns"),
    )
    workspace = tmp_path / "generated-workspace"
    monkeypatch.setattr(
        "easy_sandbox.agent.codegen.prepare_workdir",
        MagicMock(return_value=(workspace, _TEMPLATE_NAME)),
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.clarify.run_research",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.clarify.evaluate",
        MagicMock(return_value=ClarifyAssessment(completeness=1.0, question=None)),
    )
    generated = _codegen_result(tmp_path)
    generate = MagicMock(return_value=generated)
    deploy = MagicMock(return_value={"TemplateID": "tmpl-ai-123", "Status": "success"})
    monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", generate)
    monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", deploy)
    return {"generated": generated, "generate": generate, "deploy": deploy}


def _assert_local_template(directory: Path) -> None:
    assert (directory / "Dockerfile").read_text(encoding="utf-8").startswith("FROM")
    assert "name:" in (directory / "template.yaml").read_text(encoding="utf-8")
    # A Dockerfile alone is not a usable template: the HTTP server entry point
    # (commands.py) and the docs must be copied along with it.
    assert "SandboxServer" in (directory / "commands.py").read_text(encoding="utf-8")
    assert (directory / "README.md").is_file()


# ---------------------------------------------------------------------------
# Scaffold init: explicit directory, default subdirectory of cwd
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_scaffold_init_writes_the_given_directory(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / "nested" / "my-template"

    result = runner.invoke(cli, ["template", "init", str(dest), "-t", "python"])

    assert result.exit_code == 0, result.output
    assert (dest / "Dockerfile").is_file()
    assert (dest / "template.yaml").is_file()
    assert (dest / "commands.py").is_file()
    assert not (tmp_path / "python").exists()
    assert not (tmp_path / "Dockerfile").exists()


@pytest.mark.integration
def test_scaffold_init_defaults_to_a_subdirectory_of_cwd(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["template", "init", "-t", "node", "--name", "myapp"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "myapp" / "Dockerfile").is_file()
    assert not (tmp_path / "Dockerfile").exists()


# ---------------------------------------------------------------------------
# Natural-language init: files only, under cwd/<name>/
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_nl_init_writes_under_cwd_and_does_not_deploy(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_ready: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    create = AsyncMock()

    with patch("easy_sandbox.api.sandbox.Sandbox.create", create):
        result = runner.invoke(cli, ["template", "init", "-y", _DESCRIPTION])

    assert result.exit_code == 0, _shown(result)
    agent_ready["deploy"].assert_not_called()
    create.assert_not_called()
    agent_ready["generate"].assert_called_once()
    _assert_local_template(tmp_path / _TEMPLATE_NAME)
    assert "template deploy" in _shown(result)
    assert "created successfully" not in _shown(result)


@pytest.mark.integration
def test_nl_init_name_selects_the_subdirectory(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_ready: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["template", "init", "-y", "--name", "myapp", "一个数据分析环境"])

    assert result.exit_code == 0, _shown(result)
    agent_ready["deploy"].assert_not_called()
    _assert_local_template(tmp_path / "myapp")
    assert "name: myapp" in (tmp_path / "myapp" / "template.yaml").read_text(encoding="utf-8")
    assert not (tmp_path / _TEMPLATE_NAME).exists()


@pytest.mark.integration
def test_nl_init_rejects_a_second_directory_argument(runner: CliRunner, tmp_path: Path) -> None:
    """The description occupies the only positional; a path cannot ride along."""
    result = runner.invoke(
        cli,
        ["template", "init", "-y", _DESCRIPTION, str(tmp_path / "elsewhere")],
    )

    assert result.exit_code != 0
    assert not (tmp_path / "elsewhere").exists()


@pytest.mark.integration
def test_top_level_init_matches_template_init(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_ready: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["init", "-y", _DESCRIPTION])

    assert result.exit_code == 0, _shown(result)
    agent_ready["deploy"].assert_not_called()
    _assert_local_template(tmp_path / _TEMPLATE_NAME)


# ---------------------------------------------------------------------------
# create: switch to init, or continue through deploy + sandbox create
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_create_switch_stops_after_the_local_template(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_ready: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
    create = AsyncMock()

    with patch("easy_sandbox.api.sandbox.Sandbox.create", create):
        result = runner.invoke(cli, ["create", _DESCRIPTION], input="y\n")

    assert result.exit_code == 0, _shown(result)
    assert "Switch to template init" in _shown(result)
    agent_ready["deploy"].assert_not_called()
    create.assert_not_called()
    _assert_local_template(tmp_path / _TEMPLATE_NAME)


@pytest.mark.integration
def test_create_yes_deploys_and_creates_a_sandbox(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_ready: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    sandbox = _sandbox()

    with (
        patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=sandbox)),
        patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
    ):
        result = runner.invoke(cli, ["create", "-y", _DESCRIPTION])

    assert result.exit_code == 0, _shown(result)
    assert "Switch to template init" not in _shown(result)
    agent_ready["deploy"].assert_called_once()
    assert "sbx-e2e-001" in _shown(result)
    assert "created successfully" in _shown(result)
    assert not (tmp_path / _TEMPLATE_NAME).exists()


@pytest.mark.integration
def test_sandbox_create_yes_is_the_same_pipeline(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_ready: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    sandbox = _sandbox()

    with (
        patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=sandbox)),
        patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
    ):
        result = runner.invoke(cli, ["sandbox", "create", "-y", _DESCRIPTION])

    assert result.exit_code == 0, _shown(result)
    agent_ready["deploy"].assert_called_once()
    assert "sbx-e2e-001" in _shown(result)


@pytest.mark.integration
def test_noninteractive_create_reminds_about_init_and_does_not_launch(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_ready: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    create = AsyncMock()

    with patch("easy_sandbox.api.sandbox.Sandbox.create", create):
        result = runner.invoke(cli, ["create", _DESCRIPTION])

    assert result.exit_code != 0
    shown = _shown(result)
    assert "Confirmation required" in shown
    assert "ebx template init" in shown
    agent_ready["deploy"].assert_not_called()
    create.assert_not_called()


# ---------------------------------------------------------------------------
# Real generation chain: only the Qwen Code process is faked. The prompt that
# reaches the agent, the server-entry-point validation, the deliverable
# listing, the local copy, and the deploy hand-off all run for real.
# ---------------------------------------------------------------------------

_SERVER_DOCKERFILE = (
    "FROM python:3.12-slim\n"
    "COPY *.whl /tmp/\n"
    "RUN pip install --no-cache-dir easy-sandbox\n"
    "WORKDIR /app\n"
    "COPY commands.py .\n"
    "EXPOSE 9000\n"
    'CMD ["python3", "commands.py"]\n'
)
_SERVER_COMMANDS = (
    "from easy_sandbox.server import CommandRegistry, SandboxServer\n"
    "registry = CommandRegistry()\n"
    '@registry.command("hello")\n'
    "def hello(name: str = 'World') -> str:\n"
    "    return f'Hello, {name}!'\n"
    "registry.freeze()\n"
    "SandboxServer(registry=registry).serve(port=9000)\n"
)
_SERVER_YAML = (
    "name: whatever\n"
    "description: 数据分析环境\n"
    "capabilities: [shell, files, ports]\n"
    "ports: [9000]\n"
    "resources:\n  cpu: 2\n  memory: 2048\n"
)


def _fake_qwen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    commands_py: str | None = _SERVER_COMMANDS,
) -> list[str]:
    """Replace the Qwen Code process with a writer; return the prompts it received."""
    prompts: list[str] = []

    def _run(prompt: str, **kwargs: Any) -> QwenCodeRunResult:
        prompts.append(prompt)
        cwd = kwargs["cwd"]
        cwd.mkdir(parents=True, exist_ok=True)
        (cwd / "Dockerfile").write_text(_SERVER_DOCKERFILE, encoding="utf-8")
        (cwd / "template.yaml").write_text(_SERVER_YAML, encoding="utf-8")
        (cwd / "README.md").write_text("# generated\n", encoding="utf-8")
        (cwd / "app.py").write_text("print('business code')\n", encoding="utf-8")
        (cwd / ".qwen").mkdir(exist_ok=True)
        (cwd / ".qwen" / "session.json").write_text("{}", encoding="utf-8")
        if commands_py is not None:
            (cwd / "commands.py").write_text(commands_py, encoding="utf-8")
        return QwenCodeRunResult(text="done", is_error=False, exit_code=0)

    monkeypatch.setattr("easy_sandbox.agent.codegen.run_qwen_code_headless", _run)
    return prompts


@pytest.fixture
def real_codegen(agent_ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", _REAL_GENERATE)
    return agent_ready


@pytest.mark.integration
def test_nl_init_delivers_a_usable_template_not_just_a_dockerfile(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_codegen: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    prompts = _fake_qwen(monkeypatch)

    result = runner.invoke(cli, ["template", "init", "-y", _DESCRIPTION])

    assert result.exit_code == 0, _shown(result)
    real_codegen["deploy"].assert_not_called()

    # The agent was told to build a server and given the SDK reference.
    assert len(prompts) == 1
    for needle in ("commands.py", "SandboxServer", "CommandRegistry", "EXPOSE 9000"):
        assert needle in prompts[0], needle

    # Every deliverable, and only deliverables, reached ./<name>/.
    target = tmp_path / _TEMPLATE_NAME
    assert sorted(p.name for p in target.iterdir()) == [
        "Dockerfile",
        "README.md",
        "app.py",
        "commands.py",
        "template.yaml",
    ]
    assert "SandboxServer" in (target / "commands.py").read_text(encoding="utf-8")
    assert "commands.py" in (target / "Dockerfile").read_text(encoding="utf-8")
    assert f"name: {_TEMPLATE_NAME}" in (target / "template.yaml").read_text(encoding="utf-8")
    shown = _shown(result)
    assert "commands.py" in shown  # listed in the "Created files" summary


@pytest.mark.integration
def test_nl_init_rejects_a_dockerfile_only_result_and_writes_nothing(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_codegen: dict[str, Any],
) -> None:
    """The regression: a Dockerfile-only template cannot be used once deployed."""
    monkeypatch.chdir(tmp_path)
    _fake_qwen(monkeypatch, commands_py=None)

    result = runner.invoke(cli, ["template", "init", "-y", _DESCRIPTION])

    assert result.exit_code != 0
    assert "commands.py" in _shown(result)
    assert not (tmp_path / _TEMPLATE_NAME).exists()
    real_codegen["deploy"].assert_not_called()


@pytest.mark.integration
def test_nl_init_rejects_a_commands_py_that_never_starts_the_server(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_codegen: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    _fake_qwen(monkeypatch, commands_py="print('hello')\n")

    result = runner.invoke(cli, ["template", "init", "-y", _DESCRIPTION])

    assert result.exit_code != 0
    assert "SandboxServer" in _shown(result)
    assert not (tmp_path / _TEMPLATE_NAME).exists()


@pytest.mark.integration
def test_create_yes_hands_the_whole_workspace_to_deploy(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_codegen: dict[str, Any],
) -> None:
    from pathlib import Path as _Path

    monkeypatch.chdir(tmp_path)
    _fake_qwen(monkeypatch)
    sandbox = _sandbox()

    with (
        patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=sandbox)),
        patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
    ):
        result = runner.invoke(cli, ["create", "-y", _DESCRIPTION])

    assert result.exit_code == 0, _shown(result)
    real_codegen["deploy"].assert_called_once()
    built = _Path(real_codegen["deploy"].call_args.args[0])
    assert (built / "commands.py").is_file()
    assert (built / "Dockerfile").is_file()
    assert "sbx-e2e-001" in _shown(result)


@pytest.mark.integration
def test_create_yes_with_a_dockerfile_only_result_never_deploys(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_codegen: dict[str, Any],
) -> None:
    monkeypatch.chdir(tmp_path)
    _fake_qwen(monkeypatch, commands_py=None)
    create = AsyncMock()

    with patch("easy_sandbox.api.sandbox.Sandbox.create", create):
        result = runner.invoke(cli, ["create", "-y", _DESCRIPTION])

    assert result.exit_code != 0
    assert "commands.py" in _shown(result)
    real_codegen["deploy"].assert_not_called()
    create.assert_not_called()


# ---------------------------------------------------------------------------
# No stray directories from misdirected interactive answers
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_answers_typed_at_the_directory_prompt_leave_no_directories(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_codegen: dict[str, Any],
) -> None:
    """``./pandas``, ``./y``, ``./2 CPU 4 GB`` must never appear in the working directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
    _fake_qwen(monkeypatch)
    before = {p.name for p in tmp_path.iterdir()}

    # switch=n, directory="pandas" (meant as a clarification answer), confirm=y
    with (
        patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=_sandbox())),
        patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
    ):
        result = runner.invoke(cli, ["create", _DESCRIPTION], input="n\npandas\ny\n")

    assert result.exit_code == 0, _shown(result)
    assert not (tmp_path / "pandas").exists()
    created = {p.name for p in tmp_path.iterdir()} - before
    assert created <= {"generated-workspace"}, created
