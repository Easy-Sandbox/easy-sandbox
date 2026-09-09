"""Tests for the CodeContextModule API."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from serverless_sandbox.api.code import CodeContextModule
from serverless_sandbox.models.process import CodeResult


class TestCodeRun:
    """Test CodeContextModule.run()."""

    @pytest.mark.asyncio
    async def test_run_returns_code_result(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        result = await code_module.run("print(42)")
        assert isinstance(result, CodeResult)
        assert result.text == "42"
        assert result.stdout == "42\n"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_calls_run_code(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await code_module.run("print('ok')", language="python", timeout=60)

        mock_code_interpreter_protocol.run_code.assert_called_once()
        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["code"] == "print('ok')"
        assert call_kwargs["language"] == "python"
        assert call_kwargs["timeout"] == 60

    @pytest.mark.asyncio
    async def test_run_javascript(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        mock_code_interpreter_protocol.run_code.return_value = {
            "stdout": "hello\n",
            "stderr": "",
            "exitCode": 0,
            "executionTime": 0.01,
        }

        result = await code_module.run("console.log('hello')", language="javascript")
        assert result.text == "hello"

        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["language"] == "javascript"

    @pytest.mark.asyncio
    async def test_run_with_timeout(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await code_module.run("x = 1", timeout=120)

        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["timeout"] == 120

    @pytest.mark.asyncio
    async def test_run_with_context_id(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await code_module.run("x = 1", context_id="ctx-test-123")

        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["context_id"] == "ctx-test-123"

    @pytest.mark.asyncio
    async def test_run_captures_stderr(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        mock_code_interpreter_protocol.run_code.return_value = {
            "stdout": "",
            "stderr": "NameError: name 'foo' is not defined\n",
            "exitCode": 1,
            "executionTime": 0.02,
        }

        result = await code_module.run("foo")
        assert result.exit_code == 1
        assert "NameError" in result.stderr
        assert result.success is False

    @pytest.mark.asyncio
    async def test_run_result_wrapper(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        """Test handling of response with 'result' wrapper."""
        mock_code_interpreter_protocol.run_code.return_value = {
            "result": {
                "stdout": "wrapped\n",
                "stderr": "",
                "exitCode": 0,
                "executionTime": 0.01,
            }
        }

        result = await code_module.run("print('wrapped')")
        assert result.text == "wrapped"
        assert result.stdout == "wrapped\n"


class TestCodeCreateContext:
    """Test CodeContextModule.create_context()."""

    @pytest.mark.asyncio
    async def test_create_context(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        result = await code_module.create_context(language="python")
        assert result["contextId"] == "ctx-001"

        mock_code_interpreter_protocol.create_context.assert_called_once()
        call_kwargs = mock_code_interpreter_protocol.create_context.call_args.kwargs
        assert call_kwargs["language"] == "python"


class TestCodeListContexts:
    """Test CodeContextModule.list_contexts()."""

    @pytest.mark.asyncio
    async def test_list_contexts(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        result = await code_module.list_contexts()
        assert len(result) == 1
        assert result[0]["contextId"] == "ctx-001"
        mock_code_interpreter_protocol.list_contexts.assert_called_once()


class TestCodeRestartContext:
    """Test CodeContextModule.restart_context()."""

    @pytest.mark.asyncio
    async def test_restart_context(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        result = await code_module.restart_context("ctx-001")
        assert result["status"] == "active"

        mock_code_interpreter_protocol.restart_context.assert_called_once()
        call_kwargs = mock_code_interpreter_protocol.restart_context.call_args.kwargs
        assert call_kwargs["context_id"] == "ctx-001"


class TestCodeRemoveContext:
    """Test CodeContextModule.remove_context()."""

    @pytest.mark.asyncio
    async def test_remove_context(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await code_module.remove_context("ctx-001")
        mock_code_interpreter_protocol.remove_context.assert_called_once()
        call_kwargs = mock_code_interpreter_protocol.remove_context.call_args.kwargs
        assert call_kwargs["context_id"] == "ctx-001"


class TestCodeSyncVariants:
    """Test sync wrappers exist."""

    def test_run_sync_exists(self) -> None:
        assert hasattr(CodeContextModule, "run_sync")
        assert callable(CodeContextModule.run_sync)

    def test_create_context_sync_exists(self) -> None:
        assert hasattr(CodeContextModule, "create_context_sync")
        assert callable(CodeContextModule.create_context_sync)

    def test_list_contexts_sync_exists(self) -> None:
        assert hasattr(CodeContextModule, "list_contexts_sync")
        assert callable(CodeContextModule.list_contexts_sync)


class TestCodeRunEnvs:
    """Test envs pass-through on run()."""

    @pytest.mark.asyncio
    async def test_run_passes_envs(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await code_module.run("print(1)", envs={"FOO": "bar", "X": "1"})

        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["envs"] == {"FOO": "bar", "X": "1"}

    @pytest.mark.asyncio
    async def test_run_without_envs(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await code_module.run("print(1)")

        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["envs"] is None

    @pytest.mark.asyncio
    async def test_envs_reach_protocol_payload(
        self,
    ) -> None:
        """Verify envs end up as envVars in the protocol payload."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "ok\n", "stderr": "", "exitCode": 0, "executionTime": 0.01,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="print(1)", envs={"K": "V"},
        )

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert payload["envVars"] == {"K": "V"}

    @pytest.mark.asyncio
    async def test_no_envs_omits_envVars_key(
        self,
    ) -> None:
        """Verify envVars is NOT in payload when envs is None."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "ok\n", "stderr": "", "exitCode": 0, "executionTime": 0.01,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="print(1)",
        )

        payload = mock_http.envd_request.call_args.kwargs["payload"]
        assert "envVars" not in payload


class TestCodeRunStreamingCallbacks:
    """Test E2B-style streaming callbacks (buffered fallback)."""

    @pytest.mark.asyncio
    async def test_on_stdout_fires_at_protocol_level(
        self,
    ) -> None:
        """on_stdout callback is invoked with stdout content at protocol layer."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "42\n", "stderr": "", "exitCode": 0, "executionTime": 0.05,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        collected: list[str] = []
        await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="print(42)",
            on_stdout=collected.append,
        )
        assert collected == ["42\n"]

    @pytest.mark.asyncio
    async def test_on_stderr_fires_at_protocol_level(
        self,
    ) -> None:
        """on_stderr callback is invoked with stderr content at protocol layer."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "", "stderr": "error msg\n", "exitCode": 1, "executionTime": 0.01,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        collected: list[str] = []
        await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="bad()",
            on_stderr=collected.append,
        )
        assert collected == ["error msg\n"]

    @pytest.mark.asyncio
    async def test_on_result_fires_with_result_dict(
        self,
    ) -> None:
        """on_result callback receives the full result dict."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "42\n", "stderr": "", "exitCode": 0, "executionTime": 0.05,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        results: list[dict] = []
        await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="print(42)",
            on_result=results.append,
        )
        assert len(results) == 1
        assert results[0]["stdout"] == "42\n"

    @pytest.mark.asyncio
    async def test_all_callbacks_fire_together(
        self,
    ) -> None:
        """All three callbacks fire when all are provided."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "out\n", "stderr": "err\n", "exitCode": 0, "executionTime": 0.05,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        out: list[str] = []
        err: list[str] = []
        res: list[dict] = []

        response = await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="x=1",
            on_stdout=out.append,
            on_stderr=err.append,
            on_result=res.append,
        )
        assert out == ["out\n"]
        assert err == ["err\n"]
        assert len(res) == 1
        # Response dict is still returned
        assert response["stdout"] == "out\n"

    @pytest.mark.asyncio
    async def test_no_callbacks_preserves_behavior(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        """Omitting callbacks returns CodeResult as before."""
        result = await code_module.run("print(42)")
        assert isinstance(result, CodeResult)
        assert result.text == "42"

    @pytest.mark.asyncio
    async def test_on_stdout_not_called_when_empty(
        self,
    ) -> None:
        """on_stdout is NOT called when stdout is empty."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "", "stderr": "", "exitCode": 0, "executionTime": 0.01,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        collected: list[str] = []
        await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="pass",
            on_stdout=collected.append,
        )
        assert collected == []

    @pytest.mark.asyncio
    async def test_callbacks_forwarded_through_api_layer(
        self,
    ) -> None:
        """Verify callbacks pass from CodeContextModule.run() to protocol."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "stdout": "hello\n", "stderr": "warn\n",
            "exitCode": 0, "executionTime": 0.01,
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        module = CodeContextModule(
            sandbox_id="sbx-1",
            envd_url="https://envd",
            envd_token=envd_token,
            code_interpreter_protocol=proto,
        )

        out: list[str] = []
        err: list[str] = []
        res: list[dict] = []

        result = await module.run(
            "print('hello')",
            on_stdout=out.append,
            on_stderr=err.append,
            on_result=res.append,
        )

        assert out == ["hello\n"]
        assert err == ["warn\n"]
        assert len(res) == 1
        assert isinstance(result, CodeResult)
        assert result.text == "hello"

    @pytest.mark.asyncio
    async def test_callbacks_with_wrapped_result(
        self,
    ) -> None:
        """Callbacks work with response that wraps data in 'result' key."""
        from serverless_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_http = AsyncMock()
        mock_http.envd_request.return_value = {
            "result": {
                "stdout": "wrapped\n",
                "stderr": "",
                "exitCode": 0,
                "executionTime": 0.02,
            }
        }
        proto = CodeInterpreterProtocol(mock_http)
        envd_token = AsyncMock()

        out: list[str] = []
        res: list[dict] = []

        await proto.run_code(
            "sbx-1", "https://envd", envd_token,
            code="print('wrapped')",
            on_stdout=out.append,
            on_result=res.append,
        )

        assert out == ["wrapped\n"]
        assert res[0]["stdout"] == "wrapped\n"

    @pytest.mark.asyncio
    async def test_callbacks_params_accepted_by_run(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        """run() accepts callback kwargs and forwards them to protocol."""
        cb = MagicMock()
        await code_module.run(
            "print(1)",
            on_stdout=cb,
            on_stderr=cb,
            on_result=cb,
        )
        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["on_stdout"] is cb
        assert call_kwargs["on_stderr"] is cb
        assert call_kwargs["on_result"] is cb
