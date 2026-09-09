"""Tests for integrations.base — ToolSchema and format export."""
from __future__ import annotations

import pytest

from serverless_sandbox.integrations.base import (
    ToolSchema,
    get_sandbox_tools,
    get_tool_schema,
)


# ---------------------------------------------------------------------------
# ToolSchema
# ---------------------------------------------------------------------------

class TestToolSchema:
    """Test ToolSchema dataclass."""

    def test_basic_creation(self):
        schema = ToolSchema(
            name="my_tool",
            description="Does stuff",
            parameters={"type": "object", "properties": {}},
        )
        assert schema.name == "my_tool"
        assert schema.description == "Does stuff"
        assert schema.parameters["type"] == "object"

    def test_to_openai_function(self):
        schema = ToolSchema(
            name="run_code",
            description="Run code in sandbox",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        )
        result = schema.to_openai_function()
        assert result["type"] == "function"
        assert result["function"]["name"] == "run_code"
        assert result["function"]["description"] == "Run code in sandbox"
        assert result["function"]["parameters"]["required"] == ["code"]

    def test_to_openai_function_structure(self):
        schema = ToolSchema(name="t", description="d", parameters={"type": "object"})
        result = schema.to_openai_function()
        assert set(result.keys()) == {"type", "function"}
        assert set(result["function"].keys()) == {"name", "description", "parameters"}


# ---------------------------------------------------------------------------
# get_sandbox_tools
# ---------------------------------------------------------------------------

class TestGetSandboxTools:
    """Test get_sandbox_tools."""

    def test_returns_list_of_tool_schemas(self):
        tools = get_sandbox_tools()
        assert isinstance(tools, list)
        assert len(tools) == 7
        for tool in tools:
            assert isinstance(tool, ToolSchema)

    def test_tool_names(self):
        tools = get_sandbox_tools()
        names = {t.name for t in tools}
        expected = {
            "create_sandbox", "run_code", "run_command",
            "read_file", "write_file", "list_files", "kill_sandbox",
        }
        assert names == expected

    def test_tools_have_descriptions(self):
        tools = get_sandbox_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"

    def test_tools_have_parameters(self):
        tools = get_sandbox_tools()
        for tool in tools:
            assert isinstance(tool.parameters, dict)
            assert tool.parameters.get("type") == "object"


# ---------------------------------------------------------------------------
# get_tool_schema — format export
# ---------------------------------------------------------------------------

class TestGetToolSchema:
    """Test get_tool_schema format export."""

    def test_openai_format(self):
        schemas = get_tool_schema("openai")
        assert isinstance(schemas, list)
        assert len(schemas) == 7
        for s in schemas:
            assert s["type"] == "function"
            assert "function" in s
            fn = s["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_anthropic_format(self):
        schemas = get_tool_schema("anthropic")
        assert isinstance(schemas, list)
        assert len(schemas) == 7
        for s in schemas:
            assert "name" in s
            assert "description" in s
            assert "input_schema" in s
            # anthropic format should NOT have "parameters" key
            assert "parameters" not in s

    def test_langchain_format(self):
        schemas = get_tool_schema("langchain")
        assert isinstance(schemas, list)
        assert len(schemas) == 7
        for s in schemas:
            assert "name" in s
            assert "description" in s
            assert "parameters" in s
            # langchain format should NOT have OpenAI wrapper
            assert "type" not in s

    def test_unknown_format_uses_default(self):
        """Unknown format string falls through to default."""
        schemas = get_tool_schema("custom_thing")
        assert len(schemas) == 7
        for s in schemas:
            assert "name" in s
            assert "parameters" in s

    def test_default_format_is_openai(self):
        schemas = get_tool_schema()
        assert schemas[0]["type"] == "function"

    def test_openai_schema_run_code_has_required(self):
        schemas = get_tool_schema("openai")
        run_code = next(s for s in schemas if s["function"]["name"] == "run_code")
        assert "code" in run_code["function"]["parameters"].get("required", [])
