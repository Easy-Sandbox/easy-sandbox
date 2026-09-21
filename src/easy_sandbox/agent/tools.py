"""MCP Tools 定义 — 7 个 P0 核心工具。

每个 Tool 包含：
- TOOL_SCHEMA: MCP Tool schema（name, description, inputSchema）
- handler 异步函数：接收参数 + sandbox manager，返回 dict 结果
"""
from __future__ import annotations

import traceback
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from easy_sandbox.agent.mcp import SandboxManager

# ---------------------------------------------------------------------------
# Tool schemas (MCP format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "create_sandbox",
        "description": (
            "创建一个云端沙箱环境。返回 sandbox_id 用于后续操作。"
            "如果不指定 template，默认使用 code-interpreter-v1。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": "沙箱模板名称，默认 code-interpreter-v1",
                },
                "timeout": {
                    "type": "integer",
                    "description": "沙箱超时时间（秒），默认 300",
                    "default": 300,
                },
                "envs": {
                    "type": "object",
                    "description": "环境变量键值对",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
    },
    {
        "name": "run_code",
        "description": (
            "在沙箱中执行代码（通过 Code Interpreter）。"
            "支持 Python、JavaScript 等语言。省略 sandbox_id 时使用默认沙箱。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的代码"},
                "language": {
                    "type": "string",
                    "description": "编程语言，默认 python",
                    "default": "python",
                    "enum": ["python", "javascript", "shell", "typescript", "r"],
                },
                "sandbox_id": {
                    "type": "string",
                    "description": "沙箱 ID，省略时使用默认沙箱",
                },
                "timeout": {
                    "type": "integer",
                    "description": "执行超时（秒），默认 30",
                    "default": 30,
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "run_command",
        "description": "在沙箱中执行 Shell 命令。省略 sandbox_id 时使用默认沙箱。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell 命令"},
                "sandbox_id": {"type": "string", "description": "沙箱 ID"},
                "cwd": {
                    "type": "string",
                    "description": "工作目录，默认 /app",
                    "default": "/app",
                },
                "timeout": {
                    "type": "integer",
                    "description": "执行超时（秒），默认 60",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "读取沙箱中的文件内容。省略 sandbox_id 时使用默认沙箱。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件绝对路径"},
                "sandbox_id": {"type": "string", "description": "沙箱 ID"},
                "encoding": {
                    "type": "string",
                    "description": "文件编码，默认 utf-8",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "在沙箱中创建或覆写文件。省略 sandbox_id 时使用默认沙箱。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件绝对路径"},
                "content": {"type": "string", "description": "文件内容"},
                "sandbox_id": {"type": "string", "description": "沙箱 ID"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "列出沙箱中指定目录的文件和子目录。省略 sandbox_id 时使用默认沙箱。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径，默认 /app",
                    "default": "/app",
                },
                "sandbox_id": {"type": "string", "description": "沙箱 ID"},
            },
        },
    },
    {
        "name": "kill_sandbox",
        "description": "销毁指定沙箱。省略 sandbox_id 时销毁默认沙箱。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sandbox_id": {
                    "type": "string",
                    "description": "要销毁的沙箱 ID，省略时销毁默认沙箱",
                },
            },
        },
    },
]

# Quick lookup by name
TOOL_SCHEMA_MAP: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOL_SCHEMAS}


# ---------------------------------------------------------------------------
# Tool handler functions
# ---------------------------------------------------------------------------

async def handle_create_sandbox(
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Handle create_sandbox tool call."""
    template = params.get("template", "code-interpreter-v1")
    timeout = params.get("timeout", 300)
    envs = params.get("envs") or {}

    sandbox = await manager.create_sandbox(
        template=template, timeout=timeout, envs=envs,
    )
    return {
        "sandbox_id": sandbox.id,
        "status": sandbox.status.value,
        "url": sandbox.url,
    }


async def handle_run_code(
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Handle run_code tool call."""
    code = params["code"]
    language = params.get("language", "python")
    timeout = params.get("timeout", 30)
    sandbox_id = params.get("sandbox_id")

    sandbox = await manager.get_sandbox(sandbox_id)
    result = await sandbox.run_code(code, language=language, timeout=timeout)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "output_files": [
            {"name": f.name, "path": f.path, "size": f.size}
            for f in result.output_files
        ],
    }


async def handle_run_command(
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Handle run_command tool call."""
    command = params["command"]
    timeout = params.get("timeout", 60)
    cwd = params.get("cwd", "/app")
    sandbox_id = params.get("sandbox_id")

    sandbox = await manager.get_sandbox(sandbox_id)
    result = await sandbox.commands.run(command, timeout=timeout, cwd=cwd)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
    }


async def handle_read_file(
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Handle read_file tool call."""
    path = params["path"]
    encoding = params.get("encoding", "utf-8")
    sandbox_id = params.get("sandbox_id")

    sandbox = await manager.get_sandbox(sandbox_id)
    content = await sandbox.files.read(path, encoding=encoding)
    return {"content": content}


async def handle_write_file(
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Handle write_file tool call."""
    path = params["path"]
    content = params["content"]
    sandbox_id = params.get("sandbox_id")

    sandbox = await manager.get_sandbox(sandbox_id)
    await sandbox.files.write(path, content)
    return {"success": True, "bytes_written": len(content.encode("utf-8"))}


async def handle_list_files(
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Handle list_files tool call."""
    path = params.get("path", "/app")
    sandbox_id = params.get("sandbox_id")

    sandbox = await manager.get_sandbox(sandbox_id)
    files = await sandbox.files.list(path)
    return {
        "files": [
            {
                "name": f.name,
                "path": f.path,
                "type": f.type.value,
                "size": f.size,
            }
            for f in files
        ],
    }


async def handle_kill_sandbox(
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Handle kill_sandbox tool call."""
    sandbox_id = params.get("sandbox_id")
    await manager.kill_sandbox(sandbox_id)
    return {"success": True}


# Handler dispatch table
TOOL_HANDLERS: dict[str, Any] = {
    "create_sandbox": handle_create_sandbox,
    "run_code": handle_run_code,
    "run_command": handle_run_command,
    "read_file": handle_read_file,
    "write_file": handle_write_file,
    "list_files": handle_list_files,
    "kill_sandbox": handle_kill_sandbox,
}


async def dispatch_tool(
    name: str,
    params: dict[str, Any],
    manager: SandboxManager,
) -> dict[str, Any]:
    """Dispatch a tool call to its handler.

    Args:
        name: Tool name.
        params: Tool parameters.
        manager: Sandbox manager instance.

    Returns:
        Tool result dict.

    Raises:
        ValueError: If the tool name is not recognized.
    """
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    try:
        return await handler(params, manager)
    except Exception as exc:
        return {
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
