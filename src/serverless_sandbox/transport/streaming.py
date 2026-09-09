"""Connect protocol Server-Streaming response parser.

Handles NDJSON streaming from Connect protocol endpoints.
Provides typed AsyncIterator backed by a simple async-generator — backpressure
is naturally provided by httpx's response streaming (no asyncio.Queue needed).
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Generic, TypeVar, Callable

from serverless_sandbox.utils.logging import get_logger

logger = get_logger("transport.streaming")

T = TypeVar("T")


class StreamReader(Generic[T]):
    """Typed async iterator over Connect streaming frames.

    Wraps a raw frame iterator and applies a transform function
    to convert raw dicts into typed objects.

    Back-pressure is provided naturally by the underlying httpx response
    stream — no intermediate ``asyncio.Queue`` is required.
    """

    def __init__(
        self,
        raw_frames: AsyncIterator[dict[str, Any]],
        transform: Callable[[dict[str, Any]], T],
        *,
        buffer_size: int = 100,  # kept for signature compat; unused
    ) -> None:
        self._raw_frames = raw_frames
        self._transform = transform
        self._iter: AsyncIterator[T] | None = None
        self._exhausted = False
        self._error: Exception | None = None

    # --- internal generator ---------------------------------------------------

    async def _generate(self) -> AsyncIterator[T]:
        """Yield transformed items from the raw frame stream."""
        try:
            async for frame in self._raw_frames:
                try:
                    yield self._transform(frame)
                except Exception as exc:
                    logger.warning("Frame transform error: %s", exc)
                    continue
        except Exception as exc:
            self._error = exc
            logger.debug("Stream error: %s", exc)
            raise
        finally:
            self._exhausted = True

    # --- public API (unchanged signatures) ------------------------------------

    def start(self) -> StreamReader[T]:
        """No-op retained for backward compatibility.

        Previously started a background producer task. Now the generator
        is lazily created on first iteration.
        """
        return self

    def __aiter__(self) -> AsyncIterator[T]:
        if self._iter is None:
            self._iter = self._generate()
        return self

    async def __anext__(self) -> T:
        if self._iter is None:
            self._iter = self._generate()
        try:
            return await self._iter.__anext__()
        except StopAsyncIteration:
            if self._error:
                raise self._error
            raise

    async def collect(self) -> list[T]:
        """Collect all frames into a list."""
        result: list[T] = []
        async for item in self:
            result.append(item)
        return result

    async def cancel(self) -> None:
        """Cancel the stream by closing the underlying async generator."""
        if self._iter is not None:
            await self._iter.aclose()
            self._exhausted = True
