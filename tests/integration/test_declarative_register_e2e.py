"""Declarative ``@sandbox.register`` 真实执行路径测试.

验证 ``@sandbox.register`` 装饰器：
1. 正确桥接到 ``server.registry`` (``_RegisterProxy.__call__``).
2. 经 ``SandboxServer`` 的 ``POST /commands/{name}`` 走 HTTP 往返.
3. PEP 563 (``from __future__ import annotations``) 下
   int/float/bool 参数被正确识别和强转.

与 ``test_register.py`` 中基于 mock 的测试不同，这里走真实 HTTP。
"""

from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any

import httpx
import pytest

from easy_sandbox.declarative.decorator import _SandboxFactory
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
def register_and_serve(_reset_builtins, tmp_path):
    """Register commands via ``@sandbox.register``, start server, return (port, factory).

    This simulates the real declarative workflow: the user decorates functions,
    ``_RegisterProxy.__call__`` bridges them into the server-level
    ``default_registry()``, then the server serves them over HTTP.
    """
    # Use a **fresh** registry so tests are isolated.
    srv_registry = CommandRegistry()

    # Monkeypatch ``default_registry`` to return our fresh instance
    import easy_sandbox.server.registry as _reg_mod

    original_default = _reg_mod._default_registry
    _reg_mod._default_registry = srv_registry

    # Create a fresh factory whose _RegisterProxy will bridge into srv_registry
    factory = _SandboxFactory()

    # ---- Register functions (PEP 563 active in this file) ----

    @factory.register
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    @factory.register
    def add(a: int, b: int) -> int:
        return a + b

    @factory.register
    def scale(value: float, factor: float = 1.0) -> float:
        return value * factor

    @factory.register
    def negate(flag: bool) -> bool:
        return not flag

    # ---- Start server ----
    port = _free_port()
    server = SandboxServer(host="127.0.0.1", registry=srv_registry)

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

    yield port, factory, srv_registry

    server.shutdown()
    os.environ.pop("EBX_SERVER_BASE_DIR", None)
    _reg_mod._default_registry = original_default


# ---------------------------------------------------------------------------
# Helpers — direct HTTP call (bypasses Sandbox SDK, tests server side)
# ---------------------------------------------------------------------------


def _post_command(port: int, name: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
        resp = client.post(f"/commands/{name}", json=body or {}, timeout=10)
        return resp.status_code, resp.json()


def _get_commands(port: int) -> list[dict[str, Any]]:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
        resp = client.get("/commands", timeout=10)
        return resp.json()["commands"]


# ---------------------------------------------------------------------------
# Tests — bridge verification
# ---------------------------------------------------------------------------


class TestRegisterBridgeToServer:
    """``@sandbox.register`` bridges into the server registry."""

    def test_commands_visible(self, register_and_serve):
        port, factory, srv_registry = register_and_serve
        cmds = _get_commands(port)
        names = {c["name"] for c in cmds}
        assert {"greet", "add", "scale", "negate"} <= names

    def test_factory_registry_matches(self, register_and_serve):
        _, factory, srv_registry = register_and_serve
        for name in ("greet", "add", "scale", "negate"):
            assert name in factory._registry
            assert srv_registry.get(name) is not None


# ---------------------------------------------------------------------------
# Tests — real HTTP execution
# ---------------------------------------------------------------------------


class TestRegisterRealExecution:
    """Registered commands execute correctly over real HTTP."""

    def test_greet(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "greet", {"name": "World"})
        assert status == 200
        assert body["result"] == "Hello, World!"

    def test_add_integer(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "add", {"a": 2, "b": 40})
        assert status == 200
        assert body["result"] == 42

    def test_add_string_coercion(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "add", {"a": "2", "b": "40"})
        assert status == 200
        assert body["result"] == 42

    def test_scale_default(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "scale", {"value": "3.5"})
        assert status == 200
        assert body["result"] == 3.5  # factor defaults to 1.0

    def test_scale_explicit(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "scale", {"value": "2.0", "factor": "3.0"})
        assert status == 200
        assert body["result"] == 6.0

    def test_negate_bool_coercion(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "negate", {"flag": "true"})
        assert status == 200
        assert body["result"] is False

    def test_unknown_command_404(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "does_not_exist", {})
        assert status == 404

    def test_missing_required_400(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "add", {"a": 1})
        assert status == 400
        assert "b" in body["error"].lower()


# ---------------------------------------------------------------------------
# PEP 563 regression (declarative path)
# ---------------------------------------------------------------------------


class TestPEP563DeclarativeCoercion:
    """PEP 563 ``from __future__ import annotations`` under @sandbox.register.

    All functions above are defined in a PEP 563 module (this file).
    ``_RegisterProxy.__call__`` must use ``typing.get_type_hints()`` to
    resolve string annotations into real types so that int/float/bool
    arg types are correctly inferred and coercion works end-to-end.
    """

    def test_int_args_recognized(self, register_and_serve):
        _, factory, _ = register_and_serve
        cmd = factory._registry["add"]
        assert cmd.args[0].type == "integer"
        assert cmd.args[1].type == "integer"

    def test_float_args_recognized(self, register_and_serve):
        _, factory, _ = register_and_serve
        cmd = factory._registry["scale"]
        assert cmd.args[0].type == "float"
        assert cmd.args[1].type == "float"

    def test_bool_arg_recognized(self, register_and_serve):
        _, factory, _ = register_and_serve
        cmd = factory._registry["negate"]
        assert cmd.args[0].type == "boolean"

    def test_str_arg_recognized(self, register_and_serve):
        _, factory, _ = register_and_serve
        cmd = factory._registry["greet"]
        assert cmd.args[0].type == "string"

    def test_int_coercion_over_http(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "add", {"a": "10", "b": "32"})
        assert status == 200
        assert body["result"] == 42

    def test_float_coercion_over_http(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "scale", {"value": "2.5", "factor": "4.0"})
        assert status == 200
        assert body["result"] == 10.0

    def test_bool_coercion_over_http(self, register_and_serve):
        port, _, _ = register_and_serve
        status, body = _post_command(port, "negate", {"flag": "false"})
        assert status == 200
        assert body["result"] is True
