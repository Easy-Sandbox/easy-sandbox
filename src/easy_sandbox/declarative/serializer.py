"""函数参数序列化/反序列化。

仅支持 JSON 模式（适用于简单类型）。
"""

from __future__ import annotations

import json
from enum import Enum


class SerializerType(Enum):
    """Supported serializer backends."""

    JSON = "json"


class Serializer:
    """Serialize / deserialize function arguments and return values."""

    def __init__(self, mode: SerializerType = SerializerType.JSON) -> None:
        self._mode = mode

    @property
    def mode(self) -> SerializerType:
        """Current serialization mode."""
        return self._mode

    def serialize(self, obj: object) -> str:
        """Serialize *obj* to a JSON string."""
        return json.dumps(obj, default=str)

    def deserialize(self, data: str) -> object:
        """Deserialize a JSON string back to a Python object.

        Args:
            data: The serialized string produced by :meth:`serialize`.
        """
        return json.loads(data)
