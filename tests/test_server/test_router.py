"""Tests for serverless_sandbox.server.router — the declarative RouteTable.

Covers route registration + matching, path-parameter extraction, capability
group toggles, the ``SBOX_SERVER_DISABLED_GROUPS`` environment variable, and
the decorator form of :meth:`RouteTable.route`.
"""

from __future__ import annotations

from typing import Any

import pytest

from serverless_sandbox.server.router import (
    CapabilityGroup,
    RouteInfo,
    RouteTable,
    default_table,
)


def _handler(request: Any) -> str:  # pragma: no cover - trivial stub
    return "ok"


# ---------------------------------------------------------------------------
# Registration & matching
# ---------------------------------------------------------------------------


class TestRegisterAndMatch:
    """Basic registration and lookup semantics."""

    def test_register_and_match_static(self) -> None:
        table = RouteTable()
        table.register("GET", "/health", _handler, group=CapabilityGroup.CORE)
        route, params = table.match("GET", "/health")
        assert isinstance(route, RouteInfo)
        assert route.path_pattern == "/health"
        assert params == {}

    def test_method_is_normalised(self) -> None:
        table = RouteTable()
        table.register("get", "/x", _handler, group=CapabilityGroup.SYSTEM)
        route, _ = table.match("GET", "/x")
        assert route is not None
        assert route.method == "GET"

    def test_no_match_returns_none_none(self) -> None:
        table = RouteTable()
        table.register("GET", "/x", _handler, group=CapabilityGroup.SYSTEM)
        route, params = table.match("GET", "/does-not-exist")
        assert route is None
        assert params is None

    def test_method_mismatch_returns_none(self) -> None:
        table = RouteTable()
        table.register("POST", "/x", _handler, group=CapabilityGroup.SYSTEM)
        route, params = table.match("GET", "/x")
        assert route is None
        assert params is None

    def test_first_registered_wins(self) -> None:
        table = RouteTable()
        table.register("GET", "/dup", _handler, group=CapabilityGroup.SYSTEM, name="first")
        table.register("GET", "/dup", _handler, group=CapabilityGroup.SYSTEM, name="second")
        route, _ = table.match("GET", "/dup")
        assert route is not None
        assert route.name == "first"

    def test_default_name(self) -> None:
        table = RouteTable()
        table.register("get", "/y", _handler, group=CapabilityGroup.SYSTEM)
        route, _ = table.match("GET", "/y")
        assert route is not None
        assert route.name == "GET /y"


# ---------------------------------------------------------------------------
# Path parameters
# ---------------------------------------------------------------------------


class TestPathParams:
    """``{param}`` placeholders are compiled and extracted."""

    def test_single_param(self) -> None:
        table = RouteTable()
        table.register("POST", "/commands/{name}", _handler, group=CapabilityGroup.COMMANDS)
        route, params = table.match("POST", "/commands/greet")
        assert route is not None
        assert params == {"name": "greet"}

    def test_multiple_params(self) -> None:
        table = RouteTable()
        table.register(
            "POST", "/process/{pid}/signal/{sig}", _handler, group=CapabilityGroup.PROCESS
        )
        route, params = table.match("POST", "/process/123/signal/TERM")
        assert route is not None
        assert params == {"pid": "123", "sig": "TERM"}

    def test_param_does_not_span_slash(self) -> None:
        table = RouteTable()
        table.register("POST", "/commands/{name}", _handler, group=CapabilityGroup.COMMANDS)
        # An extra path segment must not match a single {name} param.
        route, params = table.match("POST", "/commands/greet/extra")
        assert route is None
        assert params is None

    def test_static_not_matched_by_param_route(self) -> None:
        table = RouteTable()
        table.register("GET", "/commands/{name}", _handler, group=CapabilityGroup.COMMANDS)
        route, params = table.match("GET", "/commands")
        assert route is None
        assert params is None


# ---------------------------------------------------------------------------
# Capability groups
# ---------------------------------------------------------------------------


