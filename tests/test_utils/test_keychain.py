"""Tests for SecretStore file-based storage (keychain calls are mocked/skipped)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from serverless_sandbox.utils.keychain import SecretStore


@pytest.fixture
def store(tmp_path: Path) -> SecretStore:
    """Provide a SecretStore backed by a temporary secrets file."""
    return SecretStore(secrets_file=tmp_path / "secrets.json")


class TestSetAndGet:
    def test_set_and_get_via_file(self, store: SecretStore) -> None:
        """Keychain fails → falls back to file → get retrieves it."""
        with patch.object(store, "_set_keychain", side_effect=NotImplementedError):
            store.set("MY_API_KEY", "super-secret-123")

        with patch.object(store, "_get_keychain", side_effect=NotImplementedError):
            val = store.get("MY_API_KEY")

        assert val == "super-secret-123"

    def test_set_overwrites(self, store: SecretStore) -> None:
        with patch.object(store, "_set_keychain", side_effect=NotImplementedError):
            store.set("KEY", "v1")
            store.set("KEY", "v2")

        with patch.object(store, "_get_keychain", side_effect=NotImplementedError):
            assert store.get("KEY") == "v2"

    def test_get_nonexistent_returns_none(self, store: SecretStore) -> None:
        with patch.object(store, "_get_keychain", side_effect=NotImplementedError):
            assert store.get("nope") is None

    def test_file_permissions(self, store: SecretStore) -> None:
        """Secrets file should be chmod 600."""
        with patch.object(store, "_set_keychain", side_effect=NotImplementedError):
            store.set("KEY", "val")

        mode = store._secrets_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_file_is_valid_json(self, store: SecretStore) -> None:
        with patch.object(store, "_set_keychain", side_effect=NotImplementedError):
            store.set("A", "1")
            store.set("B", "2")

        data = json.loads(store._secrets_file.read_text())
        assert data == {"A": "1", "B": "2"}


class TestDelete:
    def test_delete_existing(self, store: SecretStore) -> None:
        with patch.object(store, "_set_keychain", side_effect=NotImplementedError):
            store.set("TO_DEL", "value")

        with patch.object(store, "_delete_keychain", side_effect=NotImplementedError):
            result = store.delete("TO_DEL")

        assert result is True

        with patch.object(store, "_get_keychain", side_effect=NotImplementedError):
            assert store.get("TO_DEL") is None

    def test_delete_nonexistent(self, store: SecretStore) -> None:
        with patch.object(store, "_delete_keychain", side_effect=NotImplementedError):
            result = store.delete("nope")
        assert result is False


class TestListNames:
    def test_list_empty(self, store: SecretStore) -> None:
        assert store.list_names() == []

    def test_list_multiple(self, store: SecretStore) -> None:
        with patch.object(store, "_set_keychain", side_effect=NotImplementedError):
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

        with patch.object(store, "_get_keychain", side_effect=NotImplementedError):
            assert store.get("any") is None

        assert store.list_names() == []
