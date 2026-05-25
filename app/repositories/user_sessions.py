from datetime import datetime

from sqlalchemy import delete, func, select

from ..models import UserSession
from ..repository_types import UserSessionRecord


class UserSessionRepository:
    """Persistent per-user Telegram conversation sessions."""

    def __init__(self, db_manager):
        self.db = db_manager

    async def upsert_session(
        self,
        *,
        telegram_id: int,
        session_type: str,
        payload_encrypted: str,
        payload_version: int,
        expires_at: datetime,
        user_id: int | None = None,
        token: str | None = None,
    ) -> UserSessionRecord:
        async with self.db.get_session() as session:
            result = await session.execute(
                select(UserSession).where(UserSession.telegram_id == telegram_id).with_for_update()
            )
            stored_session = result.scalar_one_or_none()
            now = datetime.utcnow()
            if not stored_session:
                stored_session = UserSession(
                    telegram_id=telegram_id,
                    user_id=user_id,
                    session_type=session_type,
                    token=token,
                    payload_encrypted=payload_encrypted,
                    payload_version=payload_version,
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
                session.add(stored_session)
            else:
                stored_session.user_id = user_id
                stored_session.session_type = session_type
                stored_session.token = token
                stored_session.payload_encrypted = payload_encrypted
                stored_session.payload_version = payload_version
                stored_session.expires_at = expires_at
                stored_session.updated_at = now

            await session.flush()
            return user_session_record_from_model(stored_session)

    async def get_session(self, telegram_id: int) -> UserSessionRecord | None:
        async with self.db.get_session() as session:
            result = await session.execute(select(UserSession).where(UserSession.telegram_id == telegram_id))
            stored_session = result.scalar_one_or_none()
            return user_session_record_from_model(stored_session) if stored_session else None

    async def delete_session(self, telegram_id: int) -> None:
        async with self.db.get_session() as session:
            await session.execute(delete(UserSession).where(UserSession.telegram_id == telegram_id))

    async def pop_expired_session(self, telegram_id: int, now: datetime) -> UserSessionRecord | None:
        async with self.db.get_session() as session:
            result = await session.execute(
                select(UserSession).where(UserSession.telegram_id == telegram_id).with_for_update()
            )
            stored_session = result.scalar_one_or_none()
            if not stored_session or stored_session.expires_at > now:
                return None

            record = user_session_record_from_model(stored_session)
            await session.delete(stored_session)
            return record

    async def delete_expired_sessions(self, now: datetime) -> int:
        async with self.db.get_session() as session:
            result = await session.execute(
                delete(UserSession).where(UserSession.expires_at <= now).returning(UserSession.id)
            )
            return len(result.scalars().all())

    async def count_active_sessions(self, now: datetime) -> int:
        async with self.db.get_session() as session:
            result = await session.execute(
                select(func.count()).select_from(UserSession).where(UserSession.expires_at > now)
            )
            return int(result.scalar_one())

    async def count_expired_sessions(self, now: datetime) -> int:
        async with self.db.get_session() as session:
            result = await session.execute(
                select(func.count()).select_from(UserSession).where(UserSession.expires_at <= now)
            )
            return int(result.scalar_one())


def user_session_record_from_model(session: UserSession) -> UserSessionRecord:
    return UserSessionRecord(
        id=session.id,
        telegram_id=session.telegram_id,
        user_id=session.user_id,
        session_type=session.session_type,
        token=session.token,
        payload_encrypted=session.payload_encrypted,
        payload_version=session.payload_version,
        expires_at=session.expires_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
