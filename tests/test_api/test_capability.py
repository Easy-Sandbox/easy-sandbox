"""Tests for capability model, gating, custom commands, and resolver."""
from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

import easy_sandbox.api.capability as capability_mod
from easy_sandbox.api.capability import (
    ResolvedCapabilities,
    check_capability,
    resolve_capabilities,
)
from easy_sandbox.api.code import CodeContextModule
from easy_sandbox.api.commands import CommandsModule
from easy_sandbox.api.files import FilesModule
from easy_sandbox.api.network import NetworkModule
from easy_sandbox.api.sandbox import Sandbox
from easy_sandbox.models.errors import (
    CapabilityNotSupportedError,
    TemplateParseError,
)
from easy_sandbox.models.process import (
    ProcessChunk,
    ProcessChunkType,
    ProcessResult,
)
from easy_sandbox.models.template import (
    DEFAULT_CAPABILITIES,
    STANDARD_CAPABILITIES,
    CustomCommand,
    CustomCommandArg,
    SandboxTemplate,
)
from easy_sandbox.transport.auth import EnvdTokenManager
from tests.test_api.conftest import (
    ALL_CAPABILITIES,
    TEST_ENVD_TOKEN,
    TEST_ENVD_URL,
    _MockStreamReader,
    make_sandbox_info,
)

if TYPE_CHECKING:
    from pathlib import Path


# =====================================================================
# 1. Template / Capability Model tests
# =====================================================================

class TestStandardCapabilities:
    """Verify the vocabulary and default baseline constants."""

    def test_standard_vocab(self) -> None:
        assert {"shell", "files", "code", "terminal", "ports"} == STANDARD_CAPABILITIES

    def test_default_baseline(self) -> None:
        assert {"shell", "files", "code"} == DEFAULT_CAPABILITIES
        assert "terminal" not in DEFAULT_CAPABILITIES
        assert "ports" not in DEFAULT_CAPABILITIES


class TestSandboxTemplateCapabilities:
    """Test SandboxTemplate capability field validation."""

    def test_none_capabilities_is_valid(self) -> None:
        t = SandboxTemplate(name="test")
        assert t.capabilities is None

    def test_valid_capabilities(self) -> None:
        t = SandboxTemplate(name="test", capabilities=["shell", "files", "ports"])
        assert t.capabilities == ["shell", "files", "ports"]

    def test_invalid_capability_raises(self) -> None:
        with pytest.raises(ValidationError, match="Unknown capability"):
            SandboxTemplate(name="test", capabilities=["shell", "invalid_cap"])

    def test_empty_capabilities_is_valid(self) -> None:
        t = SandboxTemplate(name="test", capabilities=[])
        assert t.capabilities == []

    def test_custom_commands_model(self) -> None:
        t = SandboxTemplate(
            name="test",
            custom_commands={
                "build": CustomCommand(
                    cmd="npm run build",
                    description="Build project",
                    args=[CustomCommandArg(name="mode", default="production")],
                ),
            },
        )
        assert "build" in t.custom_commands
        assert t.custom_commands["build"].cmd == "npm run build"
        assert t.custom_commands["build"].args[0].name == "mode"


# =====================================================================
# 2. CapabilityNotSupportedError
# =====================================================================

class TestCapabilityNotSupportedError:
    def test_error_code_and_message(self) -> None:
        err = CapabilityNotSupportedError("terminal")
        assert err.code == "E3004"
        assert "terminal" in err.message
        assert "terminal" in err.suggestion
        assert err.capability == "terminal"

    def test_custom_message(self) -> None:
        err = CapabilityNotSupportedError(
            "ports",
            message="Custom message",
            suggestion="Custom suggestion",
        )
        assert err.message == "Custom message"
        assert err.suggestion == "Custom suggestion"


# =====================================================================
# 3. Capability gating
# =====================================================================

class TestCheckCapability:
    """Test the check_capability helper."""

    def test_passes_when_present(self) -> None:
        check_capability({"shell", "files"}, "shell")  # no error

    def test_raises_when_missing(self) -> None:
        with pytest.raises(CapabilityNotSupportedError) as exc_info:
            check_capability({"shell"}, "terminal")
        assert exc_info.value.capability == "terminal"


