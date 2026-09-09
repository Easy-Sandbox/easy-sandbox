"""Async retry decorator with exponential backoff."""
from __future__ import annotations

import asyncio
import functools
import random
from typing import Any, Callable, TypeVar, TYPE_CHECKING

from serverless_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = get_logger("utils.retry")

F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.5,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Async retry decorator with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds (doubles each retry).
        max_delay: Maximum delay cap in seconds.
        jitter: Maximum random jitter in seconds.
        retry_on: Tuple of exception types to retry on.

    Example:
        @retry(max_retries=3, retry_on=(ConnectionError, TimeoutError))
        async def fetch_data():
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as exc:
                    last_exception = exc
                    if attempt == max_retries:
                        logger.debug(
                            "Retry exhausted for %s after %d attempts: %s",
                            func.__name__,
                            max_retries + 1,
                            exc,
                        )
                        raise

                    # Check for Retry-After header
                    retry_after = getattr(exc, "retry_after", None)
                    if retry_after is not None and isinstance(
                        retry_after, (int, float)
                    ):
                        delay = float(retry_after)
                    else:
                        delay = min(base_delay * (2**attempt), max_delay)

                    delay += random.uniform(0, jitter)

                    logger.debug(
                        "Retry %d/%d for %s after %.2fs: %s",
                        attempt + 1,
                        max_retries,
                        func.__name__,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

            # Should not reach here, but just in case
            if last_exception is not None:
                raise last_exception
            raise RuntimeError("Unexpected retry loop exit")

        return wrapper  # type: ignore[return-value]

    return decorator
