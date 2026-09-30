"""Tests for the top-level ``ebx deploy`` command.

``ebx deploy`` is the fixed *publish* step of the template lifecycle
(docker build → push → register) and delegates to ``template build``.  It
takes no description and no LLM: what a template is lives in
``template.yaml``, authored earlier by ``ebx template init``.  The pipeline
itself is covered by the ``template`` tests, so here ``build`` is replaced by
a recorder that keeps its real option set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner

from easy_sandbox.cli.commands import deploy as deploy_mod
from easy_sandbox.cli.commands.template import build as real_build
from easy_sandbox.cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A template directory that already has a Dockerfile."""
    (tmp_path / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def build_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``template build`` by a recorder; ACR namespace resolves offline."""
    calls: list[dict[str, Any]] = []

    def _record(**kwargs: Any) -> None:
        calls.append(kwargs)

    stub = click.Command("build", params=list(real_build.params), callback=_record)
    monkeypatch.setattr(deploy_mod, "build", stub)
    monkeypatch.setattr(deploy_mod, "resolve_acr_namespace", MagicMock(return_value="test-ns"))
    return calls


class TestFixedPipeline:
    """No LLM, no key, no agent: just the deterministic pipeline."""

    def test_delegates_to_build_with_project_dir(
        self, runner: CliRunner, project: Path, build_calls: list[dict[str, Any]]
    ) -> None:
        result = runner.invoke(cli, ["deploy", str(project), "--acr-namespace", "ns", "-y"])

        assert result.exit_code == 0, result.output
        assert len(build_calls) == 1
        assert build_calls[0]["template_dir"] == str(project.resolve())
        assert build_calls[0]["acr_namespace"] == "ns"
        assert build_calls[0]["yes"] is True

    def test_path_defaults_to_current_directory(
        self,
        runner: CliRunner,
        project: Path,
        build_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(project)

        result = runner.invoke(cli, ["deploy"])

        assert result.exit_code == 0, result.output
        assert build_calls[0]["template_dir"] == str(project.resolve())

    def test_never_touches_the_coding_agent_or_llm_keys(
        self,
        runner: CliRunner,
        project: Path,
        build_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Publishing must not resolve, install or call any coding agent."""
        boom = MagicMock(side_effect=AssertionError("agent must not be resolved"))
        for name in (
            "resolve_coding_agent_backend",
            "ensure_coding_agent_binary",
            "resolve_coding_agent_credentials",
        ):
            monkeypatch.setattr(f"easy_sandbox.cli.commands._coding_agent.{name}", boom)
        monkeypatch.setattr("easy_sandbox.api.sandbox.Sandbox.deploy", boom)
        for var in ("EBX_LLM_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        result = runner.invoke(cli, ["deploy", str(project)])

        assert result.exit_code == 0, result.output
        boom.assert_not_called()
        assert len(build_calls) == 1

    @pytest.mark.parametrize("flag", ["-v", "--verbose"])
    def test_verbose_is_accepted(
        self, runner: CliRunner, project: Path, build_calls: list[dict[str, Any]], flag: str
    ) -> None:
        """Regression: ``ebx deploy --verbose`` used to fail with 'No such option'."""
        result = runner.invoke(cli, ["deploy", str(project), flag])

        assert result.exit_code == 0, result.output
        assert "No such option" not in result.output
        assert build_calls[0]["verbose_flag"] is True

    def test_shares_every_template_build_option(self) -> None:
        deploy_opts = {o for p in deploy_mod.deploy_shortcut.params for o in getattr(p, "opts", [])}
        for param in real_build.params:
            if isinstance(param, click.Option):
                assert set(param.opts) <= deploy_opts, param.name

    def test_help_has_no_ai_options_and_points_at_template_init(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["deploy", "--help"])

        assert result.exit_code == 0, result.output
        assert "--verbose" in result.output
        assert "--acr-namespace" in result.output
        assert "ebx template init" in result.output
        for gone in ("--agent", "--instruction", "--max-wall-time", "--max-session-turns"):
            assert gone not in result.output
        assert "--traditional" not in result.output  # deprecated, hidden

    def test_a_description_is_not_accepted(
        self, runner: CliRunner, project: Path, build_calls: list[dict[str, Any]]
    ) -> None:
        """Descriptions belong to template authoring, not to publishing."""
        result = runner.invoke(cli, ["deploy", str(project), "deploy on port 8080"])

        assert result.exit_code == 2
        assert "unexpected extra argument" in result.output.lower()
        assert build_calls == []

    @pytest.mark.parametrize("flag", ["--agent", "--instruction", "-i"])
    def test_ai_options_are_gone(
        self, runner: CliRunner, project: Path, build_calls: list[dict[str, Any]], flag: str
    ) -> None:
        args = ["deploy", str(project), flag] + ([] if flag == "--agent" else ["x"])

        result = runner.invoke(cli, args)

        assert result.exit_code == 2
        assert "No such option" in result.output
        assert build_calls == []

    def test_nonexistent_path_is_rejected(
        self, runner: CliRunner, build_calls: list[dict[str, Any]]
    ) -> None:
        result = runner.invoke(cli, ["deploy", "/nonexistent/path/xyz"])

        assert result.exit_code != 0
        assert "not an existing directory" in result.output
        assert build_calls == []

    def test_missing_dockerfile_points_at_template_init(
        self, runner: CliRunner, tmp_path: Path, build_calls: list[dict[str, Any]]
    ) -> None:
        result = runner.invoke(cli, ["deploy", str(tmp_path)])

        assert result.exit_code != 0
        assert "No Dockerfile found" in result.output
        assert "ebx template init" in result.output
        assert build_calls == []

    def test_explicit_dockerfile_option_skips_the_check(
        self, runner: CliRunner, tmp_path: Path, build_calls: list[dict[str, Any]]
    ) -> None:
        custom = tmp_path / "Dockerfile.prod"
        custom.write_text("FROM python:3.11-slim\n", encoding="utf-8")

        result = runner.invoke(cli, ["deploy", str(tmp_path), "--dockerfile", str(custom)])

        assert result.exit_code == 0, result.output
        assert len(build_calls) == 1

    def test_acr_namespace_failure_happens_before_the_build(
        self,
        runner: CliRunner,
        project: Path,
        build_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fail fast: no build when the ACR namespace is unknown."""
        monkeypatch.setattr(
            deploy_mod,
            "resolve_acr_namespace",
            MagicMock(side_effect=click.UsageError("ACR namespace is required")),
        )

        result = runner.invoke(cli, ["deploy", str(project)])

        assert result.exit_code != 0
        assert "ACR namespace is required" in result.output
        assert build_calls == []

    def test_traditional_flag_is_deprecated_but_harmless(
        self, runner: CliRunner, project: Path, build_calls: list[dict[str, Any]]
    ) -> None:
        result = runner.invoke(cli, ["deploy", str(project), "--traditional"])

        assert result.exit_code == 0, result.output
        assert "--traditional is deprecated" in result.output
        assert len(build_calls) == 1
