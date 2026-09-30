"""Commands module — run commands in sandboxes."""

from __future__ import annotations

import shlex
import time
from typing import TYPE_CHECKING

from easy_sandbox.models.process import (
    ProcessChunk,
    ProcessChunkType,
    ProcessInfo,
    ProcessResult,
)
from easy_sandbox.models.template import DEFAULT_CAPABILITIES
from easy_sandbox.utils.async_bridge import make_sync
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from easy_sandbox.protocol.process import ProcessProtocol
    from easy_sandbox.transport.auth import EnvdTokenManager
    from easy_sandbox.transport.streaming import StreamReader

logger = get_logger("api.commands")

# Shell punctuation characters that indicate the command requires ``sh -c``
# wrapping because the envd process API executes ``cmd`` directly (not via a
# shell).  Only *unquoted* occurrences trigger wrapping.
_SHELL_PUNCT: frozenset[str] = frozenset("();<>|&")


def _needs_shell_wrap(cmd: str) -> bool:
    """Return ``True`` if *cmd* contains unquoted shell operators.

    Uses :class:`shlex.shlex` with ``punctuation_chars=True`` so that
    operators inside quoted sections (single or double) are *not* flagged.
    """
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        for token in lex:
            if token and all(c in _SHELL_PUNCT for c in token):
                return True
    except ValueError:
        # Malformed quoting — let it through; the caller will get an error
        # from shlex.split or the remote side.
        pass
    return False


