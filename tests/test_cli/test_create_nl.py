"""Tests for CLI `ebx create` with natural-language description inference."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli
from easy_sandbox.models.sandbox import SandboxInfo, SandboxStatus


def _make_sandbox(
    sandbox_id: str = "sbx-nl-001",
    template: str = "code-interpreter",
    status: str = "running",
) -> MagicMock:
    """Build a mock Sandbox object."""
    sb_info = SandboxInfo.model_validate({
        "sandboxID": sandbox_id,
        "templateID": template,
        "status": status,
        "region": "cn-hangzhou",
        "timeout": 300,
        "envdUrl": f"https://{sandbox_id}.cn-hangzhou.e2b.fc.aliyuncs.com",
        "envdAccessToken": "tok",
    })
    mock_sb = MagicMock()
    mock_sb.id = sb_info.sandbox_id
    mock_sb.status = sb_info.status
    mock_sb.url = sb_info.envd_url
    mock_sb.info = sb_info
    mock_sb.files = MagicMock()
    mock_sb.files.write = AsyncMock()
    return mock_sb


# ---------------------------------------------------------------------------
# NL inference via `ebx create "<description>"`
# ---------------------------------------------------------------------------

class TestCreateNLInference:
    """Tests for `ebx create` with a natural-language description."""

    def test_create_with_python_description(self, runner: CliRunner) -> None:
        """ebx create "运行 python" → should infer and show result."""
        mock_sb = _make_sandbox(template="code-interpreter")

        call_count = [0]

        def _run_sync_side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                # infer_template call
                from easy_sandbox.agent.infer import InferResult
                return InferResult(
                    template="code-interpreter",
                    display_name="Code Interpreter",
                    cpu=2,
                    memory=4096,
                    confidence=0.88,
                    reasoning="关键词匹配: python, 运行",
                )
            # Sandbox.create call
            return mock_sb

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            side_effect=_run_sync_side_effect,
        ):
            result = runner.invoke(cli, ["create", "运行 python"])

        assert result.exit_code == 0
        assert "推断结果" in result.output
        assert "code-interpreter" in result.output
        assert "sbx-nl-001" in result.output

    def test_create_with_nodejs_description(self, runner: CliRunner) -> None:
        """ebx create "启动 Node.js 服务" → infer node-web."""
        mock_sb = _make_sandbox(template="node-web")

        call_count = [0]

        def _run_sync_side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                from easy_sandbox.agent.infer import InferResult
                return InferResult(
                    template="node-web",
                    display_name="Node.js Web",
                    cpu=1,
                    memory=2048,
                    confidence=0.88,
                    ports=[3000],
                    reasoning="关键词匹配: node.js, web",
                )
            return mock_sb

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            side_effect=_run_sync_side_effect,
        ):
            result = runner.invoke(cli, ["create", "启动 Node.js 服务"])

        assert result.exit_code == 0
        assert "node-web" in result.output

    def test_create_explicit_template_skips_inference(self, runner: CliRunner) -> None:
        """ebx create --template base → traditional behavior, no inference."""
        mock_sb = _make_sandbox(template="base")

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            return_value=mock_sb,
        ):
            result = runner.invoke(cli, ["create", "--template", "base"])

        assert result.exit_code == 0
        # Should NOT contain inference output
        assert "推断结果" not in result.output
        assert "sbx-nl-001" in result.output

    def test_create_description_with_explicit_template_prefers_template(
        self, runner: CliRunner
    ) -> None:
        """ebx create "python" --template custom → --template takes priority."""
        mock_sb = _make_sandbox(template="custom")

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            return_value=mock_sb,
        ):
            result = runner.invoke(
                cli, ["create", "python", "--template", "custom"]
            )

        assert result.exit_code == 0
        # Inference should NOT be triggered when --template is given
        assert "推断结果" not in result.output

    def test_create_with_upload(self, runner: CliRunner, tmp_path) -> None:
        """ebx create "分析 CSV" --upload <file> → show upload info."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("a,b,c\n1,2,3\n")

        mock_sb = _make_sandbox(template="python-data-science")

        call_count = [0]

        def _run_sync_side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                from easy_sandbox.agent.infer import InferResult
                return InferResult(
                    template="python-data-science",
                    display_name="Python Data Science",
                    cpu=2,
                    memory=4096,
                    confidence=0.88,
                    reasoning="关键词匹配: csv, 分析",
                )
            # _create_and_upload: run the merged coroutine
            import asyncio as _aio
            return _aio.run(coro)

        with patch(
            "easy_sandbox.api.sandbox.Sandbox.create",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ), patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            side_effect=_run_sync_side_effect,
        ):
            result = runner.invoke(
                cli, ["create", "分析 CSV", "--upload", str(csv_file)]
            )

        assert result.exit_code == 0
        assert "python-data-science" in result.output
        assert "已上传" in result.output

    def test_create_no_description_no_template_uses_base(
        self, runner: CliRunner
    ) -> None:
        """ebx create (no args) → uses default 'base' template."""
        mock_sb = _make_sandbox(template="base")

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            return_value=mock_sb,
        ):
            result = runner.invoke(cli, ["create"])

        assert result.exit_code == 0
        # No inference output
        assert "推断结果" not in result.output

    def test_create_json_output_with_description(self, runner: CliRunner) -> None:
        """ebx --json create "运行 python" → JSON output, no inference text."""
        mock_sb = _make_sandbox(template="code-interpreter")

        call_count = [0]

        def _run_sync_side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                from easy_sandbox.agent.infer import InferResult
                return InferResult(
                    template="code-interpreter",
                    display_name="Code Interpreter",
                    cpu=2,
                    memory=4096,
                    confidence=0.88,
                    reasoning="test",
                )
            return mock_sb

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            side_effect=_run_sync_side_effect,
        ):
            result = runner.invoke(cli, ["--json", "create", "运行 python"])

        assert result.exit_code == 0
        # In JSON mode, no human-readable inference text
        assert "推断结果" not in result.output

    def test_create_inference_shows_confidence(self, runner: CliRunner) -> None:
        """Inference output should include confidence score."""
        mock_sb = _make_sandbox()

        call_count = [0]

        def _run_sync_side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                from easy_sandbox.agent.infer import InferResult
                return InferResult(
                    template="browser-automation",
                    display_name="Browser Automation",
                    cpu=2,
                    memory=4096,
                    confidence=0.88,
                    reasoning="关键词匹配: playwright, 爬取",
                )
            return mock_sb

        with patch(
            "easy_sandbox.utils.async_bridge.run_sync",
            side_effect=_run_sync_side_effect,
        ):
            result = runner.invoke(
                cli, ["create", "用 playwright 爬取网页"]
            )

        assert result.exit_code == 0
        assert "置信度" in result.output
        assert "0.88" in result.output
