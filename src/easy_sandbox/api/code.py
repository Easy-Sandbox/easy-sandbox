"""Code context module — code interpreter for sandboxes.

通过 CodeInterpreterProtocol 调用 Code Interpreter RPC 服务。
支持 runCode、createCodeContext、listCodeContexts、
restartCodeContext、removeCodeContext 操作。

注意：RPC 路径基于 E2B SDK 逆向推断，阿里云官方文档未公开
Code Interpreter 的底层传输细节。需实测验证。
"""
from __future__ import annotations

from typing import Any, Callable

from easy_sandbox.api.capability import check_capability
from easy_sandbox.models.process import CodeResult
from easy_sandbox.models.template import DEFAULT_CAPABILITIES
from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol
from easy_sandbox.transport.auth import EnvdTokenManager
from easy_sandbox.utils.async_bridge import make_sync
from easy_sandbox.utils.logging import get_logger

logger = get_logger("api.code")


class CodeContextModule:
    """Code interpreter — execute code snippets in the sandbox.

    Calls CodeInterpreterProtocol for code execution and context management.

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
    ) -> None:
        self._sandbox_id = sandbox_id
        self._envd_url = envd_url
        self._envd_token = envd_token
        self._code = code_interpreter_protocol
        self._capabilities = capabilities if capabilities is not None else set(DEFAULT_CAPABILITIES)

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

        注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认。

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

        # Parse the RPC response into a CodeResult
        # Response format may vary; handle both direct and nested results
        result = response.get("result", response)
        return CodeResult(
            text=result.get("text", result.get("stdout", "")).strip(),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            exit_code=result.get("exitCode", result.get("exit_code", 0)),
            execution_time=result.get("executionTime", result.get("execution_time", 0.0)),
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
