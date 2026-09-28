"""Tests for SecretStore file-based storage."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from easy_sandbox.utils.keychain import SecretStore

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> SecretStore:
    """Provide a SecretStore backed by a temporary secrets file."""
    return SecretStore(secrets_file=tmp_path / "secrets.json")


class TestSetAndGet:
    def test_set_and_get(self, store: SecretStore) -> None:
        store.set("MY_API_KEY", "super-secret-123")
        assert store.get("MY_API_KEY") == "super-secret-123"

    def test_set_overwrites(self, store: SecretStore) -> None:
        store.set("KEY", "v1")
        store.set("KEY", "v2")
        assert store.get("KEY") == "v2"

    def test_get_nonexistent_returns_none(self, store: SecretStore) -> None:
        assert store.get("nope") is None

    def test_file_permissions(self, store: SecretStore) -> None:
        """Secrets file should be chmod 600."""
        store.set("KEY", "val")
        mode = store._secrets_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_file_is_valid_json(self, store: SecretStore) -> None:
        store.set("A", "1")
        store.set("B", "2")
        data = json.loads(store._secrets_file.read_text())
        assert data == {"A": "1", "B": "2"}


class TestDelete:
    def test_delete_existing(self, store: SecretStore) -> None:
        store.set("TO_DEL", "value")
        result = store.delete("TO_DEL")
        assert result is True
        assert store.get("TO_DEL") is None

    def test_delete_nonexistent(self, store: SecretStore) -> None:
        result = store.delete("nope")
        assert result is False


class TestListNames:
    def test_list_empty(self, store: SecretStore) -> None:
        assert store.list_names() == []

    def test_list_multiple(self, store: SecretStore) -> None:
        store.set("BETA", "b")
        store.set("ALPHA", "a")
        store.set("GAMMA", "g")
        names = store.list_names()
        assert names == ["ALPHA", "BETA", "GAMMA"]  # sorted


class TestCorruptFile:
    def test_corrupt_file_returns_empty(self, store: SecretStore) -> None:
        """If the secrets file is corrupt JSON, operations degrade gracefully."""
        store._secrets_file.parent.mkdir(parents=True, exist_ok=True)
        store._secrets_file.write_text("NOT JSON!!!")
        assert store.get("any") is None
        assert store.list_names() == []
