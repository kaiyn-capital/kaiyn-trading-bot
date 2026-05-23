from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .config import Config


class SessionStore:
    """Encapsulates in-memory per-user conversation session storage with TTL expiration."""

    def __init__(
        self,
        sessions_dict: Dict[int, Dict[str, Any]],
        ttl_seconds: Optional[int] = None,
        now_func=None,
    ):
        self._sessions = sessions_dict
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else Config.USER_SESSION_TTL_SECONDS
        self._now_func = now_func or datetime.utcnow

    def _now(self) -> datetime:
        return self._now_func()

    def set_session(self, telegram_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Set a session for a user, automatically adding expires_at."""
        session = dict(data)
        session["expires_at"] = self._now() + timedelta(seconds=self._ttl_seconds)
        self._sessions[telegram_id] = session
        return session

    def update_session(self, telegram_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing session, resetting its expiry."""
        session = self._sessions.setdefault(telegram_id, {})
        session.update(updates)
        session["expires_at"] = self._now() + timedelta(seconds=self._ttl_seconds)
        return session

    def get_session(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get the active user session if it is not expired."""
        if self.is_expired(telegram_id):
            return None
        return self._sessions.get(telegram_id)

    def peek_session(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Return a user session without applying expiry side effects."""
        return self._sessions.get(telegram_id)

    def delete_session(self, telegram_id: int) -> None:
        """Delete a user session."""
        self._sessions.pop(telegram_id, None)

    def pop_expired_session(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Remove and return an expired user session, if one exists."""
        session = self._sessions.get(telegram_id)
        if not session:
            return None

        expires_at = session.get("expires_at")
        if not isinstance(expires_at, datetime) or self._now() >= expires_at:
            return self._sessions.pop(telegram_id, None)

        return None

    def is_expired(self, telegram_id: int) -> bool:
        """Return whether a user session has expired (and clear it if so)."""
        return self.pop_expired_session(telegram_id) is not None
