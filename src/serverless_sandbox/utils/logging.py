"""Structured logging for Serverless Sandbox SDK."""
from __future__ import annotations

import logging
import os

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_CONFIGURED = False


def _configure_once() -> None:
    """Configure logging once on first call."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_str = os.environ.get("SANDBOX_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_str, logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root_logger = logging.getLogger("serverless_sandbox")
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_logger.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger for a module.

    Args:
        name: Module name, will be prefixed with 'serverless_sandbox.'

    Returns:
        Configured logger instance.

    Example:
        logger = get_logger("transport.http")
        logger.debug("Sending request to %s", url)
    """
    _configure_once()
    if not name.startswith("serverless_sandbox."):
        name = f"serverless_sandbox.{name}"
    return logging.getLogger(name)
