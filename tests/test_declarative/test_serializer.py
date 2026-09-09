"""Tests for declarative/serializer.py — three serialization modes."""
from __future__ import annotations

import json

import pytest

from serverless_sandbox.declarative.serializer import Serializer, SerializerType


# ---------------------------------------------------------------------------
# JSON mode
# ---------------------------------------------------------------------------


class TestJsonSerializer:
    """JSON serializer round-trip tests."""

    def test_round_trip_dict(self) -> None:
        ser = Serializer(SerializerType.JSON)
        original = {"key": "value", "num": 42, "nested": [1, 2, 3]}
        data = ser.serialize(original)
        restored = ser.deserialize(data)
        assert restored == original

    def test_round_trip_list(self) -> None:
        ser = Serializer(SerializerType.JSON)
        original = [1, "two", 3.0, None, True]
        assert ser.deserialize(ser.serialize(original)) == original

    def test_round_trip_string(self) -> None:
        ser = Serializer(SerializerType.JSON)
        assert ser.deserialize(ser.serialize("hello")) == "hello"

    def test_round_trip_number(self) -> None:
        ser = Serializer(SerializerType.JSON)
        assert ser.deserialize(ser.serialize(42)) == 42

    def test_round_trip_none(self) -> None:
        ser = Serializer(SerializerType.JSON)
        assert ser.deserialize(ser.serialize(None)) is None

    def test_default_str_fallback(self) -> None:
        """Non-JSON-native types fall back to str()."""
        from datetime import datetime

        ser = Serializer(SerializerType.JSON)
        dt = datetime(2024, 1, 1, 12, 0, 0)
        data = ser.serialize(dt)
        # Should not raise, result is a string representation
        restored = ser.deserialize(data)
        assert isinstance(restored, str)

    def test_serialize_produces_valid_json(self) -> None:
        ser = Serializer(SerializerType.JSON)
        data = ser.serialize({"a": 1})
        parsed = json.loads(data)
        assert parsed == {"a": 1}

    def test_mode_property(self) -> None:
        ser = Serializer(SerializerType.JSON)
        assert ser.mode == SerializerType.JSON


# ---------------------------------------------------------------------------
# Pickle mode
# ---------------------------------------------------------------------------


class TestPickleSerializer:
    """cloudpickle serializer round-trip tests."""

    @pytest.fixture(autouse=True)
    def _check_cloudpickle(self) -> None:
        pytest.importorskip("cloudpickle")

    def test_round_trip_dict(self) -> None:
        ser = Serializer(SerializerType.PICKLE)
        original = {"key": [1, 2, 3], "nested": {"a": True}}
        assert ser.deserialize(ser.serialize(original)) == original

    def test_round_trip_lambda(self) -> None:
        ser = Serializer(SerializerType.PICKLE)
        fn = lambda x: x * 2  # noqa: E731
        data = ser.serialize(fn)
        restored = ser.deserialize(data)
        assert restored(5) == 10

    def test_round_trip_complex_object(self) -> None:
        ser = Serializer(SerializerType.PICKLE)
        original = {
            "set_as_list": [1, 2, 3],
            "tuple": (4, 5),
            "bytes": b"hello",
        }
        restored = ser.deserialize(ser.serialize(original))
        assert restored["tuple"] == (4, 5)
        assert restored["bytes"] == b"hello"


# ---------------------------------------------------------------------------
# Msgpack mode
# ---------------------------------------------------------------------------


class TestMsgpackSerializer:
    """msgpack serializer round-trip tests."""

    @pytest.fixture(autouse=True)
    def _check_msgpack(self) -> None:
        pytest.importorskip("msgpack")

    def test_round_trip_dict(self) -> None:
        ser = Serializer(SerializerType.MSGPACK)
        original = {"key": "value", "num": 42}
        assert ser.deserialize(ser.serialize(original)) == original

    def test_round_trip_list(self) -> None:
        ser = Serializer(SerializerType.MSGPACK)
        original = [1, 2, 3, "four"]
        assert ser.deserialize(ser.serialize(original)) == original

    def test_round_trip_nested(self) -> None:
        ser = Serializer(SerializerType.MSGPACK)
        original = {"a": [{"b": 1}, {"c": 2}]}
        assert ser.deserialize(ser.serialize(original)) == original


# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------


class TestSerializerType:
    def test_values(self) -> None:
        assert SerializerType.JSON.value == "json"
        assert SerializerType.PICKLE.value == "pickle"
        assert SerializerType.MSGPACK.value == "msgpack"

    def test_construct_from_value(self) -> None:
        assert SerializerType("json") == SerializerType.JSON
        assert SerializerType("pickle") == SerializerType.PICKLE
        assert SerializerType("msgpack") == SerializerType.MSGPACK
