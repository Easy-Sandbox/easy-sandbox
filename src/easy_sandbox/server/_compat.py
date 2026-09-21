"""Backward-compatibility shim for the legacy built-in route toggle API.

Historically the server exposed a flat ``enable_builtin`` / ``disable_builtin``
API keyed by route *name* (``"upload"``, ``"download"``, ``"shell"``).  The
route infrastructure now models availability with :class:`CapabilityGroup`
toggles on a :class:`~easy_sandbox.server.router.RouteTable`.

This module preserves the old public names by mapping each legacy built-in
name onto its capability group and delegating to the default route table.
The historical module-level attributes ``_KNOWN_BUILTINS`` and
``_enabled_builtins`` are re-exposed as well: ``_enabled_builtins`` is a live,
set-like *view* backed by the route table, so existing code that reads or
mutates it keeps working.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableSet

from .router import CapabilityGroup, default_table

__all__ = [
    "enable_builtin",
    "disable_builtin",
    "is_builtin_enabled",
    "get_enabled_builtins",
]

# Legacy built-in name -> capability group.
_BUILTIN_GROUP_MAP: dict[str, CapabilityGroup] = {
    "upload": CapabilityGroup.FILE_OPS,
    "download": CapabilityGroup.FILE_OPS,
    "shell": CapabilityGroup.PROCESS,
}

# Names that can be toggled.  ``health`` and ``commands`` are always on.
_KNOWN_BUILTINS: frozenset[str] = frozenset(_BUILTIN_GROUP_MAP)


def _require_known(name: str) -> CapabilityGroup:
    """Return the capability group for *name* or raise ``ValueError``."""
    group = _BUILTIN_GROUP_MAP.get(name)
    if group is None:
        raise ValueError(
            f"Unknown built-in route {name!r}; allowed: {sorted(_KNOWN_BUILTINS)}"
        )
    return group


def enable_builtin(name: str) -> None:
    """Enable a built-in route by *name*.

    Args:
        name: One of ``"upload"``, ``"download"``, ``"shell"``.

    Raises:
        ValueError: If *name* is not a recognised built-in.
    """
    group = _require_known(name)
    default_table().enable_group(group)


def disable_builtin(name: str) -> None:
    """Disable a built-in route by *name*.

    Args:
        name: One of ``"upload"``, ``"download"``, ``"shell"``.

    Raises:
        ValueError: If *name* is not a recognised built-in.
    """
    group = _require_known(name)
    default_table().disable_group(group)


def is_builtin_enabled(name: str) -> bool:
    """Return whether the built-in route *name* is currently enabled."""
    group = _BUILTIN_GROUP_MAP.get(name)
    if group is None:
        return False
    return default_table().is_group_enabled(group)


def get_enabled_builtins() -> frozenset[str]:
    """Return the current set of enabled built-in names."""
    return frozenset(name for name in _KNOWN_BUILTINS if is_builtin_enabled(name))


class _EnabledBuiltinsView(MutableSet[str]):
    """A set-like live view of enabled legacy built-ins, backed by the table.

    Reading (``in``, iteration, ``len``) reflects the current capability-group
    state; mutating operations (``add``/``discard``/``clear``/``update``) are
    translated into :meth:`enable_builtin` / :meth:`disable_builtin` calls.
    """

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and is_builtin_enabled(name)

    def __iter__(self) -> Iterator[str]:
        return iter(get_enabled_builtins())

    def __len__(self) -> int:
        return len(get_enabled_builtins())

    def add(self, name: str) -> None:
        enable_builtin(name)

    def discard(self, name: str) -> None:
        if name in _BUILTIN_GROUP_MAP:
            disable_builtin(name)

    def clear(self) -> None:
        for name in _KNOWN_BUILTINS:
            disable_builtin(name)

    def update(self, names: object) -> None:
        """Enable every built-in in *names* (mirrors ``set.update``)."""
        for name in names:  # type: ignore[attr-defined]
            enable_builtin(name)

    def __repr__(self) -> str:
        return f"_EnabledBuiltinsView({sorted(get_enabled_builtins())!r})"


# Live view preserving the historical ``_enabled_builtins`` module attribute.
_enabled_builtins = _EnabledBuiltinsView()
