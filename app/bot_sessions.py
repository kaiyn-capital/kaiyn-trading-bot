from datetime import datetime, timedelta
from typing import Any

from .config import Config

SESSION_EXPIRED_MESSAGE = "⏳ 此設定流程已超过 5 分钟，请重新开始。"


class UserSessionMixin:
    """In-memory per-user conversation session helpers."""

    def _session_now(self) -> datetime:
        return datetime.utcnow()

    def _session_expiry(self) -> datetime:
        return self._session_now() + timedelta(seconds=Config.USER_SESSION_TTL_SECONDS)

    def set_user_session(self, telegram_id: int, data: dict[str, Any]) -> dict[str, Any]:
        session = dict(data)
        session["expires_at"] = self._session_expiry()
        self.user_sessions[telegram_id] = session
        return session

    def update_user_session(self, telegram_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        session = self.user_sessions.setdefault(telegram_id, {})
        session.update(updates)
        session["expires_at"] = self._session_expiry()
        return session

    def expire_user_session_if_needed(self, telegram_id: int) -> bool:
        session = self.user_sessions.get(telegram_id)
        if not session:
            return False

        expires_at = session.get("expires_at")
        if not isinstance(expires_at, datetime) or self._session_now() >= expires_at:
            self.user_sessions.pop(telegram_id, None)
            return True

        return False

    def get_active_user_session(self, telegram_id: int) -> dict[str, Any] | None:
        if self.expire_user_session_if_needed(telegram_id):
            return None
        return self.user_sessions.get(telegram_id)

    async def _reply_if_session_expired(self, update, telegram_id: int) -> bool:
        if not self.expire_user_session_if_needed(telegram_id):
            return False

        await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
        return True
