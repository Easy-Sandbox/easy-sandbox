"""Tests for the DeployModule and DeployResult."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.api.deploy import (
    DeployModule,
    DeployResult,
    _build_prompt,
    _extract_json_from_output,
    _exit_code_to_status,
    _parse_wall_time,
    resolve_llm_env,
)
from easy_sandbox.models.errors import (
    DeployAgentError,
    DeployLLMKeyMissingError,
)
from easy_sandbox.models.process import ProcessResult


# ---------------------------------------------------------------------------
# DeployResult tests
# ---------------------------------------------------------------------------


class TestDeployResult:
    """Test DeployResult dataclass."""

    def test_default_values(self) -> None:
        r = DeployResult()
        assert r.status == "unknown"
        assert r.url == ""
        assert r.port == 0
        assert r.logs == ""
        assert r.raw_output == ""
        assert r.exit_code == -1
        assert r.sandbox_id == ""
        assert r.success is False

    def test_success_property(self) -> None:
        r = DeployResult(status="success")
        assert r.success is True

        r2 = DeployResult(status="failed")
        assert r2.success is False

    def test_custom_values(self) -> None:
        r = DeployResult(
            status="success",
            url="http://localhost:8080",
            port=8080,
            logs="deployed",
            raw_output="...",
            exit_code=0,
            sandbox_id="sbx-123",
        )
        assert r.port == 8080
        assert r.sandbox_id == "sbx-123"


# ---------------------------------------------------------------------------
# Exit code mapping tests
# ---------------------------------------------------------------------------


class TestExitCodeMapping:
    """Test qwen-code exit code to status mapping."""

    def test_success(self) -> None:
        assert _exit_code_to_status(0) == "success"

    def test_turn_limit(self) -> None:
        assert _exit_code_to_status(53) == "turn_limit_exceeded"

    def test_budget_exceeded(self) -> None:
        assert _exit_code_to_status(55) == "budget_exceeded"

    def test_interrupted(self) -> None:
        assert _exit_code_to_status(130) == "interrupted"

    def test_unknown_code(self) -> None:
        assert _exit_code_to_status(1) == "failed"
        assert _exit_code_to_status(99) == "failed"


# ---------------------------------------------------------------------------
# Wall time parsing tests
# ---------------------------------------------------------------------------


class TestParseWallTime:
    """Test wall-time string parsing."""

    def test_minutes(self) -> None:
        assert _parse_wall_time("10m") == 600
        assert _parse_wall_time("5m") == 300

    def test_seconds(self) -> None:
        assert _parse_wall_time("300s") == 300

    def test_hours(self) -> None:
        assert _parse_wall_time("1h") == 3600

    def test_bare_number(self) -> None:
        assert _parse_wall_time("60") == 60

    def test_whitespace(self) -> None:
        assert _parse_wall_time("  10m  ") == 600


# ---------------------------------------------------------------------------
# LLM env resolution tests
# ---------------------------------------------------------------------------


class TestResolveLlmEnv:
    """Test LLM credential resolution."""

    def test_explicit_key(self) -> None:
        env = resolve_llm_env(llm_api_key="sk-test-123")
        assert env["DASHSCOPE_API_KEY"] == "sk-test-123"
        assert "OPENAI_BASE_URL" in env
        assert "OPENAI_MODEL" in env

    def test_env_var_bailian(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BAILIAN_CODING_PLAN_API_KEY", "bailian-key")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        env = resolve_llm_env()
        assert env["DASHSCOPE_API_KEY"] == "bailian-key"

    def test_env_var_dashscope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BAILIAN_CODING_PLAN_API_KEY", raising=False)
        monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        env = resolve_llm_env()
        assert env["DASHSCOPE_API_KEY"] == "dash-key"

    def test_env_var_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BAILIAN_CODING_PLAN_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        env = resolve_llm_env()
        assert env["DASHSCOPE_API_KEY"] == "openai-key"

    def test_no_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BAILIAN_CODING_PLAN_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(DeployLLMKeyMissingError, match="No LLM API key"):
            resolve_llm_env()

    def test_custom_base_url_and_model(self) -> None:
        env = resolve_llm_env(
            llm_api_key="key",
            openai_base_url="http://localhost:11434/v1",
            openai_model="llama3",
        )
        assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
        assert env["OPENAI_MODEL"] == "llama3"


# ---------------------------------------------------------------------------
# Prompt construction tests
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Test prompt construction."""

    def test_contains_instruction(self) -> None:
        prompt = _build_prompt("部署这个 FastAPI 项目")
        assert "部署这个 FastAPI 项目" in prompt
        assert "/workspace" in prompt
        assert "status" in prompt

    def test_json_format_mentioned(self) -> None:
        prompt = _build_prompt("deploy")
        assert "JSON" in prompt


# ---------------------------------------------------------------------------
# JSON extraction tests
# ---------------------------------------------------------------------------


class TestExtractJson:
    """Test JSON extraction from qwen-code output."""

    def test_valid_json_last_line(self) -> None:
        output = 'Some logs\nMore logs\n{"status": "success", "url": "http://localhost:8080", "port": 8080, "logs": "ok"}'
        result = _extract_json_from_output(output)
        assert result is not None
        assert result["status"] == "success"
        assert result["port"] == 8080

    def test_no_json(self) -> None:
        output = "Just some logs\nNo JSON here"
        assert _extract_json_from_output(output) is None

    def test_json_without_status_key(self) -> None:
        output = '{"foo": "bar"}'
        assert _extract_json_from_output(output) is None

    def test_json_in_middle(self) -> None:
        output = 'Before\n{"status": "success", "port": 3000}\nAfter'
        result = _extract_json_from_output(output)
        assert result is not None
        assert result["status"] == "success"

    def test_empty_output(self) -> None:
        assert _extract_json_from_output("") is None
        assert _extract_json_from_output("   ") is None


