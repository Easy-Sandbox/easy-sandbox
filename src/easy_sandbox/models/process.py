"""Process execution data models."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class ProcessChunkType(str, enum.Enum):
    """Type of streaming process output chunk."""

    STDOUT = "stdout"
    STDERR = "stderr"
    EXIT = "exit"


class ProcessChunk(BaseModel):
    """A single chunk of streaming process output."""

    type: ProcessChunkType
    data: str = ""
    exit_code: int | None = None
    pid: int | None = None
    timestamp: float | None = None


class ProcessResult(BaseModel):
    """Result of a completed process execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time: float = 0.0

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class CommandResult(BaseModel):
    """Unified result of :meth:`Sandbox.custom` — template or server command.

    ``custom()`` resolves a named command in one of two ways and wraps both
    outcomes in this single type:

    * **template** (mechanism A, ``template.yaml`` ``custom_commands``):
      ``value`` is ``stdout`` stripped of surrounding whitespace and the
      ``stdout``/``stderr``/``exit_code`` fields carry the underlying
      process result.
    * **server** (mechanism B, ``POST /commands/{name}`` on SandboxServer):
      ``value`` is the JSON return value of the Python function, ``stdout``
      and ``stderr`` are empty, and ``exit_code`` is ``0`` on success or
      ``1`` on failure.
    """

    value: Any = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time: float = 0.0
    source: str = ""  # "template" | "server"

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class OutputFile(BaseModel):
    """A file produced by code execution."""

    name: str
    path: str
    size: int = 0
    mime_type: str = "application/octet-stream"


class CodeResult(BaseModel):
    """Result of code execution (Code Interpreter)."""

    text: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    output_files: list[OutputFile] = Field(default_factory=list)
    execution_time: float = 0.0

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class ProcessInfo(BaseModel):
    """Information about a running process."""

    pid: int
    command: str = ""
    status: str = "running"
