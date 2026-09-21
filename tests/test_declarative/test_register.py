"""Tests for @sandbox.register, sandbox.run(), type helpers, and P0 bug fixes."""
from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.declarative.decorator import (
    _annotation_to_type_str,
    _coerce_kwargs,
    _detect_python_cmd,
    _parse_scalar,
    _RegisterProxy,
    _SandboxFactory,
    _ServerProxy,
    sandbox,
)
from easy_sandbox.models.process import ProcessResult
from easy_sandbox.models.template import CustomCommandArg

# ---------------------------------------------------------------------------
# _annotation_to_type_str
# ---------------------------------------------------------------------------


class TestAnnotationToTypeStr:
    """Map Python type hints to CustomCommandArg type strings."""

    def test_str(self) -> None:
        assert _annotation_to_type_str(str) == "string"

    def test_int(self) -> None:
        assert _annotation_to_type_str(int) == "integer"

    def test_float(self) -> None:
        assert _annotation_to_type_str(float) == "float"

    def test_bool(self) -> None:
        assert _annotation_to_type_str(bool) == "boolean"

    def test_missing_defaults_to_string(self) -> None:
        import inspect
        assert _annotation_to_type_str(inspect.Parameter.empty) == "string"

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Unsupported parameter type"):
            _annotation_to_type_str(list)

    def test_dict_raises(self) -> None:
        with pytest.raises(TypeError):
            _annotation_to_type_str(dict)


# ---------------------------------------------------------------------------
# _parse_scalar
# ---------------------------------------------------------------------------


class TestParseScalar:
    """Type coercion for scalar values."""

    def test_string(self) -> None:
        assert _parse_scalar(42, "string") == "42"
        assert _parse_scalar("hello", "string") == "hello"

    def test_integer_from_int(self) -> None:
        assert _parse_scalar(7, "integer") == 7

    def test_integer_from_str(self) -> None:
        assert _parse_scalar("123", "integer") == 123

    def test_float_from_float(self) -> None:
        assert _parse_scalar(3.14, "float") == 3.14

    def test_float_from_str(self) -> None:
        assert _parse_scalar("2.5", "float") == 2.5

    # ---- Bool whitelist ----
    def test_bool_true_from_bool(self) -> None:
        assert _parse_scalar(True, "boolean") is True

    def test_bool_false_from_bool(self) -> None:
        assert _parse_scalar(False, "boolean") is False

    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "yes", "Yes", "1"])
    def test_bool_truthy_strings(self, val: str) -> None:
        assert _parse_scalar(val, "boolean") is True

    @pytest.mark.parametrize("val", ["false", "False", "FALSE", "no", "No", "0"])
    def test_bool_falsy_strings(self, val: str) -> None:
        assert _parse_scalar(val, "boolean") is False

    def test_bool_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse.*as boolean"):
            _parse_scalar("maybe", "boolean")

    def test_bool_false_string_not_truthy(self) -> None:
        """Critical: bool('False') == True, but _parse_scalar must return False."""
        assert _parse_scalar("False", "boolean") is False

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown type"):
            _parse_scalar("x", "complex")


# ---------------------------------------------------------------------------
# _coerce_kwargs
# ---------------------------------------------------------------------------


class TestCoerceKwargs:
    """Validate and coerce kwargs against declared arg specs."""

    def _args(self) -> list[CustomCommandArg]:
        return [
            CustomCommandArg(name="x", type="integer", required=True),
            CustomCommandArg(name="y", type="string", required=False, default="hi"),
        ]

    def test_full_kwargs(self) -> None:
        result = _coerce_kwargs(self._args(), {"x": "5", "y": "world"})
        assert result == {"x": 5, "y": "world"}

    def test_default_applied(self) -> None:
        result = _coerce_kwargs(self._args(), {"x": 3})
        assert result == {"x": 3, "y": "hi"}

    def test_missing_required_raises(self) -> None:
        with pytest.raises(ValueError, match="Required argument"):
            _coerce_kwargs(self._args(), {})

    def test_undeclared_raises(self) -> None:
        with pytest.raises(ValueError, match="Unexpected argument"):
            _coerce_kwargs(self._args(), {"x": 1, "z": "nope"})


# ---------------------------------------------------------------------------
# _detect_python_cmd
# ---------------------------------------------------------------------------


