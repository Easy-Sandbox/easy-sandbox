"""Tests for transport.streaming module."""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from easy_sandbox.transport.streaming import StreamReader


async def _async_iter(items: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item


async def _async_iter_with_error(
    items: list[dict[str, Any]], error: Exception
) -> AsyncIterator[dict[str, Any]]:
    """Helper to create an async iterator that yields items then raises."""
    for item in items:
        yield item
    raise error


class TestStreamReader:
    """Test StreamReader with mock async iterators."""

    async def test_basic_iteration(self):
        frames = [{"data": 1}, {"data": 2}, {"data": 3}]
        reader = StreamReader(
            _async_iter(frames),
            transform=lambda f: f["data"],
        )
        result = await reader.collect()
        assert result == [1, 2, 3]

    async def test_transform_applied(self):
        frames = [{"value": "a"}, {"value": "b"}]
        reader = StreamReader(
            _async_iter(frames),
            transform=lambda f: f["value"].upper(),
        )
        result = await reader.collect()
        assert result == ["A", "B"]

    async def test_empty_stream(self):
        reader = StreamReader(
            _async_iter([]),
            transform=lambda f: f,
        )
        result = await reader.collect()
        assert result == []

    async def test_single_frame(self):
        reader = StreamReader(
            _async_iter([{"x": 42}]),
            transform=lambda f: f["x"],
        )
        result = await reader.collect()
        assert result == [42]

    async def test_async_iteration(self):
        frames = [{"n": i} for i in range(5)]
        reader = StreamReader(
            _async_iter(frames),
            transform=lambda f: f["n"] * 2,
        )
        collected = []
        async for item in reader:
            collected.append(item)
        assert collected == [0, 2, 4, 6, 8]

    async def test_error_propagation(self):
        error = RuntimeError("stream error")
        reader = StreamReader(
            _async_iter_with_error([{"data": 1}], error),
            transform=lambda f: f["data"],
        )
        with pytest.raises(RuntimeError, match="stream error"):
            await reader.collect()

    async def test_transform_error_skipped(self):
        frames = [{"data": 1}, {"bad": "frame"}, {"data": 3}]

        def transform(f):
            return f["data"]  # Will raise KeyError for {"bad": "frame"}

        reader = StreamReader(
            _async_iter(frames),
            transform=transform,
        )
        result = await reader.collect()
        assert result == [1, 3]

    async def test_start_returns_self(self):
        reader = StreamReader(
            _async_iter([]),
            transform=lambda f: f,
        )
        result = reader.start()
        assert result is reader
        # Clean up
        await reader.collect()

    async def test_cancel(self):
        # Create a slow async iterator that can be cancelled
        async def slow_iter():
            for i in range(5):
                yield {"n": i}
                await asyncio.sleep(0.01)

        reader = StreamReader(
            slow_iter(),
            transform=lambda f: f["n"],
        )
        # Read one item via async for
        async for item in reader:
            assert item == 0
            break  # stop after first
        await reader.cancel()
        # Should not hang or raise
