"""Structured logging for Easy Sandbox SDK."""

from __future__ import annotations

import logging
import os

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_CONFIGURED = False


def _configure_once() -> None:
    """Configure logging once on first call.

    The package logger's *level* always follows ``SANDBOX_LOG_LEVEL`` so that
    standalone SDK users keep the documented knob.  The fallback stderr
    handler is only installed when nothing else owns the output: when the CLI
    (or any embedding host) has already configured the root logger — the
    ``OutputManager`` installs a single bridge handler there — a second
    handler would render every record twice, so we keep only the host's.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_str = os.environ.get("SANDBOX_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_str, logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    package_logger = logging.getLogger("easy_sandbox")
    package_logger.setLevel(level)
    if not package_logger.handlers and not logging.getLogger().handlers:
        package_logger.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger for a module.

    Args:
        name: Module name, will be prefixed with 'easy_sandbox.'

    Returns:
        Configured logger instance.

    Example:
        logger = get_logger("transport.http")
        logger.debug("Sending request to %s", url)
    """
    _configure_once()
    if not name.startswith("easy_sandbox."):
        name = f"easy_sandbox.{name}"
    return logging.getLogger(name)