class TestCommandsGating:
    """Verify commands.run/stream/start require 'shell'."""

    @pytest.mark.asyncio
    async def test_run_blocked_without_shell(self) -> None:
        mod = CommandsModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=AsyncMock(),
            capabilities={"files", "code"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="shell"):
            await mod.run("echo hi")

    @pytest.mark.asyncio
    async def test_stream_blocked_without_shell(self) -> None:
        mod = CommandsModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=AsyncMock(),
            capabilities={"files"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="shell"):
            async for _ in mod.stream("ls"):
                pass

    @pytest.mark.asyncio
    async def test_start_blocked_without_shell(self) -> None:
        mod = CommandsModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=AsyncMock(),
            capabilities={"files"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="shell"):
            await mod.start("ls")

    @pytest.mark.asyncio
    async def test_run_allowed_with_shell(self) -> None:
        proto = AsyncMock()
        proto.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        mod = CommandsModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=proto,
            capabilities={"shell"},
        )
        result = await mod.run("echo ok")
        assert isinstance(result, ProcessResult)


class TestFilesGating:
    """Verify files.read/write/... require 'files'."""

    @pytest.mark.asyncio
    async def test_read_blocked_without_files(self) -> None:
        mod = FilesModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            filesystem_protocol=AsyncMock(),
            capabilities={"shell"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="files"):
            await mod.read("/app/x.py")

    @pytest.mark.asyncio
    async def test_write_blocked_without_files(self) -> None:
        mod = FilesModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            filesystem_protocol=AsyncMock(),
            capabilities={"shell"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="files"):
            await mod.write("/app/x.py", "content")

    @pytest.mark.asyncio
    async def test_upload_url_blocked_without_files(self) -> None:
        mod = FilesModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            filesystem_protocol=AsyncMock(),
            capabilities={"shell"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="files"):
            await mod.upload_url("/app/x.py")

    @pytest.mark.asyncio
    async def test_download_url_blocked_without_files(self) -> None:
        mod = FilesModule(
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            filesystem_protocol=AsyncMock(),
            capabilities={"shell"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="files"):
            await mod.download_url("/app/x.py")


class TestCodeGating:
    """Verify code.run requires 'code'."""

    @pytest.mark.asyncio
    async def test_run_blocked_without_code(self) -> None:
        mod = CodeContextModule(
            sandbox_id="sbx-1",
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            code_interpreter_protocol=AsyncMock(),
            capabilities={"shell", "files"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="code"):
            await mod.run("print(1)")

    @pytest.mark.asyncio
    async def test_create_context_blocked_without_code(self) -> None:
        mod = CodeContextModule(
            sandbox_id="sbx-1",
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            code_interpreter_protocol=AsyncMock(),
            capabilities={"shell", "files"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="code"):
            await mod.create_context()

    @pytest.mark.asyncio
    async def test_restart_context_blocked_without_code(self) -> None:
        mod = CodeContextModule(
            sandbox_id="sbx-1",
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            code_interpreter_protocol=AsyncMock(),
            capabilities={"shell", "files"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="code"):
            await mod.restart_context("ctx-001")

    @pytest.mark.asyncio
    async def test_remove_context_blocked_without_code(self) -> None:
        mod = CodeContextModule(
            sandbox_id="sbx-1",
            envd_url=TEST_ENVD_URL,
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            code_interpreter_protocol=AsyncMock(),
            capabilities={"shell", "files"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="code"):
            await mod.remove_context("ctx-001")


class TestNetworkGating:
    """Verify network.get_host/get_url/get_access_headers require 'ports'."""

    def test_get_host_blocked_without_ports(self) -> None:
        mod = NetworkModule(
            sandbox_id="sbx-1",
            domain="example.com",
            capabilities={"shell"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="ports"):
            mod.get_host(8080)

    def test_get_url_blocked_without_ports(self) -> None:
        mod = NetworkModule(
            sandbox_id="sbx-1",
            domain="example.com",
            capabilities={"shell"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="ports"):
            mod.get_url(3000)

    def test_get_access_headers_blocked_without_ports(self) -> None:
        mod = NetworkModule(
            sandbox_id="sbx-1",
            domain="example.com",
            capabilities={"shell"},
        )
        with pytest.raises(CapabilityNotSupportedError, match="ports"):
            mod.get_access_headers()

    def test_allowed_with_ports(self) -> None:
        mod = NetworkModule(
            sandbox_id="sbx-1",
            domain="example.com",
            capabilities={"ports"},
        )
        host = mod.get_host(8080)
        assert "8080" in host


class TestSandboxGating:
    """Verify Sandbox.run_code / get_terminal check capabilities."""

    @pytest.mark.asyncio
    async def test_run_code_blocked_without_code(self) -> None:
        info = make_sandbox_info()
        resolved = ResolvedCapabilities(capabilities={"shell", "files"})
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            code_interpreter_protocol=AsyncMock(),
            resolved_capabilities=resolved,
        )
        with pytest.raises(CapabilityNotSupportedError, match="code"):
            await sb.run_code("print(1)")

    @pytest.mark.asyncio
    async def test_get_terminal_blocked_without_terminal(self) -> None:
        info = make_sandbox_info()
        resolved = ResolvedCapabilities(capabilities={"shell", "files", "code"})
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            resolved_capabilities=resolved,
        )
        with pytest.raises(CapabilityNotSupportedError, match="terminal"):
            await sb.get_terminal()


# =====================================================================
# 4. Sandbox.capabilities / list_commands / run
# =====================================================================

class TestSandboxCapabilitiesProperty:
    """Test Sandbox.capabilities property."""

    def test_returns_effective_set(self) -> None:
        info = make_sandbox_info()
        resolved = ResolvedCapabilities(capabilities={"shell", "files"})
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            resolved_capabilities=resolved,
        )
        assert sb.capabilities == {"shell", "files"}
        # Contract: capabilities property returns a frozenset.
        assert isinstance(sb.capabilities, frozenset)

    def test_default_when_no_resolved(self) -> None:
        info = make_sandbox_info()
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
        )
        assert sb.capabilities == set(DEFAULT_CAPABILITIES)


class TestSandboxListCommands:
    """Test Sandbox.list_commands()."""

    def test_returns_command_catalogue(self) -> None:
        info = make_sandbox_info()
        resolved = ResolvedCapabilities(
            capabilities=ALL_CAPABILITIES,
            custom_commands={
                "build": CustomCommand(
                    cmd="npm run build",
                    description="Build it",
                    args=[
                        CustomCommandArg(
                            name="mode",
                            required=False,
                            default="production",
                            description="Build mode",
                        ),
                    ],
                ),
                "test": CustomCommand(cmd="npm test", description="Test it"),
            },
        )
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            resolved_capabilities=resolved,
        )
        cmds = sb.list_commands()
        assert len(cmds) == 2
        by_name = {c["name"]: c for c in cmds}
        assert set(by_name) == {"build", "test"}

        # Contract: each entry carries name/description/args including type.
        build = by_name["build"]
        assert build["description"] == "Build it"
        assert isinstance(build["args"], list)
        assert len(build["args"]) == 1
        arg = build["args"][0]
        assert arg == {
            "name": "mode",
            "required": False,
            "default": "production",
            "description": "Build mode",
            "type": "string",
        }

        # A command with no declared args yields an empty args list.
        assert by_name["test"]["args"] == []

    def test_requires_shell_capability(self) -> None:
        """list_commands() raises when shell capability is missing."""
        from easy_sandbox.models.errors import CapabilityNotSupportedError

        info = make_sandbox_info()
        # No shell capability
        resolved = ResolvedCapabilities(capabilities={"files", "code"})
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            resolved_capabilities=resolved,
        )
        with pytest.raises(CapabilityNotSupportedError):
            sb.list_commands()

    def test_requires_auth(self) -> None:
        """list_commands() raises when envd token is not set."""
        from easy_sandbox.models.errors import TokenExpiredError

        info = make_sandbox_info()
        resolved = ResolvedCapabilities(capabilities=ALL_CAPABILITIES)
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(None),  # No token
            resolved_capabilities=resolved,
        )
        with pytest.raises(TokenExpiredError):
            sb.list_commands()