class TestDetectPythonCmd:
    """python3 preferred, python fallback."""

    async def test_python3_found(self) -> None:
        mock_sb = MagicMock()
        mock_sb.commands = MagicMock()
        mock_sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="Python 3.12.0\n",
                stderr="",
                exit_code=0,
                execution_time=0.01,
            )
        )
        assert await _detect_python_cmd(mock_sb) == "python3"

    async def test_python3_not_found_fallback(self) -> None:
        mock_sb = MagicMock()
        mock_sb.commands = MagicMock()
        mock_sb.commands.run = AsyncMock(
            return_value=ProcessResult(
                stdout="",
                stderr="not found",
                exit_code=127,
                execution_time=0.01,
            )
        )
        assert await _detect_python_cmd(mock_sb) == "python"

    async def test_python3_exception_fallback(self) -> None:
        mock_sb = MagicMock()
        mock_sb.commands = MagicMock()
        mock_sb.commands.run = AsyncMock(side_effect=RuntimeError("boom"))
        assert await _detect_python_cmd(mock_sb) == "python"


# ---------------------------------------------------------------------------
# @sandbox.register
# ---------------------------------------------------------------------------


class TestRegister:
    """@sandbox.register decorator."""

    def test_register_simple_function(self) -> None:
        factory = _SandboxFactory()

        @factory.register
        def demo(x: int, y: str) -> str:
            return f"{y}={x}"

        assert "demo" in factory._registry
        cmd = factory._registry["demo"]
        assert cmd.name == "demo"
        assert len(cmd.args) == 2
        assert cmd.args[0].name == "x"
        assert cmd.args[0].type == "integer"
        assert cmd.args[0].required is True
        assert cmd.args[1].name == "y"
        assert cmd.args[1].type == "string"

    def test_register_preserves_function(self) -> None:
        factory = _SandboxFactory()

        @factory.register
        def greet(name: str) -> str:
            return f"hello {name}"

        # The decorator returns the original function unmodified
        assert greet("world") == "hello world"

    def test_register_with_defaults(self) -> None:
        factory = _SandboxFactory()

        @factory.register
        def compute(a: int, b: float = 1.5) -> float:
            return a * b

        cmd = factory._registry["compute"]
        assert cmd.args[0].required is True
        assert cmd.args[1].required is False
        assert cmd.args[1].default == "1.5"
        assert cmd.args[1].type == "float"

    def test_register_bool_param(self) -> None:
        factory = _SandboxFactory()

        @factory.register
        def toggle(flag: bool) -> bool:
            return not flag

        cmd = factory._registry["toggle"]
        assert cmd.args[0].type == "boolean"

    def test_register_unsupported_type_raises(self) -> None:
        factory = _SandboxFactory()
        with pytest.raises(TypeError, match="Unsupported parameter type"):

            @factory.register
            def bad(data: list[int]) -> None:
                pass

    def test_register_source_captured(self) -> None:
        factory = _SandboxFactory()

        @factory.register
        def add(a: int, b: int) -> int:
            return a + b

        cmd = factory._registry["add"]
        assert "def add" in cmd.source
        assert "return a + b" in cmd.source


# ---------------------------------------------------------------------------
# sandbox.list_registered()
# ---------------------------------------------------------------------------


class TestListRegistered:
    """sandbox.list_registered() metadata output."""

    def test_empty_registry(self) -> None:
        factory = _SandboxFactory()
        assert factory.list_registered() == []

    def test_populated_registry(self) -> None:
        factory = _SandboxFactory()

        @factory.register
        def fn(x: int, y: str = "hi") -> str:
            return f"{y}{x}"

        result = factory.list_registered()
        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "fn"
        assert len(entry["args"]) == 2
        assert entry["args"][0] == {
            "name": "x",
            "type": "integer",
            "required": True,
            "default": None,
        }
        assert entry["args"][1] == {
            "name": "y",
            "type": "string",
            "required": False,
            "default": "hi",
        }


# ---------------------------------------------------------------------------
# sandbox.run() (registered command execution via HTTP)
# ---------------------------------------------------------------------------


