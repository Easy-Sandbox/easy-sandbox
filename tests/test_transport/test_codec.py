"""Tests for transport.codec module."""
from __future__ import annotations

import pytest

from serverless_sandbox.transport.codec import (
    ConnectCodec,
    CONNECT_CONTENT_TYPE,
    json_encode,
    json_decode,
    HAS_ORJSON,
)


class TestJsonEncodeDecode:
    """Test json_encode and json_decode roundtrip."""

    def test_roundtrip_dict(self):
        data = {"key": "value", "num": 42}
        encoded = json_encode(data)
        assert isinstance(encoded, bytes)
        decoded = json_decode(encoded)
        assert decoded == data

    def test_roundtrip_list(self):
        data = [1, 2, 3, "four"]
        encoded = json_encode(data)
        decoded = json_decode(encoded)
        assert decoded == data

    def test_roundtrip_nested(self):
        data = {"nested": {"a": [1, 2], "b": True}, "c": None}
        encoded = json_encode(data)
        decoded = json_decode(encoded)
        assert decoded == data

    def test_decode_str_input(self):
        result = json_decode('{"hello": "world"}')
        assert result == {"hello": "world"}

    def test_decode_bytes_input(self):
        result = json_decode(b'{"hello": "world"}')
        assert result == {"hello": "world"}

    def test_encode_empty_dict(self):
        encoded = json_encode({})
        decoded = json_decode(encoded)
        assert decoded == {}

    def test_has_orjson_flag(self):
        assert isinstance(HAS_ORJSON, bool)


class TestConnectCodec:
    """Test ConnectCodec methods."""

    def test_content_type(self):
        assert ConnectCodec.content_type == "application/connect+json"
        assert CONNECT_CONTENT_TYPE == "application/connect+json"

    def test_encode_request(self):
        payload = {"command": "ls", "args": ["-la"]}
        result = ConnectCodec.encode_request(payload)
        assert isinstance(result, bytes)
        decoded = json_decode(result)
        assert decoded == payload

    def test_encode_request_empty(self):
        result = ConnectCodec.encode_request({})
        decoded = json_decode(result)
        assert decoded == {}

    def test_decode_response_valid(self):
        data = json_encode({"status": "ok", "data": [1, 2]})
        result = ConnectCodec.decode_response(data)
        assert result == {"status": "ok", "data": [1, 2]}

    def test_decode_response_str(self):
        result = ConnectCodec.decode_response('{"status": "ok"}')
        assert result == {"status": "ok"}

    def test_decode_response_non_dict_raises(self):
        data = json_encode([1, 2, 3])
        with pytest.raises(ValueError, match="Expected dict response"):
            ConnectCodec.decode_response(data)

    def test_decode_streaming_frame_valid(self):
        line = '{"result": {"output": "hello"}}'
        result = ConnectCodec.decode_streaming_frame(line)
        assert result == {"result": {"output": "hello"}}

    def test_decode_streaming_frame_bytes(self):
        line = b'{"result": {"output": "hello"}}'
        result = ConnectCodec.decode_streaming_frame(line)
        assert result == {"result": {"output": "hello"}}

    def test_decode_streaming_frame_empty(self):
        assert ConnectCodec.decode_streaming_frame("") == {}
        assert ConnectCodec.decode_streaming_frame("   ") == {}
        assert ConnectCodec.decode_streaming_frame(b"") == {}

    def test_decode_streaming_frame_non_dict_raises(self):
        with pytest.raises(ValueError, match="Expected dict frame"):
            ConnectCodec.decode_streaming_frame('"just a string"')

    def test_decode_streaming_frame_invalid_json(self):
        with pytest.raises(Exception):
            ConnectCodec.decode_streaming_frame("{not valid json}")

    def test_build_rpc_path(self):
        path = ConnectCodec.build_rpc_path("process", "Process", "Start")
        assert path == "/process.Process/Start"

    def test_build_rpc_path_filesystem(self):
        path = ConnectCodec.build_rpc_path("filesystem", "Filesystem", "ReadFile")
        assert path == "/filesystem.Filesystem/ReadFile"

