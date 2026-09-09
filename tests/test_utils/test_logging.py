"""Tests for logging utilities."""
from __future__ import annotations

import logging
import os
from unittest import mock

import serverless_sandbox.utils.logging as log_module
from serverless_sandbox.utils.logging import get_logger


class TestGetLogger:
    def test_returns_namespaced_logger(self):
        logger = get_logger("transport.http")
        assert logger.name == "serverless_sandbox.transport.http"

    def test_already_prefixed(self):
        logger = get_logger("serverless_sandbox.session")
        assert logger.name == "serverless_sandbox.session"

    def test_returns_logging_logger(self):
        logger = get_logger("test")
        assert isinstance(logger, logging.Logger)

    def test_respects_env_var(self):
        # Reset the configured flag to allow reconfiguration
        log_module._CONFIGURED = False
        with mock.patch.dict(os.environ, {"SANDBOX_LOG_LEVEL": "DEBUG"}):
            logger = get_logger("envtest")
            root = logging.getLogger("serverless_sandbox")
            assert root.level == logging.DEBUG
        # Reset for other tests
        log_module._CONFIGURED = False
        root = logging.getLogger("serverless_sandbox")
        root.setLevel(logging.WARNING)

    def test_default_level_is_warning(self):
        log_module._CONFIGURED = False
        # Make sure env var is not set
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SANDBOX_LOG_LEVEL", None)
            logger = get_logger("default_test")
            root = logging.getLogger("serverless_sandbox")
            assert root.level == logging.WARNING
        log_module._CONFIGURED = False
