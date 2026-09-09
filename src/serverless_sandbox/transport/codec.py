"""Connect protocol (application/connect+json) codec.

Uses orjson when available for ~3-5x faster JSON parsing on hot paths,
falls back to standard json module.

Streaming responses use binary envelope framing (已实测验证):
  flags (1 byte) + length (4 bytes big-endian) + JSON payload
  flags=0x00: data frame, flags=0x02: end-of-stream/trailer frame
"""
from __future__ import annotations

import struct
from typing import Any

try:
    import orjson

    def json_encode(obj: Any) -> bytes:
        """Encode object to JSON bytes."""
        return orjson.dumps(obj)

    def json_decode(data: bytes | str) -> Any:
        """Decode JSON bytes/str to object."""
        return orjson.loads(data)

    HAS_ORJSON = True

except ImportError:
    import json

    def json_encode(obj: Any) -> bytes:  # type: ignore[misc]
        """Encode object to JSON bytes."""
        return json.dumps(obj, separators=(",", ":")).encode("utf-8")

    def json_decode(data: bytes | str) -> Any:  # type: ignore[misc]
        """Decode JSON bytes/str to object."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return json.loads(data)

    HAS_ORJSON = False


CONNECT_CONTENT_TYPE = "application/connect+json"


class ConnectCodec:
    """Encode/decode Connect protocol messages.

    The Connect protocol uses JSON encoding with content type
    'application/connect+json'. RPC endpoints follow the pattern:
    /{package}.{Service}/{Method}

    For streaming responses, each frame is a separate JSON object
    separated by newlines (NDJSON-like).
    """

    content_type: str = CONNECT_CONTENT_TYPE

    @staticmethod
    def encode_request(payload: dict[str, Any]) -> bytes:
        """Encode a Connect RPC request body."""
        return json_encode(payload)

    @staticmethod
    def decode_response(data: bytes | str) -> dict[str, Any]:
        """Decode a Connect RPC response body."""
        result = json_decode(data)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict response, got {type(result).__name__}")
        return result

    @staticmethod
    def decode_streaming_frame(line: bytes | str) -> dict[str, Any]:
        """Decode a single streaming frame (one line of NDJSON).

        Connect streaming responses contain JSON objects separated by newlines.
        Each object has a 'result' field with the actual data.
        """
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.strip()
        if not line:
            return {}
        result = json_decode(line)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict frame, got {type(result).__name__}")
        return result

    @staticmethod
    def build_rpc_path(package: str, service: str, method: str) -> str:
        """Build a Connect RPC endpoint path.

        Example: build_rpc_path("process", "Process", "Start") -> "/process.Process/Start"
        """
        return f"/{package}.{service}/{method}"

    # --- Binary envelope framing for streaming (已实测验证) ---

    FRAME_FLAG_DATA = 0x00
    FRAME_FLAG_TRAILER = 0x02
    FRAME_HEADER_SIZE = 5  # 1 byte flags + 4 bytes length

    @staticmethod
    def parse_streaming_frames(data: bytes) -> list[dict[str, Any]]:
        """Parse binary envelope-framed streaming response into JSON frames.

        Connect streaming format (已实测验证):
          [flags: 1 byte][length: 4 bytes big-endian][JSON payload: variable]
          Repeated for each frame.

        Flags:
          0x00 = data frame (contains event JSON)
          0x02 = end-of-stream/trailer frame (skip)
        """
        frames: list[dict[str, Any]] = []
        pos = 0
        while pos < len(data):
            if pos + 5 > len(data):
                break  # Incomplete header
            flags = data[pos]
            length = struct.unpack(">I", data[pos + 1 : pos + 5])[0]
            pos += 5
            if pos + length > len(data):
                break  # Incomplete payload
            payload = data[pos : pos + length]
            pos += length

            if flags == 0x02:
                continue  # Trailer frame, skip

            if not payload:
                continue

            try:
                frame = json_decode(payload)
                if isinstance(frame, dict):
                    frames.append(frame)
            except Exception:
                continue
        return frames
