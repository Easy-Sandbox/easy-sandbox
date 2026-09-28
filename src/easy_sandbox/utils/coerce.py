"""Shared scalar type coercion for command arguments.

Both the **server** layer (``server/routes.py``) and the **declarative**
layer (``declarative/decorator.py``) need identical coerce-and-validate
logic.  This module provides the single canonical implementation so the
two paths can never drift.

The functions accept any arg object exposing ``.name``, ``.type``,
``.required``, and ``.default`` attributes — covering both
:class:`~easy_sandbox.server.registry.CommandArg` (stdlib dataclass) and
:class:`~easy_sandbox.models.template.CustomCommandArg` (Pydantic model).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "parse_scalar",
    "coerce_kwargs",
]

# ---------------------------------------------------------------------------
# Boolean whitelist
# ---------------------------------------------------------------------------

_BOOL_TRUE: frozenset[str] = frozenset({"true", "yes", "1"})
_BOOL_FALSE: frozenset[str] = frozenset({"false", "no", "0"})

# ---------------------------------------------------------------------------
# Scalar parsing
# ---------------------------------------------------------------------------


def parse_scalar(value: Any, type_str: str) -> Any:
    """Parse / coerce *value* according to its declared *type_str*.

    Supported *type_str* values: ``"string"``, ``"integer"``, ``"float"``,
    ``"boolean"``.

    Bool parsing uses a whitelist (``true/false/yes/no/1/0``) to avoid the
    ``bool("False") == True`` pitfall.

    Args:
        value: The raw value to coerce.
        type_str: One of the supported scalar type strings.

    Returns:
        The coerced value.

    Raises:
        ValueError: If *value* cannot be converted or *type_str* is
            unrecognised.
    """
    if type_str == "string":
        return str(value)

    if type_str == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return int(value)

    if type_str == "float":
        if isinstance(value, float):
            return value
        return float(value)

    if type_str == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).lower()
        if s in _BOOL_TRUE:
            return True
        if s in _BOOL_FALSE:
            return False
        raise ValueError(
            f"Cannot parse {value!r} as boolean; accepted values: true/false/yes/no/1/0"
        )

    raise ValueError(f"Unknown type: {type_str!r}")


# ---------------------------------------------------------------------------
# Arg-like protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ArgLike(Protocol):
    """Minimal interface shared by ``CommandArg`` and ``CustomCommandArg``."""

    name: str
    type: str
    required: bool
    default: str | None


# ---------------------------------------------------------------------------
# Kwargs coercion / validation
# ---------------------------------------------------------------------------


def coerce_kwargs(
    args: list[Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Coerce and validate *raw* kwargs against *args* definitions.

    Args:
        args: Ordered list of arg descriptors (anything with ``.name``,
            ``.type``, ``.required``, ``.default``).
        raw: Raw keyword arguments from the caller / JSON body.

    Returns:
        A new dict with values converted to the declared types.

    Raises:
        ValueError: If a required argument is missing or an undeclared
            argument is provided.
        TypeError: If a value cannot be converted to the declared type.
    """
    declared_names: set[str] = {arg.name for arg in args}

    # --- Reject undeclared arguments early (fail-fast) ---
    undeclared = sorted(k for k in raw if k not in declared_names)
    if undeclared:
        raise ValueError(
            f"Unexpected argument(s): {undeclared}; declared: {sorted(declared_names) or '(none)'}"
        )

    # --- Coerce declared arguments ---
    coerced: dict[str, Any] = {}
    for arg in args:
        if arg.name in raw:
            try:
                coerced[arg.name] = parse_scalar(raw[arg.name], arg.type)
            except (ValueError, TypeError) as exc:
                raise TypeError(
                    f"Cannot convert argument {arg.name!r} to {arg.type}: {exc}"
                ) from exc
        elif arg.required:
            raise ValueError(f"Required argument {arg.name!r} missing")
        elif arg.default is not None:
            # Best-effort coercion of the default; fall back to the raw
            # string if conversion fails (e.g. a placeholder like "N/A").
            try:
                coerced[arg.name] = parse_scalar(arg.default, arg.type)
            except (ValueError, TypeError):
                coerced[arg.name] = arg.default

    return coerced
