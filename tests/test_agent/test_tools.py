"""Tests for MCP tool schemas and handlers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from serverless_sandbox.agent.tools import (
    TOOL_SCHEMAS,
    TOOL_SCHEMA_MAP,
    TOOL_HANDLERS,
    dispatch_tool,
    handle_create_sandbox,
    handle_run_code,
    handle_run_command,
    handle_read_file,
    handle_write_file,
    handle_list_files,
    handle_kill_sandbox,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestToolSchemas:
    """Test tool schema definitions."""

    def test_all_7_tools_defined(self):
        """All 7 P0 core tools should be defined."""
        assert len(TOOL_SCHEMAS) == 7

    def test_tool_names(self):
        """Tool names match expected set."""
        names = {t["name"] for t in TOOL_SCHEMAS}
        expected = {
            "create_sandbox",
            "run_code",
            "run_command",
            "read_file",
            "write_file",
            "list_files",
            "kill_sandbox",
        }
        assert names == expected

    def test_each_tool_has_required_fields(self):
        """Each tool has name, description, inputSchema."""
        for tool in TOOL_SCHEMAS:
            assert "name" in tool, f"Tool missing name: {tool}"
            assert "description" in tool, f"Tool {tool['name']} missing description"
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"
            assert tool["inputSchema"]["type"] == "object"

    def test_schema_map_matches_list(self):
        """TOOL_SCHEMA_MAP should have same keys as TOOL_SCHEMAS names."""
        assert set(TOOL_SCHEMA_MAP.keys()) == {t["name"] for t in TOOL_SCHEMAS}

    def test_handler_map_matches_schemas(self):
        """Every schema should have a handler."""
        for tool in TOOL_SCHEMAS:
            assert tool["name"] in TOOL_HANDLERS, f"No handler for {tool['name']}"

    def test_run_code_requires_code(self):
        """run_code should have 'code' as required parameter."""
        schema = TOOL_SCHEMA_MAP["run_code"]
        assert "code" in schema["inputSchema"].get("required", [])

    def test_run_command_requires_command(self):
        """run_command should have 'command' as required parameter."""
        schema = TOOL_SCHEMA_MAP["run_command"]
        assert "command" in schema["inputSchema"].get("required", [])

    def test_read_file_requires_path(self):
        """read_file should have 'path' as required parameter."""
        schema = TOOL_SCHEMA_MAP["read_file"]
        assert "path" in schema["inputSchema"].get("required", [])

    def test_write_file_requires_path_and_content(self):
        """write_file should have 'path' and 'content' as required."""
        schema = TOOL_SCHEMA_MAP["write_file"]
        required = schema["inputSchema"].get("required", [])
        assert "path" in required
        assert "content" in required

    def test_create_sandbox_has_template_param(self):
        """create_sandbox should accept 'template' parameter."""
        schema = TOOL_SCHEMA_MAP["create_sandbox"]
        assert "template" in schema["inputSchema"]["properties"]

    def test_kill_sandbox_has_sandbox_id(self):
        """kill_sandbox should accept optional sandbox_id."""
        schema = TOOL_SCHEMA_MAP["kill_sandbox"]
        assert "sandbox_id" in schema["inputSchema"]["properties"]


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------

def _make_mock_manager():
    """Create a mock SandboxManager."""
    manager = AsyncMock()

    # Mock sandbox
    sandbox = AsyncMock()
    sandbox.id = "sbx-test-001"
    sandbox.status = MagicMock()
    sandbox.status.value = "running"
    sandbox.url = "https://49983-sbx-test-001.cn-hangzhou.e2b.fc.aliyuncs.com"

    # Mock commands.run
    from serverless_sandbox.models.process import ProcessResult
    sandbox.commands.run = AsyncMock(return_value=ProcessResult(
        stdout="hello\n", stderr="", exit_code=0, execution_time=0.5,
    ))

    # Mock run_code
    from serverless_sandbox.models.process import CodeResult
    sandbox.run_code = AsyncMock(return_value=CodeResult(
        text="42", stdout="42\n", stderr="", exit_code=0, output_files=[], execution_time=0.3,
    ))

    # Mock files
    from serverless_sandbox.models.filesystem import FileInfo, FileType
    sandbox.files.read = AsyncMock(return_value="file content here")
    sandbox.files.write = AsyncMock(return_value=None)
    sandbox.files.list = AsyncMock(return_value=[
        FileInfo(name="main.py", path="/app/main.py", type=FileType.FILE, size=128),
        FileInfo(name="data", path="/app/data", type=FileType.DIRECTORY, size=0),
    ])

    manager.create_sandbox = AsyncMock(return_value=sandbox)
    manager.get_sandbox = AsyncMock(return_value=sandbox)
    manager.kill_sandbox = AsyncMock(return_value=None)

    return manager


class TestToolHandlers:
    """Test individual tool handler functions."""

    @pytest.fixture
    def manager(self):
        return _make_mock_manager()

    async def test_create_sandbox(self, manager):
        result = await handle_create_sandbox(
            {"template": "python-base", "timeout": 300}, manager,
        )
        assert result["sandbox_id"] == "sbx-test-001"
        assert result["status"] == "running"
        manager.create_sandbox.assert_awaited_once_with(
            template="python-base", timeout=300, envs={},
        )

    async def test_create_sandbox_defaults(self, manager):
        result = await handle_create_sandbox({}, manager)
        assert result["sandbox_id"] == "sbx-test-001"
        manager.create_sandbox.assert_awaited_once_with(
            template="code-interpreter-v1", timeout=300, envs={},
        )

    async def test_run_code(self, manager):
        result = await handle_run_code(
            {"code": "print(42)", "language": "python"}, manager,
        )
        assert result["stdout"] == "42\n"
        assert result["exit_code"] == 0
        manager.get_sandbox.assert_awaited_once_with(None)

    async def test_run_code_with_sandbox_id(self, manager):
        result = await handle_run_code(
            {"code": "1+1", "sandbox_id": "sbx-specific"}, manager,
        )
        manager.get_sandbox.assert_awaited_once_with("sbx-specific")

    async def test_run_command(self, manager):
        result = await handle_run_command(
            {"command": "echo hello"}, manager,
        )
        assert result["stdout"] == "hello\n"
        assert result["exit_code"] == 0

    async def test_run_command_with_cwd(self, manager):
        await handle_run_command(
            {"command": "ls", "cwd": "/tmp", "timeout": 10}, manager,
        )
        sandbox = await manager.get_sandbox(None)
        sandbox.commands.run.assert_awaited_with("ls", timeout=10, cwd="/tmp")

    async def test_read_file(self, manager):
        result = await handle_read_file({"path": "/app/main.py"}, manager)
        assert result["content"] == "file content here"

    async def test_write_file(self, manager):
        result = await handle_write_file(
            {"path": "/app/test.py", "content": "print('hi')"}, manager,
        )
        assert result["success"] is True
        assert result["bytes_written"] == len("print('hi')".encode("utf-8"))

    async def test_list_files(self, manager):
        result = await handle_list_files({"path": "/app"}, manager)
        assert len(result["files"]) == 2
        assert result["files"][0]["name"] == "main.py"
        assert result["files"][0]["type"] == "file"
        assert result["files"][1]["name"] == "data"
        assert result["files"][1]["type"] == "directory"

    async def test_list_files_default_path(self, manager):
        result = await handle_list_files({}, manager)
        sandbox = await manager.get_sandbox(None)
        sandbox.files.list.assert_awaited_with("/app")

    async def test_kill_sandbox(self, manager):
        result = await handle_kill_sandbox({}, manager)
        assert result["success"] is True
        manager.kill_sandbox.assert_awaited_once_with(None)

    async def test_kill_sandbox_specific(self, manager):
        result = await handle_kill_sandbox({"sandbox_id": "sbx-002"}, manager)
        assert result["success"] is True
        manager.kill_sandbox.assert_awaited_once_with("sbx-002")


class TestDispatch:
    """Test the dispatch_tool function."""

    async def test_dispatch_known_tool(self):
        manager = _make_mock_manager()
        result = await dispatch_tool("run_code", {"code": "1+1"}, manager)
        assert "stdout" in result

    async def test_dispatch_unknown_tool(self):
        manager = _make_mock_manager()
        with pytest.raises(ValueError, match="Unknown tool"):
            await dispatch_tool("nonexistent_tool", {}, manager)

    async def test_dispatch_handler_error_returns_error(self):
        """If a handler raises, dispatch_tool returns error dict."""
        manager = _make_mock_manager()
        manager.get_sandbox = AsyncMock(side_effect=RuntimeError("connection failed"))
        result = await dispatch_tool("run_code", {"code": "x"}, manager)
        assert "error" in result
        assert "connection failed" in result["error"]