class TestSandboxRunCustomCommand:
    """Test Sandbox.run() custom command dispatch."""

    @pytest.mark.asyncio
    async def test_run_unknown_command(self) -> None:
        info = make_sandbox_info()
        resolved = ResolvedCapabilities(capabilities=ALL_CAPABILITIES)
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=AsyncMock(),
            resolved_capabilities=resolved,
        )
        with pytest.raises(ValueError, match="Unknown custom command"):
            await sb.run("nonexistent")

    @pytest.mark.asyncio
    async def test_run_missing_required_arg(self) -> None:
        info = make_sandbox_info()
        resolved = ResolvedCapabilities(
            capabilities=ALL_CAPABILITIES,
            custom_commands={
                "deploy": CustomCommand(
                    cmd="deploy {target}",
                    args=[CustomCommandArg(name="target", required=True)],
                ),
            },
        )
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=AsyncMock(),
            resolved_capabilities=resolved,
        )
        with pytest.raises(ValueError, match="Required argument"):
            await sb.run("deploy")

    @pytest.mark.asyncio
    async def test_run_fills_placeholders_with_shlex_quote(self) -> None:
        info = make_sandbox_info()
        mock_proto = AsyncMock()
        mock_proto.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.STDOUT, data="ok\n"),
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        resolved = ResolvedCapabilities(
            capabilities=ALL_CAPABILITIES,
            custom_commands={
                "greet": CustomCommand(
                    cmd="echo {msg}",
                    args=[CustomCommandArg(name="msg", required=True)],
                ),
            },
        )
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=mock_proto,
            resolved_capabilities=resolved,
        )
        await sb.run("greet", msg="hello world; rm -rf /")
        # The argument should be shlex-quoted in the cmd string to
        # prevent injection.  After _parse_cmd (shlex.split), the
        # dangerous payload is a single atomic arg, not a separate command.
        call_args = mock_proto.start.call_args[1]["args"]
        # The arg list should contain exactly one element that is the
        # whole payload (shlex.split re-joins the quoted string).
        assert len(call_args) == 1
        assert call_args[0] == "hello world; rm -rf /"

    @pytest.mark.asyncio
    async def test_run_uses_default_arg(self) -> None:
        info = make_sandbox_info()
        mock_proto = AsyncMock()
        mock_proto.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        resolved = ResolvedCapabilities(
            capabilities=ALL_CAPABILITIES,
            custom_commands={
                "run": CustomCommand(
                    cmd="python3 {file}",
                    args=[CustomCommandArg(name="file", default="main.py")],
                ),
            },
        )
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=mock_proto,
            resolved_capabilities=resolved,
        )
        await sb.run("run")
        # Should have used default "main.py" → shlex-quoted
        call_kwargs = mock_proto.start.call_args[1]
        reconstructed = f"{call_kwargs['cmd']} {' '.join(call_kwargs['args'])}"
        assert "main.py" in reconstructed

    @pytest.mark.asyncio
    async def test_run_value_that_looks_like_placeholder_is_not_misjudged(
        self,
    ) -> None:
        """A legitimate value such as ``{id}`` must NOT be reported as an
        unfilled placeholder (single-pass substitution over the original
        template only)."""
        info = make_sandbox_info()
        mock_proto = AsyncMock()
        mock_proto.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        resolved = ResolvedCapabilities(
            capabilities=ALL_CAPABILITIES,
            custom_commands={
                "render": CustomCommand(
                    cmd="render {tpl}",
                    args=[CustomCommandArg(name="tpl", required=True)],
                ),
            },
        )
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=mock_proto,
            resolved_capabilities=resolved,
        )
        # Should NOT raise ValueError about unfilled placeholders.
        await sb.run("render", tpl="{id}")
        call_args = mock_proto.start.call_args[1]["args"]
        assert call_args == ["{id}"]

    @pytest.mark.asyncio
    async def test_run_no_second_pass_expansion_injection(self) -> None:
        """Injection attempt: a value that itself references another
        placeholder must NOT be re-expanded into extra argv tokens."""
        info = make_sandbox_info()
        mock_proto = AsyncMock()
        mock_proto.start.return_value = _MockStreamReader([
            ProcessChunk(type=ProcessChunkType.EXIT, exit_code=0),
        ])
        resolved = ResolvedCapabilities(
            capabilities=ALL_CAPABILITIES,
            custom_commands={
                "x": CustomCommand(
                    cmd="run {a} {b}",
                    args=[
                        CustomCommandArg(name="a", required=True),
                        CustomCommandArg(name="b", required=True),
                    ],
                ),
            },
        )
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=mock_proto,
            resolved_capabilities=resolved,
        )
        await sb.run("x", a="{b}", b="; rm -rf /")
        # After shlex.split, a's value stays a SINGLE token "{b}" — it was
        # not re-scanned/re-expanded into b's payload, and b's payload stays
        # one atomic token (no injected extra argv).
        call_args = mock_proto.start.call_args[1]["args"]
        assert call_args == ["{b}", "; rm -rf /"]

    @pytest.mark.asyncio
    async def test_run_rejects_undeclared_kwarg(self) -> None:
        """Passing an arg not declared in cmd_def.args raises ValueError
        instead of being silently dropped."""
        info = make_sandbox_info()
        resolved = ResolvedCapabilities(
            capabilities=ALL_CAPABILITIES,
            custom_commands={
                "greet": CustomCommand(
                    cmd="echo {msg}",
                    args=[CustomCommandArg(name="msg", required=True)],
                ),
            },
        )
        sb = Sandbox(
            info=info,
            config=MagicMock(),
            http_client=AsyncMock(),
            auth=AsyncMock(),
            envd_token=EnvdTokenManager(TEST_ENVD_TOKEN),
            process_protocol=AsyncMock(),
            resolved_capabilities=resolved,
        )
        with pytest.raises(ValueError, match="Unexpected argument"):
            await sb.run("greet", msg="hi", bogus="x")


