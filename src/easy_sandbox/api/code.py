"""Code context module — code interpreter for sandboxes.

通过 CodeInterpreterProtocol 调用 Code Interpreter RPC 服务。
支持 runCode、createCodeContext、listCodeContexts、
restartCodeContext、removeCodeContext 操作。

当 CodeInterpreter 服务不可用（HTTP 404）时，自动降级为通过
ProcessProtocol 写文件 + shell 执行的模式（与 @sandbox 装饰器同一机制），
对调用方透明。

注意：RPC 路径基于 E2B SDK 逆向推断，阿里云官方文档未公开
Code Interpreter 的底层传输细节。需实测验证。
"""
from __future__ import annotations

import base64
import time
from typing import Any, Callable
from uuid import uuid4

import httpx

from easy_sandbox.api.capability import check_capability
from easy_sandbox.models.process import CodeResult, ProcessChunkType
from easy_sandbox.models.template import DEFAULT_CAPABILITIES
from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol
from easy_sandbox.protocol.process import ProcessProtocol
from easy_sandbox.transport.auth import EnvdTokenManager
from easy_sandbox.utils.async_bridge import make_sync
from easy_sandbox.utils.logging import get_logger

logger = get_logger("api.code")

# Language → interpreter command for shell fallback (mirrors routes_devtools.py)
_LANGUAGE_COMMANDS: dict[str, str] = {
    "python": "python3",
    "javascript": "node",
    "typescript": "node",
    "shell": "bash",
    "bash": "bash",
    "r": "Rscript",
}

# Language → temp-file extension
_LANGUAGE_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "shell": ".sh",
    "bash": ".sh",
    "r": ".R",
}


