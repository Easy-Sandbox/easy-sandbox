"""Filesystem data models."""
from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class FileType(str, enum.Enum):
    """Type of filesystem entry."""

    FILE = "file"
    DIRECTORY = "directory"


class FileInfo(BaseModel):
    """Information about a file or directory."""

    name: str
    path: str
    type: FileType = FileType.FILE
    size: int = 0
    modified: datetime | None = None


class WatchEventType(str, enum.Enum):
    """Type of filesystem watch event."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class WatchEvent(BaseModel):
    """A filesystem change event from WatchDir."""

    type: WatchEventType
    path: str
    old_path: str | None = None  # For rename events
    timestamp: float | None = None
