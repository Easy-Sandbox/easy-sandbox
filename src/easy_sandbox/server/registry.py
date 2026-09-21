"""Server-side command registry — stdlib-only, zero external dependencies.

Provides a lightweight command registration mechanism that lives entirely
within the ``server`` package and has **no** imports from the ``declarative``,
``models``, or any other SDK layer.  This removes the previous circular
dependency where ``routes.py`` had to lazy-import
``declarative.decorator.sandbox._registry`` at request time.

Typical usage inside a sandbox template's ``commands.py``::

    from easy_sandbox.server.registry import registry

    @registry.command("greet")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    registry.freeze()  # lock before the server starts accepting requests

Or with the programmatic API::

    registry.register("add", add_fn, args=[
        CommandArg(name="a", type="integer", required=True),
        CommandArg(name="b", type="integer", required=True),
    ])
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

__all__ = [
    "CommandArg",
    "RegisteredCommand",
    "CommandRegistry",
    "default_registry",
]

# ---------------------------------------------------------------------------
# Valid scalar types
# ---------------------------------------------------------------------------

_VALID_ARG_TYPES: frozenset[str] = frozenset({"string", "integer", "float", "boolean"})


# ---------------------------------------------------------------------------
# Data models (stdlib dataclasses only)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CommandArg:
    """A single argument definition for a registered command.

    Attributes:
        name: Argument name (must match the function parameter name).
        type: Scalar type hint — one of ``"string"``, ``"integer"``,
            ``"float"``, or ``"boolean"``.
        required: Whether the caller *must* supply this argument.
        default: Default value (as a string) when the argument is omitted.
        description: Human-readable description shown in ``GET /commands``.
    """

    name: str
    type: str = "string"
    required: bool = False
    default: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        """Validate that *type* is one of the allowed scalar types."""
        if self.type not in _VALID_ARG_TYPES:
            raise ValueError(f"Invalid arg type {self.type!r}; allowed: {sorted(_VALID_ARG_TYPES)}")


@dataclasses.dataclass
class RegisteredCommand:
    """Metadata for a command registered with :class:`CommandRegistry`.

    Attributes:
        name: Unique command name used in ``POST /commands/{name}``.
        fn: Direct reference to the callable that implements the command.
        args: Ordered list of :class:`CommandArg` definitions.
        description: Human-readable description shown in ``GET /commands``.
        hidden: When ``True`` the command is executable but omitted from the
            ``GET /commands`` listing (see :meth:`CommandRegistry.list_visible`).
    """

    name: str
    fn: Any  # Callable[..., Any] — kept as Any to avoid typing import
    args: list[CommandArg] = dataclasses.field(default_factory=list)
    description: str = ""
    hidden: bool = False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class CommandRegistry:
    """Server-side command registry — independent of the declarative layer.

    Maintains a mapping of command names to :class:`RegisteredCommand`
    entries.  The registry can optionally be *frozen* to prevent
    runtime modifications after the server has started.

    Example::

        reg = CommandRegistry()

        @reg.command("greet")
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        reg.freeze()
        assert "greet" in reg
    """

    def __init__(self) -> None:
        self._commands: dict[str, RegisteredCommand] = {}
        self._frozen: bool = False

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def register(
        self,
        name: str,
        fn: Any,
        *,
        args: list[CommandArg] | None = None,
        description: str = "",
        hidden: bool = False,
    ) -> None:
        """Register a command by *name*.

        Args:
            name: Unique command name.
            fn: The callable that implements the command.
            args: Optional list of :class:`CommandArg` definitions.
                Defaults to an empty list.
            description: Human-readable description.
            hidden: When ``True`` the command is executable but excluded from
                the ``GET /commands`` listing.

        Raises:
            RuntimeError: If the registry has been frozen via
                :meth:`freeze`.
        """
        if self._frozen:
            raise RuntimeError("Cannot register command after the registry has been frozen")
        self._commands[name] = RegisteredCommand(
            name=name,
            fn=fn,
            args=args if args is not None else [],
            description=description,
            hidden=hidden,
        )

    def command(
        self,
        name: str | None = None,
        *,
        hidden: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Decorator for registering a command.

        Supports both ``@registry.command("my_cmd")`` and
        ``@registry.command()`` (name inferred from the function).

        Args:
            name: Explicit command name.  When ``None``, the decorated
                function's ``__name__`` is used.
            hidden: When ``True`` the command is executable but excluded from
                the ``GET /commands`` listing.
            **kwargs: Forwarded to :meth:`register` (e.g. ``args``,
                ``description``).

        Returns:
            A decorator that registers the function and returns it
            unchanged.

        Example::

            @registry.command("add")
            def add(a: int, b: int) -> int:
                return a + b

            @registry.command()
            def greet(name: str) -> str:
                return f"Hello, {name}!"
        """

        def decorator(fn: Any) -> Any:
            cmd_name = name if name is not None else fn.__name__
            # If no explicit args were provided, infer from function signature.
            if "args" not in kwargs or kwargs["args"] is None:
                sig = inspect.signature(fn)
                inferred_args: list[CommandArg] = []
                for param_name, param in sig.parameters.items():
                    arg_type = "string"  # default
                    # Infer type from annotation
                    if param.annotation != inspect.Parameter.empty:
                        _annotation_map = {
                            int: "integer",
                            float: "float",
                            bool: "boolean",
                        }
                        arg_type = _annotation_map.get(param.annotation, "string")

                    required = param.default is inspect.Parameter.empty
                    default = (
                        None
                        if required
                        else (str(param.default) if param.default is not None else None)
                    )

                    inferred_args.append(
                        CommandArg(
                            name=param_name,
                            type=arg_type,
                            required=required,
                            default=default,
                        )
                    )
                kwargs["args"] = inferred_args
            self.register(cmd_name, fn, hidden=hidden, **kwargs)
            return fn

        return decorator

    def freeze(self) -> None:
        """Lock the registry to prevent further modifications.

        Once frozen, any call to :meth:`register` (including via
        :meth:`command`) will raise :class:`RuntimeError`.
        """
        self._frozen = True

    # ------------------------------------------------------------------ #
    # Lookup
    # ------------------------------------------------------------------ #

    def get(self, name: str) -> RegisteredCommand | None:
        """Return the :class:`RegisteredCommand` for *name*, or ``None``.

        Args:
            name: The command name to look up.

        Returns:
            The registered command, or ``None`` if not found.
        """
        return self._commands.get(name)

    def list_all(self) -> dict[str, RegisteredCommand]:
        """Return a shallow copy of all registered commands.

        Returns:
            A new ``dict`` mapping command names to
            :class:`RegisteredCommand` instances.
        """
        return dict(self._commands)

    def list_visible(self) -> dict[str, RegisteredCommand]:
        """Return all registered commands that are not marked ``hidden``.

        Returns:
            A new ``dict`` mapping command names to
            :class:`RegisteredCommand` instances, excluding any registered
            with ``hidden=True``.
        """
        return {name: cmd for name, cmd in self._commands.items() if not cmd.hidden}

    # ------------------------------------------------------------------ #
    # Dunder helpers
    # ------------------------------------------------------------------ #

    def __contains__(self, name: str) -> bool:
        """Return ``True`` if *name* is registered."""
        return name in self._commands

    def __len__(self) -> int:
        """Return the number of registered commands."""
        return len(self._commands)

    def __repr__(self) -> str:
        frozen_tag = " (frozen)" if self._frozen else ""
        return f"<CommandRegistry commands={list(self._commands.keys())}{frozen_tag}>"


# ---------------------------------------------------------------------------
# Module-level default registry
# ---------------------------------------------------------------------------

_default_registry = CommandRegistry()


def default_registry() -> CommandRegistry:
    """Return the module-level default :class:`CommandRegistry` instance.

    Returns:
        The singleton :data:`_default_registry`.
    """
    return _default_registry