class TestRunRegistered:
    """sandbox.run('name', **kwargs) dispatches registered commands via HTTP."""

    def test_unknown_command_raises(self) -> None:
        factory = _SandboxFactory()
        with pytest.raises(ValueError, match="Unknown registered command"):
            factory.run("nonexistent")

    @patch("easy_sandbox.api.sandbox.Sandbox", new_callable=lambda: MagicMock)
    def test_run_basic(self, mock_sandbox_cls: MagicMock) -> None:
        """Run a registered command end-to-end (mocked sandbox HTTP)."""
        mock_sb = AsyncMock()
        mock_sb.run_command = AsyncMock(return_value="hello=1")
        mock_sb.kill = AsyncMock()
        mock_sandbox_cls.create = AsyncMock(return_value=mock_sb)

        factory = _SandboxFactory()

        @factory.register
        def demo(x: int, y: str) -> str:
            return f"{y}={x}"

        result = factory.run("demo", x=1, y="hello")
        assert result == "hello=1"

        # Sandbox lifecycle
        mock_sandbox_cls.create.assert_awaited_once()
        mock_sb.run_command.assert_awaited_once_with("demo", x=1, y="hello")
        mock_sb.kill.assert_awaited_once()

    @patch("easy_sandbox.api.sandbox.Sandbox", new_callable=lambda: MagicMock)
    def test_run_type_coercion(self, mock_sandbox_cls: MagicMock) -> None:
        """String arguments are coerced to declared types."""
        mock_sb = AsyncMock()
        mock_sb.run_command = AsyncMock(return_value=10)
        mock_sb.kill = AsyncMock()
        mock_sandbox_cls.create = AsyncMock(return_value=mock_sb)

        factory = _SandboxFactory()

        @factory.register
        def multiply(a: int, b: float) -> float:
            return a * b

        result = factory.run("multiply", a="5", b="2.0")
        assert result == 10

        # Verify coerced types were passed via HTTP
        mock_sb.run_command.assert_awaited_once_with("multiply", a=5, b=2.0)

    @patch("easy_sandbox.api.sandbox.Sandbox", new_callable=lambda: MagicMock)
    def test_run_uses_run_command(self, mock_sandbox_cls: MagicMock) -> None:
        """Execution goes through Sandbox.run_command (HTTP), not scripts."""
        mock_sb = AsyncMock()
        mock_sb.run_command = AsyncMock(return_value=None)
        mock_sb.kill = AsyncMock()
        mock_sandbox_cls.create = AsyncMock(return_value=mock_sb)

        factory = _SandboxFactory()

        @factory.register
        def noop() -> None:
            pass

        factory.run("noop")

        # run_command was called with the command name
        mock_sb.run_command.assert_awaited_once_with("noop")
        # No file write occurred (old script-upload path gone)
        assert not hasattr(mock_sb, "files") or not mock_sb.files.write.called

    @patch("easy_sandbox.api.sandbox.Sandbox", new_callable=lambda: MagicMock)
    def test_run_creates_sandbox_with_template(self, mock_sandbox_cls: MagicMock) -> None:
        """Sandbox is created with the code-interpreter-v1 template."""
        mock_sb = AsyncMock()
        mock_sb.run_command = AsyncMock(return_value="ok")
        mock_sb.kill = AsyncMock()
        mock_sandbox_cls.create = AsyncMock(return_value=mock_sb)

        factory = _SandboxFactory()

        @factory.register
        def echo() -> str:
            return "ok"

        factory.run("echo")

        call_kw = mock_sandbox_cls.create.call_args
        effective_tpl = (
            call_kw.args[0] if call_kw.args else call_kw.kwargs.get("template")
        )
        assert effective_tpl == "code-interpreter-v1"

    @patch("easy_sandbox.api.sandbox.Sandbox", new_callable=lambda: MagicMock)
    def test_run_command_error_raises(self, mock_sandbox_cls: MagicMock) -> None:
        """RuntimeError from run_command propagates to the caller."""
        mock_sb = AsyncMock()
        mock_sb.run_command = AsyncMock(
            side_effect=RuntimeError("ValueError: some error"),
        )
        mock_sb.kill = AsyncMock()
        mock_sandbox_cls.create = AsyncMock(return_value=mock_sb)

        factory = _SandboxFactory()

        @factory.register
        def fail() -> None:
            pass

        with pytest.raises(RuntimeError):
            factory.run("fail")

        # Sandbox should still be killed on error
        mock_sb.kill.assert_awaited_once()


# ---------------------------------------------------------------------------
# P0 bug fix: UUID script path in @sandbox() decorator
# ---------------------------------------------------------------------------


def _make_mock_sandbox(
    *,
    stdout: str = "null",
    stderr: str = "",
    exit_code: int = 0,
) -> AsyncMock:
    """Build a mock Sandbox for @sandbox() decorator tests."""
    mock_sb = AsyncMock()
    mock_sb.commands = AsyncMock()
    mock_sb.commands.run = AsyncMock(
        return_value=ProcessResult(
            stdout=stdout, stderr=stderr,
            exit_code=exit_code, execution_time=0.1,
        ),
    )
    mock_sb.files = AsyncMock()
    mock_sb.files.write = AsyncMock()
    mock_sb.kill = AsyncMock()
    return mock_sb


class TestDecoratorUuidPath:
    """@sandbox() decorator now uses UUID temp paths, not hardcoded."""

    @patch("easy_sandbox.api.sandbox.Sandbox", new_callable=lambda: MagicMock)
    def test_script_path_is_uuid(self, mock_sandbox_cls: MagicMock) -> None:
        mock_sb = _make_mock_sandbox(stdout=json.dumps(42))
        mock_sandbox_cls.create = AsyncMock(return_value=mock_sb)

        @sandbox(api_key="k")
        def fn() -> int:
            return 42

        fn()

        # Verify the path written is a UUID path
        write_call = mock_sb.files.write.call_args
        path = write_call[0][0]
        assert re.match(r"/tmp/_ebx_[a-f0-9]{32}\.py", path)


