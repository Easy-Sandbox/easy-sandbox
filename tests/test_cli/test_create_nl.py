"""Tests for the `ebx create "<description>"` AI generation routing.

The natural-language path now drives Qwen Code codegen behind a
research-first clarification loop (plain research round on a native
session, then the structured assessment, then one question per round);
`--template` keeps the direct template path.  Nothing here touches the
network or the real CLI.
"""

from __future__ import annotations

import sys as _sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.agent import clarify
from easy_sandbox.agent.clarify import ClarifyAssessment
from easy_sandbox.agent.codegen import CodegenResult
from easy_sandbox.agent.qwen_code import QwenCodeCredentials
from easy_sandbox.cli.commands import sandbox as sandbox_cmd
from easy_sandbox.cli.main import cli
from easy_sandbox.models.errors import (
    AICodegenError,
    DockerBuildError,
    QwenCodeCredentialError,
)
from easy_sandbox.models.sandbox import SandboxInfo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from click.testing import CliRunner

_CREDS = QwenCodeCredentials(
    source="qwen-stored",
    api_key="sk-test",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    model="qwen3-coder-plus",
)

#: A description that already covers all six clarification facets (100%).
#: Tests that must reach a gate *after* the clarification step pair it with a
#: stubbed "complete" assessment so the single-question loop asks nothing.
_COMPLETE_DESCRIPTION = (
    "Python 3.12 runtime with pandas and jupyter installed, "
    "entry command 'jupyter notebook --ip 0.0.0.0', "
    "port 8888, 2 CPU 4 GB memory, upload a data.csv dataset"
)

#: Fixed native session id (``clarify.new_session_id`` is patched in qwen_env).
_SESSION = "6f0f8e9a-1b2c-4d5e-8f90-123456789abc"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sandbox(
    sandbox_id: str = "sbx-nl-001",
    template: str = "ebx-nl-sandbox-abc123",
    status: str = "running",
) -> MagicMock:
    """Build a mock Sandbox object."""
    sb_info = SandboxInfo.model_validate(
        {
            "sandboxID": sandbox_id,
            "templateID": template,
            "status": status,
            "region": "cn-hangzhou",
            "timeout": 300,
            "envdUrl": f"https://{sandbox_id}.cn-hangzhou.e2b.fc.aliyuncs.com",
            "envdAccessToken": "tok",
        }
    )
    mock_sb = MagicMock()
    mock_sb.id = sb_info.sandbox_id
    mock_sb.status = sb_info.status
    mock_sb.url = sb_info.envd_url
    mock_sb.info = sb_info
    mock_sb.files = MagicMock()
    mock_sb.files.write = AsyncMock()
    return mock_sb


def _make_codegen_result(tmp_path: Path, name: str = "ebx-nl-sandbox-abc123") -> CodegenResult:
    """Build a CodegenResult whose files exist on disk."""
    workdir = tmp_path / "generated"
    workdir.mkdir(parents=True, exist_ok=True)
    dockerfile = workdir / "Dockerfile"
    dockerfile.write_text("FROM python:3.12-slim\n", encoding="utf-8")
    template_yaml = workdir / "template.yaml"
    template_yaml.write_text(f"name: {name}\n", encoding="utf-8")
    return CodegenResult(
        workdir=workdir,
        template_name=name,
        dockerfile=dockerfile,
        template_yaml=template_yaml,
        description="a python env",
        raw_output="generated",
    )


def _run_coro(coro: Any) -> Any:
    """Side effect for patched ``run_sync`` that really awaits the coroutine."""
    import asyncio

    return asyncio.run(coro)


class _FakeTTYStdin:
    def isatty(self) -> bool:
        return True


class _FakeSys:
    """``sys`` shim for TTY-gated prompts.

    ``CliRunner`` replaces the real ``sys.stdin`` while a command runs, so
    TTY detection has to be faked at the module-reference level instead.
    Install it on every command module whose prompts the test drives
    (``sandbox`` for clarification/confirmation, ``_coding_agent`` for the
    install/credential prompts).
    """

    def __init__(self) -> None:
        self.stdin = _FakeTTYStdin()

    def __getattr__(self, name: str) -> Any:
        return getattr(_sys, name)


