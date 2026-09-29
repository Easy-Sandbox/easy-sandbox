"""Unit tests for the pluggable coding-agent backend boundary.

These tests pin the seam that ``ebx create "<description>"`` uses
(:mod:`easy_sandbox.agent.coding_agent`): the resolver, the protocol
surface shipped by :class:`QwenCodeBackend`, and — most importantly — the
lazy delegation to the verified implementation modules
(:mod:`easy_sandbox.agent.qwen_code`, :mod:`easy_sandbox.agent.codegen`,
:mod:`easy_sandbox.agent.clarify`), so the existing patch points on those
modules keep intercepting every adapter call.

No test executes a real agent binary or touches the network.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from easy_sandbox.agent.clarify import ClarifyAssessment
from easy_sandbox.agent.codegen import CodegenResult
from easy_sandbox.agent.coding_agent import (
    DEFAULT_CODING_AGENT,
    CodingAgentCredentials,
    QwenCodeBackend,
    resolve_coding_agent_backend,
)
from easy_sandbox.agent.qwen_code import QwenCodeCredentials
from easy_sandbox.models.errors import (
    QwenCodeCredentialError,
    QwenCodeNotInstalledError,
    SandboxCreationError,
)

if TYPE_CHECKING:
    from pathlib import Path

_CREDS = QwenCodeCredentials(
    source="qwen-stored",
    api_key="sk-test",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    model="qwen3-coder-plus",
)

#: Every class variable the CLI reads off a backend.
_REQUIRED_CLASS_VARS = (
    "name",
    "display_name",
    "config_key",
    "env_var",
    "base_url_config_key",
    "model_config_key",
    "credential_prompt",
    "credential_error",
    "not_installed_error",
)

#: Every method the create pipeline drives.
_REQUIRED_METHODS = (
    "quick_setup_lines",
    "find_binary",
    "install",
    "resolve_credentials",
    "prepare_workdir",
    "assess",
    "generate",
)


class TestResolver:
    """``resolve_coding_agent_backend`` selection semantics."""

    def test_default_backend_is_qwen_code(self) -> None:
        backend = resolve_coding_agent_backend()
        assert DEFAULT_CODING_AGENT == "qwen-code"
        assert isinstance(backend, QwenCodeBackend)
        assert backend.name == "qwen-code"

    def test_explicit_name_selects_the_same_backend(self) -> None:
        assert isinstance(resolve_coding_agent_backend("qwen-code"), QwenCodeBackend)

    def test_each_resolution_returns_a_fresh_instance(self) -> None:
        assert resolve_coding_agent_backend() is not resolve_coding_agent_backend()

    def test_unknown_backend_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown coding agent backend 'qoder-cli'"):
            resolve_coding_agent_backend("qoder-cli")

    def test_unknown_backend_lists_the_available_names(self) -> None:
        with pytest.raises(ValueError, match="available: qwen-code"):
            resolve_coding_agent_backend("codex")


class TestProtocolSurface:
    """The shipped backend must satisfy the full boundary contract."""

    def test_backend_declares_the_full_protocol_surface(self) -> None:
        backend = QwenCodeBackend()
        for attr in _REQUIRED_CLASS_VARS:
            assert hasattr(backend, attr), attr
        for method in _REQUIRED_METHODS:
            assert callable(getattr(backend, method)), method

    def test_declared_error_types_are_creation_errors(self) -> None:
        assert QwenCodeBackend.not_installed_error is QwenCodeNotInstalledError
        assert QwenCodeBackend.credential_error is QwenCodeCredentialError
        assert issubclass(QwenCodeNotInstalledError, SandboxCreationError)
        assert issubclass(QwenCodeCredentialError, SandboxCreationError)

    def test_qwen_credentials_satisfy_the_credential_contract(self) -> None:
        env = _CREDS.as_env()
        assert isinstance(env, dict)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
        contract: CodingAgentCredentials = _CREDS
        assert contract.as_env() == env


class TestQuickSetupWording:
    """The Quick Setup lines are user-facing copy — pin them byte for byte."""

    def test_not_installed_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.official_install_command",
            MagicMock(return_value="curl -fsSL https://example.test/install.sh | bash"),
        )
        lines = QwenCodeBackend().quick_setup_lines(reason="not-installed")
        assert lines == [
            "Quick Setup - AI template generation (Qwen Code):",
            "  1. Install the Qwen Code CLI (official standalone build):",
            "       curl -fsSL https://example.test/install.sh | bash",
            "     or re-run 'ebx create \"<description>\"' and accept the install prompt",
            "     or bypass AI generation with:  ebx create --template base",
            "  2. Docs: https://github.com/QwenLM/qwen-code",
        ]

    def test_no_credentials_lines(self) -> None:
        lines = QwenCodeBackend().quick_setup_lines(reason="no-credentials")
        assert lines == [
            "Quick Setup - AI template generation (Qwen Code):",
            "  1. Configure a DashScope/ModelStudio API key for Qwen Code:",
            "       ebx config set qwen_code_api_key <KEY>   (stored in ~/.ebx/.env)",
            "       or run the guided wizard:  ebx config init",
            "       (exported OPENAI_API_KEY / DASHSCOPE_API_KEY also work)",
            "  2. Docs: https://github.com/QwenLM/qwen-code",
        ]


class TestDelegation:
    """Every adapter method must reach its source module lazily.

    The patches target ``easy_sandbox.agent.qwen_code`` /
    ``easy_sandbox.agent.codegen`` / ``easy_sandbox.agent.clarify``
    directly — exactly what the CLI test suites do — so these tests also
    pin the lazy-import contract that keeps those patch points alive.
    """

    def test_importing_the_adapter_stays_import_light(self) -> None:
        """Importing the boundary must not pull in any implementation module."""
        code = (
            "import sys\n"
            "import easy_sandbox.agent.coding_agent\n"
            "for name in ('easy_sandbox.agent.qwen_code',\n"
            "             'easy_sandbox.agent.codegen',\n"
            "             'easy_sandbox.agent.clarify'):\n"
            "    assert name not in sys.modules, name\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)

    def test_find_binary_delegates(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        binary = tmp_path / "qwen"
        mock = MagicMock(return_value=binary)
        monkeypatch.setattr("easy_sandbox.agent.qwen_code.find_qwen_code_binary", mock)
        assert QwenCodeBackend().find_binary() == binary
        mock.assert_called_once_with()

    def test_find_binary_returns_none_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "easy_sandbox.agent.qwen_code.find_qwen_code_binary", MagicMock(return_value=None)
        )
        assert QwenCodeBackend().find_binary() is None

    def test_install_forwards_the_progress_callback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        installed = tmp_path / "bin" / "qwen"
        mock = MagicMock(return_value=installed)
        monkeypatch.setattr("easy_sandbox.agent.qwen_code.download_and_install_standalone", mock)
        progress = MagicMock()
        assert QwenCodeBackend().install(on_progress=progress) == installed
        mock.assert_called_once_with(on_progress=progress)

    def test_install_defaults_progress_to_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        mock = MagicMock(return_value=tmp_path / "qwen")
        monkeypatch.setattr("easy_sandbox.agent.qwen_code.download_and_install_standalone", mock)
        QwenCodeBackend().install()
        mock.assert_called_once_with(on_progress=None)

    def test_resolve_credentials_forwards_every_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock = MagicMock(return_value=_CREDS)
        monkeypatch.setattr("easy_sandbox.agent.qwen_code.resolve_qwen_code_credentials", mock)
        result = QwenCodeBackend().resolve_credentials(
            stored_api_key="stored",
            llm_api_key="llm",
            stored_base_url="https://example.test/v1",
            stored_model="qwen-test",
        )
        assert result is _CREDS
        mock.assert_called_once_with(
            stored_api_key="stored",
            llm_api_key="llm",
            stored_base_url="https://example.test/v1",
            stored_model="qwen-test",
        )

    def test_prepare_workdir_delegates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        expected = (tmp_path / "ws", "ebx-nl-test-abc")
        mock = MagicMock(return_value=expected)
        monkeypatch.setattr("easy_sandbox.agent.codegen.prepare_workdir", mock)
        assert QwenCodeBackend().prepare_workdir("a python env") == expected
        mock.assert_called_once_with("a python env")

    def test_assess_first_round_creates_the_session(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assessment = ClarifyAssessment(completeness=0.3, question="Which ports?")
        mock = MagicMock(return_value=assessment)
        monkeypatch.setattr("easy_sandbox.agent.clarify.evaluate", mock)
        env = {"OPENAI_API_KEY": "sk-test"}
        binary = tmp_path / "qwen"

        result = QwenCodeBackend().assess(
            "assess me",
            workdir=tmp_path,
            binary=binary,
            env=env,
            session_id="sess-1",
        )

        assert result is assessment
        mock.assert_called_once_with(
            "assess me",
            binary=binary,
            env=env,
            cwd=tmp_path,
            session_id="sess-1",
            resume=None,
        )

    def test_assess_followup_resumes_the_session(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        mock = MagicMock(return_value=None)
        monkeypatch.setattr("easy_sandbox.agent.clarify.evaluate", mock)

        result = QwenCodeBackend().assess(
            "answer",
            workdir=tmp_path,
            binary="qwen",
            env=None,
            resume="sess-1",
        )

        assert result is None
        kwargs = mock.call_args.kwargs
        assert kwargs["resume"] == "sess-1"
        assert kwargs["session_id"] is None

    def test_generate_forwards_every_argument(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        gen = CodegenResult(
            workdir=tmp_path,
            template_name="ebx-nl-test-abc",
            dockerfile=tmp_path / "Dockerfile",
            template_yaml=tmp_path / "template.yaml",
            description="a python env",
            raw_output="ok",
        )
        mock = MagicMock(return_value=gen)
        monkeypatch.setattr("easy_sandbox.agent.codegen.generate_template_files", mock)
        progress = MagicMock()
        env = {"OPENAI_API_KEY": "sk-test"}

        result = QwenCodeBackend().generate(
            "a python env",
            workdir=tmp_path,
            template_name="ebx-nl-test-abc",
            resume_session="sess-1",
            binary=tmp_path / "qwen",
            env=env,
            on_progress=progress,
        )

        assert result is gen
        mock.assert_called_once_with(
            "a python env",
            workdir=tmp_path,
            template_name="ebx-nl-test-abc",
            resume_session="sess-1",
            binary=tmp_path / "qwen",
            env=env,
            on_progress=progress,
        )