class CodeContextModule:
    """Code interpreter — execute code snippets in the sandbox.

    Calls CodeInterpreterProtocol for code execution and context management.
    When the CodeInterpreter service is unavailable (HTTP 404), ``run()``
    falls back transparently to writing the code to a temp file and executing
    it via the process/shell protocol.

    注意：RPC 路径基于 E2B SDK 逆向推断，阿里云官方文档未公开
    Code Interpreter 的底层传输细节。需实测验证。
    """

    def __init__(
        self,
        sandbox_id: str,
        envd_url: str,
        envd_token: EnvdTokenManager,
        code_interpreter_protocol: CodeInterpreterProtocol,
        capabilities: set[str] | None = None,
        process_protocol: ProcessProtocol | None = None,
    ) -> None:
        self._sandbox_id = sandbox_id
        self._envd_url = envd_url
        self._envd_token = envd_token
        self._code = code_interpreter_protocol
        self._process = process_protocol
        self._capabilities = (
            capabilities if capabilities is not None else set(DEFAULT_CAPABILITIES)
        )
        # Assume CodeInterpreter is available until a 404 proves otherwise.
        self._ci_available = True

    async def run(
        self,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
        context_id: str | None = None,
        envs: dict[str, str] | None = None,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
        on_result: Callable[..., None] | None = None,
    ) -> CodeResult:
        """Execute code in the sandbox via Code Interpreter RPC.

        If the CodeInterpreter service returns HTTP 404 (not deployed on this
        backend), falls back transparently to shell execution — writes the code
        to a temp file and runs the appropriate interpreter via the process
        protocol (same mechanism as the ``@sandbox`` decorator).

        Args:
            code: Source code to execute.
            language: Programming language (default: python).
            timeout: Execution timeout in seconds.
            context_id: Optional execution context ID for stateful execution.
            envs: Optional environment variables for this execution.
            on_stdout: Optional callback invoked with stdout content.
            on_stderr: Optional callback invoked with stderr content.
            on_result: Optional callback invoked with the execution result dict.

        Returns:
            CodeResult with stdout, stderr, exit_code, and execution_time.
        """
        check_capability(self._capabilities, "code")

        # Fast path: CI already known unavailable — skip straight to fallback.
        if not self._ci_available:
            return await self._run_via_shell(
                code,
                language=language,
                timeout=timeout,
                envs=envs,
                on_stdout=on_stdout,
                on_stderr=on_stderr,
                on_result=on_result,
            )

        try:
            response = await self._code.run_code(
                self._sandbox_id,
                self._envd_url,
                self._envd_token,
                code=code,
                language=language,
                context_id=context_id,
                timeout=timeout,
                envs=envs,
                on_stdout=on_stdout,
                on_stderr=on_stderr,
                on_result=on_result,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning(
                    "CodeInterpreter service unavailable (HTTP 404), "
                    "falling back to shell execution"
                )
                self._ci_available = False
                return await self._run_via_shell(
                    code,
                    language=language,
                    timeout=timeout,
                    envs=envs,
                    on_stdout=on_stdout,
                    on_stderr=on_stderr,
                    on_result=on_result,
                )
            raise

        # Parse the RPC response into a CodeResult
        # Response format may vary; handle both direct and nested results
        result = response.get("result", response)
        return CodeResult(
            text=result.get("text", result.get("stdout", "")).strip(),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            exit_code=result.get("exitCode", result.get("exit_code", 0)),
            execution_time=result.get(
                "executionTime", result.get("execution_time", 0.0)
            ),
        )

    # ------------------------------------------------------------------
    # Shell fallback (CodeInterpreter 404)
    # ------------------------------------------------------------------

    async def _run_via_shell(
        self,
        code: str,
        *,
        language: str,
        timeout: int,
        envs: dict[str, str] | None,
        on_stdout: Callable[[str], None] | None,
        on_stderr: Callable[[str], None] | None,
        on_result: Callable[..., None] | None,
    ) -> CodeResult:
        """Execute code via the process protocol (shell fallback).

        Writes the code to a temp file using base64 (avoids shell-quoting
        issues), runs the appropriate interpreter, collects stdout/stderr,
        and cleans up.  Output format is aligned with CodeResult from the
        native CodeInterpreter path.
        """
        if self._process is None:
            raise RuntimeError(
                "Shell fallback for code execution requires process_protocol "
                "to be injected but it was not provided."
            )

        interpreter = _LANGUAGE_COMMANDS.get(language, language)
        ext = _LANGUAGE_EXTENSIONS.get(language, "")
        tmp_path = f"/tmp/_ebx_code_{uuid4().hex}{ext}"

        try:
            # Step 1 — write code to temp file via base64 (quoting-safe)
            b64_code = base64.b64encode(code.encode()).decode()
            write_reader = await self._process.start(
                self._envd_url,
                self._envd_token,
                cmd="python3",
                args=[
                    "-c",
                    (
                        f"import base64; "
                        f"open('{tmp_path}','wb')"
                        f".write(base64.b64decode('{b64_code}'))"
                    ),
                ],
                timeout=30,
            )
            async for _ in write_reader:
                pass  # drain

            # Step 2 — execute the code file with the correct interpreter
            start_time = time.monotonic()
            exec_reader = await self._process.start(
                self._envd_url,
                self._envd_token,
                cmd=interpreter,
                args=[tmp_path],
                env=envs or None,
                timeout=timeout,
            )

            stdout_parts: list[str] = []
            stderr_parts: list[str] = []
            exit_code = 0

            async for chunk in exec_reader:
                if chunk.type == ProcessChunkType.STDOUT:
                    stdout_parts.append(chunk.data)
                    if on_stdout and chunk.data:
                        on_stdout(chunk.data)
                elif chunk.type == ProcessChunkType.STDERR:
                    stderr_parts.append(chunk.data)
                    if on_stderr and chunk.data:
                        on_stderr(chunk.data)
                elif chunk.type == ProcessChunkType.EXIT:
                    exit_code = chunk.exit_code or 0

            execution_time = time.monotonic() - start_time
            stdout = "".join(stdout_parts)
            stderr = "".join(stderr_parts)

            if on_result:
                on_result({
                    "stdout": stdout,
                    "stderr": stderr,
                    "exitCode": exit_code,
                    "executionTime": execution_time,
                })

            return CodeResult(
                text=stdout.strip(),
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                output_files=[],
                execution_time=execution_time,
            )
        finally:
            # Best-effort cleanup of the temp file — runs even if Step 2 raises
            try:
                rm_reader = await self._process.start(
                    self._envd_url,
                    self._envd_token,
                    cmd="rm",
                    args=["-f", tmp_path],
                    timeout=10,
                )
                async for _ in rm_reader:
                    pass
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Context management (require live CodeInterpreter service)
    # ------------------------------------------------------------------

    def reset_ci_availability(self) -> None:
        """Re-enable CodeInterpreter probing after backend recovery.

        After calling this, the next :meth:`run` call will attempt the native
        CodeInterpreter RPC again instead of going straight to the shell
        fallback.  If the service still returns 404 the flag will be set
        back to *unavailable* automatically.
        """
        self._ci_available = True

    def _check_ci_available(self, operation: str) -> None:
        """Raise if CI is known unavailable (set after first 404)."""
        if not self._ci_available:
            raise NotImplementedError(
                f"Context operation '{operation}' requires the CodeInterpreter "
                "service which is currently unavailable (HTTP 404). Code "
                "execution works via shell fallback but stateful contexts "
                "are not supported in fallback mode."
            )

    async def create_context(
        self,
        *,
        language: str = "python",
    ) -> dict[str, Any]:
        """Create a new execution context.

        注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认。

        Args:
            language: Programming language for the context.

        Returns:
            Context info dict (includes contextId).
        """
        check_capability(self._capabilities, "code")
        self._check_ci_available("create_context")
        return await self._code.create_context(
            self._sandbox_id,
            self._envd_url,
            self._envd_token,
            language=language,
        )

    async def list_contexts(self) -> list[dict[str, Any]]:
        """List all execution contexts.

        注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认。

        Returns:
            List of context info dicts.
        """
        self._check_ci_available("list_contexts")
        return await self._code.list_contexts(
            self._sandbox_id,
            self._envd_url,
            self._envd_token,
        )

    async def restart_context(self, context_id: str) -> dict[str, Any]:
        """Restart an execution context.

        注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认。

        Args:
            context_id: ID of the context to restart.

        Returns:
            Updated context info dict.
        """
        check_capability(self._capabilities, "code")
        self._check_ci_available("restart_context")
        return await self._code.restart_context(
            self._sandbox_id,
            self._envd_url,
            self._envd_token,
            context_id=context_id,
        )

    async def remove_context(self, context_id: str) -> None:
        """Remove an execution context.

        注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认。

        Args:
            context_id: ID of the context to remove.
        """
        check_capability(self._capabilities, "code")
        self._check_ci_available("remove_context")
        await self._code.remove_context(
            self._sandbox_id,
            self._envd_url,
            self._envd_token,
            context_id=context_id,
        )

    # Sync variants
    run_sync = make_sync(run)
    create_context_sync = make_sync(create_context)
    list_contexts_sync = make_sync(list_contexts)
    restart_context_sync = make_sync(restart_context)
    remove_context_sync = make_sync(remove_context)