@pytest.fixture(autouse=True)
def _isolated_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Run every test in its own working directory.

    Interactive tests feed scripted answers; an answer that lands on the wrong
    prompt (``--dir``, ``--name``) must never create directories such as
    ``./pandas`` or ``./y`` inside the repository checkout.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def qwen_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Hermetic defaults for every AI-path test.

    Individual tests override the returned patches as needed.
    """
    binary = tmp_path / "qwen"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.find_qwen_code_binary", MagicMock(return_value=binary)
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials",
        MagicMock(return_value=_CREDS),
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.config_cmd.load_config_dict", MagicMock(return_value={})
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.config_cmd.read_env_var", MagicMock(return_value=None)
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.template.resolve_acr_namespace",
        MagicMock(return_value="test-acr-ns"),
    )
    # The generation workspace is prepared before clarification so both
    # phases share one cwd (Qwen sessions are stored per working directory);
    # fake it so tests never create directories under the real ~/.ebx.
    generated = tmp_path / "generated-workspace"
    monkeypatch.setattr(
        "easy_sandbox.agent.codegen.prepare_workdir",
        MagicMock(return_value=(generated, "ebx-nl-sandbox-abc123")),
    )
    # Deterministic native session id for the resume assertions.
    monkeypatch.setattr("easy_sandbox.agent.clarify.new_session_id", lambda: _SESSION)
    # The research round (phase R) runs before the first assessment; mock it
    # hermetically so no test ever shells out to the stub binary above.
    # ``True`` (a plain bool — the legacy backend contract) means the public
    # facts were researched on the native session; tests that need a
    # classified failure swap in a ``ResearchOutcome``.
    research = MagicMock(return_value=True)
    monkeypatch.setattr("easy_sandbox.agent.clarify.run_research", research)
    return {"binary": binary, "workdir": generated, "research": research}


def _patch_success_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    template_id: str = "tmpl-ai-123",
) -> tuple[CodegenResult, MagicMock, MagicMock]:
    """Patch codegen + deploy to succeed; return (result, gen_mock, deploy_mock)."""
    gen = _make_codegen_result(tmp_path)
    gen_mock = MagicMock(return_value=gen)
    deploy_mock = MagicMock(return_value={"TemplateID": template_id, "Status": "success"})
    monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", gen_mock)
    monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", deploy_mock)
    return gen, gen_mock, deploy_mock


def _clarify_assessment(
    completeness: float,
    *,
    question: str | None = None,
    missing: tuple[str, ...] = (),
    example: str | None = None,
) -> ClarifyAssessment:
    """Build the structured assessment ``clarify.evaluate`` would return."""
    return ClarifyAssessment(
        completeness=completeness, question=question, missing=missing, example=example
    )


def _patch_clarify_evaluate(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[ClarifyAssessment | None],
) -> MagicMock:
    """Fake the structured assessment rounds (one outcome per evaluate call)."""
    mock = MagicMock(side_effect=outcomes)
    monkeypatch.setattr("easy_sandbox.agent.clarify.evaluate", mock)
    return mock


class _FakePhaseOut:
    """Recording stand-in for OutputManager in ``_phase_status`` unit tests."""

    def __init__(self, *, use_rich_spinner: bool, quiet: bool = False) -> None:
        self.use_rich_spinner = use_rich_spinner
        self.quiet = quiet
        self.progress_messages: list[str] = []
        self.spinner_messages: list[str] = []

    def progress(self, message: str) -> None:
        self.progress_messages.append(message)

    @contextmanager
    def spinner(self, message: str) -> Iterator[None]:
        self.spinner_messages.append(message)
        yield

    @contextmanager
    def activity(self, message: str) -> Iterator[None]:
        self.spinner_messages.append(message)
        yield None


# ---------------------------------------------------------------------------
# Routing: AI path vs direct template path
# ---------------------------------------------------------------------------


class TestCreateRouting:
    def test_ai_flow_with_yes_creates_from_deployed_template(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        gen, gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        mock_sb = _make_sandbox()
        mock_create = AsyncMock(return_value=mock_sb)

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "-y", "a python data science env"])

        assert result.exit_code == 0, result.output
        assert "AI generated template" in result.output
        assert "sbx-nl-001" in result.output

        gen_mock.assert_called_once()
        assert gen_mock.call_args.args[0] == "a python data science env"
        deploy_mock.assert_called_once_with(
            str(gen.workdir), acr_namespace="test-acr-ns", ctx=ANY, verbose=False
        )
        assert mock_create.call_args.kwargs["template"] == "tmpl-ai-123"

    def test_create_falls_back_to_template_name_when_no_id(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        gen, _gen_mock, _deploy_mock = _patch_success_pipeline(
            monkeypatch, tmp_path, template_id="N/A"
        )
        mock_sb = _make_sandbox()
        mock_create = AsyncMock(return_value=mock_sb)

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "-y", "node service"])

        assert result.exit_code == 0, result.output
        assert mock_create.call_args.kwargs["template"] == gen.template_name

    def test_explicit_template_bypasses_codegen(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        gen_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", gen_mock)
        mock_sb = _make_sandbox(template="base")

        with patch("easy_sandbox.utils.async_bridge.run_sync", return_value=mock_sb):
            result = runner.invoke(cli, ["create", "--template", "base"])

        assert result.exit_code == 0, result.output
        gen_mock.assert_not_called()
        assert "AI generated template" not in result.output

    @pytest.mark.parametrize("template_flag", ["--template", "-T"])
    def test_description_with_explicit_template_is_rejected(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
        template_flag: str,
    ) -> None:
        """DESCRIPTION + --template is a usage error, never a silent drop."""
        gen_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", gen_mock)
        deploy_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", deploy_mock)
        create_mock = AsyncMock()

        with patch("easy_sandbox.api.sandbox.Sandbox.create", create_mock):
            result = runner.invoke(cli, ["create", "python", template_flag, "custom"])

        assert result.exit_code == 1
        assert "cannot be combined" in result.output
        assert "--template" in result.output
        gen_mock.assert_not_called()
        deploy_mock.assert_not_called()
        create_mock.assert_not_called()

    def test_description_with_template_and_missing_template_value_still_errors(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """Order of arguments does not matter: the conflict is detected either way."""
        gen_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", gen_mock)

        result = runner.invoke(cli, ["create", "--template", "base", "python"])

        assert result.exit_code == 1
        assert "cannot be combined" in result.output
        gen_mock.assert_not_called()

    def test_no_description_no_template_is_usage_error(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """Bare ``ebx create`` requires an explicit route (task 210)."""
        gen_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", gen_mock)

        result = runner.invoke(cli, ["create"])

        assert result.exit_code == 2, result.output
        assert "No DESCRIPTION or --template given" in result.output
        assert "ebx create --template base" in result.output
        gen_mock.assert_not_called()

    def test_json_mode_suppresses_generated_summary(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _patch_success_pipeline(monkeypatch, tmp_path)
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["--json", "create", "-y", "python env"])

        assert result.exit_code == 0, result.output
        assert "AI generated template" not in result.output


# ---------------------------------------------------------------------------
# Qwen Code availability
# ---------------------------------------------------------------------------


class TestQwenCodeInstallGate:
    def test_not_installed_non_tty_shows_quick_setup_and_fails(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.find_qwen_code_binary", MagicMock(return_value=None)
        )
        gen_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", gen_mock)

        result = runner.invoke(cli, ["create", "python env"])

        assert result.exit_code == 1
        assert "Quick Setup" in result.output
        assert "install-qwen-standalone.sh" in result.output
        assert "E2005" in result.output
        gen_mock.assert_not_called()

    def test_tty_declining_install_raises(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.find_qwen_code_binary", MagicMock(return_value=None)
        )
        install_mock = MagicMock()
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.download_and_install_standalone", install_mock
        )
        monkeypatch.setattr("easy_sandbox.cli.commands._coding_agent.sys", _FakeSys())

        result = runner.invoke(cli, ["create", "python env"], input="n\n")

        assert result.exit_code == 1
        assert "Declined to install" in result.output
        install_mock.assert_not_called()

    def test_tty_accepting_install_runs_pipeline(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.find_qwen_code_binary", MagicMock(return_value=None)
        )
        installed = tmp_path / "qwen"
        install_mock = MagicMock(return_value=installed)
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.download_and_install_standalone", install_mock
        )
        # The install prompt lives in the shared coding-agent module; the
        # build/deploy confirmation still lives in the sandbox command.
        monkeypatch.setattr("easy_sandbox.cli.commands._coding_agent.sys", _FakeSys())
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION], input="n\ny\n\ny\n")

        assert result.exit_code == 0, result.output
        install_mock.assert_called_once()
        assert "Installed Qwen Code" in result.output


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class TestQwenCodeCredentialGate:
    def test_missing_credentials_non_tty_fails(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials",
            MagicMock(side_effect=QwenCodeCredentialError("no model credentials found")),
        )

        result = runner.invoke(cli, ["create", "python env"])

        assert result.exit_code == 1
        assert "E2006" in result.output
        assert "llm_api_key" in result.output

    def test_missing_credentials_with_yes_fails_fast(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials",
            MagicMock(side_effect=QwenCodeCredentialError("no model credentials found")),
        )

        result = runner.invoke(cli, ["create", "-y", "python env"])

        assert result.exit_code == 1
        assert "E2006" in result.output

    def test_tty_prompts_for_key_and_stores_it(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        resolve_mock = MagicMock(
            side_effect=[QwenCodeCredentialError("no model credentials found"), _CREDS]
        )
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials", resolve_mock
        )
        write_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.cli.commands.config_cmd.write_env_var", write_mock)
        # The credential prompt lives in the shared coding-agent module; the
        # build/deploy confirmation still lives in the sandbox command.
        monkeypatch.setattr("easy_sandbox.cli.commands._coding_agent.sys", _FakeSys())
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(
                cli, ["create", _COMPLETE_DESCRIPTION], input="n\nsk-user-key\n\ny\n"
            )

        assert result.exit_code == 0, result.output
        write_mock.assert_called_once_with("EBX_LLM_API_KEY", "sk-user-key")
        assert "Stored llm_api_key" in result.output
        assert resolve_mock.call_count == 2
        # The second resolve must reuse the freshly entered key.
        assert resolve_mock.call_args.kwargs["stored_api_key"] == "sk-user-key"

    def test_empty_key_input_aborts(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials",
            MagicMock(side_effect=QwenCodeCredentialError("no model credentials found")),
        )
        monkeypatch.setattr("easy_sandbox.cli.commands._coding_agent.sys", _FakeSys())

        result = runner.invoke(cli, ["create", "python env"], input="\n")

        assert result.exit_code == 1
        assert "No Qwen Code API key provided" in result.output


# ---------------------------------------------------------------------------
# Confirmation + generation failures
# ---------------------------------------------------------------------------


class TestConfirmationAndFailures:
    def test_non_tty_without_yes_requires_confirmation(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        deploy_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", deploy_mock)

        # The assessment clears the threshold, so the clarification loop asks
        # nothing and the flow reaches the non-interactive confirmation gate.
        result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION])

        assert result.exit_code == 1
        assert "Confirmation required" in result.output
        assert 'ebx template init "' in result.output + (result.stderr or "")
        deploy_mock.assert_not_called()

    def test_codegen_failure_surfaces_e2007(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.codegen.generate_template_files",
            MagicMock(side_effect=AICodegenError("Qwen Code did not create the expected file(s)")),
        )
        deploy_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", deploy_mock)

        result = runner.invoke(cli, ["create", "-y", "python env"])

        assert result.exit_code == 1
        assert "E2007" in result.output
        deploy_mock.assert_not_called()

    def test_build_failure_propagates(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "easy_sandbox.cli.commands.template.do_deploy",
            MagicMock(side_effect=DockerBuildError("build failed")),
        )
        mock_sb = _make_sandbox()

        with patch("easy_sandbox.utils.async_bridge.run_sync", return_value=mock_sb):
            result = runner.invoke(cli, ["create", "-y", "python env"])

        assert result.exit_code == 1
        assert "build failed" in result.output


# ---------------------------------------------------------------------------
# Description clarification loop
# ---------------------------------------------------------------------------


class TestDescriptionClarification:
    """The research-first loop that guards Qwen Code generation.

    Research, evaluation, and questions all come from Qwen Code itself;
    these tests fake the thin adapters (``clarify.run_research`` and
    ``clarify.evaluate``) and verify the Easy Sandbox surface only: the
    research round before the first assessment, one question per round,
    the 80% threshold gate, one native session for every round,
    non-interactive fail-fast, cancel/EOF handling, and graceful
    degradation.
    """

    def test_complete_description_skips_questions_and_reaches_confirm_gate(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION])

        assert result.exit_code == 1
        assert "Confirmation required" in result.output
        assert "/5" not in result.output  # the internal round cap is never shown
        assert "Question 1" not in result.output
        evaluate_mock.assert_called_once()
        # Research settled the public facts before the single assessment,
        # and the assessment resumed that very session.
        qwen_env["research"].assert_called_once()
        assert evaluate_mock.call_args.kwargs["resume"] == _SESSION
        gen_mock.assert_called_once()
        # Clarification and generation share one workspace and native session.
        assert gen_mock.call_args.kwargs["workdir"] == qwen_env["workdir"]
        assert gen_mock.call_args.kwargs["resume_session"] == _SESSION

    def test_incomplete_non_tty_raises_e2008_with_missing_details_and_example(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(
                    0.3,
                    question="Which dependencies must be preinstalled?",
                    missing=("dependencies", "ports"),
                    example="Python 3.12 with pandas, expose port 8888",
                )
            ],
        )

        result = runner.invoke(cli, ["create", "运行 python"])

        assert result.exit_code == 1
        assert "E2008" in result.output
        assert "30%" in result.output
        assert "cannot ask clarifying questions" in result.output
        assert "Question 1" not in result.output
        assert "Missing details: dependencies, ports." in result.output
        assert "Example description:" in result.output
        assert "Python 3.12 with pandas, expose port 8888" in result.output
        assert "--yes/-y" in result.output
        assert "ebx create --template <name>" in result.output
        gen_mock.assert_not_called()
        deploy_mock.assert_not_called()

    def test_json_mode_never_prompts_and_raises_e2008(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """--json never blocks on questions: it fails fast with E2008."""
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(
            monkeypatch, [_clarify_assessment(0.5, question="Q?", missing=("ports",))]
        )

        result = runner.invoke(cli, ["--json", "create", "运行 python"])

        assert result.exit_code == 1
        assert "E2008" in result.output
        assert "Question 1" not in result.output
        gen_mock.assert_not_called()

    def test_yes_skips_research_and_assessment_entirely(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """--yes is the fast non-interactive path: no research, no assessment."""
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [])
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "-y", "运行 python"])

        assert result.exit_code == 0, result.output
        evaluate_mock.assert_not_called()
        qwen_env["research"].assert_not_called()
        assert "Question 1" not in result.output
        # No assessment session exists, so generation starts fresh.
        assert gen_mock.call_args.kwargs["resume_session"] is None

    def test_tty_asks_one_question_per_round_until_threshold(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        evaluate_mock = _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(
                    0.4,
                    question="Which dependencies must be preinstalled?",
                    missing=("dependencies",),
                ),
                _clarify_assessment(
                    0.6,
                    question="Which command starts the service?",
                    missing=("entry command",),
                ),
                _clarify_assessment(0.9),
            ],
        )
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(
                cli, ["create", "运行 python"], input="n\n\npandas\njupyter notebook\ny\n"
            )

        assert result.exit_code == 0, result.output
        # One question per round, numbered with no total shown: Question 1
        # and Question 2 were asked, Question 3 was never reached because the
        # second answer lifted the description to the threshold.
        assert "Question 1: Which dependencies must be preinstalled?" in result.output
        assert "Question 2: Which command starts the service?" in result.output
        assert "Question 3:" not in result.output
        assert "/5" not in result.output
        assert "Description is now about 90%; generating." in result.output

        # Research settled the public facts first, on the native session.
        qwen_env["research"].assert_called_once()
        assert qwen_env["research"].call_args.args[0] == clarify.research_prompt("运行 python")
        assert qwen_env["research"].call_args.kwargs["session_id"] == _SESSION

        first_call, second_call, third_call = evaluate_mock.call_args_list
        # Research created the native session; round 1 resumes it, and every
        # later round keeps resuming the same session.
        assert first_call.kwargs["session_id"] is None
        assert first_call.kwargs["resume"] == _SESSION
        assert second_call.kwargs["resume"] == _SESSION
        assert third_call.kwargs["resume"] == _SESSION
        # Each answer travels through the same session, never a rebuilt prompt.
        assert "pandas" in second_call.args[0]
        assert "jupyter notebook" in third_call.args[0]
        # The follow-up prompt carries the already-asked question so the
        # model cannot repeat the topic.
        assert "已问过的问题" in second_call.args[0]
        # Generation continues that very session.
        assert gen_mock.call_args.kwargs["resume_session"] == _SESSION
        assert gen_mock.call_args.args[0] == "运行 python"

    def test_tty_empty_answer_cancels_generation(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_clarify_evaluate(
            monkeypatch,
            [_clarify_assessment(0.4, question="Q?", missing=("dependencies",))],
        )

        result = runner.invoke(cli, ["create", "运行 python"], input="n\n\n\n")

        assert result.exit_code == 1
        assert "E2008" in result.output
        assert "Clarification was cancelled" in result.output
        gen_mock.assert_not_called()

    def test_tty_eof_aborts_with_e2008(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_clarify_evaluate(
            monkeypatch,
            [_clarify_assessment(0.4, question="Q?", missing=("dependencies",))],
        )

        result = runner.invoke(cli, ["create", "运行 python"], input="n\n\n")

        assert result.exit_code == 1
        assert "E2008" in result.output
        assert "interrupted (EOF)" in result.output
        gen_mock.assert_not_called()

    def test_tty_exhausted_rounds_warn_and_generate(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        # The model never reaches the threshold: the loop stops at the round
        # cap instead of asking questions forever.
        evaluate_mock = _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(0.2, question=f"Missing detail {n}?", missing=("ports",))
                for n in range(1, 7)
            ],
        )
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(
                cli, ["create", "运行 python"], input="n\n\n" + "unknown\n" * 5 + "y\n"
            )

        assert result.exit_code == 0, result.output
        assert "Question 5: Missing detail 5?" in result.output
        assert "Question 6:" not in result.output
        assert "/5" not in result.output
        assert "Reached the 5-question safety limit" in result.output
        assert "Description is about 20% complete" in result.output
        assert "Generating anyway." in result.output
        assert evaluate_mock.call_count == 6  # 1 initial + 5 capped rounds
        assert gen_mock.call_args.kwargs["resume_session"] == _SESSION

    def test_assessment_unavailable_degrades_to_direct_generation(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """A broken model must never block: warn, then generate directly."""
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [None])
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "运行 python"], input="n\n\ny\n")

        assert result.exit_code == 0, result.output
        assert "Could not assess the description completeness" in result.output
        assert "Question 1" not in result.output
        evaluate_mock.assert_called_once()
        qwen_env["research"].assert_called_once()  # research ran, assessment failed
        gen_mock.assert_called_once()
        # The session never came up, so generation starts fresh.
        assert gen_mock.call_args.kwargs["resume_session"] is None

    def test_mid_loop_assessment_loss_keeps_the_session_for_generation(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(0.5, question="Which dependencies?", missing=("dependencies",)),
                None,
            ],
        )
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "运行 python"], input="n\n\npandas\ny\n")

        assert result.exit_code == 0, result.output
        assert "became unavailable" in result.output
        gen_mock.assert_called_once()
        # Round 1 did create the session; generation still resumes it.
        assert gen_mock.call_args.kwargs["resume_session"] == _SESSION


# ---------------------------------------------------------------------------
# Research-first two-phase contract (phase R → phase A, one session)
# ---------------------------------------------------------------------------


class TestResearchFirstFlow:
    """Round 1 = plain research run, then the structured assessment.

    Both phases come from Qwen Code itself on ONE native session; Easy
    Sandbox only wires them together and never echoes the research output.
    """

    def test_round1_research_then_assessment_on_one_session(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _patch_success_pipeline(monkeypatch, tmp_path)
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION])

        assert result.exit_code == 1, result.output  # stopped at the confirm gate
        research = qwen_env["research"]
        research.assert_called_once()
        # Phase R: the research prompt embeds the description.
        assert research.call_args.args[0] == clarify.research_prompt(_COMPLETE_DESCRIPTION)
        assert research.call_args.kwargs["session_id"] == _SESSION
        assert research.call_args.kwargs["cwd"] == qwen_env["workdir"]
        # Phase A: the assessment resumes the very session research created.
        assert evaluate_mock.call_args.args[0] == clarify.assessment_prompt(_COMPLETE_DESCRIPTION)
        assert evaluate_mock.call_args.kwargs["resume"] == _SESSION
        assert evaluate_mock.call_args.kwargs["session_id"] is None

    def test_research_failure_warns_and_assessment_pins_the_session(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """A failed research round never blocks: warn, then assess from scratch."""
        qwen_env["research"].return_value = False
        _patch_success_pipeline(monkeypatch, tmp_path)
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION])

        assert result.exit_code == 1, result.output
        assert "could not research the public facts" in result.output
        # No session came out of research, so the assessment pins it itself.
        assert evaluate_mock.call_args.kwargs["session_id"] == _SESSION
        assert evaluate_mock.call_args.kwargs["resume"] is None
        # Generation still continues the session the assessment created.

    def test_failed_research_never_reuses_its_session_id(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """Regression: qwen rejects ``--session-id`` of an existing session.

        The failed research round may already have created its session, and
        re-pinning that id made every assessment exit 1 ("Session Id ... is
        already in use"), which surfaced as the bogus "assessment
        unavailable" warning.  The assessment must start a FRESH session and
        generation must continue that one.
        """
        second = "22222222-2222-4222-8222-222222222222"
        ids = iter([_SESSION, second])
        monkeypatch.setattr("easy_sandbox.agent.clarify.new_session_id", lambda: next(ids))
        qwen_env["research"].return_value = clarify.ResearchOutcome(
            ok=False, reason=clarify.RESEARCH_REASON_TIMEOUT
        )
        _, gen_mock, _ = _patch_success_pipeline(monkeypatch, tmp_path)
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION])

        assert result.exit_code == 1, result.output
        assert qwen_env["research"].call_args.kwargs["session_id"] == _SESSION
        assert evaluate_mock.call_args.kwargs["session_id"] == second
        assert evaluate_mock.call_args.kwargs["session_id"] != _SESSION
        assert gen_mock.call_args.kwargs["resume_session"] == second
        assert "assessment unavailable" not in result.output

    @pytest.mark.parametrize(
        ("reason", "hint_fragment"),
        [
            (clarify.RESEARCH_REASON_TIMEOUT, "timed out"),
            (clarify.RESEARCH_REASON_AGENT_UNAVAILABLE, "could not be started"),
            (clarify.RESEARCH_REASON_COMMAND_FAILED, "--verbose"),
            (clarify.RESEARCH_REASON_TURN_LIMIT, "step budget"),
        ],
    )
    def test_research_failure_reason_adds_a_safe_hint(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
        reason: str,
        hint_fragment: str,
    ) -> None:
        """A classified failure adds a reason hint; the detail never leaks."""
        qwen_env["research"].return_value = clarify.ResearchOutcome(
            ok=False, reason=reason, detail="raw internal detail"
        )
        _patch_success_pipeline(monkeypatch, tmp_path)
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION])

        assert result.exit_code == 1, result.output  # stopped at the confirm gate
        assert "could not research the public facts" in result.output
        assert hint_fragment in result.output
        assert "raw internal detail" not in result.output
        # The failed round did not create the session: the assessment pins it.
        assert evaluate_mock.call_args.kwargs["session_id"] == _SESSION
        assert evaluate_mock.call_args.kwargs["resume"] is None

    def test_serverless_devs_public_facts_are_researched_not_asked(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """Acceptance case: Serverless Devs facts are settled by research.

        Whether it is a Node.js tool, its official install method, and its
        common dependencies are publicly verifiable facts: the research
        prompt must carry them, and the assessment may never turn them into
        a question.
        """
        description = "一个 sandbox 里面运行 Serverless Devs CLI"
        _patch_success_pipeline(monkeypatch, tmp_path)
        evaluate_mock = _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["create", description])

        assert result.exit_code == 1, result.output  # reached the confirm gate
        research = qwen_env["research"]
        research.assert_called_once()
        assert "Serverless Devs CLI" in research.call_args.args[0]
        # The research-first assessment ran once and asked nothing — the
        # public facts counted as complete.
        evaluate_mock.assert_called_once()
        assert "Question 1" not in result.output
        assert "Node.js" not in result.output
        assert "安装方式" not in result.output


# ---------------------------------------------------------------------------
# Delegation answers
# ---------------------------------------------------------------------------


class TestDelegationAnswers:
    """Answers like “你自己决定”/"you decide" delegate the choice to the agent."""

    def test_delegation_answer_teaches_the_agent_to_decide(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        evaluate_mock = _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(
                    0.4, question="Which resource size?", missing=("resource size",)
                ),
                _clarify_assessment(0.9),
            ],
        )
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "运行 python"], input="n\n\n你自己决定吧\ny\n")

        assert result.exit_code == 0, result.output
        assert "Description is now about 90%; generating." in result.output
        # The follow-up prompt embeds the delegation instruction...
        followup = evaluate_mock.call_args_list[1].args[0]
        assert "委托你自行决定" in followup
        # ...plus the user's words verbatim and the already-asked question.
        assert "你自己决定吧" in followup
        assert "已问过的问题" in followup
        # The delegation settled the topic: no second question was asked.
        assert "Question 2" not in result.output

    def test_concrete_answer_needs_no_delegation_clause(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """A concrete answer carries no delegation pressure."""
        _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        evaluate_mock = _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(
                    0.4, question="Which resource size?", missing=("resource size",)
                ),
                _clarify_assessment(0.9),
            ],
        )
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "运行 python"], input="n\n\n2 CPU 4 GB\ny\n")

        assert result.exit_code == 0, result.output
        followup = evaluate_mock.call_args_list[1].args[0]
        assert "委托你自行决定" not in followup
        assert "2 CPU 4 GB" in followup


# ---------------------------------------------------------------------------
# Anti-repetition
# ---------------------------------------------------------------------------


class TestAntiRepetition:
    """Asked topics never repeat; a repeated question breaks the loop."""

    def test_exact_repeat_breaks_the_loop(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _gen, gen_mock, _deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        question = "Which port should the service expose?"
        evaluate_mock = _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(0.4, question=question, missing=("ports",)),
                _clarify_assessment(0.6, question=question, missing=("ports",)),
            ],
        )
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "运行 python"], input="n\n\n8888\ny\n")

        assert result.exit_code == 0, result.output
        # The question was shown exactly once — the repeat was caught before
        # a second prompt, even though the model kept returning it.
        assert "Question 1: Which port should the service expose?" in result.output
        assert "Question 2:" not in result.output
        assert "The agent repeated an already-answered question" in result.output
        assert "Generating anyway." in result.output
        assert evaluate_mock.call_count == 2
        # Generation still continues the session with the collected answers.
        assert gen_mock.call_args.kwargs["resume_session"] == _SESSION

    def test_asked_questions_travel_with_every_followup(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """Every follow-up prompt embeds the already-asked questions."""
        _patch_success_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        evaluate_mock = _patch_clarify_evaluate(
            monkeypatch,
            [
                _clarify_assessment(
                    0.4, question="Which port should the service expose?", missing=("ports",)
                ),
                _clarify_assessment(0.9),
            ],
        )
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "运行 python"], input="n\n\n8888\ny\n")

        assert result.exit_code == 0, result.output
        followup = evaluate_mock.call_args_list[1].args[0]
        assert "已问过的问题" in followup
        assert "Which port should the service expose?" in followup


# ---------------------------------------------------------------------------
# Phase-status channels (spinner / progress: stderr only, stdout untouched)
# ---------------------------------------------------------------------------


class TestPhaseStatusChannels:
    """Assess / re-assess / generate status never leaks to stdout."""

    def test_spinner_mode_skips_the_progress_line(self) -> None:
        """TTY spinner mode: only the spinner runs, no plain progress line."""
        out = _FakePhaseOut(use_rich_spinner=True)
        with sandbox_cmd._phase_status(out, "Assessing description"):
            pass
        assert out.spinner_messages == ["Assessing description"]
        assert out.progress_messages == []

    def test_plain_mode_prints_one_progress_line(self) -> None:
        """Non-TTY: one machine-readable progress line replaces the spinner."""
        out = _FakePhaseOut(use_rich_spinner=False)
        with sandbox_cmd._phase_status(out, "Generating template"):
            pass
        assert out.progress_messages == ["Generating template"]
        assert out.spinner_messages == ["Generating template"]  # spinner ctx still entered

    def test_quiet_mode_prints_no_progress_line(self) -> None:
        """Quiet/CI: the phase status is fully silent."""
        out = _FakePhaseOut(use_rich_spinner=False, quiet=True)
        with sandbox_cmd._phase_status(out, "Assessing description"):
            pass
        assert out.progress_messages == []

    def test_phase_lines_stay_on_stderr(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """Non-TTY end-to-end: phase lines on stderr, stdout stays clean."""
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION])

        assert result.exit_code == 1, result.output
        assert "Assessing description" in result.stderr
        assert "Generating template" in result.stderr
        assert "Assessing description" not in result.stdout
        assert "Generating template" not in result.stdout

    def test_json_mode_progress_on_stderr_stdout_machine_readable(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """--json: diagnostics stay on stderr; stdout is a JSON document."""
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["--json", "create", "-y", "python env"])

        assert result.exit_code == 0, result.output
        # stdout: machine readable JSON only — no phase prose, no questions.
        # (``--yes`` skips clarification, so the generation phase is the only
        # one that runs here.)
        assert "Generating template" not in result.stdout
        assert "Question 1" not in result.stdout
        # stderr carries the progress diagnostics as JSON.
        assert "Generating template" in result.stderr
        assert '"level": "progress"' in result.stderr

    def test_quiet_mode_silent_progress(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """--quiet: phase lines are suppressed entirely (stdout bare values)."""
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["--quiet", "create", "-y", "python env"])

        assert result.exit_code == 0, result.output
        assert "Assessing description" not in result.stderr
        assert "Generating template" not in result.stderr
        assert "Assessing description" not in result.stdout


# ---------------------------------------------------------------------------
# Template-only switch and natural-language init
# ---------------------------------------------------------------------------


class TestTemplateOnlySwitch:
    """Interactive create can stop after the local template."""

    def test_tty_yes_writes_template_and_skips_build(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        gen, gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        mock_create = AsyncMock()

        with patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create):
            result = runner.invoke(cli, ["create", _COMPLETE_DESCRIPTION], input="y\n")

        assert result.exit_code == 0, result.output
        shown = result.output + (result.stderr or "")
        assert "Switch to template init" in shown
        deploy_mock.assert_not_called()
        mock_create.assert_not_called()
        gen_mock.assert_called_once()
        target = tmp_path / gen.template_name
        assert (target / "Dockerfile").is_file()
        assert (target / "template.yaml").is_file()
        assert f"Template '{gen.template_name}' created" in shown

    def test_yes_flag_skips_the_switch_and_deploys(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """--yes is the full pipeline: no template-only question."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _gen, _gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        mock_sb = _make_sandbox()

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "-y", _COMPLETE_DESCRIPTION], input="y\n")

        assert result.exit_code == 0, result.output
        assert "Switch to template init" not in result.output
        deploy_mock.assert_called_once()
        assert not (tmp_path / _gen.template_name).exists()