class CommandsModule:
    """High-level interface for running commands in a sandbox.

    Wraps ProcessProtocol and provides convenient methods for
    executing shell commands, streaming output, and managing processes.

    Note: Commands containing unquoted shell operators (|, ;, &&, ||, >, <, ())
    are automatically wrapped in ``sh -c``. Variable expansion ($VAR), backticks,
    and glob patterns still require explicit ``sh -c '...'`` wrapping.
    """

    def __init__(
        self,
        envd_url: str,
        envd_token: EnvdTokenManager,
        process_protocol: ProcessProtocol,
        capabilities: set[str] | None = None,
    ) -> None:
        self._envd_url = envd_url
        self._envd_token = envd_token
        self._process = process_protocol
        self._capabilities = capabilities if capabilities is not None else set(DEFAULT_CAPABILITIES)

    @staticmethod
    def _parse_cmd(cmd: str) -> tuple[str, list[str]]:
        """Parse a command string into command and args.

        When the command contains unquoted shell operators (pipes, redirects,
        semicolons, etc.) it is wrapped in ``sh -c`` so the remote shell
        interprets the full pipeline.  Simple commands are split via
        :func:`shlex.split` as before.
        """
        if _needs_shell_wrap(cmd):
            return "sh", ["-c", cmd]
        parts = shlex.split(cmd)
        if not parts:
            return cmd, []
        return parts[0], parts[1:]

    async def run(
        self,
        cmd: str,
        *,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        cwd: str = "",
        user: str = "",
        background: bool = False,
        shell: bool = False,
    ) -> ProcessResult | StreamReader[ProcessChunk]:
        """Run a command and wait for completion.

        Args:
            cmd: Shell command string (e.g., "echo hello").
            timeout: Max execution time in seconds.
            env: Additional environment variables.
            cwd: Working directory.
            user: OS user to run the command as.
            background: If True, delegate to start() and return a
                StreamReader handle immediately without blocking.
            shell: When True, always run ``cmd`` via ``sh -c`` so variable
                expansion, ``cd``, and other shell syntax work. The MCP
                ``run_command`` tool sets this. The default keeps the existing
                split-or-wrap behavior for SDK and CLI callers.

        Returns:
            ProcessResult with stdout, stderr, exit_code when
            background=False.  When background=True a
            :class:`~easy_sandbox.transport.streaming.StreamReader`
            handle is returned instead (not a ProcessResult); iterate
            over it to consume :class:`ProcessChunk` items.
        """
        if background:
            return await self.start(
                cmd,
                timeout=timeout,
                env=env,
                cwd=cwd,
                user=user,
            )

        if shell:
            command, args = "sh", ["-c", cmd]
        else:
            command, args = self._parse_cmd(cmd)

        # start_and_wait logic (previously in ProcessProtocol, now in API layer)
        start_time = time.monotonic()

        reader = await self._process.start(
            self._envd_url,
            self._envd_token,
            cmd=command,
            args=args,
            env=env,
            cwd=cwd,
            timeout=timeout,
            user=user,
        )

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        exit_code = 0

        async for chunk in reader:
            if chunk.type == ProcessChunkType.STDOUT:
                stdout_parts.append(chunk.data)
            elif chunk.type == ProcessChunkType.STDERR:
                stderr_parts.append(chunk.data)
            elif chunk.type == ProcessChunkType.EXIT:
                exit_code = chunk.exit_code or 0

        execution_time = time.monotonic() - start_time

        return ProcessResult(
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            exit_code=exit_code,
            execution_time=execution_time,
        )

    async def stream(
        self,
        cmd: str,
        *,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        cwd: str = "",
        user: str = "",
    ) -> AsyncIterator[ProcessChunk]:
        """Run a command and stream output chunks.

        Args:
            cmd: Shell command string.
            timeout: Max execution time in seconds.
            env: Additional environment variables.
            cwd: Working directory.
            user: OS user to run the command as.

        Yields:
            ProcessChunk items (stdout, stderr, exit events).
        """
        command, args = self._parse_cmd(cmd)
        reader = await self._process.start(
            self._envd_url,
            self._envd_token,
            cmd=command,
            args=args,
            env=env,
            cwd=cwd,
            timeout=timeout,
            user=user,
        )
        async for chunk in reader:
            yield chunk

    async def start(
        self,
        cmd: str,
        *,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        cwd: str = "",
        user: str = "",
    ) -> StreamReader[ProcessChunk]:
        """Start a command without waiting, returning a StreamReader.

        Args:
            cmd: Shell command string.
            timeout: Max execution time in seconds.
            env: Additional environment variables.
            cwd: Working directory.
            user: OS user to run the command as.

        Returns:
            StreamReader for consuming output asynchronously.
        """
        command, args = self._parse_cmd(cmd)
        return await self._process.start(
            self._envd_url,
            self._envd_token,
            cmd=command,
            args=args,
            env=env,
            cwd=cwd,
            timeout=timeout,
            user=user,
        )

    async def list(self) -> list[ProcessInfo]:
        """List running processes in the sandbox."""
        return await self._process.list_processes(
            self._envd_url,
            self._envd_token,
        )

    async def kill(self, pid: int) -> None:
        """Kill a process by PID."""
        await self._process.kill(
            self._envd_url,
            self._envd_token,
            pid=pid,
        )

    async def send_stdin(self, pid: int, data: str) -> None:
        """Send data to a process's stdin.

        Deprecated: use send_input() instead.

        Args:
            pid: Process ID.
            data: String data to send.
        """
        await self.send_input(pid, data)

    async def send_input(self, pid: int, data: str) -> None:
        """Send data to a process's stdin.

        Args:
            pid: Process ID.
            data: String data to send.
        """
        await self._process.send_input(
            self._envd_url,
            self._envd_token,
            pid=pid,
            data=data,
        )

    async def send_signal(self, pid: int, signal: int = 15) -> None:
        """Send a signal to a process (e.g. SIGTERM=15, SIGKILL=9).

        Args:
            pid: Process ID.
            signal: Signal number (default: 15/SIGTERM).
        """
        await self._process.send_signal(
            self._envd_url,
            self._envd_token,
            pid=pid,
            signal=signal,
        )

    # Sync variants
    run_sync = make_sync(run)
    list_sync = make_sync(list)
    kill_sync = make_sync(kill)
    send_stdin_sync = make_sync(send_stdin)
    send_input_sync = make_sync(send_input)
    send_signal_sync = make_sync(send_signal)

    def stream_sync(
        self,
        cmd: str,
        *,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        cwd: str = "",
        user: str = "",
    ) -> list[ProcessChunk]:  # type: ignore[valid-type]
        """Synchronous variant of :meth:`stream`.

        Collects all chunks from the async generator and returns them
        as a list.  Unlike the other ``*_sync`` wrappers this cannot
        use :func:`make_sync` because ``stream()`` is an async
        generator, not a plain coroutine.

        Returns:
            List of :class:`ProcessChunk` items.
        """
        from easy_sandbox.utils.async_bridge import run_sync

        async def _collect() -> list[ProcessChunk]:
            chunks: list[ProcessChunk] = []
            async for chunk in self.stream(
                cmd,
                timeout=timeout,
                env=env,
                cwd=cwd,
                user=user,
            ):
                chunks.append(chunk)
            return chunks

        return run_sync(_collect())
