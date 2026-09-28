"""Client SDK ``run_command`` 全链路 E2E 测试.

启动一个真实 :class:`SandboxServer` (本地 HTTP)，然后通过
:meth:`Sandbox.run_command` 的 **实际 httpx 客户端路径** 进行往返调用。
覆盖机制 B：typed 参数强转、错误传递、PEP 563 注解回归。

Tests use the same fixture pattern as ``test_server_e2e.py``.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from unittest.mock import MagicMock

import httpx
import pytest

from easy_sandbox.api.sandbox import Sandbox
from easy_sandbox.server import CommandRegistry, SandboxServer
from easy_sandbox.server.routes import (
    _KNOWN_BUILTINS,
    _enabled_builtins,
    enable_builtin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Commands (some defined under PEP 563 — this file uses
# ``from __future__ import annotations``)
# ---------------------------------------------------------------------------


def hello(who: str) -> str:
    return f"Hello, {who}!"


def add(a: int, b: int) -> int:
    return a + b


def multiply(x: float, y: float) -> float:
    return x * y


def toggle(flag: bool) -> bool:
    return not flag


def failing() -> str:
    raise ValueError("intentional boom")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _reset_builtins():
    original = set(_enabled_builtins)
    yield
    _enabled_builtins.clear()
    _enabled_builtins.update(original)


@pytest.fixture()
def local_server(_reset_builtins, tmp_path):
    """Start a real SandboxServer and return ``(port, registry)``."""
    registry = CommandRegistry()

    # Use the @registry.command() decorator so annotation inference runs
    # (this also validates PEP 563 handling in registry.command).
    registry.command("hello")(hello)
    registry.command("add")(add)
    registry.command("multiply")(multiply)
    registry.command("toggle")(toggle)
    registry.command("failing")(failing)

    port = _free_port()
    server = SandboxServer(host="127.0.0.1", registry=registry)

    for name in _KNOWN_BUILTINS:
        enable_builtin(name)

    os.environ["EBX_SERVER_BASE_DIR"] = str(tmp_path)
    t = threading.Thread(target=server.serve, kwargs={"port": port}, daemon=True)
    t.start()

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            with httpx.Client() as c:
                r = c.get(f"{base_url}/health", timeout=2)
                if r.status_code == 200:
                    break
        except Exception:
            time.sleep(0.05)
    else:
        pytest.fail("Server did not start within 2 seconds")

    yield port, registry

    server.shutdown()
    os.environ.pop("EBX_SERVER_BASE_DIR", None)


@pytest.fixture()
def sandbox_stub(local_server):
    """Build a Sandbox-like object whose ``run_command`` calls our local server.

    Only ``network`` and ``_http_client`` are wired; everything else is
    unused by :meth:`Sandbox.run_command`.
    """
    port, _ = local_server

    # Minimal network stub → localhost
    network = MagicMock()
    network.get_url = lambda p: f"http://127.0.0.1:{port}"
    network.get_access_headers = lambda: {}

    # Real httpx client via a thin wrapper
    _envd_clients: dict[str, httpx.AsyncClient] = {}

    class _LocalHttpClient:
        def _create_envd_client(self, envd_url: str) -> httpx.AsyncClient:
            existing = _envd_clients.get(envd_url)
            if existing is not None and not existing.is_closed:
                return existing
            client = httpx.AsyncClient(base_url=envd_url, timeout=10)
            _envd_clients[envd_url] = client
            return client

    sb = MagicMock(spec=Sandbox)
    sb.network = network
    sb._http_client = _LocalHttpClient()
    # ``run_command`` is now a deprecated alias that delegates to ``custom``,
    # which in turn calls ``_call_server_command`` for mechanism B.  Bind the
    # *real* methods (and the instance attrs they read) so the full dispatch
    # chain runs against the local server instead of returning auto-mocks.
    sb._custom_commands = {}
    sb._server_probe_failed = False
    sb._call_server_command = Sandbox._call_server_command.__get__(sb, Sandbox)
    sb.custom = Sandbox.custom.__get__(sb, Sandbox)
    sb.run_command = Sandbox.run_command.__get__(sb, Sandbox)

    yield sb

    # Cleanup httpx clients
    for c in _envd_clients.values():
        if not c.is_closed:
            import asyncio
            import contextlib

            with contextlib.suppress(Exception):
                asyncio.get_event_loop().run_until_complete(c.aclose())


# ---------------------------------------------------------------------------
# Tests — run_command full-round-trip via real HTTP
# ---------------------------------------------------------------------------


class TestRunCommandE2E:
    """Client SDK ``run_command`` via real HTTP to a real SandboxServer."""

    @pytest.mark.asyncio
    async def test_hello_returns_greeting(self, sandbox_stub):
        result = await sandbox_stub.run_command("hello", who="World")
        assert result == "Hello, World!"

    @pytest.mark.asyncio
    async def test_add_returns_integer(self, sandbox_stub):
        result = await sandbox_stub.run_command("add", a=2, b=40)
        assert result == 42
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_add_string_coercion(self, sandbox_stub):
        """String '2' and '40' should be coerced to int on the server side."""
        result = await sandbox_stub.run_command("add", a="2", b="40")
        assert result == 42
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_multiply_float_coercion(self, sandbox_stub):
        result = await sandbox_stub.run_command("multiply", x="3.5", y="2.0")
        assert result == 7.0
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_toggle_bool_coercion(self, sandbox_stub):
        result = await sandbox_stub.run_command("toggle", flag="false")
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_command_raises_command_not_found(self, sandbox_stub):
        from easy_sandbox.models.errors import CommandNotFoundError

        # Server replies 404 for unknown commands; ``custom`` maps that to
        # CommandNotFoundError, which the deprecated alias propagates.
        with pytest.raises(CommandNotFoundError, match="not found"):
            await sandbox_stub.run_command("nonexistent")

    @pytest.mark.asyncio
    async def test_handler_exception_reported_via_command_result(self, sandbox_stub):
        # A handler that raises returns HTTP 500; ``custom`` maps a reachable
        # non-2xx (non-404) to a CommandResult with exit_code=1 and the error
        # in stderr (rather than raising).  Assert via ``custom`` directly.
        result = await sandbox_stub.custom("failing")
        assert result.exit_code == 1
        assert result.source == "server"
        assert "intentional boom" in result.stderr


# ---------------------------------------------------------------------------
# PEP 563 regression — annotations in this file are ALL stringified
# because of ``from __future__ import annotations`` at the top.
# The ``@registry.command()`` decorator must resolve them correctly.
# ---------------------------------------------------------------------------


class TestPEP563ServerCoercion:
    """Verify PEP 563 string annotations → real types for server commands.

    All functions (``hello``, ``add``, ``multiply``, ``toggle``) are
    defined under ``from __future__ import annotations``.  If annotation
    resolution fails, int/float/bool args would be treated as string and
    coercion would break or produce wrong results.
    """

    @pytest.mark.asyncio
    async def test_int_params_coerced(self, sandbox_stub):
        """``add(a: int, b: int)`` — verify int coercion under PEP 563."""
        result = await sandbox_stub.run_command("add", a="10", b="32")
        assert result == 42

    @pytest.mark.asyncio
    async def test_float_params_coerced(self, sandbox_stub):
        result = await sandbox_stub.run_command("multiply", x="2.5", y="4.0")
        assert result == 10.0

    @pytest.mark.asyncio
    async def test_bool_param_coerced(self, sandbox_stub):
        result = await sandbox_stub.run_command("toggle", flag="true")
        assert result is False

    @pytest.mark.asyncio
    async def test_str_param_unchanged(self, sandbox_stub):
        result = await sandbox_stub.run_command("hello", who="PEP563")
        assert result == "Hello, PEP563!"
