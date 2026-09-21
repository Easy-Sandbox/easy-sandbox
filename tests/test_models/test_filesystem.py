"""Tests for filesystem data models."""
from __future__ import annotations

from datetime import datetime, timezone

from easy_sandbox.models.filesystem import (
    FileType,
    FileInfo,
    WatchEventType,
    WatchEvent,
)


class TestFileType:
    def test_enum_values(self):
        assert FileType.FILE == "file"
        assert FileType.DIRECTORY == "directory"

    def test_enum_count(self):
        assert len(FileType) == 2


class TestFileInfo:
    def test_all_fields(self):
        now = datetime.now(timezone.utc)
        info = FileInfo(
            name="test.py",
            path="/home/user/test.py",
            type=FileType.FILE,
            size=1234,
            modified=now,
        )
        assert info.name == "test.py"
        assert info.path == "/home/user/test.py"
        assert info.type == FileType.FILE
        assert info.size == 1234
        assert info.modified == now

    def test_defaults(self):
        info = FileInfo(name="a.txt", path="/a.txt")
        assert info.type == FileType.FILE
        assert info.size == 0
        assert info.modified is None

    def test_directory_type(self):
        info = FileInfo(name="src", path="/src", type=FileType.DIRECTORY)
        assert info.type == FileType.DIRECTORY


class TestWatchEventType:
    def test_enum_values(self):
        assert WatchEventType.CREATED == "created"
        assert WatchEventType.MODIFIED == "modified"
        assert WatchEventType.DELETED == "deleted"
        assert WatchEventType.RENAMED == "renamed"

    def test_enum_count(self):
        assert len(WatchEventType) == 4


class TestWatchEvent:
    def test_serialization(self):
        event = WatchEvent(
            type=WatchEventType.CREATED,
            path="/home/user/new.txt",
            timestamp=1234567890.0,
        )
        d = event.model_dump()
        assert d["type"] == "created"
        assert d["path"] == "/home/user/new.txt"
        assert d["old_path"] is None
        assert d["timestamp"] == 1234567890.0

    def test_rename_event(self):
        event = WatchEvent(
            type=WatchEventType.RENAMED,
            path="/new_name.txt",
            old_path="/old_name.txt",
        )
        assert event.old_path == "/old_name.txt"
