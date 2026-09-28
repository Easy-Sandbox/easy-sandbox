"""Unit tests for the shared ``easy_sandbox.utils.coerce`` module.

Covers ``parse_scalar`` and ``coerce_kwargs`` with both
:class:`CommandArg` (server) and :class:`CustomCommandArg` (declarative)
arg types to guarantee identical behaviour after the dedup refactor.
"""

from __future__ import annotations

import pytest

from easy_sandbox.models.template import CustomCommandArg
from easy_sandbox.server.registry import CommandArg
from easy_sandbox.utils.coerce import coerce_kwargs, parse_scalar

# ---------------------------------------------------------------------------
# parse_scalar
# ---------------------------------------------------------------------------


class TestParseScalar:
    """Type coercion for scalar values."""

    # ---- string ----
    def test_string_passthrough(self) -> None:
        assert parse_scalar("hello", "string") == "hello"

    def test_string_from_int(self) -> None:
        assert parse_scalar(42, "string") == "42"

    # ---- integer ----
    def test_integer_passthrough(self) -> None:
        assert parse_scalar(7, "integer") == 7

    def test_integer_from_str(self) -> None:
        assert parse_scalar("123", "integer") == 123

    def test_integer_rejects_float_str(self) -> None:
        with pytest.raises(ValueError):
            parse_scalar("3.14", "integer")

    # ---- float ----
    def test_float_passthrough(self) -> None:
        assert parse_scalar(3.14, "float") == 3.14

    def test_float_from_str(self) -> None:
        assert parse_scalar("2.5", "float") == 2.5

    def test_float_from_int(self) -> None:
        assert parse_scalar(3, "float") == 3.0

    # ---- boolean ----
    def test_bool_true_passthrough(self) -> None:
        assert parse_scalar(True, "boolean") is True

    def test_bool_false_passthrough(self) -> None:
        assert parse_scalar(False, "boolean") is False

    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "yes", "Yes", "1"])
    def test_bool_truthy_strings(self, val: str) -> None:
        assert parse_scalar(val, "boolean") is True

    @pytest.mark.parametrize("val", ["false", "False", "FALSE", "no", "No", "0"])
    def test_bool_falsy_strings(self, val: str) -> None:
        assert parse_scalar(val, "boolean") is False

    def test_bool_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse.*as boolean"):
            parse_scalar("maybe", "boolean")

    def test_bool_false_string_not_truthy(self) -> None:
        """Critical: ``bool('False') == True``, but parse_scalar must return False."""
        assert parse_scalar("False", "boolean") is False

    # ---- unknown type ----
    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown type"):
            parse_scalar("x", "complex")


# ---------------------------------------------------------------------------
# coerce_kwargs with CommandArg (server dataclass)
# ---------------------------------------------------------------------------


class TestCoerceKwargsCommandArg:
    """``coerce_kwargs`` with :class:`CommandArg` (server layer)."""

    def _args(self) -> list[CommandArg]:
        return [
            CommandArg(name="x", type="integer", required=True),
            CommandArg(name="y", type="string", required=False, default="hi"),
        ]

    def test_full_kwargs(self) -> None:
        result = coerce_kwargs(self._args(), {"x": "5", "y": "world"})
        assert result == {"x": 5, "y": "world"}

    def test_default_applied(self) -> None:
        result = coerce_kwargs(self._args(), {"x": 3})
        assert result == {"x": 3, "y": "hi"}

    def test_missing_required_raises(self) -> None:
        with pytest.raises(ValueError, match="Required argument"):
            coerce_kwargs(self._args(), {})

    def test_undeclared_raises(self) -> None:
        with pytest.raises(ValueError, match="Unexpected argument"):
            coerce_kwargs(self._args(), {"x": 1, "z": "nope"})

    def test_type_error_on_bad_conversion(self) -> None:
        with pytest.raises(TypeError, match="Cannot convert"):
            coerce_kwargs(self._args(), {"x": "not_a_number"})


# ---------------------------------------------------------------------------
# coerce_kwargs with CustomCommandArg (declarative Pydantic model)
# ---------------------------------------------------------------------------


class TestCoerceKwargsCustomCommandArg:
    """``coerce_kwargs`` with :class:`CustomCommandArg` (declarative layer)."""

    def _args(self) -> list[CustomCommandArg]:
        return [
            CustomCommandArg(name="a", type="integer", required=True),
            CustomCommandArg(name="b", type="float", required=False, default="1.5"),
        ]

    def test_full_kwargs(self) -> None:
        result = coerce_kwargs(self._args(), {"a": "3", "b": "2.5"})
        assert result == {"a": 3, "b": 2.5}

    def test_default_applied(self) -> None:
        result = coerce_kwargs(self._args(), {"a": 7})
        assert result == {"a": 7, "b": 1.5}

    def test_missing_required_raises(self) -> None:
        with pytest.raises(ValueError, match="Required argument"):
            coerce_kwargs(self._args(), {})

    def test_undeclared_raises(self) -> None:
        with pytest.raises(ValueError, match="Unexpected argument"):
            coerce_kwargs(self._args(), {"a": 1, "c": "nope"})


# ---------------------------------------------------------------------------
# Boolean arg coercion with defaults
# ---------------------------------------------------------------------------


class TestCoerceBooleanDefaults:
    """Boolean default coercion edge cases."""

    def test_bool_default_true_string(self) -> None:
        args = [CommandArg(name="flag", type="boolean", required=False, default="true")]
        result = coerce_kwargs(args, {})
        assert result == {"flag": True}

    def test_bool_default_false_string(self) -> None:
        args = [CommandArg(name="flag", type="boolean", required=False, default="false")]
        result = coerce_kwargs(args, {})
        assert result == {"flag": False}

    def test_bool_default_invalid_falls_back(self) -> None:
        """An invalid boolean default should fall back to the raw string."""
        args = [CommandArg(name="flag", type="boolean", required=False, default="maybe")]
        result = coerce_kwargs(args, {})
        assert result == {"flag": "maybe"}
