"""Declarative route registry for the sandbox HTTP server — stdlib-only.

Replaces the hand-written ``if/elif`` dispatch chain in :mod:`app` with a
data-driven :class:`RouteTable`.  Each route is described by a
:class:`RouteInfo` record that couples an HTTP method + path pattern with a
handler function, a :class:`CapabilityGroup`, and metadata (auth requirement,
streaming flag, name).

Path patterns use ``{param}`` placeholders which are compiled to named regex
groups (``(?P<param>[^/]+)``) so path parameters can be extracted during
matching.  Adding a new endpoint therefore requires **zero** changes to
``app.py`` — only a :meth:`RouteTable.register` call (or the :meth:`route`
decorator).

Capability groups can be toggled at runtime (or via the
``SBOX_SERVER_DISABLED_GROUPS`` environment variable) to enable/disable whole
families of endpoints.  The :data:`CapabilityGroup.CORE` group is *always on*
and cannot be disabled.

Example::

    table = RouteTable()

    @table.route("GET", "/status", group=CapabilityGroup.SYSTEM)
    def status(request):
        return ServerResponse.ok({"status": "ok"})

    route, params = table.match("GET", "/status")
"""

from __future__ import annotations

import dataclasses
import os
import re
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "CapabilityGroup",
    "RouteInfo",
    "RouteTable",
    "default_table",
]


class CapabilityGroup(Enum):
    """A family of endpoints that can be enabled/disabled as a unit.

    ``CORE`` is always on and cannot be disabled; all other groups may be
    toggled at runtime or via ``SBOX_SERVER_DISABLED_GROUPS``.
    """

    CORE = "core"           # always_on, cannot be disabled
    COMMANDS = "commands"
    FILE_OPS = "file_ops"
    PROCESS = "process"
    TERMINAL = "terminal"
    SYSTEM = "system"
    DEV_TOOLS = "dev_tools"


# Groups disabled by default (opt-in surface such as developer tooling).
_DEFAULT_DISABLED = frozenset({CapabilityGroup.DEV_TOOLS})

# Environment variable used to disable additional groups at process start.
_DISABLED_GROUPS_ENV_VAR = "SBOX_SERVER_DISABLED_GROUPS"


@dataclasses.dataclass
class RouteInfo:
    """Metadata describing a single registered route.

    Attributes:
        method: Upper-cased HTTP method (``"GET"``, ``"POST"``, ``"DELETE"``).
        path_pattern: Path template with ``{param}`` placeholders, e.g.
            ``"/process/{pid}/signal"``.
        handler: Callable invoked as ``handler(request) -> ServerResponse``
            (or ``SSEResponse`` when :attr:`streaming` is ``True``).
        group: The :class:`CapabilityGroup` this route belongs to.
        auth_required: Whether the request must pass token authentication
            (``/health`` sets this to ``False``).
        streaming: ``True`` for Server-Sent-Events handlers.
        name: Human-readable route name used in logging.
        _regex: Pre-compiled pattern used for matching (internal).
        _param_names: Ordered list of path-parameter names (internal).
    """

    method: str
    path_pattern: str
    handler: Callable[..., Any]
    group: CapabilityGroup
    auth_required: bool = True
    streaming: bool = False
    name: str = ""
    _regex: re.Pattern[str] | None = dataclasses.field(default=None, repr=False)
    _param_names: list[str] = dataclasses.field(default_factory=list, repr=False)


