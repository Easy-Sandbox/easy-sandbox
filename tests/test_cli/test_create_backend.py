"""End-to-end decoupling proof for the pluggable coding-agent backend.

``ebx create "<description>"`` must run entirely through the backend
returned by ``resolve_coding_agent_backend``: these tests replace the
backend with a dummy (no Qwen Code anywhere) and assert that no function
of the Qwen Code / codegen / clarify modules is ever touched, while the
rest of the create pipeline (deploy, ``Sandbox.create``) still runs
unchanged.

The dummy also pins the message templating contract: every user-facing
sentence must name the backend's ``display_name`` / ``config_key`` /
``env_var`` instead of hard-coded "Qwen Code" strings.

Nothing here touches the network or the real Qwen Code CLI.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.agent.clarify import (
    RESEARCH_REASON_AGENT_UNAVAILABLE,
    ClarifyAssessment,
    ResearchOutcome,
)
from easy_sandbox.agent.codegen import CodegenResult
from easy_sandbox.cli.main import cli
from easy_sandbox.models.errors import SandboxCreationError
from easy_sandbox.models.sandbox import SandboxInfo

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


class _DummyNotInstalledError(SandboxCreationError):
    code = "E2905"


class _DummyCredentialError(SandboxCreationError):
    code = "E2906"


class _DummyCredentials:
    """Credential object carrying a marker env for assertions."""

    def as_env(self) -> dict[str, str]:
        return {"DUMMY_AGENT_KEY": "dummy-secret"}


class _DummyBackend:
    """A complete ``CodingAgentBackend`` implementation with zero Qwen code."""

    name = "dummy"
    display_name = "Dummy Agent"
    config_key = "dummy_api_key"
    env_var = "EBX_DUMMY_API_KEY"
    base_url_config_key = "dummy_base_url"
    model_config_key = "dummy_model"
    credential_prompt = "Dummy API key (hidden; leave empty to cancel)"
    credential_error = _DummyCredentialError
    not_installed_error = _DummyNotInstalledError

    def __init__(
        self,
        *,
        binary: Path | None,
        workdir: Path,
        template_name: str,
        assessment: ClarifyAssessment | None = None,
        research_ok: bool = True,
    ) -> None:
        self.binary = binary
        self.workdir = workdir
        self.template_name = template_name
        self.assessment = assessment
        self.research_ok = research_ok
        # Optional classified failure; ``None`` keeps the bool contract.
        self.research_outcome: ResearchOutcome | None = None
        self.research_calls: list[dict[str, Any]] = []
        self.assess_calls: list[dict[str, Any]] = []
        self.generate_calls: list[dict[str, Any]] = []

    def quick_setup_lines(self, *, reason: str) -> list[str]:
        return [f"Dummy setup ({reason}); docs: https://example.test/dummy"]

    def find_binary(self) -> Path | None:
        return self.binary

    def install(self, *, on_progress: Any = None) -> Path:
        raise AssertionError("dummy backend must never install")

    def resolve_credentials(
        self,
        *,
        stored_api_key: str | None = None,
        llm_api_key: str | None = None,
        stored_base_url: str | None = None,
        stored_model: str | None = None,
    ) -> _DummyCredentials:
        return _DummyCredentials()

    def prepare_workdir(self, description: str) -> tuple[Path, str]:
        return self.workdir, self.template_name

    def research(
        self,
        prompt: str,
        *,
        workdir: Path,
        binary: Path | str,
        env: dict[str, str] | None,
        session_id: str,
    ) -> bool | ResearchOutcome:
        self.research_calls.append(
            {
                "prompt": prompt,
                "workdir": workdir,
                "binary": binary,
                "env": env,
                "session_id": session_id,
            }
        )
        if self.research_outcome is not None:
            return self.research_outcome
        return self.research_ok

    def assess(
        self,
        prompt: str,
        *,
        workdir: Path,
        binary: Path | str,
        env: dict[str, str] | None,
        session_id: str | None = None,
        resume: str | None = None,
    ) -> ClarifyAssessment | None:
        self.assess_calls.append(
            {
                "prompt": prompt,
                "workdir": workdir,
                "binary": binary,
                "env": env,
                "session_id": session_id,
                "resume": resume,
            }
        )
        return self.assessment

    def generate(
        self,
        description: str,
        *,
        workdir: Path,
        template_name: str,
        resume_session: str | None = None,
        binary: Path | str | None = None,
        env: dict[str, str] | None = None,
        on_progress: Any = None,
    ) -> CodegenResult:
        self.generate_calls.append(
            {
                "description": description,
                "workdir": workdir,
                "template_name": template_name,
                "resume_session": resume_session,
                "binary": binary,
                "env": env,
                "on_progress": on_progress,
            }
        )
        dockerfile = workdir / "Dockerfile"
        dockerfile.write_text("FROM scratch\n", encoding="utf-8")
        template_yaml = workdir / "template.yaml"
        template_yaml.write_text(f"name: {template_name}\n", encoding="utf-8")
        return CodegenResult(
            workdir=workdir,
            template_name=template_name,
            dockerfile=dockerfile,
            template_yaml=template_yaml,
            description=description,
            raw_output="dummy",
        )


def _make_sandbox(sandbox_id: str = "sbx-dummy-001", template: str = "x") -> MagicMock:
    """Build a mock Sandbox object (pattern shared with test_create_nl)."""
    sb_info = SandboxInfo.model_validate(
        {
            "sandboxID": sandbox_id,
            "templateID": template,
            "status": "running",
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


def _run_coro(coro: Any) -> Any:
    """Side effect for the patched ``run_sync`` that really awaits the coroutine."""
    return asyncio.run(coro)


def _patch_backend(monkeypatch: pytest.MonkeyPatch, backend: _DummyBackend) -> MagicMock:
    """Route ``resolve_coding_agent_backend()`` to the dummy instance."""
    resolver = MagicMock(return_value=backend)
    monkeypatch.setattr("easy_sandbox.agent.coding_agent.resolve_coding_agent_backend", resolver)
    return resolver


@pytest.fixture
def dummy_backend(tmp_path: Path) -> _DummyBackend:
    binary = tmp_path / "dummy-agent"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    workdir = tmp_path / "dummy-workspace"
    workdir.mkdir()
    return _DummyBackend(binary=binary, workdir=workdir, template_name="ebx-nl-dummy-xyz")


@pytest.fixture
def no_real_agent(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Patch every Qwen Code / codegen / clarify entry point (recording mocks)."""
    mocks = {
        "qwen_find_binary": MagicMock(return_value=None),
        "qwen_install": MagicMock(),
        "qwen_install_command": MagicMock(return_value="curl dummy"),
        "qwen_resolve_credentials": MagicMock(),
        "codegen_prepare_workdir": MagicMock(),
        "codegen_generate": MagicMock(),
        "clarify_run_research": MagicMock(return_value=True),
        "clarify_evaluate": MagicMock(),
    }
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.find_qwen_code_binary", mocks["qwen_find_binary"]
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.download_and_install_standalone", mocks["qwen_install"]
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.official_install_command", mocks["qwen_install_command"]
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials",
        mocks["qwen_resolve_credentials"],
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.codegen.prepare_workdir", mocks["codegen_prepare_workdir"]
    )
    monkeypatch.setattr(
        "easy_sandbox.agent.codegen.generate_template_files", mocks["codegen_generate"]
    )
    monkeypatch.setattr("easy_sandbox.agent.clarify.run_research", mocks["clarify_run_research"])
    monkeypatch.setattr("easy_sandbox.agent.clarify.evaluate", mocks["clarify_evaluate"])
    # Keep the configuration sources hermetic.
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.config_cmd.load_config_dict", MagicMock(return_value={})
    )
    monkeypatch.setattr(
        "easy_sandbox.cli.commands.config_cmd.read_env_var", MagicMock(return_value=None)
    )
    return mocks


