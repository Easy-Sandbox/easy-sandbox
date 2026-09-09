"""Code Interpreter 协议层。

注意：当前实现基于 E2B SDK 逆向推断，阿里云官方文档未公开
Code Interpreter 的底层传输细节。需实测验证。

Uses Connect RPC over HTTP with application/connect+json content type.

RPC endpoints:
- /code.CodeInterpreter/Execute — Execute code in a context
- /code.CodeInterpreter/CreateContext — Create an execution context
- /code.CodeInterpreter/ListContexts — List execution contexts
- /code.CodeInterpreter/RestartContext — Restart an execution context
- /code.CodeInterpreter/RemoveContext — Remove an execution context
"""
from __future__ import annotations

from typing import Any, Callable

from serverless_sandbox.transport.auth import EnvdTokenManager
from serverless_sandbox.transport.codec import ConnectCodec
from serverless_sandbox.transport.http import HttpClient
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("protocol.code_interpreter")

_codec = ConnectCodec()

# RPC paths — 注意：路径基于 E2B SDK 逆向推断，未经官方文档确认
_EXECUTE = _codec.build_rpc_path("code", "CodeInterpreter", "Execute")
_CREATE_CONTEXT = _codec.build_rpc_path("code", "CodeInterpreter", "CreateContext")
_LIST_CONTEXTS = _codec.build_rpc_path("code", "CodeInterpreter", "ListContexts")
_RESTART_CONTEXT = _codec.build_rpc_path("code", "CodeInterpreter", "RestartContext")
_REMOVE_CONTEXT = _codec.build_rpc_path("code", "CodeInterpreter", "RemoveContext")


class CodeInterpreterProtocol:
    """Code Interpreter Connect RPC 协议客户端。

    注意：当前实现基于 E2B SDK 逆向推断，阿里云官方文档未公开
    Code Interpreter 的底层传输细节。所有 RPC 路径和请求/响应格式
    均需实测验证。
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    async def run_code(
        self,
        sandbox_id: str,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        code: str,
        language: str = "python",
        context_id: str | None = None,
        timeout: int = 30,
        envs: dict[str, str] | None = None,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
        on_result: Callable[..., None] | None = None,
    ) -> dict[str, Any]:
        """执行代码。对应官方 sandbox.runCode() / sandbox.run_code()。

        POST envd_url + /code.CodeInterpreter/Execute (Connect unary)
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认

        Implementation note — **buffered fallback path**:
        The CodeInterpreter/Execute endpoint is accessed as a Connect unary
        RPC (not a server-streaming RPC), so true incremental streaming is
        not available at the protocol level.  When ``on_stdout``,
        ``on_stderr``, or ``on_result`` callbacks are supplied they are
        invoked **once** after the full response is received — this keeps
        the E2B-style callback API contract (callers can rely on the
        callbacks firing) while the underlying transport remains unary.
        """
        payload: dict[str, Any] = {
            "code": code,
            "language": language,
            "timeout": timeout,
        }
        if context_id:
            payload["contextId"] = context_id
        if envs:
            payload["envVars"] = envs

        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        response = await self._http.envd_request(
            envd_url, _EXECUTE,
            payload=payload,
            envd_token=envd_token,
        )

        # --- Buffered callback dispatch ------------------------------------
        # Fire callbacks with the complete response data so callers using
        # the E2B streaming-callback style still receive notifications.
        if on_stdout or on_stderr or on_result:
            result = response.get("result", response)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")

            if on_stdout and stdout:
                on_stdout(stdout)
            if on_stderr and stderr:
                on_stderr(stderr)
            if on_result:
                on_result(result)

        return response

    async def create_context(
        self,
        sandbox_id: str,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        language: str = "python",
    ) -> dict[str, Any]:
        """创建执行上下文。对应官方 sandbox.createCodeContext()。

        POST envd_url + /code.CodeInterpreter/CreateContext (Connect unary)
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        response = await self._http.envd_request(
            envd_url, _CREATE_CONTEXT,
            payload={"language": language},
            envd_token=envd_token,
        )
        return response

    async def list_contexts(
        self,
        sandbox_id: str,
        envd_url: str,
        envd_token: EnvdTokenManager,
    ) -> list[dict[str, Any]]:
        """查询执行上下文列表。对应官方 sandbox.listCodeContexts()。

        POST envd_url + /code.CodeInterpreter/ListContexts (Connect unary)
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        response = await self._http.envd_request(
            envd_url, _LIST_CONTEXTS,
            payload={},
            envd_token=envd_token,
        )
        contexts = response.get("contexts", response.get("result", {}).get("contexts", []))
        return contexts

    async def restart_context(
        self,
        sandbox_id: str,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        context_id: str,
    ) -> dict[str, Any]:
        """重启执行上下文。对应官方 sandbox.restartCodeContext()。

        POST envd_url + /code.CodeInterpreter/RestartContext (Connect unary)
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        response = await self._http.envd_request(
            envd_url, _RESTART_CONTEXT,
            payload={"contextId": context_id},
            envd_token=envd_token,
        )
        return response

    async def remove_context(
        self,
        sandbox_id: str,
        envd_url: str,
        envd_token: EnvdTokenManager,
        *,
        context_id: str,
    ) -> None:
        """删除执行上下文。对应官方 sandbox.removeCodeContext()。

        POST envd_url + /code.CodeInterpreter/RemoveContext (Connect unary)
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        # 注意：RPC 路径基于 E2B SDK 逆向推断，未经官方文档确认
        await self._http.envd_request(
            envd_url, _REMOVE_CONTEXT,
            payload={"contextId": context_id},
            envd_token=envd_token,
        )
