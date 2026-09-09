"""Tests for async/sync bridging utilities."""
from __future__ import annotations

import asyncio

import pytest

from serverless_sandbox.utils.async_bridge import run_sync, make_sync


class TestRunSync:
    def test_executes_coroutine(self):
        async def greet():
            return "hello"

        result = run_sync(greet())
        assert result == "hello"

    def test_propagates_exception(self):
        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            run_sync(fail())

    def test_returns_correct_type(self):
        async def compute():
            return 42

        result = run_sync(compute())
        assert result == 42
        assert isinstance(result, int)


class TestMakeSync:
    def test_creates_sync_wrapper(self):
        async def async_method(x: int) -> int:
            return x * 2

        sync_method = make_sync(async_method)
        result = sync_method(5)
        assert result == 10

    def test_has_sync_wrapper_attribute(self):
        async def async_method():
            return "ok"

        sync_method = make_sync(async_method)
        assert hasattr(sync_method, "_is_sync_wrapper")
        assert sync_method._is_sync_wrapper is True

    def test_preserves_function_name(self):
        async def my_function():
            return "ok"

        sync_fn = make_sync(my_function)
        assert sync_fn.__name__ == "my_function"

    def test_propagates_exception(self):
        async def fail():
            raise RuntimeError("nope")

        sync_fn = make_sync(fail)
        with pytest.raises(RuntimeError, match="nope"):
            sync_fn()