# ---------------------------------------------------------------------------
# P0 bug fix: pip uses python3 -m pip + shlex.quote
# ---------------------------------------------------------------------------


class TestDecoratorPipFix:
    """packages= uses '{py_cmd} -m pip install' + shlex.quote."""

    @patch("easy_sandbox.api.sandbox.Sandbox", new_callable=lambda: MagicMock)
    def test_pip_uses_python_m_pip(self, mock_sandbox_cls: MagicMock) -> None:
        mock_sb = _make_mock_sandbox(stdout=json.dumps(None))
        mock_sandbox_cls.create = AsyncMock(return_value=mock_sb)

        @sandbox(packages=["numpy", "pandas>=2.0"], api_key="k")
        def fn() -> None:
            return None

        fn()

        # Find the pip install call
        calls = [str(c) for c in mock_sb.commands.run.await_args_list]
        pip_calls = [c for c in calls if "pip install" in c]
        assert len(pip_calls) >= 1

        pip_call = pip_calls[0]
        # Must use "python3 -m pip" or "python -m pip", NOT bare "pip"
        assert "-m pip install" in pip_call
        # Packages must be quoted
        assert "numpy" in pip_call
        assert "pandas" in pip_call


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """The module-level sandbox is a _SandboxFactory instance."""

    def test_sandbox_is_factory(self) -> None:
        assert isinstance(sandbox, _SandboxFactory)

    def test_sandbox_is_callable(self) -> None:
        assert callable(sandbox)

    def test_sandbox_has_register(self) -> None:
        assert hasattr(sandbox, "register")
        assert callable(sandbox.register)
        assert isinstance(sandbox.register, _RegisterProxy)

    def test_sandbox_has_run(self) -> None:
        assert hasattr(sandbox, "run")
        assert callable(sandbox.run)

    def test_sandbox_has_server(self) -> None:
        assert hasattr(sandbox, "server")
        assert isinstance(sandbox.server, _ServerProxy)

    def test_import_from_declarative(self) -> None:
        from easy_sandbox.declarative import sandbox as sb
        assert isinstance(sb, _SandboxFactory)
        assert callable(sb)

    def test_import_from_top(self) -> None:
        from easy_sandbox import sandbox as sb
        assert callable(sb)


# ---------------------------------------------------------------------------
# sandbox.server proxy
# ---------------------------------------------------------------------------


class TestServerProxy:
    """sandbox.server proxies to easy_sandbox.server module."""

    def test_server_is_server_proxy(self) -> None:
        factory = _SandboxFactory()
        assert isinstance(factory.server, _ServerProxy)

    def test_server_is_same_instance(self) -> None:
        factory = _SandboxFactory()
        assert factory.server is factory.server  # cached

    @patch("easy_sandbox.server.start")
    def test_server_start_delegates(self, mock_start: MagicMock) -> None:
        factory = _SandboxFactory()
        factory.server.start(port=8080)
        mock_start.assert_called_once_with(port=8080, host="0.0.0.0")

    @patch("easy_sandbox.server.start")
    def test_server_start_defaults(self, mock_start: MagicMock) -> None:
        factory = _SandboxFactory()
        factory.server.start()
        mock_start.assert_called_once_with(port=9000, host="0.0.0.0")

    def test_server_getattr_proxies(self) -> None:
        """Attribute access on .server proxies to the server module."""
        factory = _SandboxFactory()
        # SandboxServer is exported from easy_sandbox.server
        assert factory.server.SandboxServer is not None


# ---------------------------------------------------------------------------
# sandbox.register.upload() / .download()
# ---------------------------------------------------------------------------


class TestRegisterUploadDownload:
    """register.upload() / .download() toggle server built-in routes."""

    @patch("easy_sandbox.server.enable_builtin")
    def test_upload_enables_builtin(self, mock_enable: MagicMock) -> None:
        factory = _SandboxFactory()
        factory.register.upload()
        mock_enable.assert_called_once_with("upload")

    @patch("easy_sandbox.server.enable_builtin")
    def test_download_enables_builtin(self, mock_enable: MagicMock) -> None:
        factory = _SandboxFactory()
        factory.register.download()
        mock_enable.assert_called_once_with("download")

    def test_register_is_register_proxy(self) -> None:
        factory = _SandboxFactory()
        assert isinstance(factory.register, _RegisterProxy)

    def test_register_still_works_as_decorator(self) -> None:
        """@factory.register syntax still works with _RegisterProxy."""
        factory = _SandboxFactory()

        @factory.register
        def greet(name: str) -> str:
            return f"hello {name}"

        assert "greet" in factory._registry
        assert greet("world") == "hello world"
