import json
from datetime import datetime, timedelta

from .encryption import EncryptionManager
from .repository_types import UserSessionRecord
from .session_types import (
    SESSION_PAYLOAD_VERSION,
    UserSessionPayload,
    coerce_session_payload,
    session_payload_from_json_data,
    session_payload_to_json_data,
    session_token_for,
    session_type_for,
    with_session_expiry,
)
from .settings import Settings


class InMemorySessionStore:
    """Async in-memory session store for tests and simple local fakes."""

    def __init__(
        self,
        sessions_dict: dict[int, UserSessionPayload],
        ttl_seconds: int | None = None,
        now_func=None,
    ):
        self._sessions = sessions_dict
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else Settings.from_env().user_session_ttl_seconds
        self._now_func = now_func or datetime.utcnow

    def _now(self) -> datetime:
        return self._now_func()

    def _expires_at(self) -> datetime:
        return self._now() + timedelta(seconds=self._ttl_seconds)

    async def set_session(
        self,
        telegram_id: int,
        payload: UserSessionPayload | dict,
        user_id: int | None = None,
    ) -> UserSessionPayload:
        payload = coerce_session_payload(payload)
        session = with_session_expiry(payload, self._expires_at())
        self._sessions[telegram_id] = session
        return session

    async def update_session(
        self,
        telegram_id: int,
        payload: UserSessionPayload | dict,
        user_id: int | None = None,
    ) -> UserSessionPayload:
        return await self.set_session(telegram_id, payload)

    async def get_session(self, telegram_id: int) -> UserSessionPayload | None:
        if await self.is_expired(telegram_id):
            return None
        return self._sessions.get(telegram_id)

    async def peek_session(self, telegram_id: int) -> UserSessionPayload | None:
        return self._sessions.get(telegram_id)

    async def delete_session(self, telegram_id: int) -> None:
        self._sessions.pop(telegram_id, None)

    async def pop_expired_session(self, telegram_id: int) -> UserSessionPayload | None:
        session = self._sessions.get(telegram_id)
        if not session:
            return None

        expires_at = session.expires_at
        if not isinstance(expires_at, datetime) or self._now() >= expires_at:
            return self._sessions.pop(telegram_id, None)

        return None

    async def is_expired(self, telegram_id: int) -> bool:
        return await self.pop_expired_session(telegram_id) is not None

    async def delete_expired_sessions(self) -> int:
        expired = [
            telegram_id
            for telegram_id, session in self._sessions.items()
            if not isinstance(session.expires_at, datetime) or self._now() >= session.expires_at
        ]
        for telegram_id in expired:
            self._sessions.pop(telegram_id, None)
        return len(expired)


class DatabaseSessionStore:
    """Encrypted PostgreSQL-backed Telegram conversation session store."""

    def __init__(
        self,
        session_repo,
        encryption_manager: EncryptionManager,
        ttl_seconds: int | None = None,
        now_func=None,
    ):
        self._repo = session_repo
        self._encryption_manager = encryption_manager
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else Settings.from_env().user_session_ttl_seconds
        self._now_func = now_func or datetime.utcnow

    def _now(self) -> datetime:
        return self._now_func()

    def _expires_at(self) -> datetime:
        return self._now() + timedelta(seconds=self._ttl_seconds)

    async def set_session(
        self,
        telegram_id: int,
        payload: UserSessionPayload | dict,
        user_id: int | None = None,
    ) -> UserSessionPayload:
        payload = coerce_session_payload(payload)
        session = with_session_expiry(payload, self._expires_at())
        await self._repo.upsert_session(
            telegram_id=telegram_id,
            user_id=user_id,
            session_type=session_type_for(session),
            token=session_token_for(session),
            payload_encrypted=self._encode_payload(session),
            payload_version=SESSION_PAYLOAD_VERSION,
            expires_at=session.expires_at,
        )
        return session

    async def update_session(
        self,
        telegram_id: int,
        payload: UserSessionPayload | dict,
        user_id: int | None = None,
    ) -> UserSessionPayload:
        return await self.set_session(telegram_id, payload, user_id=user_id)

    async def get_session(self, telegram_id: int) -> UserSessionPayload | None:
        if await self.is_expired(telegram_id):
            return None
        record = await self._repo.get_session(telegram_id)
        return self._decode_record(record) if record else None

    async def peek_session(self, telegram_id: int) -> UserSessionPayload | None:
        record = await self._repo.get_session(telegram_id)
        return self._decode_record(record) if record else None

    async def delete_session(self, telegram_id: int) -> None:
        await self._repo.delete_session(telegram_id)

    async def pop_expired_session(self, telegram_id: int) -> UserSessionPayload | None:
        record = await self._repo.pop_expired_session(telegram_id, self._now())
        return self._decode_record(record) if record else None

    async def is_expired(self, telegram_id: int) -> bool:
        return await self.pop_expired_session(telegram_id) is not None

    async def delete_expired_sessions(self) -> int:
        return await self._repo.delete_expired_sessions(self._now())

    def _encode_payload(self, payload: UserSessionPayload) -> str:
        data = session_payload_to_json_data(payload)
        return self._encryption_manager.encrypt(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    def _decode_record(self, record: UserSessionRecord | None) -> UserSessionPayload | None:
        if record is None:
            return None
        if record.payload_version != SESSION_PAYLOAD_VERSION:
            raise ValueError(f"unsupported session payload version: {record.payload_version}")

        raw_payload = self._encryption_manager.decrypt(record.payload_encrypted)
        data = json.loads(raw_payload)
        if not isinstance(data, dict):
            raise ValueError("session payload must be a JSON object")
        return session_payload_from_json_data(record.session_type, data, record.expires_at)


SessionStore = InMemorySessionStore
