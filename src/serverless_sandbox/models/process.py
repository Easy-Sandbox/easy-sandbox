"""Process execution data models."""
from __future__ import annotations

import enum

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
