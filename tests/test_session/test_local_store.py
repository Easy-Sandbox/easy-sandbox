"""Tests for LocalSessionStore CRUD operations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from easy_sandbox.models.session import SessionInfo
from easy_sandbox.session.local import LocalSessionStore


@pytest.fixture
def store(tmp_path: Path) -> LocalSessionStore:
    """Provide a LocalSessionStore backed by a temporary directory."""
    return LocalSessionStore(base_dir=str(tmp_path / "sessions"))


def _make_session(
    name: str = "test-session",
    sandbox_id: str = "sbx-001",
    template: str = "base",
    status: str = "running",
) -> SessionInfo:
    return SessionInfo(
        name=name,
        sandbox_id=sandbox_id,
        template=template,
        status=status,
        created_at=datetime.now(timezone.utc),
        metadata={"owner": "test"},
    )


class TestSave:
    async def test_save_creates_file(self, store: LocalSessionStore) -> None:
        session = _make_session()
        await store.save("test-session", session)

        fpath = store._path_for("test-session")
        assert fpath.exists()
        data = json.loads(fpath.read_text())
        assert data["name"] == "test-session"
        assert data["sandboxId"] == "sbx-001"

    async def test_save_overwrites(self, store: LocalSessionStore) -> None:
        s1 = _make_session(sandbox_id="sbx-001")
        s2 = _make_session(sandbox_id="sbx-002")

        await store.save("test-session", s1)
        await store.save("test-session", s2)

        loaded = await store.load("test-session")
        assert loaded is not None
        assert loaded.sandbox_id == "sbx-002"


class TestLoad:
    async def test_load_existing(self, store: LocalSessionStore) -> None:
        session = _make_session()
        await store.save("my-session", session)

        loaded = await store.load("my-session")
        assert loaded is not None
        assert loaded.name == "test-session"
        assert loaded.sandbox_id == "sbx-001"
        assert loaded.template == "base"

    async def test_load_nonexistent(self, store: LocalSessionStore) -> None:
        result = await store.load("does-not-exist")
        assert result is None


class TestDelete:
    async def test_delete_existing(self, store: LocalSessionStore) -> None:
        session = _make_session()
        await store.save("del-me", session)
        assert (await store.load("del-me")) is not None

        await store.delete("del-me")
        assert (await store.load("del-me")) is None

    async def test_delete_nonexistent(self, store: LocalSessionStore) -> None:
        # Should not raise
        await store.delete("nope")


class TestListAll:
    async def test_list_empty(self, store: LocalSessionStore) -> None:
        result = await store.list_all()
        assert result == []

    async def test_list_multiple(self, store: LocalSessionStore) -> None:
        for i in range(3):
            s = _make_session(name=f"session-{i}", sandbox_id=f"sbx-{i}")
            await store.save(f"session-{i}", s)

        result = await store.list_all()
        assert len(result) == 3
        names = {s.name for s in result}
        assert names == {"session-0", "session-1", "session-2"}

    async def test_list_skips_corrupt_files(
        self, store: LocalSessionStore, tmp_path: Path
    ) -> None:
        # Write valid session
        s = _make_session()
        await store.save("good", s)

        # Write corrupt JSON
        corrupt = store._path_for("bad")
        corrupt.write_text("NOT VALID JSON", encoding="utf-8")

        result = await store.list_all()
        assert len(result) == 1
        assert result[0].name == "test-session"


class TestSanitisedNames:
    async def test_special_chars(self, store: LocalSessionStore) -> None:
        session = _make_session(name="my/special:session")
        await store.save("my/special:session", session)

        loaded = await store.load("my/special:session")
        assert loaded is not None
        assert loaded.name == "my/special:session"
