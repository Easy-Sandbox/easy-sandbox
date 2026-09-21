"""Session storage abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from easy_sandbox.models.session import SessionInfo


class SessionStore(ABC):
    """Pluggable session storage backend.

    Concrete implementations persist session metadata so that
    a sandbox connection can be resumed across CLI invocations.
    """

    @abstractmethod
    async def save(self, name: str, session: SessionInfo) -> None:
        """Persist a session under *name*, overwriting any previous value."""
        ...

    @abstractmethod
    async def load(self, name: str) -> Optional[SessionInfo]:
        """Load a session by *name*, returning ``None`` if not found."""
        ...

    @abstractmethod
    async def delete(self, name: str) -> None:
        """Delete a session by *name*.  No error if it doesn't exist."""
        ...

    @abstractmethod
    async def list_all(self) -> list[SessionInfo]:
        """Return every persisted session."""
        ...
