"""Session manager — create, connect, list, and stop named sessions.

A *session* is a thin wrapper that pairs a human-friendly name with a
sandbox ID and persists the mapping so a user can resume work later.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from easy_sandbox.api.sandbox import Sandbox
from easy_sandbox.models.errors import SessionNotFoundError, SessionAlreadyExistsError
from easy_sandbox.models.session import SessionInfo
from easy_sandbox.session.base import SessionStore
from easy_sandbox.session.local import LocalSessionStore
from easy_sandbox.utils.logging import get_logger

logger = get_logger("api.session_manager")


class SessionManager:
    """High-level API for named session lifecycle management.

    Parameters
    ----------
    store:
        Pluggable storage backend.  Defaults to ``LocalSessionStore``.
    """

    def __init__(self, store: SessionStore | None = None) -> None:
        self._store = store or LocalSessionStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(
        self,
        name: str,
        template: str = "base",
        *,
        timeout: int = 300,
        metadata: dict[str, str] | None = None,
        envs: dict[str, str] | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
    ) -> Sandbox:
        """Create a new sandbox and persist the session.

        Raises ``SessionAlreadyExistsError`` if *name* is already in use.
        """
        existing = await self._store.load(name)
        if existing is not None:
            raise SessionAlreadyExistsError(
                f"Session {name!r} already exists (sandbox {existing.sandbox_id})"
            )

        sandbox = await Sandbox.create(
            template=template,
            timeout=timeout,
            metadata=metadata,
            envs=envs,
            api_key=api_key,
            api_url=api_url,
            domain=domain,
        )

        session_info = SessionInfo(
            name=name,
            sandbox_id=sandbox.id,
            template=template,
            api_url=api_url or "",
            domain=domain or "",
            envd_access_token=sandbox.info.envd_access_token or "",
            status="running",
            created_at=datetime.now(timezone.utc),
            last_connected=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        await self._store.save(name, session_info)
        logger.info("Session %r started (sandbox %s)", name, sandbox.id)
        return sandbox

    async def connect(
        self,
        name: str,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
    ) -> Sandbox:
        """Resume a session by name.

        Raises ``SessionNotFoundError`` if the session does not exist.
        """
        session = await self._store.load(name)
        if session is None:
            raise SessionNotFoundError(f"Session {name!r} not found")

        sandbox = await Sandbox.connect(
            session.sandbox_id,  # type: ignore[arg-type]
            api_key=api_key,
            api_url=api_url or session.api_url or None,
            domain=domain or session.domain or None,
        )

        # Update last_connected timestamp
        session.last_connected = datetime.now(timezone.utc)
        session.status = "running"
        await self._store.save(name, session)

        logger.info("Session %r reconnected (sandbox %s)", name, sandbox.id)
        return sandbox

    async def list_sessions(self) -> list[SessionInfo]:
        """Return all persisted sessions."""
        return await self._store.list_all()

    async def stop(self, name: str, *, kill: bool = True) -> None:
        """Stop a session.

        Parameters
        ----------
        name:
            Session name.
        kill:
            If ``True`` (default), kill the sandbox and remove the session
            record.  If ``False``, keep the sandbox alive and only mark
            the session as stopped.
        """
        session = await self._store.load(name)
        if session is None:
            raise SessionNotFoundError(f"Session {name!r} not found")

        if kill and session.sandbox_id:
            try:
                await Sandbox.kill_by_id(session.sandbox_id)
                logger.info("Sandbox %s killed for session %r", session.sandbox_id, name)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to kill sandbox %s for session %r",
                    session.sandbox_id,
                    name,
                    exc_info=True,
                )

        if kill:
            await self._store.delete(name)
        else:
            session.status = "stopped"
            await self._store.save(name, session)

    async def get_info(self, name: str) -> SessionInfo:
        """Return session info.

        Raises ``SessionNotFoundError`` if the session does not exist.
        """
        session = await self._store.load(name)
        if session is None:
            raise SessionNotFoundError(f"Session {name!r} not found")
        return session
