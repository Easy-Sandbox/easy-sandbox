"""Tests for transport.codec module."""

from __future__ import annotations

import struct

import pytest

from easy_sandbox.transport.codec import (
    CONNECT_CONTENT_TYPE,
    HAS_ORJSON,
    ConnectCodec,
    EnvelopeStreamParser,
    json_decode,
    json_encode,
)


def _frame(payload: dict, flags: int = 0x00) -> bytes:
    """Build one binary envelope frame."""
    body = json_encode(payload)
    return struct.pack(">BI", flags, len(body)) + body


def _feed_all(parser: EnvelopeStreamParser, chunks: list[bytes]) -> list[dict]:
    """Feed every chunk and collect yielded frames in order."""
    out: list[dict] = []
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    return out


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
        with pytest.raises((ValueError, Exception)):
            ConnectCodec.decode_streaming_frame("{not valid json}")

    def test_build_rpc_path(self):
        path = ConnectCodec.build_rpc_path("process", "Process", "Start")
        assert path == "/process.Process/Start"

    def test_build_rpc_path_filesystem(self):
        path = ConnectCodec.build_rpc_path("filesystem", "Filesystem", "ReadFile")
        assert path == "/filesystem.Filesystem/ReadFile"


class TestEnvelopeStreamParser:
    """Incremental binary-envelope parsing (task 166)."""

    def test_single_frame_single_chunk(self):
        parser = EnvelopeStreamParser()
        assert parser.feed(_frame({"a": 1})) == [{"a": 1}]
        assert parser.pending_bytes() == 0

    def test_header_split_across_chunks(self):
        """5-byte frame header split 1+2+2 across chunks."""
        raw = _frame({"event": {"data": {"stdout": "aGk="}}})
        parser = EnvelopeStreamParser()
        assert parser.feed(raw[0:1]) == []
        assert parser.feed(raw[1:3]) == []
        frames = parser.feed(raw[3:])
        assert frames == [{"event": {"data": {"stdout": "aGk="}}}]
        assert parser.pending_bytes() == 0

    def test_payload_split_across_chunks(self):
        """Payload split mid-way across three chunks."""
        raw = _frame({"n": 12345678901234})
        parser = EnvelopeStreamParser()
        assert parser.feed(raw[:5]) == []  # full header, no payload yet
        assert parser.feed(raw[5:10]) == []
        assert parser.feed(raw[10:]) == [{"n": 12345678901234}]

    def test_multiple_frames_in_one_chunk(self):
        blob = _frame({"a": 1}) + _frame({"b": 2}) + _frame({"c": 3})
        parser = EnvelopeStreamParser()
        assert parser.feed(blob) == [{"a": 1}, {"b": 2}, {"c": 3}]

    def test_frame_boundary_mixes_complete_and_partial(self):
        """Chunk contains a whole frame + the start of the next frame."""
        first = _frame({"a": 1})
        second = _frame({"b": 2})
        parser = EnvelopeStreamParser()
        assert parser.feed(first + second[:4]) == [{"a": 1}]
        assert parser.pending_bytes() == 4
        assert parser.feed(second[4:]) == [{"b": 2}]

    def test_trailer_and_empty_frames_skipped(self):
        parser = EnvelopeStreamParser()
        out = parser.feed(
            _frame({"a": 1})
            + _frame({"error": {"code": "x"}}, flags=0x02)
            + struct.pack(">BI", 0x00, 0)  # empty data frame
        )
        assert out == [{"a": 1}]

    def test_truncated_trailing_frame_stays_pending(self):
        raw = _frame({"big": "x" * 100})
        parser = EnvelopeStreamParser()
        assert parser.feed(raw[:60]) == []
        assert parser.pending_bytes() == 60  # not silently discarded

    def test_invalid_json_payload_skipped(self):
        bad_payload = b"{not json"
        bad = struct.pack(">BI", 0x00, len(bad_payload)) + bad_payload
        parser = EnvelopeStreamParser()
        assert parser.feed(bad + _frame({"ok": True})) == [{"ok": True}]

    def test_non_dict_payload_skipped(self):
        arr = struct.pack(">BI", 0x00, 7) + b"[1,2,3]"
        parser = EnvelopeStreamParser()
        assert parser.feed(arr) == []

    def test_empty_chunk_is_noop(self):
        parser = EnvelopeStreamParser()
        assert parser.feed(b"") == []
        assert parser.feed(_frame({"a": 1})) == [{"a": 1}]

    def test_error_trailer_logged_not_yielded(self, caplog):
        """A trailer carrying an error is skipped but logged for diagnostics."""
        import logging

        parser = EnvelopeStreamParser()
        with caplog.at_level(logging.WARNING, logger="transport.codec"):
            out = parser.feed(_frame({"a": 1}) + _frame({"error": {"code": "boom"}}, flags=0x02))

        assert out == [{"a": 1}]  # error trailer never yielded
        assert any("error trailer" in r.message for r in caplog.records)

    def test_success_trailer_not_logged(self, caplog):
        """A normal (empty / non-error) trailer is skipped silently."""
        import logging

        parser = EnvelopeStreamParser()
        with caplog.at_level(logging.WARNING, logger="transport.codec"):
            out = parser.feed(_frame({"a": 1}) + _frame({}, flags=0x02))

        assert out == [{"a": 1}]
        assert not caplog.records

    def test_equivalence_with_parse_streaming_frames(self):
        """For every systematic split, incremental == one-shot parsing.

        Feeds the same byte stream at every possible 2-split point and
        verifies the concatenated incremental output equals
        :meth:`ConnectCodec.parse_streaming_frames` on the whole stream.
        """
        stream = (
            _frame({"event": {"start": {"pid": 9}}})
            + _frame({"event": {"data": {"stdout": "MQ=="}}})
            + _frame({"event": {"data": {"stderr": "Mg=="}}})
            + _frame({"event": {"end": {"exitCode": 0}}})
            + _frame({}, flags=0x02)
        )
        expected = ConnectCodec.parse_streaming_frames(stream)
        assert len(expected) == 4

        for split in range(1, len(stream)):
            parser = EnvelopeStreamParser()
            got = _feed_all(parser, [stream[:split], stream[split:]])
            assert got == expected, f"mismatch at split={split}"

    def test_equivalence_random_three_way_splits(self):
        """Three-way splits (including 0-length chunks) stay equivalent."""
        import random

        stream = (
            _frame({"a": 1})
            + _frame({"b": 2})
            + _frame({"c": 3})
            + _frame({"error": {"code": "boom"}}, flags=0x02)
        )
        expected = ConnectCodec.parse_streaming_frames(stream)

        rng = random.Random(42)
        for _ in range(50):
            i = rng.randrange(0, len(stream) + 1)
            j = rng.randrange(0, len(stream) + 1)
            cuts = sorted((i, j))
            chunks = [stream[: cuts[0]], stream[cuts[0] : cuts[1]], stream[cuts[1] :]]
            parser = EnvelopeStreamParser()
            assert _feed_all(parser, chunks) == expected
