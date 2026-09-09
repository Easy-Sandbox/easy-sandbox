"""Tests for async retry decorator."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from serverless_sandbox.utils.retry import retry


class TestRetry:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call should not retry."""
        call_count = 0

        @retry(max_retries=3, retry_on=(ValueError,))
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        """Should retry and eventually succeed."""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01, jitter=0.0, retry_on=(ValueError,))
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        """Should raise last exception after exhausting retries."""

        @retry(max_retries=2, base_delay=0.01, jitter=0.0, retry_on=(ValueError,))
        async def always_fail():
            raise ValueError("always")

        with pytest.raises(ValueError, match="always"):
            await always_fail()

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Should use exponential backoff between retries."""
        delays = []

        @retry(max_retries=3, base_delay=1.0, jitter=0.0, retry_on=(ValueError,))
        async def always_fail():
            raise ValueError("fail")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError):
                await always_fail()

            # Delays: 1.0 * 2^0 = 1.0, 1.0 * 2^1 = 2.0, 1.0 * 2^2 = 4.0
            assert mock_sleep.call_count == 3
            calls = [c.args[0] for c in mock_sleep.call_args_list]
            assert calls[0] == pytest.approx(1.0)
            assert calls[1] == pytest.approx(2.0)
            assert calls[2] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_only_retries_specified_exceptions(self):
        """Should not retry on exceptions not in retry_on."""

        @retry(max_retries=3, base_delay=0.01, jitter=0.0, retry_on=(ValueError,))
        async def raise_type_error():
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            await raise_type_error()

    @pytest.mark.asyncio
    async def test_retry_after_attribute(self):
        """Should respect retry_after attribute on exception."""

        class RetryableError(Exception):
            def __init__(self, msg, retry_after=None):
                super().__init__(msg)
                self.retry_after = retry_after

        call_count = 0

        @retry(max_retries=2, base_delay=1.0, jitter=0.0, retry_on=(RetryableError,))
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RetryableError("retry me", retry_after=5.0)
            return "ok"

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await flaky()
            assert result == "ok"
            # Should have used the retry_after value (5.0) instead of exponential
            assert mock_sleep.call_count == 1
            assert mock_sleep.call_args.args[0] == pytest.approx(5.0)
