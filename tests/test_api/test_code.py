"""Tests for the CodeContextModule API."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from easy_sandbox.api.code import CodeContextModule
from easy_sandbox.models.process import CodeResult


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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

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


# ======================================================================
# Fallback tests — CodeInterpreter 404 → shell execution
# ======================================================================


def _make_404_exc() -> httpx.HTTPStatusError:
    """Create a realistic httpx.HTTPStatusError with status 404."""
    request = httpx.Request("POST", "https://envd/code.CodeInterpreter/Execute")
    response = httpx.Response(status_code=404, request=request)
    return httpx.HTTPStatusError(
        "404 Not Found", request=request, response=response
    )


def _make_500_exc() -> httpx.HTTPStatusError:
    """Create a realistic httpx.HTTPStatusError with status 500."""
    request = httpx.Request("POST", "https://envd/code.CodeInterpreter/Execute")
    response = httpx.Response(status_code=500, request=request)
    return httpx.HTTPStatusError(
        "500 Internal Server Error", request=request, response=response
    )


def _mock_process_stream(stdout: str = "", stderr: str = "", exit_code: int = 0):
    """Return a _MockStreamReader that yields typical process chunks."""
    from easy_sandbox.models.process import ProcessChunk, ProcessChunkType
    from tests.test_api.conftest import _MockStreamReader

    chunks = []
    if stdout:
        chunks.append(ProcessChunk(type=ProcessChunkType.STDOUT, data=stdout))
    if stderr:
        chunks.append(ProcessChunk(type=ProcessChunkType.STDERR, data=stderr))
    chunks.append(ProcessChunk(type=ProcessChunkType.EXIT, exit_code=exit_code))
    return _MockStreamReader(chunks)


class TestCodeRunFallback:
    """CodeInterpreter 404 → transparent shell fallback."""

    @pytest.mark.asyncio
    async def test_fallback_on_404_produces_code_result(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """404 from CI → fallback via process protocol → valid CodeResult."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        # write-file call, exec call, rm call
        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),                           # write
            _mock_process_stream(stdout="42\n", exit_code=0),  # exec
            _mock_process_stream(),                           # rm
        ]

        result = await code_module.run("print(42)")
        assert isinstance(result, CodeResult)
        assert result.text == "42"
        assert result.stdout == "42\n"
        assert result.exit_code == 0
        assert result.output_files == []
        assert result.execution_time > 0
        # process.start called 3 times (write, exec, rm)
        assert mock_process_protocol.start.await_count == 3

    @pytest.mark.asyncio
    async def test_fallback_stderr_and_nonzero_exit(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """Fallback captures stderr and non-zero exit code."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stderr="NameError: foo\n", exit_code=1),
            _mock_process_stream(),
        ]

        result = await code_module.run("foo")
        assert result.exit_code == 1
        assert "NameError" in result.stderr
        assert result.success is False

    @pytest.mark.asyncio
    async def test_normal_path_no_fallback(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """When CI works, process protocol is never called."""
        result = await code_module.run("print(42)")
        assert result.text == "42"
        # process_protocol.start should NOT have been called
        mock_process_protocol.start.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_404_error_propagates(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        """Non-404 HTTPStatusError (e.g. 500) is NOT swallowed."""
        import httpx

        mock_code_interpreter_protocol.run_code.side_effect = _make_500_exc()

        with pytest.raises(httpx.HTTPStatusError) as ei:
            await code_module.run("print(1)")
        assert ei.value.response.status_code == 500

    @pytest.mark.asyncio
    async def test_second_run_skips_ci_directly(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """After first 404, subsequent runs skip CI entirely."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="first\n"),
            _mock_process_stream(),
            # second run:
            _mock_process_stream(),
            _mock_process_stream(stdout="second\n"),
            _mock_process_stream(),
        ]

        r1 = await code_module.run("print('first')")
        r2 = await code_module.run("print('second')")

        assert r1.text == "first"
        assert r2.text == "second"
        # CI was only called once (the first time, which 404'd)
        assert mock_code_interpreter_protocol.run_code.await_count == 1

    @pytest.mark.asyncio
    async def test_fallback_callbacks_fire(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """on_stdout / on_stderr / on_result fire during fallback."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="out\n", stderr="err\n"),
            _mock_process_stream(),
        ]

        out: list[str] = []
        err: list[str] = []
        res: list[dict] = []

        await code_module.run(
            "x=1",
            on_stdout=out.append,
            on_stderr=err.append,
            on_result=res.append,
        )

        assert out == ["out\n"]
        assert err == ["err\n"]
        assert len(res) == 1
        assert res[0]["stdout"] == "out\n"

    @pytest.mark.asyncio
    async def test_create_context_blocked_after_404(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """Context operations raise NotImplementedError after CI 404."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="ok\n"),
            _mock_process_stream(),
        ]
        await code_module.run("print('ok')")  # triggers 404 → flag set

        with pytest.raises(NotImplementedError, match="CodeInterpreter"):
            await code_module.create_context()

        with pytest.raises(NotImplementedError, match="CodeInterpreter"):
            await code_module.list_contexts()

        with pytest.raises(NotImplementedError, match="CodeInterpreter"):
            await code_module.restart_context("ctx-1")

        with pytest.raises(NotImplementedError, match="CodeInterpreter"):
            await code_module.remove_context("ctx-1")

    @pytest.mark.asyncio
    async def test_fallback_no_process_protocol_raises(
        self,
    ) -> None:
        """If process_protocol was not injected, fallback raises RuntimeError."""
        from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol

        mock_ci = AsyncMock(spec=CodeInterpreterProtocol)
        mock_ci.run_code.side_effect = _make_404_exc()

        envd_token = AsyncMock()
        module = CodeContextModule(
            sandbox_id="sbx-1",
            envd_url="https://envd",
            envd_token=envd_token,
            code_interpreter_protocol=mock_ci,
            # process_protocol deliberately omitted
        )

        with pytest.raises(RuntimeError, match="process_protocol"):
            await module.run("print(1)")

    @pytest.mark.asyncio
    async def test_fallback_multiline_code(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """Multi-line code (import + prints) aggregates stdout correctly."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="3\nhello\n", exit_code=0),
            _mock_process_stream(),
        ]

        code = "import math\nprint(1+2)\nprint('hello')"
        result = await code_module.run(code)
        assert result.text == "3\nhello"
        assert result.stdout == "3\nhello\n"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_normal_path_multiline_code(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        """Multi-line code via CI path aggregates correctly."""
        mock_code_interpreter_protocol.run_code.return_value = {
            "stdout": "3\nhello\n",
            "stderr": "",
            "exitCode": 0,
            "executionTime": 0.02,
        }

        code = "import math\nprint(1+2)\nprint('hello')"
        result = await code_module.run(code)
        assert result.text == "3\nhello"
        assert result.stdout == "3\nhello\n"

    @pytest.mark.asyncio
    async def test_fallback_javascript_uses_node(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """language='javascript' → cmd='node', extension='.js'."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="hi\n"),
            _mock_process_stream(),
        ]

        result = await code_module.run("console.log('hi')", language="javascript")
        assert result.text == "hi"
        # Second start call is the exec call
        exec_call = mock_process_protocol.start.call_args_list[1]
        assert exec_call.kwargs["cmd"] == "node"
        assert exec_call.kwargs["args"][0].endswith(".js")

    @pytest.mark.asyncio
    async def test_fallback_bash_uses_bash(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """language='bash' → cmd='bash', extension='.sh'."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="ok\n"),
            _mock_process_stream(),
        ]

        result = await code_module.run("echo ok", language="bash")
        assert result.text == "ok"
        exec_call = mock_process_protocol.start.call_args_list[1]
        assert exec_call.kwargs["cmd"] == "bash"
        assert exec_call.kwargs["args"][0].endswith(".sh")

    @pytest.mark.asyncio
    async def test_fallback_empty_stdout(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """Empty stdout + exit_code=0 produces empty text."""
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="", exit_code=0),
            _mock_process_stream(),
        ]

        result = await code_module.run("pass")
        assert result.text == ""
        assert result.stdout == ""
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_fallback_warning_logged(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """First 404 triggers a WARNING log with expected message."""
        import logging

        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()

        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="x\n"),
            _mock_process_stream(),
        ]

        with caplog.at_level(logging.WARNING, logger="easy_sandbox.api.code"):
            await code_module.run("print('x')")

        assert any(
            "CodeInterpreter service unavailable (HTTP 404)" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_reset_ci_availability(
        self,
        code_module: CodeContextModule,
        mock_code_interpreter_protocol: AsyncMock,
        mock_process_protocol: AsyncMock,
    ) -> None:
        """reset_ci_availability() re-enables CI probing."""
        # First call: 404 → fallback
        mock_code_interpreter_protocol.run_code.side_effect = _make_404_exc()
        mock_process_protocol.start.side_effect = [
            _mock_process_stream(),
            _mock_process_stream(stdout="fb\n"),
            _mock_process_stream(),
        ]
        r1 = await code_module.run("print('fb')")
        assert r1.text == "fb"
        assert mock_code_interpreter_protocol.run_code.await_count == 1

        # Reset + CI now works
        code_module.reset_ci_availability()
        mock_code_interpreter_protocol.run_code.side_effect = None
        mock_code_interpreter_protocol.run_code.return_value = {
            "stdout": "native\n",
            "stderr": "",
            "exitCode": 0,
            "executionTime": 0.01,
        }

        r2 = await code_module.run("print('native')")
        assert r2.text == "native"
        # CI was called again (count goes to 2)
        assert mock_code_interpreter_protocol.run_code.await_count == 2
        # process protocol was NOT called for the second run (still 3 from first)
        assert mock_process_protocol.start.await_count == 3
