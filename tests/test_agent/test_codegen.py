"""Unit tests for the AI code-generation orchestrator.

No test performs real network access or executes the real Qwen Code CLI:
every headless run is replaced by a fake that writes files into the
requested workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from easy_sandbox.agent import codegen
from easy_sandbox.agent.codegen import (
    DEFAULT_CODEGEN_TIMEOUT,
    TEMPLATE_NAME_PREFIX,
    build_codegen_prompt,
    default_codegen_timeout,
    generate_template_files,
    make_template_name,
    prepare_workdir,
)
from easy_sandbox.agent.qwen_code import QwenCodeRunResult
from easy_sandbox.models.errors import AICodegenError

VALID_TEMPLATE_YAML = """\
name: whatever-the-model-wrote
description: 一个用于数据分析的 Python 环境
resources:
  cpu: 2
  memory: 4096
"""

DOCKERFILE = "FROM python:3.12-slim\nRUN pip install pandas\n"


def _fake_run_writing(
    dockerfile: str | None = DOCKERFILE,
    template_yaml: str | None = VALID_TEMPLATE_YAML,
    *,
    result: QwenCodeRunResult | None = None,
) -> Any:
    """Return a fake ``run_qwen_code_headless`` that writes the given files."""

    def _fake(prompt: str, **kwargs: Any) -> QwenCodeRunResult:
        cwd = Path(kwargs["cwd"])
        if dockerfile is not None:
            (cwd / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        if template_yaml is not None:
            (cwd / "template.yaml").write_text(template_yaml, encoding="utf-8")
        if result is not None:
            return result
        return QwenCodeRunResult(text="done", is_error=False, exit_code=0)

    return _fake


# ---------------------------------------------------------------------------
# Template naming
# ---------------------------------------------------------------------------


class TestTemplateName:
    def test_ascii_slug_with_injected_token(self) -> None:
        name = make_template_name("Run a Python data analysis job", token="abc123")
        assert name == f"{TEMPLATE_NAME_PREFIX}-run-a-python-dat-abc123"

    def test_non_ascii_description_falls_back(self) -> None:
        name = make_template_name("运行数据分析", token="abc123")
        assert name == f"{TEMPLATE_NAME_PREFIX}-sandbox-abc123"

    def test_ascii_words_inside_non_ascii_description_survive(self) -> None:
        name = make_template_name("运行 Python 数据分析", token="abc123")
        assert name == f"{TEMPLATE_NAME_PREFIX}-python-abc123"

    def test_token_is_random_hex_when_omitted(self) -> None:
        first = make_template_name("node service")
        second = make_template_name("node service")
        assert first != second
        assert len(first.rsplit("-", 1)[-1]) == 6


class TestPrompt:
    def test_prompt_mentions_description_and_template_name(self) -> None:
        prompt = build_codegen_prompt("用 playwright 截图", "ebx-nl-sandbox-abc123")
        assert "用 playwright 截图" in prompt
        assert "ebx-nl-sandbox-abc123" in prompt
        assert "Dockerfile" in prompt
        assert "template.yaml" in prompt

    def test_prompt_has_no_replayed_transcript(self) -> None:
        """Generation resumes the native session; no Q/A section is embedded."""
        prompt = build_codegen_prompt("用 playwright 截图", "ebx-nl-sandbox-abc123")
        assert "澄清" not in prompt
        assert "用户需求：用 playwright 截图\n\n必须创建的文件：" in prompt


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


class TestGenerateTemplateFiles:
    def test_success_writes_validated_workspace(self, tmp_path: Path) -> None:
        with patch(
            "easy_sandbox.agent.codegen.run_qwen_code_headless",
            _fake_run_writing(),
        ):
            result = generate_template_files("运行 Python 数据分析", base_dir=tmp_path)

        assert result.workdir.is_dir()
        assert result.workdir.parent == tmp_path
        assert result.dockerfile.is_file()
        assert result.template_yaml.is_file()
        assert result.raw_output == "done"

        # The generated name replaces the model-provided one.
        data = yaml.safe_load(result.template_yaml.read_text(encoding="utf-8"))
        assert data["name"] == result.template_name
        assert data["resources"] == {"cpu": 2, "memory": 4096}
        assert data["description"] == "一个用于数据分析的 Python 环境"

    def test_passes_bounded_options_and_progress(self, tmp_path: Path) -> None:
        captured: dict[str, Any] = {}
        progress: list[str] = []

        def _fake(prompt: str, **kwargs: Any) -> QwenCodeRunResult:
            captured.update(kwargs)
            captured["prompt"] = prompt
            cwd = Path(kwargs["cwd"])
            (cwd / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
            (cwd / "template.yaml").write_text(VALID_TEMPLATE_YAML, encoding="utf-8")
            return QwenCodeRunResult(text="ok", exit_code=0)

        with patch("easy_sandbox.agent.codegen.run_qwen_code_headless", _fake):
            result = generate_template_files(
                "node service",
                binary=Path("/opt/qwen"),
                env={"OPENAI_API_KEY": "sk-test"},
                timeout=42.0,
                base_dir=tmp_path,
                on_progress=progress.append,
            )

        assert captured["binary"] == Path("/opt/qwen")
        assert captured["env"] == {"OPENAI_API_KEY": "sk-test"}
        assert captured["timeout"] == 42.0
        assert captured["cwd"] == result.workdir
        assert result.template_name in captured["prompt"]
        assert any("Generating template" in msg for msg in progress)

    def test_resume_session_reaches_the_generation_run(self, tmp_path: Path) -> None:
        """The clarification session is continued via ``--resume``, not replayed."""
        captured: dict[str, Any] = {}

        def _fake(prompt: str, **kwargs: Any) -> QwenCodeRunResult:
            captured.update(kwargs)
            cwd = Path(kwargs["cwd"])
            (cwd / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
            (cwd / "template.yaml").write_text(VALID_TEMPLATE_YAML, encoding="utf-8")
            return QwenCodeRunResult(text="ok", exit_code=0)

        session = "3f5c1c9e-2f6a-4a5b-9d1e-0a1b2c3d4e5f"
        with patch("easy_sandbox.agent.codegen.run_qwen_code_headless", _fake):
            generate_template_files("运行 python", resume_session=session, base_dir=tmp_path)

        assert captured["resume"] == session

    def test_resume_defaults_to_none(self, tmp_path: Path) -> None:
        captured: dict[str, Any] = {}

        def _fake(prompt: str, **kwargs: Any) -> QwenCodeRunResult:
            captured.update(kwargs)
            captured["prompt"] = prompt
            cwd = Path(kwargs["cwd"])
            (cwd / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
            (cwd / "template.yaml").write_text(VALID_TEMPLATE_YAML, encoding="utf-8")
            return QwenCodeRunResult(text="ok", exit_code=0)

        with patch("easy_sandbox.agent.codegen.run_qwen_code_headless", _fake):
            generate_template_files("node service", base_dir=tmp_path)

        assert captured["resume"] is None
        assert "澄清" not in captured["prompt"]

    def test_missing_files_raise_and_keep_workspace(self, tmp_path: Path) -> None:
        with (
            patch(
                "easy_sandbox.agent.codegen.run_qwen_code_headless",
                _fake_run_writing(dockerfile=None, template_yaml=None),
            ),
            pytest.raises(AICodegenError, match="Dockerfile, template.yaml"),
        ):
            generate_template_files("empty run", base_dir=tmp_path)

        # The workspace is kept for inspection.
        workspaces = list(tmp_path.iterdir())
        assert len(workspaces) == 1
        assert workspaces[0].is_dir()

    def test_dockerfile_without_from_raises(self, tmp_path: Path) -> None:
        with (
            patch(
                "easy_sandbox.agent.codegen.run_qwen_code_headless",
                _fake_run_writing(dockerfile="# just a comment\n"),
            ),
            pytest.raises(AICodegenError, match="no FROM instruction"),
        ):
            generate_template_files("bad dockerfile", base_dir=tmp_path)

    def test_invalid_yaml_syntax_raises(self, tmp_path: Path) -> None:
        with (
            patch(
                "easy_sandbox.agent.codegen.run_qwen_code_headless",
                _fake_run_writing(template_yaml="name: [unclosed\n"),
            ),
            pytest.raises(AICodegenError, match="could not be parsed"),
        ):
            generate_template_files("bad yaml", base_dir=tmp_path)

    def test_yaml_failing_schema_raises(self, tmp_path: Path) -> None:
        bad = "name: x\ncapabilities: [not-a-real-capability]\n"
        with (
            patch(
                "easy_sandbox.agent.codegen.run_qwen_code_headless",
                _fake_run_writing(template_yaml=bad),
            ),
            pytest.raises(AICodegenError, match="schema validation"),
        ):
            generate_template_files("bad schema", base_dir=tmp_path)

    def test_yaml_not_a_mapping_raises(self, tmp_path: Path) -> None:
        with (
            patch(
                "easy_sandbox.agent.codegen.run_qwen_code_headless",
                _fake_run_writing(template_yaml="- a\n- b\n"),
            ),
            pytest.raises(AICodegenError, match="not a YAML mapping"),
        ):
            generate_template_files("list yaml", base_dir=tmp_path)

    def test_empty_description_rejected_before_running(self, tmp_path: Path) -> None:
        with patch("easy_sandbox.agent.codegen.run_qwen_code_headless") as mock_run:
            with pytest.raises(AICodegenError, match="empty description"):
                generate_template_files("   ", base_dir=tmp_path)
            mock_run.assert_not_called()

    def test_failure_details_include_exit_code_and_stderr(self, tmp_path: Path) -> None:
        result = QwenCodeRunResult(
            text="",
            is_error=True,
            exit_code=55,
            raw_stderr="budget exceeded\n",
        )
        with (
            patch(
                "easy_sandbox.agent.codegen.run_qwen_code_headless",
                _fake_run_writing(dockerfile=None, template_yaml=None, result=result),
            ),
            pytest.raises(AICodegenError, match="exit_code=55"),
        ):
            generate_template_files("budget", base_dir=tmp_path)


class TestPrepareWorkdir:
    def test_creates_the_workspace_under_base_dir(self, tmp_path: Path) -> None:
        workdir, name = prepare_workdir("运行 Python 数据分析", base_dir=tmp_path)
        assert workdir.is_dir()
        assert workdir.parent == tmp_path
        assert name.startswith(f"{TEMPLATE_NAME_PREFIX}-")
        assert workdir.name.endswith(name[-6:])

    def test_generate_reuses_a_prepared_workspace(self, tmp_path: Path) -> None:
        """Clarification and generation must share one cwd (Qwen sessions are per-cwd)."""
        workdir, name = prepare_workdir("node service", base_dir=tmp_path)
        with patch(
            "easy_sandbox.agent.codegen.run_qwen_code_headless",
            _fake_run_writing(),
        ):
            result = generate_template_files("node service", workdir=workdir, template_name=name)
        assert result.workdir == workdir
        assert result.template_name == name


class TestDefaults:
    def test_timeout_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EBX_QWEN_CODEGEN_TIMEOUT", raising=False)
        assert default_codegen_timeout() == DEFAULT_CODEGEN_TIMEOUT

    def test_timeout_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EBX_QWEN_CODEGEN_TIMEOUT", "120")
        assert default_codegen_timeout() == 120.0

    def test_invalid_timeout_env_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EBX_QWEN_CODEGEN_TIMEOUT", "not-a-number")
        assert default_codegen_timeout() == DEFAULT_CODEGEN_TIMEOUT
        monkeypatch.setenv("EBX_QWEN_CODEGEN_TIMEOUT", "-5")
        assert default_codegen_timeout() == DEFAULT_CODEGEN_TIMEOUT

    def test_generated_dir_default(self) -> None:
        assert codegen.default_generated_dir() == Path.home() / ".ebx" / "generated"
