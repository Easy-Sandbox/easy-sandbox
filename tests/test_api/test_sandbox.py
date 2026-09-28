"""Tests for the Sandbox core API class."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from easy_sandbox.api.sandbox import Sandbox
from easy_sandbox.models.errors import CommandNotFoundError
from easy_sandbox.models.process import CodeResult
from easy_sandbox.models.sandbox import SandboxConfig, SandboxInfo, SandboxStatus
from easy_sandbox.transport.auth import EnvdTokenManager
from easy_sandbox.transport.config import TransportConfig
from easy_sandbox.transport.http import HttpClient
from tests.test_api.conftest import (
    TEST_API_KEY,
    TEST_ENVD_TOKEN,
    TEST_ENVD_URL,
    TEST_SANDBOX_ID,
    make_sandbox_info,
)


class TestSandboxProperties:
    """Test Sandbox instance properties."""

    def test_id(self, sandbox: Sandbox) -> None:
        assert sandbox.id == TEST_SANDBOX_ID

    def test_status(self, sandbox: Sandbox) -> None:
        assert sandbox.status == SandboxStatus.RUNNING

    def test_url(self, sandbox: Sandbox) -> None:
        assert sandbox.url == TEST_ENVD_URL

    def test_info(self, sandbox: Sandbox) -> None:
        assert sandbox.info.sandbox_id == TEST_SANDBOX_ID
        assert sandbox.info.template == "python-base"

    def test_repr(self, sandbox: Sandbox) -> None:
        r = repr(sandbox)
        assert TEST_SANDBOX_ID in r
        assert "running" in r


class TestSandboxCreate:
    """Test Sandbox.create() classmethod."""

    @pytest.mark.asyncio
    async def test_create_returns_sandbox(self) -> None:
        info = make_sandbox_info()

        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        mock_http = AsyncMock(spec=HttpClient)
        mock_auth = AsyncMock()
        mock_auth.get_headers.return_value = {"X-API-KEY": TEST_API_KEY}

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_load_config,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_create_auth,
            patch("easy_sandbox.api.sandbox.HttpClient") as mock_http_cls,
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_proto_cls,
        ):
            mock_load_config.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_create_auth.return_value = mock_auth
            mock_http_cls.return_value = mock_http
            mock_proto_cls.return_value = mock_sandbox_proto

            sb = await Sandbox.create(template="python-base", api_key=TEST_API_KEY)

            assert sb.id == TEST_SANDBOX_ID
            assert sb.status == SandboxStatus.RUNNING
            assert sb.url == TEST_ENVD_URL
            mock_sandbox_proto.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_passes_config(self) -> None:
        info = make_sandbox_info()

        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_load_config,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_create_auth,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_proto_cls,
        ):
            mock_load_config.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_create_auth.return_value = AsyncMock()
            mock_proto_cls.return_value = mock_sandbox_proto

            await Sandbox.create(
                template="node-base",
                timeout=600,
                envs={"FOO": "bar"},
                api_key=TEST_API_KEY,
            )

            call_args = mock_sandbox_proto.create.call_args
            config: SandboxConfig = call_args[0][0]
            assert config.template == "node-base"
            assert config.timeout == 600
            assert config.env_vars == {"FOO": "bar"}

    @pytest.mark.asyncio
    async def test_create_default_request_timeout_is_none(self) -> None:
        """Without an explicit request_timeout, None is forwarded (default behaviour)."""
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_load_config,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_create_auth,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_proto_cls,
        ):
            mock_load_config.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_create_auth.return_value = AsyncMock()
            mock_proto_cls.return_value = mock_sandbox_proto

            await Sandbox.create(template="base", api_key=TEST_API_KEY)

            assert mock_sandbox_proto.create.call_args.kwargs["request_timeout"] is None

    @pytest.mark.asyncio
    async def test_create_explicit_request_timeout_forwarded(self) -> None:
        """An explicit request_timeout reaches SandboxProtocol.create() as a kwarg."""
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_load_config,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_create_auth,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_proto_cls,
        ):
            mock_load_config.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_create_auth.return_value = AsyncMock()
            mock_proto_cls.return_value = mock_sandbox_proto

            await Sandbox.create(
                template="python-hello",
                request_timeout=120.0,
                api_key=TEST_API_KEY,
            )

            assert mock_sandbox_proto.create.call_args.kwargs["request_timeout"] == 120.0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_value", [0, -1, -0.5])
    async def test_create_rejects_non_positive_request_timeout(self, bad_value: float) -> None:
        """request_timeout must be positive when provided; else ValueError."""
        with pytest.raises(ValueError, match="request_timeout must be a positive number"):
            await Sandbox.create(
                template="base",
                request_timeout=bad_value,
                api_key=TEST_API_KEY,
            )


class TestSandboxConnect:
    """Test Sandbox.connect() classmethod."""

    @pytest.mark.asyncio
    async def test_connect_returns_sandbox(self) -> None:
        info = make_sandbox_info()

        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.connect.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_load_config,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_create_auth,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_proto_cls,
        ):
            mock_load_config.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_create_auth.return_value = AsyncMock()
            mock_proto_cls.return_value = mock_sandbox_proto

            sb = await Sandbox.connect(TEST_SANDBOX_ID, api_key=TEST_API_KEY)

            assert sb.id == TEST_SANDBOX_ID
            mock_sandbox_proto.connect.assert_called_once_with(TEST_SANDBOX_ID)


class TestSandboxLifecycle:
    """Test kill, set_timeout, is_running, pause."""

    @pytest.mark.asyncio
    async def test_kill_calls_protocol_and_closes_http(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        await sandbox.kill()
        mock_sandbox_protocol.kill.assert_called_once_with(TEST_SANDBOX_ID)
        mock_http_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_kill_closes_http_even_on_protocol_error(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        mock_sandbox_protocol.kill.side_effect = Exception("kill failed")
        with pytest.raises(Exception, match="kill failed"):
            await sandbox.kill()
        # HTTP client should still be closed
        mock_http_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_timeout(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
    ) -> None:
        await sandbox.set_timeout(600)
        mock_sandbox_protocol.set_timeout.assert_called_once_with(TEST_SANDBOX_ID, 600)

    @pytest.mark.asyncio
    async def test_is_running(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
    ) -> None:
        result = await sandbox.is_running()
        assert result is True
        mock_sandbox_protocol.is_running.assert_called_once_with(TEST_SANDBOX_ID)

    @pytest.mark.asyncio
    async def test_pause(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
    ) -> None:
        await sandbox.pause()
        mock_sandbox_protocol.pause.assert_called_once_with(TEST_SANDBOX_ID)


class TestSandboxContextManager:
    """Test async context manager behavior."""

    @pytest.mark.asyncio
    async def test_context_manager_calls_kill_on_exit(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
        mock_http_client: AsyncMock,
    ) -> None:
        async with sandbox:
            pass
        mock_sandbox_protocol.kill.assert_called_once_with(TEST_SANDBOX_ID)
        mock_http_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_suppresses_kill_error(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
    ) -> None:
        mock_sandbox_protocol.kill.side_effect = Exception("kill failed")
        # Should NOT raise
        async with sandbox:
            pass

    @pytest.mark.asyncio
    async def test_context_manager_enters_returns_sandbox(
        self,
        sandbox: Sandbox,
    ) -> None:
        async with sandbox as sb:
            assert sb is sandbox


class TestSandboxSubmodules:
    """Test lazy cached property sub-modules."""

    def test_commands_property(self, sandbox: Sandbox) -> None:
        from easy_sandbox.api.commands import CommandsModule

        cmds = sandbox.commands
        assert isinstance(cmds, CommandsModule)
        # Cached - same object
        assert sandbox.commands is cmds

    def test_files_property(self, sandbox: Sandbox) -> None:
        from easy_sandbox.api.files import FilesModule

        files = sandbox.files
        assert isinstance(files, FilesModule)
        assert sandbox.files is files

    def test_network_property(self, sandbox: Sandbox) -> None:
        from easy_sandbox.api.network import NetworkModule

        net = sandbox.network
        assert isinstance(net, NetworkModule)
        assert sandbox.network is net

    def test_code_property(self, sandbox: Sandbox) -> None:
        from easy_sandbox.api.code import CodeContextModule

        code = sandbox.code
        assert isinstance(code, CodeContextModule)
        assert sandbox.code is code


class TestSandboxRunCode:
    """Test the run_code convenience method."""

    @pytest.mark.asyncio
    async def test_run_code_delegates_to_code_module(
        self,
        sandbox: Sandbox,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        result = await sandbox.run_code("print(42)")
        assert isinstance(result, CodeResult)
        # Should have called run_code on the code interpreter protocol
        mock_code_interpreter_protocol.run_code.assert_called()


class TestSandboxSyncVariants:
    """Test sync method wrappers exist and are callable."""

    def test_create_sync_exists(self) -> None:
        assert hasattr(Sandbox, "create_sync")
        assert callable(Sandbox.create_sync)

    def test_kill_sync_exists(self) -> None:
        assert hasattr(Sandbox, "kill_sync")
        assert callable(Sandbox.kill_sync)

    def test_run_code_sync_exists(self) -> None:
        assert hasattr(Sandbox, "run_code_sync")
        assert callable(Sandbox.run_code_sync)

    def test_resume_sync_exists(self) -> None:
        assert hasattr(Sandbox, "resume_sync")
        assert callable(Sandbox.resume_sync)

    def test_get_terminal_sync_exists(self) -> None:
        assert hasattr(Sandbox, "get_terminal_sync")
        assert callable(Sandbox.get_terminal_sync)


class TestSandboxResourceParams:
    """Test cpu/memory/disk/gpu payload mapping through create()."""

    @pytest.mark.asyncio
    async def test_create_with_cpu_memory(self) -> None:
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            await Sandbox.create(
                template="python-base",
                cpu=4,
                memory=8192,
                api_key=TEST_API_KEY,
            )

            config: SandboxConfig = mock_sandbox_proto.create.call_args[0][0]
            assert config.cpu == 4
            assert config.memory == 8192
            payload = config.to_create_payload()
            assert payload["cpuCount"] == 4
            assert payload["memoryMB"] == 8192
            assert "diskSizeMB" not in payload
            assert "gpu" not in payload

    @pytest.mark.asyncio
    async def test_create_with_disk_gpu(self) -> None:
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            await Sandbox.create(
                template="python-base",
                disk=10240,
                gpu="A10",
                api_key=TEST_API_KEY,
            )

            config: SandboxConfig = mock_sandbox_proto.create.call_args[0][0]
            assert config.disk == 10240
            assert config.gpu == "A10"
            payload = config.to_create_payload()
            assert payload["diskSizeMB"] == 10240
            assert payload["gpu"] == "A10"
            assert "cpuCount" not in payload
            assert "memoryMB" not in payload

    @pytest.mark.asyncio
    async def test_create_without_resources_omits_keys(self) -> None:
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            await Sandbox.create(template="base", api_key=TEST_API_KEY)

            config: SandboxConfig = mock_sandbox_proto.create.call_args[0][0]
            payload = config.to_create_payload()
            assert "cpuCount" not in payload
            assert "memoryMB" not in payload
            assert "diskSizeMB" not in payload
            assert "gpu" not in payload


class TestSandboxDescriptionInfer:
    """Test that description with default template logs a hint (infer removed from API layer)."""

    @pytest.mark.asyncio
    async def test_description_logs_hint_uses_base(self) -> None:
        """description + default template logs a hint and uses 'base' template."""
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            await Sandbox.create(
                description="分析 CSV 数据并画图",
                api_key=TEST_API_KEY,
            )

            # Template should remain "base" since infer is no longer called
            config: SandboxConfig = mock_sandbox_proto.create.call_args[0][0]
            assert config.template == "base"

    @pytest.mark.asyncio
    async def test_explicit_template_skips_hint(self) -> None:
        """Explicit template does not trigger description hint."""
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            await Sandbox.create(
                template="node-web",
                description="分析 CSV 数据",
                api_key=TEST_API_KEY,
            )

            config: SandboxConfig = mock_sandbox_proto.create.call_args[0][0]
            assert config.template == "node-web"

    @pytest.mark.asyncio
    async def test_explicit_cpu_memory_preserved(self) -> None:
        """Explicit cpu/memory are preserved when description is given."""
        info = make_sandbox_info()
        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            await Sandbox.create(
                description="运行 Python",
                cpu=8,
                memory=16384,
                api_key=TEST_API_KEY,
            )

            config: SandboxConfig = mock_sandbox_proto.create.call_args[0][0]
            assert config.cpu == 8
            assert config.memory == 16384


class TestSandboxResume:
    """Test resume() method."""

    @pytest.mark.asyncio
    async def test_resume(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
    ) -> None:
        await sandbox.resume()
        mock_sandbox_protocol.resume.assert_called_once_with(TEST_SANDBOX_ID)


class TestSandboxRunCodeEnvs:
    """Test run_code envs pass-through."""

    @pytest.mark.asyncio
    async def test_run_code_passes_envs(
        self,
        sandbox: Sandbox,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await sandbox.run_code("print(1)", envs={"MY_VAR": "123"})
        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["envs"] == {"MY_VAR": "123"}

    @pytest.mark.asyncio
    async def test_run_code_without_envs(
        self,
        sandbox: Sandbox,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        await sandbox.run_code("print(1)")
        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["envs"] is None


class TestSandboxRunCodeCallbacks:
    """Test run_code streaming callback pass-through."""

    @pytest.mark.asyncio
    async def test_run_code_forwards_callbacks(
        self,
        sandbox: Sandbox,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        """run_code() forwards on_stdout/on_stderr/on_result to the protocol."""
        cb = MagicMock()
        await sandbox.run_code(
            "print(1)",
            on_stdout=cb,
            on_stderr=cb,
            on_result=cb,
        )
        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["on_stdout"] is cb
        assert call_kwargs["on_stderr"] is cb
        assert call_kwargs["on_result"] is cb

    @pytest.mark.asyncio
    async def test_run_code_without_callbacks_still_works(
        self,
        sandbox: Sandbox,
        mock_code_interpreter_protocol: AsyncMock,
    ) -> None:
        """run_code() without callbacks preserves existing behavior."""
        result = await sandbox.run_code("print(42)")
        assert isinstance(result, CodeResult)
        call_kwargs = mock_code_interpreter_protocol.run_code.call_args.kwargs
        assert call_kwargs["on_stdout"] is None
        assert call_kwargs["on_stderr"] is None
        assert call_kwargs["on_result"] is None


class TestSandboxE2BUrlStubs:
    """Test get_upload_url / get_download_url raise NotImplementedError."""

    @pytest.mark.asyncio
    async def test_get_upload_url_raises_not_implemented(
        self,
        sandbox: Sandbox,
    ) -> None:
        with pytest.raises(NotImplementedError, match="get_upload_url is not yet implemented"):
            await sandbox.get_upload_url("/app/data.csv")

    @pytest.mark.asyncio
    async def test_get_download_url_raises_not_implemented(
        self,
        sandbox: Sandbox,
    ) -> None:
        with pytest.raises(NotImplementedError, match="get_download_url is not yet implemented"):
            await sandbox.get_download_url("/app/data.csv")


class TestSandboxTerminal:
    """Test terminal wiring."""

    @pytest.mark.asyncio
    async def test_get_terminal_calls_terminal_session_create(
        self,
        sandbox: Sandbox,
    ) -> None:
        mock_session = AsyncMock()
        with patch(
            "easy_sandbox.protocol.terminal.TerminalSession.create",
            new_callable=AsyncMock,
            return_value=mock_session,
        ) as mock_create:
            terminal = await sandbox.get_terminal(cols=120, rows=40)
            assert terminal is mock_session
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["cols"] == 120
            assert call_kwargs["rows"] == 40


class TestSandboxEnvdUrlDerivation:
    """Test envd URL derivation when platform response omits envdUrl (Bug 1)."""

    @pytest.mark.asyncio
    async def test_create_derives_envd_url_when_missing(self) -> None:
        """create() should derive envd_url via build_envd_url when API omits it."""
        # Simulate real FC response: no envdUrl field
        info = SandboxInfo.model_validate(
            {
                "sandboxID": TEST_SANDBOX_ID,
                "templateID": "base",
                "envdAccessToken": TEST_ENVD_TOKEN,
                "envdVersion": "0.5.2",
            }
        )
        assert info.envd_url is None  # precondition

        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.create.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            sb = await Sandbox.create(template="base", api_key=TEST_API_KEY)

            expected_url = f"https://49983-{TEST_SANDBOX_ID}.cn-hangzhou.e2b.fc.aliyuncs.com"
            assert sb.url == expected_url
            assert sb.url != ""

    @pytest.mark.asyncio
    async def test_connect_derives_envd_url_when_missing(self) -> None:
        """connect() should derive envd_url via build_envd_url when API omits it."""
        info = SandboxInfo.model_validate(
            {
                "sandboxID": TEST_SANDBOX_ID,
                "templateID": "base",
                "envdAccessToken": TEST_ENVD_TOKEN,
                "envdVersion": "0.5.2",
            }
        )

        mock_sandbox_proto = AsyncMock()
        mock_sandbox_proto.connect.return_value = info

        with (
            patch("easy_sandbox.api.sandbox.load_config") as mock_lc,
            patch("easy_sandbox.api.sandbox.create_auth_provider") as mock_ca,
            patch("easy_sandbox.api.sandbox.HttpClient"),
            patch("easy_sandbox.api.sandbox.SandboxProtocol") as mock_pc,
        ):
            mock_lc.return_value = TransportConfig(api_key=TEST_API_KEY)
            mock_ca.return_value = AsyncMock()
            mock_pc.return_value = mock_sandbox_proto

            sb = await Sandbox.connect(TEST_SANDBOX_ID, api_key=TEST_API_KEY)

            expected_url = f"https://49983-{TEST_SANDBOX_ID}.cn-hangzhou.e2b.fc.aliyuncs.com"
            assert sb.url == expected_url

    @pytest.mark.asyncio
    async def test_refresh_info_derives_envd_url_when_missing(
        self,
        sandbox: Sandbox,
        mock_sandbox_protocol: AsyncMock,
    ) -> None:
        """refresh_info() should re-derive envd_url if platform still omits it."""
        refreshed_info = SandboxInfo.model_validate(
            {
                "sandboxID": TEST_SANDBOX_ID,
                "templateID": "python-base",
                "envdAccessToken": TEST_ENVD_TOKEN,
            }
        )
        mock_sandbox_protocol.get_info.return_value = refreshed_info

        result = await sandbox.refresh_info()

        expected_url = f"https://49983-{TEST_SANDBOX_ID}.cn-hangzhou.e2b.fc.aliyuncs.com"
        assert result.envd_url == expected_url
        assert sandbox.url == expected_url

    def test_existing_envd_url_not_overwritten(self) -> None:
        """If platform provides envdUrl, it should NOT be overwritten."""
        info = make_sandbox_info()  # includes envd_url
        original_url = info.envd_url
        assert original_url  # precondition

        sb = Sandbox(
            info=info,
            config=TransportConfig(api_key=TEST_API_KEY),
            http_client=AsyncMock(spec=HttpClient),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
        )

        assert sb.url == original_url


class TestSandboxRunCommand:
    """Test Sandbox.custom() (mechanism B) and the run_command alias."""

    @pytest.mark.asyncio
    async def test_custom_server_success(
        self,
        sandbox: Sandbox,
        mock_http_client: AsyncMock,
    ) -> None:
        """custom() returns a server-sourced CommandResult on HTTP 200."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"result": 42}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_http_client._create_envd_client.return_value = mock_client

        result = await sandbox.custom("add", x=1, y=2)

        assert result.value == 42
        assert result.source == "server"
        assert result.exit_code == 0
        assert result.success is True
        mock_client.post.assert_called_once_with(
            "/commands/add",
            json={"x": 1, "y": 2},
            headers=mock_client.post.call_args.kwargs["headers"],
        )

    @pytest.mark.asyncio
    async def test_custom_server_error_returns_exit_code_1(
        self,
        sandbox: Sandbox,
        mock_http_client: AsyncMock,
    ) -> None:
        """A reachable server that fails (non-404) yields exit_code=1, not a raise."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.json.return_value = {
            "error": "boom",
            "type": "RuntimeError",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_http_client._create_envd_client.return_value = mock_client

        result = await sandbox.custom("bad")

        assert result.source == "server"
        assert result.exit_code == 1
        assert result.success is False
        assert "RuntimeError: boom" in result.stderr

    @pytest.mark.asyncio
    async def test_custom_server_404_raises_command_not_found(
        self,
        sandbox: Sandbox,
        mock_http_client: AsyncMock,
    ) -> None:
        """A 404 from the server means the command is genuinely unknown."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 404
        mock_response.json.return_value = {
            "error": "not found",
            "type": "ValueError",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_http_client._create_envd_client.return_value = mock_client

        with pytest.raises(CommandNotFoundError):
            await sandbox.custom("nonexistent")

    @pytest.mark.asyncio
    async def test_custom_connection_failure_caches_probe(
        self,
        sandbox: Sandbox,
        mock_http_client: AsyncMock,
    ) -> None:
        """A connection failure raises CommandNotFoundError, sets the probe
        flag, and short-circuits subsequent calls without re-hitting HTTP."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        mock_http_client._create_envd_client.return_value = mock_client

        with pytest.raises(CommandNotFoundError):
            await sandbox.custom("whatever")
        assert sandbox._server_probe_failed is True

        # Second call is short-circuited by the cached probe flag.
        with pytest.raises(CommandNotFoundError):
            await sandbox.custom("whatever")
        assert mock_client.post.await_count == 1

        # reset_server_probe() re-enables mechanism-B probing.
        sandbox.reset_server_probe()
        assert sandbox._server_probe_failed is False

    @pytest.mark.asyncio
    async def test_run_command_deprecated_alias(
        self,
        sandbox: Sandbox,
        mock_http_client: AsyncMock,
    ) -> None:
        """run_command() warns DeprecationWarning and returns CommandResult.value."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"result": 7}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_http_client._create_envd_client.return_value = mock_client

        with pytest.warns(DeprecationWarning, match="custom"):
            result = await sandbox.run_command("add", x=1)

        assert result == 7

    @pytest.mark.asyncio
    async def test_custom_name_kwarg_no_conflict(
        self,
        sandbox: Sandbox,
        mock_http_client: AsyncMock,
    ) -> None:
        """custom('hello', name='World') must not raise TypeError.

        Because ``name`` is positional-only (after the ``/``), passing
        ``name=`` as a keyword goes into **kwargs, not the command-name
        parameter.
        """
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"result": "Hello World"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_http_client._create_envd_client.return_value = mock_client

        result = await sandbox.custom("hello", name="World")

        assert result.value == "Hello World"
        assert result.source == "server"
        mock_client.post.assert_called_once_with(
            "/commands/hello",
            json={"name": "World"},
            headers=mock_client.post.call_args.kwargs["headers"],
        )

    @pytest.mark.asyncio
    async def test_custom_502_non_json_raises_command_not_found(
        self,
        sandbox: Sandbox,
        mock_http_client: AsyncMock,
    ) -> None:
        """A 502 with non-JSON body should raise CommandNotFoundError,
        not a raw RuntimeError."""
        import json as _json

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 502
        mock_response.text = "<html>502 Bad Gateway</html>"
        mock_response.json.side_effect = _json.JSONDecodeError("x", "y", 0)

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_http_client._create_envd_client.return_value = mock_client

        with pytest.raises(CommandNotFoundError, match="invalid response"):
            await sandbox.custom("anything")

        # Should also cache the probe failure.
        assert sandbox._server_probe_failed is True
