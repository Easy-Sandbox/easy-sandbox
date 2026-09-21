"""函数参数序列化/反序列化。

支持三种模式：
1. JSON（默认，适用于简单类型）
2. cloudpickle（适用于复杂 Python 对象，需要 cloudpickle 包）
3. msgpack（适用于高性能场景，需要 msgpack 包）
"""
from __future__ import annotations

import base64
import json
from enum import Enum


class SerializerType(Enum):
    """Supported serializer backends."""

    JSON = "json"
    PICKLE = "pickle"
    MSGPACK = "msgpack"


class Serializer:
    """Serialize / deserialize function arguments and return values."""

    def __init__(self, mode: SerializerType = SerializerType.JSON) -> None:
        self._mode = mode

    @property
    def mode(self) -> SerializerType:
        """Current serialization mode."""
        return self._mode

    def serialize(self, obj: object) -> str:
        """Serialize *obj* to a string representation.

        Returns:
            A JSON string (``JSON`` mode), or a base64-encoded string
            (``PICKLE`` / ``MSGPACK`` modes).
        """
        if self._mode == SerializerType.JSON:
            return json.dumps(obj, default=str)

        if self._mode == SerializerType.PICKLE:
            try:
                import cloudpickle
            except ImportError as exc:
                raise ImportError(
                    "cloudpickle is required for PICKLE serializer: pip install cloudpickle"
                ) from exc
            return base64.b64encode(cloudpickle.dumps(obj)).decode()

        if self._mode == SerializerType.MSGPACK:
            try:
                import msgpack
            except ImportError as exc:
                raise ImportError(
                    "msgpack is required for MSGPACK serializer: pip install msgpack"
                ) from exc
            return base64.b64encode(msgpack.packb(obj, use_bin_type=True)).decode()

        raise ValueError(f"Unknown serializer mode: {self._mode}")  # pragma: no cover

    def deserialize(self, data: str) -> object:
        """Deserialize a string back to a Python object.

        Args:
            data: The serialized string produced by :meth:`serialize`.
        """
        if self._mode == SerializerType.JSON:
            return json.loads(data)

        if self._mode == SerializerType.PICKLE:
            try:
                import cloudpickle
            except ImportError as exc:
                raise ImportError(
                    "cloudpickle is required for PICKLE serializer: pip install cloudpickle"
                ) from exc
            return cloudpickle.loads(base64.b64decode(data))

        if self._mode == SerializerType.MSGPACK:
            try:
                import msgpack
            except ImportError as exc:
                raise ImportError(
                    "msgpack is required for MSGPACK serializer: pip install msgpack"
                ) from exc
            return msgpack.unpackb(base64.b64decode(data), raw=False)

        raise ValueError(f"Unknown serializer mode: {self._mode}")  # pragma: no cover
