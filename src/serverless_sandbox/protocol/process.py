"""envd API protocol — process management (Connect protocol).

Uses Connect RPC over HTTP with application/connect+json content type.
Streaming endpoints (Start, Connect) return AsyncIterator of typed chunks.

RPC endpoints（已实测验证）:
- /process.Process/Start (streaming) — Start a process and stream output
- /process.Process/List — List running processes
- /process.Process/Connect (streaming) — Connect to existing process output
- /process.Process/Update — Update process settings
- /process.Process/SendInput — Send stdin to a process
- /process.Process/SendSignal — Send signal to a process
"""
from __future__ import annotations

import base64
from typing import Any

from serverless_sandbox.models.process import (
    ProcessChunk,
    ProcessChunkType,
    ProcessInfo,
)
from serverless_sandbox.transport.auth import EnvdTokenManager
from serverless_sandbox.transport.codec import ConnectCodec
from serverless_sandbox.transport.http import HttpClient
from serverless_sandbox.transport.streaming import StreamReader
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("protocol.process")

_codec = ConnectCodec()

# RPC paths（已实测验证）
_START = _codec.build_rpc_path("process", "Process", "Start")
_LIST = _codec.build_rpc_path("process", "Process", "List")
_CONNECT = _codec.build_rpc_path("process", "Process", "Connect")
_UPDATE = _codec.build_rpc_path("process", "Process", "Update")
_SEND_INPUT = _codec.build_rpc_path("process", "Process", "SendInput")
_SEND_SIGNAL = _codec.build_rpc_path("process", "Process", "SendSignal")


def _parse_process_chunk(frame: dict[str, Any]) -> ProcessChunk:
    """Parse a streaming frame into a ProcessChunk.

    已实测验证的 NDJSON event 格式:
    - {"event":{"start":{"pid":N}}} — 进程启动
    - {"event":{"data":{"stdout":"base64"}}} — stdout 数据（base64 编码）
    - {"event":{"data":{"stderr":"base64"}}} — stderr 数据（base64 编码）
    - {"event":{"end":{"exitCode":N,"exited":bool,"status":"exited"}}} — 进程结束
    - {} — 空结束帧（忽略）
    """
    event = frame.get("event")
    if not event or not isinstance(event, dict):
        # 空帧或无 event 字段 — 忽略
        return ProcessChunk(type=ProcessChunkType.STDOUT, data="")

    # 进程启动事件
    if "start" in event:
        start_data = event["start"]
        pid = start_data.get("pid", 0)
        return ProcessChunk(
            type=ProcessChunkType.STDOUT,
            data="",
            exit_code=None,
            pid=pid,
        )

    # 数据输出事件（stdout/stderr，base64 编码）
    if "data" in event:
        data_obj = event["data"]
        if "stdout" in data_obj:
            raw = data_obj["stdout"]
            try:
                decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
            except Exception:
                decoded = raw
            return ProcessChunk(type=ProcessChunkType.STDOUT, data=decoded)
        if "stderr" in data_obj:
            raw = data_obj["stderr"]
            try:
                decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
            except Exception:
                decoded = raw
            return ProcessChunk(type=ProcessChunkType.STDERR, data=decoded)

    # 进程结束事件
    if "end" in event:
        end_data = event["end"]
        exit_code = end_data.get("exitCode", 0)
        return ProcessChunk(
            type=ProcessChunkType.EXIT,
            exit_code=exit_code,
        )

    # 未知事件
    return ProcessChunk(type=ProcessChunkType.STDOUT, data="")


class ProcessProtocol:
    """Typed wrapper for envd process operations (Connect protocol).

    已实测验证的方法: Start, List, Connect, Update, SendInput, SendSignal
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    async def start(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        cmd: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str = "",
        timeout: int = 60,
        user: str = "",
    ) -> StreamReader[ProcessChunk]:
        """Start a process and return a streaming reader.

        POST envd_url + /process.Process/Start (Connect streaming)

        请求格式（已实测验证）: {"process": {"cmd": "...", "args": [...]}}

        Note: ``cwd`` and ``user`` are only included in the payload when
        explicitly provided (non-empty).  Sending ``user="user"`` to
        certain platform base images triggers ``fork/exec: no such file
        or directory`` because the envd uses a namespace that doesn't
        recognise that user account.
        """
        process_obj: dict[str, Any] = {
            "cmd": cmd,
        }
        if args:
            process_obj["args"] = args
        if env:
            process_obj["envVars"] = env
        if cwd:
            process_obj["cwd"] = cwd
        if user:
            process_obj["user"] = user

        payload: dict[str, Any] = {"process": process_obj}

        raw_stream = self._http.envd_stream(
            envd_url, _START,
            payload=payload,
            envd_token=envd_token,
        )

        return StreamReader(raw_stream, _parse_process_chunk)

    async def list_processes(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
    ) -> list[ProcessInfo]:
        """List running processes in the sandbox.

        POST envd_url + /process.Process/List (Connect unary, 已实测验证)
        """
        response = await self._http.envd_request(
            envd_url, _LIST,
            payload={},
            envd_token=envd_token,
        )

        processes = response.get("processes", response.get("result", {}).get("processes", []))
        return [ProcessInfo.model_validate(p) for p in processes]

    async def connect_to_process(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        pid: int,
    ) -> StreamReader[ProcessChunk]:
        """Connect to an existing process and stream its output.

        POST envd_url + /process.Process/Connect (Connect streaming, 已实测验证)
        """
        raw_stream = self._http.envd_stream(
            envd_url, _CONNECT,
            payload={"pid": pid},
            envd_token=envd_token,
        )
        return StreamReader(raw_stream, _parse_process_chunk)

    async def update(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        pid: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update process settings.

        POST envd_url + /process.Process/Update (Connect unary, 已实测验证)
        """
        payload: dict[str, Any] = {"pid": pid, **kwargs}
        return await self._http.envd_request(
            envd_url, _UPDATE,
            payload=payload,
            envd_token=envd_token,
        )

    async def send_input(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        pid: int,
        data: str,
    ) -> None:
        """Send data to a process's stdin.

        POST envd_url + /process.Process/SendInput (Connect unary, 已实测验证)
        """
        await self._http.envd_request(
            envd_url, _SEND_INPUT,
            payload={"pid": pid, "data": data},
            envd_token=envd_token,
        )

    async def send_signal(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        pid: int,
        signal: int = 15,
    ) -> None:
        """Send a signal to a process (e.g. SIGTERM=15, SIGKILL=9).

        POST envd_url + /process.Process/SendSignal (Connect unary, 已实测验证)
        """
        await self._http.envd_request(
            envd_url, _SEND_SIGNAL,
            payload={"pid": pid, "signal": signal},
            envd_token=envd_token,
        )

    # --- backward-compat aliases ---

    async def send_stdin(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        pid: int,
        data: str,
    ) -> None:
        """Deprecated: use send_input(). Kept for backward compatibility."""
        await self.send_input(envd_url, envd_token, pid=pid, data=data)

    async def kill(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        pid: int,
    ) -> None:
        """Deprecated: use send_signal(). Kept for backward compatibility."""
        await self.send_signal(envd_url, envd_token, pid=pid, signal=9)