# ---------------------------------------------------------------------------
# DeployModule tests (mocked sandbox)
# ---------------------------------------------------------------------------


class TestDeployModule:
    """Test DeployModule with mocked sandbox."""

    @pytest.fixture
    def mock_sandbox(self) -> MagicMock:
        """Create a mock Sandbox for testing."""
        sandbox = MagicMock()
        sandbox.id = "sbx-deploy-test"
        sandbox.commands = MagicMock()
        sandbox.files = MagicMock()
        return sandbox

    @pytest.fixture
    def deployer(self, mock_sandbox: MagicMock) -> DeployModule:
        return DeployModule(mock_sandbox)

    @pytest.mark.asyncio
    async def test_deploy_success(self, deployer: DeployModule, mock_sandbox: MagicMock) -> None:
        """Test successful deployment with JSON output."""
        json_output = json.dumps({
            "status": "success",
            "url": "http://localhost:8080",
            "port": 8080,
            "logs": "Deployed successfully",
        })
        mock_sandbox.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout=f"Installing deps...\n{json_output}",
                stderr="",
                exit_code=0,
            )
        )
        mock_sandbox.files.write = AsyncMock()

        # Create a temp project dir
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a marker file
            Path(tmpdir, "requirements.txt").write_text("flask\n")
            Path(tmpdir, "app.py").write_text("print('hello')\n")

            result = await deployer.deploy_project(
                tmpdir, "部署这个 Flask 项目"
            )

        assert result.status == "success"
        assert result.port == 8080
        assert result.url == "http://localhost:8080"
        assert result.sandbox_id == "sbx-deploy-test"

    @pytest.mark.asyncio
    async def test_deploy_agent_failure(self, deployer: DeployModule, mock_sandbox: MagicMock) -> None:
        """Test deployment with non-zero exit code."""
        mock_sandbox.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="Error: something went wrong",
                stderr="fatal error",
                exit_code=1,
            )
        )
        mock_sandbox.files.write = AsyncMock()

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "app.py").write_text("print('hello')\n")

            result = await deployer.deploy_project(tmpdir, "deploy")

        assert result.status == "failed"
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_deploy_turn_limit(self, deployer: DeployModule, mock_sandbox: MagicMock) -> None:
        """Test deployment with turn limit exceeded (exit code 53)."""
        mock_sandbox.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="...",
                stderr="",
                exit_code=53,
            )
        )
        mock_sandbox.files.write = AsyncMock()

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "app.py").write_text("print('hello')\n")
            result = await deployer.deploy_project(tmpdir, "deploy")

        assert result.status == "turn_limit_exceeded"

    @pytest.mark.asyncio
    async def test_deploy_nonexistent_path(self, deployer: DeployModule) -> None:
        """Test with non-existent project path."""
        with pytest.raises(DeployAgentError, match="does not exist"):
            await deployer.deploy_project("/nonexistent/path", "deploy")

    @pytest.mark.asyncio
    async def test_deploy_file_instead_of_dir(self, deployer: DeployModule) -> None:
        """Test with a file instead of directory."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py") as tmp:
            with pytest.raises(DeployAgentError, match="not a directory"):
                await deployer.deploy_project(tmp.name, "deploy")

    @pytest.mark.asyncio
    async def test_deploy_skips_git_and_venv(self, deployer: DeployModule, mock_sandbox: MagicMock) -> None:
        """Test that .git, __pycache__, node_modules are skipped."""
        mock_sandbox.commands.run = AsyncMock(
            return_value=ProcessResult(stdout="ok", stderr="", exit_code=0)
        )
        mock_sandbox.files.write = AsyncMock()

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files in skip dirs
            (Path(tmpdir) / ".git").mkdir()
            (Path(tmpdir) / ".git" / "config").write_text("git config")
            (Path(tmpdir) / "node_modules").mkdir()
            (Path(tmpdir) / "node_modules" / "pkg.json").write_text("{}")
            (Path(tmpdir) / "app.py").write_text("print('hello')")

            await deployer.deploy_project(tmpdir, "deploy")

        # Only app.py should be uploaded, not .git or node_modules files
        write_calls = mock_sandbox.files.write.call_args_list
        uploaded_paths = [call.args[0] for call in write_calls]
        assert any("app.py" in p for p in uploaded_paths)
        assert not any(".git" in p for p in uploaded_paths)
        assert not any("node_modules" in p for p in uploaded_paths)

    @pytest.mark.asyncio
    async def test_progress_callback(self, deployer: DeployModule, mock_sandbox: MagicMock) -> None:
        """Test that progress callback is called."""
        mock_sandbox.commands.run = AsyncMock(
            return_value=ProcessResult(stdout="ok", stderr="", exit_code=0)
        )
        mock_sandbox.files.write = AsyncMock()
        progress_msgs: list[str] = []

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "app.py").write_text("print('hello')")
            await deployer.deploy_project(
                tmpdir, "deploy", on_progress=progress_msgs.append
            )

        assert len(progress_msgs) >= 3  # upload, start, parse, finish
        assert any("Uploading" in m for m in progress_msgs)
        assert any("qwen-code" in m for m in progress_msgs)

    def test_build_qwen_command(self) -> None:
        """Test that the qwen command is built correctly."""
        cmd = DeployModule._build_qwen_command(prompt="deploy this", max_tool_calls=50)
        assert "qwen" in cmd
        assert "--yolo" in cmd
        assert "--output-format json" in cmd
        assert "--max-turns 50" in cmd
        assert "deploy this" in cmd