class TestCapabilityGroups:
    """Enable/disable semantics for capability groups."""

    def test_default_enabled(self) -> None:
        table = RouteTable()
        assert table.is_group_enabled(CapabilityGroup.FILE_OPS) is True
        assert table.is_group_enabled(CapabilityGroup.COMMANDS) is True

    def test_dev_tools_disabled_by_default(self) -> None:
        table = RouteTable()
        assert table.is_group_enabled(CapabilityGroup.DEV_TOOLS) is False

    def test_disable_then_enable(self) -> None:
        table = RouteTable()
        table.disable_group(CapabilityGroup.FILE_OPS)
        assert table.is_group_enabled(CapabilityGroup.FILE_OPS) is False
        table.enable_group(CapabilityGroup.FILE_OPS)
        assert table.is_group_enabled(CapabilityGroup.FILE_OPS) is True

    def test_core_always_on(self) -> None:
        table = RouteTable()
        assert table.is_group_enabled(CapabilityGroup.CORE) is True
        # enable_group is a no-op for CORE and never raises.
        table.enable_group(CapabilityGroup.CORE)
        assert table.is_group_enabled(CapabilityGroup.CORE) is True

    def test_cannot_disable_core(self) -> None:
        table = RouteTable()
        with pytest.raises(ValueError, match="Cannot disable CORE"):
            table.disable_group(CapabilityGroup.CORE)

    def test_list_groups(self) -> None:
        table = RouteTable()
        groups = table.list_groups()
        assert groups[CapabilityGroup.CORE.value] is True
        assert groups[CapabilityGroup.DEV_TOOLS.value] is False
        assert set(groups) == {g.value for g in CapabilityGroup}


# ---------------------------------------------------------------------------
# Environment-variable configuration
# ---------------------------------------------------------------------------


class TestEnvConfig:
    """``SBOX_SERVER_DISABLED_GROUPS`` seeds disabled groups at construction."""

    def test_env_disables_groups(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("SBOX_SERVER_DISABLED_GROUPS", "file_ops,process")
        table = RouteTable()
        assert table.is_group_enabled(CapabilityGroup.FILE_OPS) is False
        assert table.is_group_enabled(CapabilityGroup.PROCESS) is False
        # DEV_TOOLS remains disabled by default too.
        assert table.is_group_enabled(CapabilityGroup.DEV_TOOLS) is False
        # Untouched group stays enabled.
        assert table.is_group_enabled(CapabilityGroup.COMMANDS) is True

    def test_env_ignores_unknown_and_core(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("SBOX_SERVER_DISABLED_GROUPS", "core, bogus , system")
        table = RouteTable()
        # CORE cannot be disabled; unknown names are ignored.
        assert table.is_group_enabled(CapabilityGroup.CORE) is True
        assert table.is_group_enabled(CapabilityGroup.SYSTEM) is False

    def test_empty_env_uses_defaults(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("SBOX_SERVER_DISABLED_GROUPS", "")
        table = RouteTable()
        assert table.is_group_enabled(CapabilityGroup.FILE_OPS) is True
        assert table.is_group_enabled(CapabilityGroup.DEV_TOOLS) is False


# ---------------------------------------------------------------------------
# Decorator form
# ---------------------------------------------------------------------------


class TestRouteDecorator:
    """The ``@table.route(...)`` decorator registers and returns the fn."""

    def test_decorator_registers(self) -> None:
        table = RouteTable()

        @table.route("GET", "/deco", group=CapabilityGroup.SYSTEM, name="deco")
        def handler(request: Any) -> str:
            return "deco"

        route, _ = table.match("GET", "/deco")
        assert route is not None
        assert route.name == "deco"
        # Decorator returns the function unchanged.
        assert handler(None) == "deco"


# ---------------------------------------------------------------------------
# Default table singleton
# ---------------------------------------------------------------------------


class TestDefaultTable:
    """The module-level default table is a populated singleton."""

    def test_default_table_is_singleton(self) -> None:
        assert default_table() is default_table()

    def test_builtin_routes_registered(self) -> None:
        table = default_table()
        # Routes registered by routes.py import side-effect.
        health, _ = table.match("GET", "/health")
        assert health is not None
        assert health.auth_required is False
        run, params = table.match("POST", "/commands/add")
        assert run is not None
        assert params == {"name": "add"}
