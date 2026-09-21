"""Tests for agent/builtin.py — AgentModule."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from easy_sandbox.agent.builtin import AgentModule


def _make_mock_sandbox() -> MagicMock:
    """Create a mock Sandbox with commands, code, and files sub-modules."""
    sandbox = MagicMock()

    # Mock commands.run
    proc_result = MagicMock()
    proc_result.stdout = "hello world\n"
    proc_result.stderr = ""
    proc_result.exit_code = 0
    sandbox.commands.run = AsyncMock(return_value=proc_result)

    # Mock code.run
    code_result = MagicMock()
    code_result.text = "42"
    sandbox.code.run = AsyncMock(return_value=code_result)

    # Mock files
    sandbox.files.write = AsyncMock()
    sandbox.files.read = AsyncMock(return_value=b"file content")

    return sandbox


class TestAgentModule:
    """Tests for AgentModule."""

    def test_init(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        assert agent._sandbox is sandbox

    @pytest.mark.asyncio
    async def test_code_with_code_param(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        result = await agent.code("run this", code="print(42)")
        sandbox.code.run.assert_awaited_once_with("print(42)", language="python")
        assert result == "42"

    @pytest.mark.asyncio
    async def test_code_with_instruction_only(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        result = await agent.code("print('hello')")
        sandbox.code.run.assert_awaited_once_with("print('hello')", language="python")

    @pytest.mark.asyncio
    async def test_code_custom_language(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        await agent.code("code", code="console.log(1)", language="javascript")
        sandbox.code.run.assert_awaited_once_with(
            "console.log(1)", language="javascript"
        )

    @pytest.mark.asyncio
    async def test_shell(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        result = await agent.shell("ls -la")
        sandbox.commands.run.assert_awaited_once_with("ls -la", timeout=60)
        assert result == "hello world\n"

    @pytest.mark.asyncio
    async def test_shell_custom_timeout(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        await agent.shell("long command", timeout=120)
        sandbox.commands.run.assert_awaited_once_with("long command", timeout=120)

    @pytest.mark.asyncio
    async def test_browse(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        result = await agent.browse("https://example.com")
        sandbox.commands.run.assert_awaited_once_with("curl -sL https://example.com")
        assert result == "hello world\n"

    @pytest.mark.asyncio
    async def test_install(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        result = await agent.install("pandas", "numpy")
        sandbox.commands.run.assert_awaited_once_with(
            "pip install --quiet pandas numpy", timeout=120,
        )

    @pytest.mark.asyncio
    async def test_upload_str(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        await agent.upload("hello world", "/app/test.txt")
        sandbox.files.write.assert_awaited_once_with(
            "/app/test.txt", b"hello world"
        )

    @pytest.mark.asyncio
    async def test_upload_bytes(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        await agent.upload(b"\x00\x01\x02", "/app/binary.bin")
        sandbox.files.write.assert_awaited_once_with(
            "/app/binary.bin", b"\x00\x01\x02"
        )

    @pytest.mark.asyncio
    async def test_download(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        result = await agent.download("/app/test.txt")
        sandbox.files.read.assert_awaited_once_with("/app/test.txt")
        assert result == b"file content"

    @pytest.mark.asyncio
    async def test_analyze(self) -> None:
        sandbox = _make_mock_sandbox()
        agent = AgentModule(sandbox)
        result = await agent.analyze("x = 1 + 2")
        # Should have called commands.run twice (write + analyze)
        assert sandbox.commands.run.await_count == 2