def _assert_no_real_agent_calls(no_real_agent: dict[str, MagicMock]) -> None:
    for name, mock in no_real_agent.items():
        mock.assert_not_called()
        assert not mock.called, name


class TestBackendDecoupling:
    def test_yes_path_runs_entirely_on_the_dummy_backend(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        dummy_backend: _DummyBackend,
        no_real_agent: dict[str, MagicMock],
    ) -> None:
        resolver = _patch_backend(monkeypatch, dummy_backend)
        deploy_mock = MagicMock(return_value={"TemplateID": "tmpl-dummy-1", "Status": "success"})
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", deploy_mock)
        monkeypatch.setattr(
            "easy_sandbox.cli.commands.template.resolve_acr_namespace",
            MagicMock(return_value="acr-ns"),
        )
        mock_sb = _make_sandbox()
        mock_create = AsyncMock(return_value=mock_sb)

        with (
            patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create),
            patch("easy_sandbox.utils.async_bridge.run_sync", side_effect=_run_coro),
        ):
            result = runner.invoke(cli, ["create", "-y", "dummy description"])

        assert result.exit_code == 0, result.output
        assert "AI generated template: ebx-nl-dummy-xyz" in result.output
        assert "sbx-dummy-001" in result.output

        resolver.assert_called_once_with()
        # --yes skips clarification entirely: neither research nor assess
        # must be called.
        assert dummy_backend.research_calls == []
        assert dummy_backend.assess_calls == []
        assert len(dummy_backend.generate_calls) == 1
        gen_call = dummy_backend.generate_calls[0]
        assert gen_call["description"] == "dummy description"
        assert gen_call["template_name"] == "ebx-nl-dummy-xyz"
        assert gen_call["resume_session"] is None
        assert gen_call["env"] == {"DUMMY_AGENT_KEY": "dummy-secret"}

        deploy_mock.assert_called_once_with(
            str(dummy_backend.workdir), acr_namespace="acr-ns", ctx=ANY, verbose=False
        )
        assert mock_create.call_args.kwargs["template"] == "tmpl-dummy-1"
        _assert_no_real_agent_calls(no_real_agent)

    def test_complete_assessment_reaches_the_confirmation_gate(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        dummy_backend: _DummyBackend,
        no_real_agent: dict[str, MagicMock],
    ) -> None:
        dummy_backend.assessment = ClarifyAssessment(completeness=0.95, question=None)
        monkeypatch.setattr("easy_sandbox.agent.clarify.new_session_id", lambda: "dummy-session-1")
        _patch_backend(monkeypatch, dummy_backend)
        deploy_mock = MagicMock()
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", deploy_mock)
        mock_create = AsyncMock()

        with patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create):
            result = runner.invoke(cli, ["create", "a complete dummy description"])

        # Non-interactive without --yes: generation ran, then the gate refused.
        assert result.exit_code == 1
        assert "Confirmation required to build and deploy" in result.output

        # Round 1 runs the research phase first, on the fresh session.
        assert len(dummy_backend.research_calls) == 1
        research_call = dummy_backend.research_calls[0]
        assert research_call["session_id"] == "dummy-session-1"
        assert research_call["env"] == {"DUMMY_AGENT_KEY": "dummy-secret"}

        # Research succeeded, so the assessment resumes that same session.
        assert len(dummy_backend.assess_calls) == 1
        first_round = dummy_backend.assess_calls[0]
        assert first_round["session_id"] is None
        assert first_round["resume"] == "dummy-session-1"
        assert first_round["env"] == {"DUMMY_AGENT_KEY": "dummy-secret"}

        # Generation resumed the very session the research created.
        assert len(dummy_backend.generate_calls) == 1
        assert dummy_backend.generate_calls[0]["resume_session"] == "dummy-session-1"

        deploy_mock.assert_not_called()
        mock_create.assert_not_called()
        _assert_no_real_agent_calls(no_real_agent)

    def test_failed_research_pins_the_session_for_assessment(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        dummy_backend: _DummyBackend,
        no_real_agent: dict[str, MagicMock],
    ) -> None:
        # Research fails: the assessment must still run, but pinned to the
        # session itself (session_id=) instead of resuming it (resume=).
        dummy_backend.research_ok = False
        dummy_backend.assessment = ClarifyAssessment(completeness=0.95, question=None)
        monkeypatch.setattr("easy_sandbox.agent.clarify.new_session_id", lambda: "dummy-session-1")
        _patch_backend(monkeypatch, dummy_backend)
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", MagicMock())
        mock_create = AsyncMock()

        with patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create):
            result = runner.invoke(cli, ["create", "a complete dummy description"])

        assert result.exit_code == 1
        assert "Confirmation required to build and deploy" in result.output
        # The research failure is a warning, never a gate.
        assert "could not research the public facts" in result.output

        assert len(dummy_backend.research_calls) == 1
        assert dummy_backend.research_calls[0]["session_id"] == "dummy-session-1"
        assert len(dummy_backend.assess_calls) == 1
        assert dummy_backend.assess_calls[0]["session_id"] == "dummy-session-1"
        assert dummy_backend.assess_calls[0]["resume"] is None

        mock_create.assert_not_called()
        _assert_no_real_agent_calls(no_real_agent)

    def test_research_outcome_reason_adds_a_backend_agnostic_hint(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        dummy_backend: _DummyBackend,
        no_real_agent: dict[str, MagicMock],
    ) -> None:
        """A classified ``ResearchOutcome`` becomes a hint on any backend."""
        dummy_backend.research_outcome = ResearchOutcome(
            ok=False,
            reason=RESEARCH_REASON_AGENT_UNAVAILABLE,
            detail="sanitised detail",
        )
        dummy_backend.assessment = ClarifyAssessment(completeness=0.95, question=None)
        monkeypatch.setattr("easy_sandbox.agent.clarify.new_session_id", lambda: "dummy-session-1")
        _patch_backend(monkeypatch, dummy_backend)
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", MagicMock())
        mock_create = AsyncMock()

        with patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create):
            result = runner.invoke(cli, ["create", "a complete dummy description"])

        assert result.exit_code == 1
        assert "could not research the public facts" in result.output
        assert "could not be started" in result.output  # reason-specific hint
        assert "sanitised detail" not in result.output  # detail is never rendered
        # The failed round hands the session to the assessment (pinned).
        assert len(dummy_backend.assess_calls) == 1
        assert dummy_backend.assess_calls[0]["session_id"] == "dummy-session-1"
        assert dummy_backend.assess_calls[0]["resume"] is None
        mock_create.assert_not_called()
        _assert_no_real_agent_calls(no_real_agent)

    def test_unavailable_assessment_degrades_and_names_the_backend(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        dummy_backend: _DummyBackend,
        no_real_agent: dict[str, MagicMock],
    ) -> None:
        dummy_backend.assessment = None  # backend cannot assess at all
        _patch_backend(monkeypatch, dummy_backend)
        monkeypatch.setattr("easy_sandbox.cli.commands.template.do_deploy", MagicMock())
        mock_create = AsyncMock()

        with patch("easy_sandbox.api.sandbox.Sandbox.create", mock_create):
            result = runner.invoke(cli, ["create", "a vague dummy description"])

        assert result.exit_code == 1
        assert (
            "Could not assess the description completeness with Dummy Agent "
            "(assessment unavailable); continuing straight to generation."
        ) in result.output
        # Research ran (round 1 always does); the assessment was unavailable.
        assert len(dummy_backend.research_calls) == 1
        assert len(dummy_backend.assess_calls) == 1
        # Degraded outcome carries no session: generation starts fresh.
        assert len(dummy_backend.generate_calls) == 1
        assert dummy_backend.generate_calls[0]["resume_session"] is None
        mock_create.assert_not_called()
        _assert_no_real_agent_calls(no_real_agent)

    def test_missing_binary_uses_the_backend_error_and_wording(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        no_real_agent: dict[str, MagicMock],
    ) -> None:
        backend = _DummyBackend(
            binary=None,
            workdir=tmp_path / "ws",
            template_name="ebx-nl-dummy-xyz",
        )
        _patch_backend(monkeypatch, backend)

        result = runner.invoke(cli, ["create", "dummy description"])

        assert result.exit_code == 1
        assert "Dummy Agent CLI was not found on PATH or in ~/.ebx/bin." in result.output
        assert "Dummy setup (not-installed); docs: https://example.test/dummy" in result.output
        assert "[E2905]" in result.output
        assert "Dummy Agent CLI is required for AI template generation" in result.output
        _assert_no_real_agent_calls(no_real_agent)

    def test_missing_credentials_use_the_backend_error_and_wording(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        dummy_backend: _DummyBackend,
        no_real_agent: dict[str, MagicMock],
    ) -> None:
        class _RejectingBackend(_DummyBackend):
            def resolve_credentials(self, **kwargs: Any) -> _DummyCredentials:
                raise _DummyCredentialError("no key")

        backend = _RejectingBackend(
            binary=dummy_backend.binary,
            workdir=dummy_backend.workdir,
            template_name=dummy_backend.template_name,
        )
        _patch_backend(monkeypatch, backend)

        result = runner.invoke(cli, ["create", "-y", "dummy description"])

        assert result.exit_code == 1
        assert "Dummy Agent is installed but no model credentials were found." in result.output
        assert "[E2906]" in result.output
        assert "ebx config set dummy_api_key <KEY>" in result.output
        _assert_no_real_agent_calls(no_real_agent)