class RouteTable:
    """A registry of :class:`RouteInfo` records with capability-group gating.

    Routes are matched in registration order.  Capability groups gate whole
    families of routes; a request that matches a route whose group is disabled
    is treated as unavailable by the dispatcher.
    """

    def __init__(self) -> None:
        """Create an empty table, seeding disabled groups from the environment."""
        self._routes: list[RouteInfo] = []
        self._disabled_groups: set[CapabilityGroup] = set(_DEFAULT_DISABLED)
        # Read additional disabled groups from the environment.
        env_disabled = os.environ.get(_DISABLED_GROUPS_ENV_VAR, "")
        if env_disabled:
            for raw in env_disabled.split(","):
                name = raw.strip()
                try:
                    group = CapabilityGroup(name)
                except ValueError:
                    continue
                if group != CapabilityGroup.CORE:
                    self._disabled_groups.add(group)

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def register(
        self,
        method: str,
        path_pattern: str,
        handler: Callable[..., Any],
        *,
        group: CapabilityGroup,
        auth_required: bool = True,
        streaming: bool = False,
        name: str = "",
    ) -> None:
        """Register *handler* for *method* + *path_pattern*.

        The pattern is compiled to a regex where each ``{param}`` placeholder
        becomes a named capture group ``(?P<param>[^/]+)``.

        Args:
            method: HTTP method (case-insensitive).
            path_pattern: Path template with optional ``{param}`` placeholders.
            handler: Callable invoked with the parsed request object.
            group: The :class:`CapabilityGroup` gating this route.
            auth_required: Whether token auth is enforced (default ``True``).
            streaming: ``True`` for SSE handlers (default ``False``).
            name: Optional human-readable name (defaults to
                ``"{METHOD} {path_pattern}"``).
        """
        param_names = re.findall(r"\{(\w+)\}", path_pattern)
        regex_str = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path_pattern) + "$"
        compiled = re.compile(regex_str)

        route = RouteInfo(
            method=method.upper(),
            path_pattern=path_pattern,
            handler=handler,
            group=group,
            auth_required=auth_required,
            streaming=streaming,
            name=name or f"{method.upper()} {path_pattern}",
            _regex=compiled,
            _param_names=param_names,
        )
        self._routes.append(route)

    def route(
        self,
        method: str,
        path_pattern: str,
        **kwargs: object,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator form of :meth:`register`.

        Example::

            @table.route("GET", "/status", group=CapabilityGroup.SYSTEM)
            def status(request):
                ...

        Args:
            method: HTTP method.
            path_pattern: Path template.
            **kwargs: Forwarded to :meth:`register` (``group``,
                ``auth_required``, ``streaming``, ``name``).

        Returns:
            A decorator that registers the wrapped function and returns it
            unchanged.
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(method, path_pattern, fn, **kwargs)  # type: ignore[arg-type]
            return fn

        return decorator

    # ------------------------------------------------------------------ #
    # Matching
    # ------------------------------------------------------------------ #

    def match(
        self,
        method: str,
        path: str,
    ) -> tuple[RouteInfo, dict[str, str]] | tuple[None, None]:
        """Find the first route matching *method* + *path*.

        Args:
            method: HTTP method (case-insensitive).
            path: Concrete request path (query string already stripped).

        Returns:
            ``(route, path_params)`` for the first match, or ``(None, None)``
            when no route matches.
        """
        upper = method.upper()
        for route in self._routes:
            if route.method != upper:
                continue
            if route._regex is None:
                continue
            m = route._regex.match(path)
            if m:
                return route, m.groupdict()
        return None, None

    # ------------------------------------------------------------------ #
    # Capability-group toggles
    # ------------------------------------------------------------------ #

    def enable_group(self, group: CapabilityGroup) -> None:
        """Enable *group* (no-op for :data:`CapabilityGroup.CORE`)."""
        if group == CapabilityGroup.CORE:
            return  # always on
        self._disabled_groups.discard(group)

    def disable_group(self, group: CapabilityGroup) -> None:
        """Disable *group*.

        Args:
            group: The group to disable.

        Raises:
            ValueError: If *group* is :data:`CapabilityGroup.CORE`.
        """
        if group == CapabilityGroup.CORE:
            raise ValueError("Cannot disable CORE capability group")
        self._disabled_groups.add(group)

    def is_group_enabled(self, group: CapabilityGroup) -> bool:
        """Return whether *group* is currently enabled."""
        return group not in self._disabled_groups

    def list_groups(self) -> dict[str, bool]:
        """Return a ``{group_value: enabled}`` mapping for every group."""
        return {g.value: self.is_group_enabled(g) for g in CapabilityGroup}


# ---------------------------------------------------------------------------
# Module-level default table
# ---------------------------------------------------------------------------

_default_table = RouteTable()


def default_table() -> RouteTable:
    """Return the module-level default :class:`RouteTable` singleton."""
    return _default_table
