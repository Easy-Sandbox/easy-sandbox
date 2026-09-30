"""STDIO process checks for the MCP server.

These start the real ``ebx mcp start`` process. The sandbox API is a local
stub, so the tests do not create a cloud sandbox.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _SlowHandler(BaseHTTPRequestHandler):
    """Hold the sandbox API call long enough to prove ping is not blocked."""

    delay = 0.8

    def do_POST(self) -> None:  # noqa: N802
        time.sleep(self.delay)
        body = b'{"message":"unavailable"}'
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _start_mcp(api_url: str) -> subprocess.Popen[str]:
    runtime = tempfile.mkdtemp(prefix="ebx-mcp-stdio-")
    env = os.environ.copy()
    env["EBX_MCP_RUNTIME_DIR"] = runtime
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "easy_sandbox.cli.main",
            "mcp",
            "start",
            "--api-key",
            "stdio-e2e-placeholder",
            "--api-url",
            api_url,
            "--template",
            "python-hello",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    proc.ebx_runtime = runtime  # type: ignore[attr-defined]
    return proc


def _send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _readline(proc: subprocess.Popen[str], timeout: float = 8) -> dict[str, Any]:
    assert proc.stdout is not None
    box: list[str] = []

    def _read() -> None:
        assert proc.stdout is not None
        box.append(proc.stdout.readline())

    thread = threading.Thread(target=_read)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        proc.kill()
        raise AssertionError("timed out waiting for MCP stdout")
    if not box or not box[0]:
        proc.kill()
        err = proc.stderr.read() if proc.stderr is not None else ""
        raise AssertionError(f"EOF on MCP stdout\n{err}")
    parsed = json.loads(box[0])
    assert isinstance(parsed, dict)
    return parsed


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.stdin is not None:
        proc.stdin.close()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
    runtime = getattr(proc, "ebx_runtime", None)
    if isinstance(runtime, str):
        shutil.rmtree(runtime, ignore_errors=True)


def _initialize(proc: subprocess.Popen[str]) -> None:
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "0"},
            },
        },
    )
    response = _readline(proc)
    assert response["result"]["protocolVersion"] == "2024-11-05"


class TestStdioProcess:
    """The real STDIO server stays up for the calls an agent actually sends."""

    def test_large_tool_call_does_not_kill_the_process(self) -> None:
        proc = _start_mcp("http://127.0.0.1:9")
        try:
            _initialize(proc)
            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "write_file",
                        "arguments": {"path": "/tmp/big.txt", "content": "x" * 70_000},
                    },
                },
            )
            response = _readline(proc, timeout=10)
            assert response["id"] == 2
            assert proc.poll() is None
            text = response["result"]["content"][0]["text"]
            assert "mozilla.org" not in text
        finally:
            _stop(proc)

    def test_ping_is_answered_while_a_tool_call_is_in_flight(self) -> None:
        port = _free_port()
        server = ThreadingHTTPServer(("127.0.0.1", port), _SlowHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        proc = _start_mcp(f"http://127.0.0.1:{port}")
        try:
            _initialize(proc)
            started = time.monotonic()
            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "run_code", "arguments": {"code": "print(1)"}},
                },
            )
            _send(proc, {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}})
            first = _readline(proc, timeout=5)
            ping_at = time.monotonic() - started
            second = _readline(proc, timeout=8)
            assert first["id"] == 3
            assert first["result"] == {}
            assert ping_at < 0.5
            assert second["id"] == 2
            assert proc.poll() is None
        finally:
            _stop(proc)
            server.shutdown()
