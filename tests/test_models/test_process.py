"""Tests for process data models."""
from __future__ import annotations

from easy_sandbox.models.process import (
    ProcessChunkType,
    ProcessChunk,
    ProcessResult,
    CodeResult,
    OutputFile,
    ProcessInfo,
)


class TestProcessResult:
    def test_success_true(self):
        result = ProcessResult(stdout="hello", exit_code=0)
        assert result.success is True

    def test_success_false(self):
        result = ProcessResult(exit_code=1, stderr="error")
        assert result.success is False

    def test_defaults(self):
        result = ProcessResult()
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.execution_time == 0.0


class TestProcessChunk:
    def test_stdout_chunk(self):
        chunk = ProcessChunk(type=ProcessChunkType.STDOUT, data="hello")
        assert chunk.type == ProcessChunkType.STDOUT
        assert chunk.data == "hello"
        assert chunk.exit_code is None

    def test_stderr_chunk(self):
        chunk = ProcessChunk(type=ProcessChunkType.STDERR, data="err")
        assert chunk.type == ProcessChunkType.STDERR

    def test_exit_chunk(self):
        chunk = ProcessChunk(
            type=ProcessChunkType.EXIT, exit_code=0, timestamp=1234567890.0
        )
        assert chunk.type == ProcessChunkType.EXIT
        assert chunk.exit_code == 0
        assert chunk.timestamp == 1234567890.0

    def test_chunk_type_enum(self):
        assert ProcessChunkType.STDOUT == "stdout"
        assert ProcessChunkType.STDERR == "stderr"
        assert ProcessChunkType.EXIT == "exit"


class TestOutputFile:
    def test_serialization(self):
        f = OutputFile(name="plot.png", path="/tmp/plot.png", size=1024, mime_type="image/png")
        d = f.model_dump()
        assert d["name"] == "plot.png"
        assert d["path"] == "/tmp/plot.png"
        assert d["size"] == 1024
        assert d["mime_type"] == "image/png"

    def test_defaults(self):
        f = OutputFile(name="a.txt", path="/a.txt")
        assert f.size == 0
        assert f.mime_type == "application/octet-stream"


class TestCodeResult:
    def test_with_output_files(self):
        files = [OutputFile(name="out.csv", path="/out.csv")]
        result = CodeResult(
            text="result",
            stdout="ok",
            exit_code=0,
            output_files=files,
            execution_time=1.5,
        )
        assert result.success is True
        assert len(result.output_files) == 1
        assert result.output_files[0].name == "out.csv"
        assert result.execution_time == 1.5

    def test_success_false(self):
        result = CodeResult(exit_code=1)
        assert result.success is False

    def test_defaults(self):
        result = CodeResult()
        assert result.text == ""
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.output_files == []
        assert result.execution_time == 0.0


class TestProcessInfo:
    def test_model(self):
        info = ProcessInfo(pid=1234, command="python main.py")
        assert info.pid == 1234
        assert info.command == "python main.py"
        assert info.status == "running"

    def test_defaults(self):
        info = ProcessInfo(pid=1)
        assert info.command == ""
        assert info.status == "running"
