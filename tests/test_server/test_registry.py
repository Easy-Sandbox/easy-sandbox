"""Tests for easy_sandbox.server.registry — stdlib-only command registry.

Covers registration, decorator syntax, freezing, lookup helpers, dunder
methods, and :class:`CommandArg` type validation.
"""

from __future__ import annotations

import pytest

from easy_sandbox.server.registry import (
    CommandArg,
    CommandRegistry,
    RegisteredCommand,
    default_registry,
)

# ---------------------------------------------------------------------------
# CommandArg validation
# ---------------------------------------------------------------------------


class TestCommandArg:
    """CommandArg type validation and defaults."""

    @pytest.mark.parametrize("arg_type", ["string", "integer", "float", "boolean"])
    def test_valid_types_accepted(self, arg_type: str) -> None:
        arg = CommandArg(name="x", type=arg_type)
        assert arg.type == arg_type

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid arg type"):
            CommandArg(name="x", type="bogus")

    def test_defaults(self) -> None:
        arg = CommandArg(name="x")
        assert arg.type == "string"
        assert arg.required is False
        assert arg.default is None
        assert arg.description == ""


# ---------------------------------------------------------------------------
# register / get
# ---------------------------------------------------------------------------


class TestRegisterAndGet:
    """Programmatic registration and lookup."""

    def test_register_and_get(self) -> None:
        reg = CommandRegistry()

        def greet(name: str) -> str:
            return f"Hello, {name}!"

        reg.register(
            "greet",
            greet,
            args=[CommandArg(name="name", required=True)],
            description="Greet someone",
        )

        cmd = reg.get("greet")
        assert cmd is not None
        assert isinstance(cmd, RegisteredCommand)
        assert cmd.name == "greet"
        assert cmd.fn is greet
        assert cmd.description == "Greet someone"
        assert len(cmd.args) == 1
        assert cmd.args[0].name == "name"
        # The function reference is directly callable.
        assert cmd.fn("World") == "Hello, World!"

    def test_register_without_args_defaults_to_empty_list(self) -> None:
        reg = CommandRegistry()
        reg.register("noop", lambda: None)
        cmd = reg.get("noop")
        assert cmd is not None
        assert cmd.args == []

    def test_get_missing_returns_none(self) -> None:
        reg = CommandRegistry()
        assert reg.get("does-not-exist") is None

    def test_register_overwrites_existing(self) -> None:
        reg = CommandRegistry()
        reg.register("cmd", lambda: 1)
        reg.register("cmd", lambda: 2)
        cmd = reg.get("cmd")
        assert cmd is not None
        assert cmd.fn() == 2
        assert len(reg) == 1


# ---------------------------------------------------------------------------
# command() decorator
# ---------------------------------------------------------------------------


class TestCommandDecorator:
    """Decorator-style registration."""

    def test_decorator_with_explicit_name(self) -> None:
        reg = CommandRegistry()

        @reg.command("add")
        def add(a: int, b: int) -> int:
            return a + b

        cmd = reg.get("add")
        assert cmd is not None
        assert cmd.name == "add"
        assert cmd.fn is add
        # Decorator returns the function unchanged.
        assert add(2, 3) == 5

    def test_decorator_without_name_uses_func_name(self) -> None:
        reg = CommandRegistry()

        @reg.command()
        def greet(name: str) -> str:
            return f"Hi {name}"

        assert "greet" in reg
        cmd = reg.get("greet")
        assert cmd is not None
        assert cmd.name == "greet"

    def test_decorator_forwards_kwargs(self) -> None:
        reg = CommandRegistry()

        @reg.command("echo", description="Echo input")
        def echo(msg: str) -> str:
            return msg

        cmd = reg.get("echo")
        assert cmd is not None
        assert cmd.description == "Echo input"


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------


class TestFreeze:
    """Freezing prevents further mutation."""

    def test_register_after_freeze_raises(self) -> None:
        reg = CommandRegistry()
        reg.register("cmd", lambda: None)
        reg.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            reg.register("cmd2", lambda: None)

    def test_command_decorator_after_freeze_raises(self) -> None:
        reg = CommandRegistry()
        reg.freeze()
        with pytest.raises(RuntimeError, match="frozen"):

            @reg.command("late")
            def late() -> None:
                return None

    def test_freeze_is_idempotent(self) -> None:
        reg = CommandRegistry()
        reg.freeze()
        reg.freeze()  # no error
        with pytest.raises(RuntimeError):
            reg.register("x", lambda: None)


# ---------------------------------------------------------------------------
# list_all / dunder helpers
# ---------------------------------------------------------------------------


class TestListingAndDunders:
    """list_all, __contains__, __len__."""

    def test_list_all_returns_copy(self) -> None:
        reg = CommandRegistry()
        reg.register("a", lambda: 1)
        reg.register("b", lambda: 2)

        all_cmds = reg.list_all()
        assert set(all_cmds.keys()) == {"a", "b"}
        assert isinstance(all_cmds["a"], RegisteredCommand)

        # Mutating the returned dict must not affect the registry.
        all_cmds.clear()
        assert len(reg) == 2

    def test_contains(self) -> None:
        reg = CommandRegistry()
        reg.register("present", lambda: None)
        assert "present" in reg
        assert "absent" not in reg

    def test_len(self) -> None:
        reg = CommandRegistry()
        assert len(reg) == 0
        reg.register("a", lambda: None)
        reg.register("b", lambda: None)
        assert len(reg) == 2

    def test_repr(self) -> None:
        reg = CommandRegistry()
        reg.register("a", lambda: None)
        assert "CommandRegistry" in repr(reg)
        assert "a" in repr(reg)
        reg.freeze()
        assert "frozen" in repr(reg)

    def test_list_visible_excludes_hidden(self) -> None:
        reg = CommandRegistry()
        reg.register("visible", lambda: 1)
        reg.register("secret", lambda: 2, hidden=True)
        visible = reg.list_visible()
        assert set(visible) == {"visible"}
        # list_all still includes hidden commands.
        assert set(reg.list_all()) == {"visible", "secret"}

    def test_command_decorator_hidden(self) -> None:
        reg = CommandRegistry()

        @reg.command("secret", hidden=True)
        def secret() -> str:
            return "s"

        cmd = reg.get("secret")
        assert cmd is not None
        assert cmd.hidden is True
        assert "secret" not in reg.list_visible()


# ---------------------------------------------------------------------------
# default registry
# ---------------------------------------------------------------------------


class TestDefaultRegistry:
    """Module-level default registry."""

    def test_default_registry_is_singleton(self) -> None:
        assert default_registry() is default_registry()

    def test_default_registry_is_registry_instance(self) -> None:
        assert isinstance(default_registry(), CommandRegistry)