class TestTemplateInitNaturalLanguage:
    """``ebx template init "DESCRIPTION"`` generates files and stops."""

    def test_description_writes_local_files_without_deploy(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        gen, gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)

        result = runner.invoke(cli, ["template", "init", "-y", "a python data science env"])

        assert result.exit_code == 0, result.output
        deploy_mock.assert_not_called()
        gen_mock.assert_called_once()
        assert gen_mock.call_args.args[0] == "a python data science env"
        assert "Directory for the template project" not in result.output
        target = tmp_path / gen.template_name
        assert (target / "Dockerfile").read_text(encoding="utf-8").startswith("FROM")
        assert "template deploy" in result.output
        assert "created successfully" not in result.output

    def test_name_overrides_directory_and_yaml(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _patch_success_pipeline(monkeypatch, tmp_path)

        result = runner.invoke(
            cli,
            ["template", "init", "-y", "--name", "myapp", "a python data science env"],
        )

        assert result.exit_code == 0, result.output
        yaml_text = (tmp_path / "myapp" / "template.yaml").read_text(encoding="utf-8")
        assert "name: myapp" in yaml_text
        assert not (tmp_path / "ebx-nl-sandbox-abc123").exists()

    def test_existing_files_need_force(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        gen, _gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        target = tmp_path / gen.template_name
        target.mkdir()
        (target / "Dockerfile").write_text("kept\n", encoding="utf-8")

        blocked = runner.invoke(cli, ["template", "init", "-y", "a python data science env"])
        assert blocked.exit_code == 1
        assert "already exist" in blocked.output
        assert (target / "Dockerfile").read_text(encoding="utf-8") == "kept\n"
        deploy_mock.assert_not_called()

        forced = runner.invoke(
            cli, ["template", "init", "-y", "--force", "a python data science env"]
        )
        assert forced.exit_code == 0, forced.output
        assert (target / "Dockerfile").read_text(encoding="utf-8").startswith("FROM")

    def test_description_rejects_scaffold_flags(self, runner: CliRunner) -> None:
        for args in (
            ["template", "init", "a python env", "-t", "python"],
            ["template", "init", "a python env", "--from", "owner/repo"],
        ):
            result = runner.invoke(cli, args)
            assert result.exit_code != 0
            assert "cannot be combined" in result.output

    def test_top_level_init_shortcut_accepts_a_description(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        gen, _gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)

        result = runner.invoke(cli, ["init", "-y", "一个数据分析环境"])

        assert result.exit_code == 0, result.output
        deploy_mock.assert_not_called()
        assert (tmp_path / gen.template_name / "template.yaml").is_file()

    def test_tty_asks_for_a_directory_and_enter_keeps_the_default(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        gen, _gen_mock, deploy_mock = _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        result = runner.invoke(cli, ["init", "a python data science env"], input="\n")

        assert result.exit_code == 0, result.output
        shown = result.output + (result.stderr or "")
        assert "Directory for the template project" in shown
        assert "./<name>" in shown
        deploy_mock.assert_not_called()
        assert (tmp_path / gen.template_name / "Dockerfile").is_file()

    def test_tty_directory_answer_is_the_project_directory(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        gen, _gen_mock, _deploy = _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        chosen = tmp_path / "serverless-devs"

        result = runner.invoke(
            cli, ["template", "init", "a python data science env"], input=f"{chosen}\n"
        )

        assert result.exit_code == 0, result.output
        assert (chosen / "Dockerfile").read_text(encoding="utf-8").startswith("FROM")
        assert (chosen / "template.yaml").is_file()
        assert not (tmp_path / gen.template_name).exists()
        assert not chosen.joinpath("serverless-devs").exists()

    def test_tty_rejects_a_file_before_generation(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _gen, gen_mock, _deploy = _patch_success_pipeline(monkeypatch, tmp_path)
        blocked = tmp_path / "not-a-dir"
        blocked.write_text("x", encoding="utf-8")

        result = runner.invoke(cli, ["init", "a python data science env"], input=f"{blocked}\n")

        assert result.exit_code != 0
        assert "not a directory" in result.output
        gen_mock.assert_not_called()
        assert blocked.read_text(encoding="utf-8") == "x"

    def test_tty_existing_files_fail_before_generation(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _gen, gen_mock, _deploy = _patch_success_pipeline(monkeypatch, tmp_path)
        chosen = tmp_path / "app"
        chosen.mkdir()
        (chosen / "Dockerfile").write_text("kept\n", encoding="utf-8")

        result = runner.invoke(cli, ["init", "a python data science env"], input=f"{chosen}\n")

        assert result.exit_code != 0
        assert "already exist" in result.output
        gen_mock.assert_not_called()
        assert (chosen / "Dockerfile").read_text(encoding="utf-8") == "kept\n"


class TestOutputDir:
    """``--dir`` / interactive prompt: where the AI template workspace lives."""

    def _invoke(
        self,
        runner: CliRunner,
        args: list[str],
        *,
        input: str | None = None,
    ) -> Any:
        mock_sb = _make_sandbox()
        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", AsyncMock(return_value=mock_sb)),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            return runner.invoke(cli, args, input=input)

    def test_explicit_dir_is_used_as_parent_and_not_created_by_validation(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        from easy_sandbox.agent import codegen

        _patch_success_pipeline(monkeypatch, tmp_path)
        target = tmp_path / "my" / "templates"

        result = self._invoke(runner, ["create", "-y", "--dir", str(target), "python env"])

        assert result.exit_code == 0, result.output
        # Generation (mocked here) creates the workspace; validation alone must not.
        assert not target.exists()
        assert codegen.prepare_workdir.call_args.kwargs["base_dir"] == target.resolve()  # type: ignore[attr-defined]

    def test_default_location_when_dir_omitted_and_not_interactive(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """No --dir and no TTY: never prompt, keep the standard location."""
        from easy_sandbox.agent import codegen

        _patch_success_pipeline(monkeypatch, tmp_path)

        result = self._invoke(runner, ["create", "-y", "python env"])

        assert result.exit_code == 0, result.output
        assert "which directory" not in result.output
        assert "base_dir" not in codegen.prepare_workdir.call_args.kwargs  # type: ignore[attr-defined]

    def test_tty_prompts_and_enter_accepts_the_default(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        from easy_sandbox.agent import codegen

        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])

        # switch=n, directory=<Enter>, confirm=y
        result = self._invoke(runner, ["create", _COMPLETE_DESCRIPTION], input="n\n\ny\n")

        assert result.exit_code == 0, result.output
        assert "Save the generated template under which directory?" in result.output
        assert "generated" in result.output  # the default is shown
        assert "base_dir" not in codegen.prepare_workdir.call_args.kwargs  # type: ignore[attr-defined]

    def test_tty_prompt_answer_is_used(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        from easy_sandbox.agent import codegen

        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        chosen = tmp_path / "chosen"

        result = self._invoke(runner, ["create", _COMPLETE_DESCRIPTION], input=f"n\n{chosen}\ny\n")

        assert result.exit_code == 0, result.output
        assert not chosen.exists()
        assert codegen.prepare_workdir.call_args.kwargs["base_dir"] == chosen.resolve()  # type: ignore[attr-defined]

    def test_answer_at_the_directory_prompt_creates_no_directory(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        """A clarification answer typed at the directory prompt must not leave ``./pandas``."""
        monkeypatch.setattr("easy_sandbox.cli.commands.sandbox.sys", _FakeSys())
        _patch_success_pipeline(monkeypatch, tmp_path)
        _patch_clarify_evaluate(monkeypatch, [_clarify_assessment(1.0)])
        before = {p.name for p in tmp_path.iterdir()}

        # switch=n, directory="pandas" (meant as a clarification answer), confirm=y
        result = self._invoke(runner, ["create", _COMPLETE_DESCRIPTION], input="n\npandas\ny\n")

        assert result.exit_code == 0, result.output
        assert not (tmp_path / "pandas").exists()
        assert {p.name for p in tmp_path.iterdir()} - before <= {"generated-workspace"}

    def test_unwritable_parent_is_rejected_without_creating_anything(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _patch_success_pipeline(monkeypatch, tmp_path)
        locked = tmp_path / "locked"
        locked.mkdir()
        monkeypatch.setattr(
            "easy_sandbox.cli.commands.sandbox.os.access",
            lambda path, mode: str(path) != str(locked.resolve()),
        )

        result = runner.invoke(cli, ["create", "-y", "--dir", str(locked / "sub"), "python env"])

        assert result.exit_code == 1
        assert "not writable" in result.output
        assert not (locked / "sub").exists()

    def test_dir_without_description_is_a_usage_error(
        self,
        runner: CliRunner,
        tmp_path: Path,
        qwen_env: dict[str, Any],
    ) -> None:
        result = runner.invoke(cli, ["create", "--template", "base", "--dir", str(tmp_path)])

        assert result.exit_code == 1
        assert "--dir only applies" in result.output

    def test_dir_pointing_at_a_file_is_rejected(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        qwen_env: dict[str, Any],
    ) -> None:
        _patch_success_pipeline(monkeypatch, tmp_path)
        a_file = tmp_path / "file.txt"
        a_file.write_text("x", encoding="utf-8")

        result = runner.invoke(cli, ["create", "-y", "--dir", str(a_file), "python env"])

        assert result.exit_code == 1
        assert "not a directory" in result.output
