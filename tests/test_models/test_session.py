"""Tests for session data models."""
from __future__ import annotations

from datetime import datetime, timezone

from easy_sandbox.models.session import SessionConfig, SessionInfo


class TestSessionConfig:
    def test_defaults(self):
        cfg = SessionConfig(name="test-session")
        assert cfg.name == "test-session"
        assert cfg.description == ""
        assert cfg.sandbox_template == "base"
        assert cfg.auto_connect is True
        assert cfg.ttl == 86400
        assert cfg.envs == {}
        assert cfg.metadata == {}

    def test_custom_values(self):
        cfg = SessionConfig(
            name="dev",
            description="Dev session",
            sandbox_template="python3",
            auto_connect=False,
            ttl=3600,
            envs={"KEY": "val"},
            metadata={"owner": "me"},
        )
        assert cfg.name == "dev"
        assert cfg.description == "Dev session"
        assert cfg.sandbox_template == "python3"
        assert cfg.auto_connect is False
        assert cfg.ttl == 3600


class TestSessionInfo:
    def test_from_aliases(self):
        data = {
            "sessionId": "sess-001",
            "name": "test",
            "sandboxId": "sbx-111",
            "status": "active",
            "createdAt": "2025-06-01T12:00:00Z",
            "lastConnected": "2025-06-01T13:00:00Z",
        }
        info = SessionInfo(**data)
        assert info.session_id == "sess-001"
        assert info.name == "test"
        assert info.sandbox_id == "sbx-111"
        assert info.created_at is not None
        assert info.last_connected is not None

    def test_from_python_names(self):
        info = SessionInfo(session_id="sess-002", name="dev")
        assert info.session_id == "sess-002"

    def test_defaults(self):
        info = SessionInfo(session_id="sess-005", name="x")
        assert info.sandbox_id is None
        assert info.status == "active"
        assert info.created_at is None
        assert info.last_connected is None
        assert info.config is None