# =====================================================================
# 5. Resolver tests
# =====================================================================

class TestResolveCapabilities:
    """Test resolve_capabilities from local YAML."""

    @pytest.mark.asyncio
    async def test_resolve_from_local_yaml(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            name: test-template
            capabilities:
              - shell
              - files
              - terminal
            custom_commands:
              build:
                cmd: "make build"
                description: "Build the project"
        """)
        yaml_file = tmp_path / "template.yaml"
        yaml_file.write_text(yaml_content)

        result = await resolve_capabilities(
            "test-template",
            local_yaml_path=str(yaml_file),
        )
        assert result.capabilities == {"shell", "files", "terminal"}
        assert "build" in result.custom_commands
        assert result.custom_commands["build"].cmd == "make build"

    @pytest.mark.asyncio
    async def test_resolve_fallback_to_defaults(self) -> None:
        """When template is not found, use DEFAULT_CAPABILITIES."""
        result = await resolve_capabilities("nonexistent-template-xyz")
        assert result.capabilities == set(DEFAULT_CAPABILITIES)
        assert result.custom_commands == {}

    @pytest.mark.asyncio
    async def test_resolve_none_capabilities_uses_defaults(
        self, tmp_path: Path,
    ) -> None:
        """A template with no capabilities field uses DEFAULT_CAPABILITIES."""
        yaml_content = textwrap.dedent("""\
            name: minimal
        """)
        yaml_file = tmp_path / "template.yaml"
        yaml_file.write_text(yaml_content)

        result = await resolve_capabilities(
            "minimal",
            local_yaml_path=str(yaml_file),
        )
        assert result.capabilities == set(DEFAULT_CAPABILITIES)

    @pytest.mark.asyncio
    async def test_malformed_local_yaml_fails_closed(
        self, tmp_path: Path,
    ) -> None:
        """A matched template whose capabilities fail validation must NOT
        silently fall back to DEFAULT_CAPABILITIES (permission widening)."""
        yaml_content = textwrap.dedent("""\
            name: broken
            capabilities:
              - shell
              - not_a_real_capability
        """)
        yaml_file = tmp_path / "template.yaml"
        yaml_file.write_text(yaml_content)

        with pytest.raises(TemplateParseError):
            await resolve_capabilities(
                "broken",
                local_yaml_path=str(yaml_file),
            )

    @pytest.mark.asyncio
    async def test_malformed_scanned_template_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scanning ~/.ebx/templates: a matched-but-malformed template
        raises instead of falling back to defaults."""
        cache = tmp_path / "templates"
        (cache / "broken-tmpl").mkdir(parents=True)
        (cache / "broken-tmpl" / "template.yaml").write_text(
            textwrap.dedent("""\
                name: broken-tmpl
                capabilities:
                  - bogus_capability
            """)
        )
        monkeypatch.setattr(capability_mod, "TEMPLATE_CACHE_DIR", cache)

        with pytest.raises(TemplateParseError):
            await resolve_capabilities("broken-tmpl")

    @pytest.mark.asyncio
    async def test_unreadable_scanned_template_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A non-dict / unreadable document cannot match, so it is skipped
        and resolution falls back to defaults (no fail-closed)."""
        cache = tmp_path / "templates"
        (cache / "junk").mkdir(parents=True)
        (cache / "junk" / "template.yaml").write_text("just a string\n")
        monkeypatch.setattr(capability_mod, "TEMPLATE_CACHE_DIR", cache)

        result = await resolve_capabilities("anything")
        assert result.capabilities == set(DEFAULT_CAPABILITIES)

    @pytest.mark.asyncio
    async def test_match_by_alias_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A template referenced by its ``alias`` field must be matched
        (previously only ``name`` was compared → wrongful DEFAULT fallback)."""
        cache = tmp_path / "templates"
        (cache / "some-dir").mkdir(parents=True)
        (cache / "some-dir" / "template.yaml").write_text(
            textwrap.dedent("""\
                name: real-name
                alias: my-alias
                capabilities:
                  - shell
                  - terminal
            """)
        )
        monkeypatch.setattr(capability_mod, "TEMPLATE_CACHE_DIR", cache)

        result = await resolve_capabilities("my-alias")
        assert result.capabilities == {"shell", "terminal"}

    @pytest.mark.asyncio
    async def test_match_by_aliases_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = tmp_path / "templates"
        (cache / "dir").mkdir(parents=True)
        (cache / "dir" / "template.yaml").write_text(
            textwrap.dedent("""\
                name: real-name
                aliases:
                  - first-alias
                  - second-alias
                capabilities:
                  - ports
            """)
        )
        monkeypatch.setattr(capability_mod, "TEMPLATE_CACHE_DIR", cache)

        result = await resolve_capabilities("second-alias")
        assert result.capabilities == {"ports"}

    @pytest.mark.asyncio
    async def test_match_by_directory_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A template referenced by its containing directory name matches."""
        cache = tmp_path / "templates"
        (cache / "dir-name-ref").mkdir(parents=True)
        (cache / "dir-name-ref" / "template.yaml").write_text(
            textwrap.dedent("""\
                name: something-else
                capabilities:
                  - shell
                  - ports
            """)
        )
        monkeypatch.setattr(capability_mod, "TEMPLATE_CACHE_DIR", cache)

        result = await resolve_capabilities("dir-name-ref")
        assert result.capabilities == {"shell", "ports"}


# =====================================================================
# 6. Default capabilities in default-constructed modules
# =====================================================================

class TestDefaultCapabilities:
    """Modules get DEFAULT_CAPABILITIES when none are passed."""

    def test_commands_default(self) -> None:
        mod = CommandsModule(
            envd_url="http://x",
            envd_token=EnvdTokenManager("tok"),
            process_protocol=AsyncMock(),
        )
        assert mod._capabilities == set(DEFAULT_CAPABILITIES)

    def test_files_default(self) -> None:
        mod = FilesModule(
            envd_url="http://x",
            envd_token=EnvdTokenManager("tok"),
            filesystem_protocol=AsyncMock(),
        )
        assert mod._capabilities == set(DEFAULT_CAPABILITIES)

    def test_code_default(self) -> None:
        mod = CodeContextModule(
            sandbox_id="sbx-1",
            envd_url="http://x",
            envd_token=EnvdTokenManager("tok"),
            code_interpreter_protocol=AsyncMock(),
        )
        assert mod._capabilities == set(DEFAULT_CAPABILITIES)

    def test_network_default(self) -> None:
        mod = NetworkModule(
            sandbox_id="sbx-1",
            domain="example.com",
        )
        assert mod._capabilities == set(DEFAULT_CAPABILITIES)
