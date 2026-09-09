"""Agent 框架集成基础。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSchema:
    """通用 Tool Schema。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

    def to_openai_function(self) -> dict:
        """导出为 OpenAI Function Calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def get_sandbox_tools() -> list[ToolSchema]:
    """获取所有沙箱 Tool Schemas。"""
    from ..agent.tools import TOOL_SCHEMAS

    return [
        ToolSchema(
            name=t["name"],
            description=t["description"],
            parameters=t["inputSchema"],
        )
        for t in TOOL_SCHEMAS
    ]


def get_tool_schema(format: str = "openai") -> list[dict]:
    """导出 Tool Schema 为指定格式。

    Args:
        format: "openai" | "langchain" | "anthropic"
    """
    tools = get_sandbox_tools()
    if format == "openai":
        return [t.to_openai_function() for t in tools]
    elif format == "anthropic":
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
    else:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in tools
        ]
