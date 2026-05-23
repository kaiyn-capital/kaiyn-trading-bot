from datetime import datetime
from typing import Any

from .config import Config
from .session_store import SessionStore

SESSION_EXPIRED_MESSAGE = "⏳ 此設定流程已超过 5 分钟，请重新开始。"


class UserSessionMixin:
    """In-memory per-user conversation session helpers."""

    def _session_now(self) -> datetime:
        return datetime.utcnow()

    @property
    def session_store(self) -> SessionStore:
        if not hasattr(self, "_session_store_delegate"):
            if not hasattr(self, "user_sessions"):
                self.user_sessions: dict[int, object] = {}
            self._session_store_delegate = SessionStore(
                sessions_dict=self.user_sessions,
                ttl_seconds=Config.USER_SESSION_TTL_SECONDS,
                now_func=self._session_now,
            )
        return self._session_store_delegate

    @session_store.setter
    def session_store(self, value: SessionStore):
        self._session_store_delegate = value

    def set_user_session(self, telegram_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return self.session_store.set_session(telegram_id, data)

    def update_user_session(self, telegram_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        return self.session_store.update_session(telegram_id, updates)

    def expire_user_session_if_needed(self, telegram_id: int) -> bool:
        return self.session_store.is_expired(telegram_id)

    def get_active_user_session(self, telegram_id: int) -> dict[str, Any] | None:
        return self.session_store.get_session(telegram_id)

    def peek_user_session(self, telegram_id: int) -> dict[str, Any] | None:
        return self.session_store.peek_session(telegram_id)

    def pop_expired_user_session(self, telegram_id: int) -> dict[str, Any] | None:
        return self.session_store.pop_expired_session(telegram_id)

    def delete_user_session(self, telegram_id: int) -> None:
        self.session_store.delete_session(telegram_id)

    async def _reply_if_session_expired(self, update, telegram_id: int) -> bool:
        if not self.expire_user_session_if_needed(telegram_id):
            return False

        await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
        return True
