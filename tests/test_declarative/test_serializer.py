"""Tests for declarative/serializer.py — JSON-only serialization."""

from __future__ import annotations

import json

from easy_sandbox.declarative.serializer import Serializer, SerializerType

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
# Enum values
# ---------------------------------------------------------------------------


class TestSerializerType:
    def test_values(self) -> None:
        assert SerializerType.JSON.value == "json"

    def test_construct_from_value(self) -> None:
        assert SerializerType("json") == SerializerType.JSON
