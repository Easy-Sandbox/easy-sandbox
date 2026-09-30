"""Tests for logging utilities."""

from __future__ import annotations

import logging
import os
from unittest import mock

import easy_sandbox.utils.logging as log_module
from easy_sandbox.utils.logging import get_logger


class TestGetLogger:
    def test_returns_namespaced_logger(self):
        logger = get_logger("transport.http")
        assert logger.name == "easy_sandbox.transport.http"

    def test_already_prefixed(self):
        logger = get_logger("easy_sandbox.session")
        assert logger.name == "easy_sandbox.session"

    def test_returns_logging_logger(self):
        logger = get_logger("test")
        assert isinstance(logger, logging.Logger)

    def test_respects_env_var(self):
        # Reset the configured flag to allow reconfiguration
        log_module._CONFIGURED = False
        root_logger = logging.getLogger()
        saved_handlers = list(root_logger.handlers)
        for handler in saved_handlers:
            root_logger.removeHandler(handler)
        try:
            with mock.patch.dict(os.environ, {"SANDBOX_LOG_LEVEL": "DEBUG"}):
                get_logger("envtest")
                package = logging.getLogger("easy_sandbox")
                assert package.level == logging.DEBUG
        finally:
            for handler in saved_handlers:
                root_logger.addHandler(handler)
            log_module._CONFIGURED = False
            logging.getLogger("easy_sandbox").setLevel(logging.WARNING)

    def test_default_level_is_warning(self):
        log_module._CONFIGURED = False
        root_logger = logging.getLogger()
        saved_handlers = list(root_logger.handlers)
        for handler in saved_handlers:
            root_logger.removeHandler(handler)
        try:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SANDBOX_LOG_LEVEL", None)
                get_logger("default_test")
                package = logging.getLogger("easy_sandbox")
                assert package.level == logging.WARNING
        finally:
            for handler in saved_handlers:
                root_logger.addHandler(handler)
            log_module._CONFIGURED = False

    def test_host_handler_does_not_drop_info(self):
        """A CLI root handler must see INFO; the package logger must not filter it."""
        log_module._CONFIGURED = False
        root_logger = logging.getLogger()
        handler = logging.NullHandler()
        root_logger.addHandler(handler)
        try:
            with mock.patch.dict(os.environ, {"SANDBOX_LOG_LEVEL": "WARNING"}):
                get_logger("hosted")
                assert logging.getLogger("easy_sandbox").level == logging.NOTSET
        finally:
            root_logger.removeHandler(handler)
            log_module._CONFIGURED = False
            logging.getLogger("easy_sandbox").setLevel(logging.WARNING)
