from datetime import datetime

from .session_store import InMemorySessionStore
from .session_types import UserSessionPayload
from .settings import Settings

SESSION_EXPIRED_MESSAGE = "⏳ 此設定流程已超过 5 分钟，请重新开始。"


class UserSessionMixin:
    """Per-user conversation session helpers."""

    def _session_now(self) -> datetime:
        return datetime.utcnow()

    @property
    def session_store(self):
        if not hasattr(self, "_session_store_delegate"):
            if not hasattr(self, "user_sessions"):
                self.user_sessions: dict[int, UserSessionPayload] = {}
            settings = getattr(self, "settings", None)
            ttl_seconds = (
                settings.user_session_ttl_seconds
                if isinstance(settings, Settings)
                else Settings.from_env().user_session_ttl_seconds
            )
            self._session_store_delegate = InMemorySessionStore(
                sessions_dict=self.user_sessions,
                ttl_seconds=ttl_seconds,
                now_func=self._session_now,
            )
        return self._session_store_delegate

    @session_store.setter
    def session_store(self, value):
        self._session_store_delegate = value

    async def set_user_session(
        self,
        telegram_id: int,
        payload: UserSessionPayload | dict,
        user_id: int | None = None,
    ) -> UserSessionPayload:
        return await self.session_store.set_session(telegram_id, payload, user_id=user_id)

    async def update_user_session(
        self,
        telegram_id: int,
        payload: UserSessionPayload | dict,
        user_id: int | None = None,
    ) -> UserSessionPayload:
        return await self.session_store.update_session(telegram_id, payload, user_id=user_id)

    async def expire_user_session_if_needed(self, telegram_id: int) -> bool:
        return await self.session_store.is_expired(telegram_id)

    async def get_active_user_session(self, telegram_id: int) -> UserSessionPayload | None:
        return await self.session_store.get_session(telegram_id)

    async def peek_user_session(self, telegram_id: int) -> UserSessionPayload | None:
        return await self.session_store.peek_session(telegram_id)

    async def pop_expired_user_session(self, telegram_id: int) -> UserSessionPayload | None:
        return await self.session_store.pop_expired_session(telegram_id)

    async def delete_user_session(self, telegram_id: int) -> None:
        await self.session_store.delete_session(telegram_id)

    async def delete_expired_user_sessions(self) -> int:
        return await self.session_store.delete_expired_sessions()

    async def _reply_if_session_expired(self, update, telegram_id: int) -> bool:
        if not await self.expire_user_session_if_needed(telegram_id):
            return False

        await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
        return True
