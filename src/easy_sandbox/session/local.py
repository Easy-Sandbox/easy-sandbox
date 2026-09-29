"""Local filesystem session store.

Sessions are persisted as JSON files under ``~/.ebx/sessions/``.
Concurrent access is protected by ``filelock`` when available,
falling back to ``fcntl`` on POSIX systems.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from easy_sandbox.models.session import SessionInfo

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".ebx", "sessions")


def _get_lock(path: str) -> Any:
    """Return a context-manager file lock (filelock preferred, fcntl fallback)."""
    try:
        from filelock import FileLock

        return FileLock(path + ".lock", timeout=5)
    except ImportError:
        pass

    # Fallback: fcntl (POSIX only)
    import fcntl

    class _FcntlLock:
        def __init__(self, lock_path: str) -> None:
            self._path = lock_path

        def __enter__(self) -> _FcntlLock:
            self._fd = open(self._path, "w")
            fcntl.flock(self._fd, fcntl.LOCK_EX)
            return self

        def __exit__(self, *args: Any) -> None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()

    return _FcntlLock(path + ".lock")


class LocalSessionStore:
    """File-backed session store (``~/.ebx/sessions/``)."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or DEFAULT_DIR)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, name: str) -> Path:
        # Sanitise: replace anything non-alphanumeric / dash / underscore
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
        return self._base_dir / f"{safe}.json"

    async def save(self, name: str, session: SessionInfo) -> None:
        fpath = self._path_for(name)
        data = session.model_dump(mode="json", by_alias=True)
        with _get_lock(str(fpath)):
            fpath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    async def load(self, name: str) -> SessionInfo | None:
        fpath = self._path_for(name)
        if not fpath.exists():
            return None
        with _get_lock(str(fpath)):
            raw = fpath.read_text(encoding="utf-8")
        return SessionInfo.model_validate_json(raw)

    async def delete(self, name: str) -> None:
        fpath = self._path_for(name)
        lock_path = Path(str(fpath) + ".lock")
        with contextlib.suppress(OSError):
            fpath.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            lock_path.unlink(missing_ok=True)

    async def list_all(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        for fp in sorted(self._base_dir.glob("*.json")):
            try:
                raw = fp.read_text(encoding="utf-8")
                sessions.append(SessionInfo.model_validate_json(raw))
            except Exception:
                continue
        return sessions
