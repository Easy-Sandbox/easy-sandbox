"""Tests for SessionManager (mock Sandbox)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.api.session_manager import SessionManager
from easy_sandbox.models.errors import SessionNotFoundError, SessionAlreadyExistsError
from easy_sandbox.models.session import SessionInfo
from easy_sandbox.models.sandbox import SandboxInfo, SandboxStatus
from easy_sandbox.session.local import LocalSessionStore


@pytest.fixture
def store(tmp_path: Path) -> LocalSessionStore:
    return LocalSessionStore(base_dir=str(tmp_path / "sessions"))


@pytest.fixture
def manager(store: LocalSessionStore) -> SessionManager:
    return SessionManager(store=store)


def _mock_sandbox(
    sandbox_id: str = "sbx-mgr-001",
    template: str = "base",
) -> MagicMock:
    sb_info = SandboxInfo.model_validate({
        "sandboxID": sandbox_id,
        "templateID": template,
        "status": "running",
        "region": "cn-hangzhou",
        "timeout": 300,
        "envdUrl": f"https://{sandbox_id}.e2b.fc.aliyuncs.com",
        "envdAccessToken": "tok-test-123",
    })
    mock = MagicMock()
    mock.id = sb_info.sandbox_id
    mock.status = sb_info.status
    mock.url = sb_info.envd_url
    mock.info = sb_info
    return mock


class TestStart:
    async def test_start_creates_session(self, manager: SessionManager, store: LocalSessionStore) -> None:
        mock_sb = _mock_sandbox()
        with patch(
            "easy_sandbox.api.session_manager.Sandbox.create",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            sandbox = await manager.start("my-project", "base", timeout=120)

        assert sandbox.id == "sbx-mgr-001"

        # Check session was persisted
        session = await store.load("my-project")
        assert session is not None
        assert session.name == "my-project"
        assert session.sandbox_id == "sbx-mgr-001"
        assert session.template == "base"
        assert session.status == "running"

    async def test_start_duplicate_raises(self, manager: SessionManager) -> None:
        mock_sb = _mock_sandbox()
        with patch(
            "easy_sandbox.api.session_manager.Sandbox.create",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            await manager.start("dup-session")

        with pytest.raises(SessionAlreadyExistsError):
            with patch(
                "easy_sandbox.api.session_manager.Sandbox.create",
                new_callable=AsyncMock,
                return_value=mock_sb,
            ):
                await manager.start("dup-session")


class TestConnect:
    async def test_connect_existing(self, manager: SessionManager, store: LocalSessionStore) -> None:
        # Pre-populate a session
        session = SessionInfo(
            name="saved-session",
            sandbox_id="sbx-saved-001",
            template="python3",
            status="running",
            created_at=datetime.now(timezone.utc),
        )
        await store.save("saved-session", session)

        mock_sb = _mock_sandbox(sandbox_id="sbx-saved-001")
        with patch(
            "easy_sandbox.api.session_manager.Sandbox.connect",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            sandbox = await manager.connect("saved-session")

        assert sandbox.id == "sbx-saved-001"

        # last_connected should have been updated
        updated = await store.load("saved-session")
        assert updated is not None
        assert updated.last_connected is not None

    async def test_connect_nonexistent(self, manager: SessionManager) -> None:
        with pytest.raises(SessionNotFoundError):
            await manager.connect("ghost")


class TestListSessions:
    async def test_list_empty(self, manager: SessionManager) -> None:
        result = await manager.list_sessions()
        assert result == []

    async def test_list_populated(self, manager: SessionManager, store: LocalSessionStore) -> None:
        for i in range(2):
            s = SessionInfo(
                name=f"s-{i}",
                sandbox_id=f"sbx-{i}",
                template="base",
                status="running",
            )
            await store.save(f"s-{i}", s)

        result = await manager.list_sessions()
        assert len(result) == 2


class TestStop:
    async def test_stop_kills_and_deletes(self, manager: SessionManager, store: LocalSessionStore) -> None:
        session = SessionInfo(
            name="to-stop",
            sandbox_id="sbx-stop-001",
            template="base",
            status="running",
        )
        await store.save("to-stop", session)

        with patch(
            "easy_sandbox.api.session_manager.Sandbox.kill_by_id",
            new_callable=AsyncMock,
        ) as mock_kill:
            await manager.stop("to-stop", kill=True)

        mock_kill.assert_awaited_once_with("sbx-stop-001")
        assert (await store.load("to-stop")) is None

    async def test_stop_keep_alive(self, manager: SessionManager, store: LocalSessionStore) -> None:
        session = SessionInfo(
            name="keep-me",
            sandbox_id="sbx-keep-001",
            template="base",
            status="running",
        )
        await store.save("keep-me", session)

        await manager.stop("keep-me", kill=False)

        kept = await store.load("keep-me")
        assert kept is not None
        assert kept.status == "stopped"

    async def test_stop_nonexistent(self, manager: SessionManager) -> None:
        with pytest.raises(SessionNotFoundError):
            await manager.stop("nothing")


class TestGetInfo:
    async def test_get_info_existing(self, manager: SessionManager, store: LocalSessionStore) -> None:
        session = SessionInfo(
            name="info-session",
            sandbox_id="sbx-info-001",
            template="base",
            status="running",
        )
        await store.save("info-session", session)

        info = await manager.get_info("info-session")
        assert info.name == "info-session"
        assert info.sandbox_id == "sbx-info-001"

    async def test_get_info_nonexistent(self, manager: SessionManager) -> None:
        with pytest.raises(SessionNotFoundError):
            await manager.get_info("nope")
